"""Workflow prompt templates: workflows are data, not code.

Resolution order for a workflow name is *project override* →
*built-in template*. Project overrides live at
``<project.root_path>/.tasks/workflows/<name>.md`` (falling back to
``cwd/.tasks/workflows/<name>.md`` when the project has no ``root_path``).
Agents may author project-level templates on the filesystem; v1 exposes no
tool that writes them (open question 7).
"""

from __future__ import annotations

import logging
from importlib.resources import files
from pathlib import Path
from typing import Any

from .db import Database
from .errors import NotFound, TaskManagerError, ValidationError

logger = logging.getLogger(__name__)

DEFAULT_LEASE_MINUTES = 60
BUILTIN_NAMES = ("simple", "bugfix", "feature", "spike")
FRONTMATTER = "---"


def _builtin_dir():
    return files("task_manager").joinpath("workflows")


def _parse_template(text: str, *, source: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER:
        raise ValidationError(f"workflow template {source}: missing frontmatter")
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER:
            closing = index
            break
    if closing is None:
        raise ValidationError(
            f"workflow template {source}: unterminated frontmatter (missing closing ---)"
        )

    meta: dict[str, str] = {}
    for line in lines[1:closing]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition(":")
        if not separator:
            raise ValidationError(
                f"workflow template {source}: malformed frontmatter line '{stripped}'"
            )
        meta[key.strip()] = value.strip()

    name = meta.get("name", "").strip()
    if not name:
        raise ValidationError(f"workflow template {source}: missing 'name'")
    description = meta.get("description", "").strip()
    if not description:
        raise ValidationError(f"workflow template {source}: missing 'description'")

    lease_raw = meta.get("lease_minutes", str(DEFAULT_LEASE_MINUTES))
    try:
        lease_minutes = int(lease_raw)
    except ValueError as exc:
        raise ValidationError(
            f"workflow template {source}: lease_minutes must be an integer"
        ) from exc
    if lease_minutes <= 0:
        raise ValidationError(
            f"workflow template {source}: lease_minutes must be positive"
        )

    prompt = "\n".join(lines[closing + 1 :]).strip()
    if not prompt:
        raise ValidationError(f"workflow template {source}: empty prompt body")

    return {
        "name": name,
        "description": description,
        "lease_minutes": lease_minutes,
        "prompt": prompt,
        "source": "builtin",
    }


def _workflow_dir(db: Database, project_id: int) -> Path:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT root_path FROM projects WHERE id=?", (project_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise NotFound(f"project {project_id} not found")
    return _workflow_base(row["root_path"]) / ".tasks" / "workflows"


def _workflow_base(root_path: str | None) -> Path:
    return Path(root_path) if root_path else Path.cwd()


def _read_workflow_file(path: Path, name: str) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"workflow template {path}: {exc}") from exc
    template = _parse_template(text, source=str(path))
    template["name"] = name
    template["source"] = "project"
    return template


def load_workflow(db: Database, project_id: int, name: str) -> dict[str, Any]:
    """Load one workflow, preferring the project override over the built-in."""
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("workflow name must be a non-empty string")
    name = name.strip()

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT root_path FROM projects WHERE id=?", (project_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise NotFound(f"project {project_id} not found")
    return load_from_root(row["root_path"], name)


def list_workflows(db: Database, project_id: int) -> list[dict[str, Any]]:
    """Merged view of built-ins and project overrides (overrides win)."""
    names = {
        entry.name[: -len(".md")]
        for entry in _builtin_dir().iterdir()
        if entry.name.endswith(".md")
    }
    project_dir = _workflow_dir(db, project_id)
    if project_dir.is_dir():
        names.update(
            entry.stem for entry in project_dir.iterdir() if entry.suffix == ".md"
        )
    workflows: list[dict[str, Any]] = []
    for name in sorted(names):
        try:
            workflows.append(load_workflow(db, project_id, name))
        except TaskManagerError:
            continue
    return workflows


def render_prompt(template: str, *, title: str, task_id: int, project: str) -> str:
    """Fill ``{title}``, ``{id}``, and ``{project}`` without touching other braces."""
    return (
        template.replace("{title}", title)
        .replace("{id}", str(task_id))
        .replace("{project}", project)
    )


def default_lease_minutes(project: Any, workflow: str) -> int:
    """The workflow's lease default, or the global default on any load error.

    Takes the project row rather than a database handle so the lifecycle
    transitions can resolve it without opening a second connection inside
    their write transaction.
    """
    try:
        return int(load_from_root(project["root_path"], workflow)["lease_minutes"])
    except (TaskManagerError, OSError, ValueError, KeyError, IndexError) as exc:
        logger.warning(
            "workflow '%s' could not supply a lease default: %s", workflow, exc
        )
        return DEFAULT_LEASE_MINUTES


def load_from_root(root_path: str | None, name: str) -> dict[str, Any]:
    """Resolve a workflow against ``root_path`` (cwd fallback) and the built-ins."""
    base = _workflow_base(root_path)
    override = base / ".tasks" / "workflows" / f"{name}.md"
    if override.is_file():
        return _read_workflow_file(override, name)
    builtin = _builtin_dir().joinpath(f"{name}.md")
    if builtin.is_file():
        return _parse_template(builtin.read_text(encoding="utf-8"), source=f"{name}.md")
    raise NotFound(f"unknown workflow '{name}'")
