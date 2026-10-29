"""On-demand export of a project to Markdown or EDNL.

Export is strictly read-only with respect to the database: it opens
connections through :mod:`task_manager.db` only to read, never writes, and no
mirror is kept in sync (open question 6 — export now, mirror never).

Ordering is deterministic everywhere — ``priority, seq, id`` for tasks,
ascending ids for journal/context/relations — so two exports of the same state
are byte-identical.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import repository
from .db import Database
from .errors import ValidationError

FORMATS = ("markdown", "ednl")
SECTIONS = (
    ("In progress", ("in_progress",)),
    ("Open", ("open",)),
    ("Blocked", ("blocked",)),
    ("Done / Closed / Cancelled", ("done", "closed", "cancelled")),
)
RELATION_LABELS = {
    "blocked_by": "blocked by",
    "related": "related",
    "discovered_during": "discovered during",
}
PREVIEW_CHARS = 1000
MAX_CHECKPOINTS = 20


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _ednl_value(text: str | None) -> str:
    if text is None:
        return ""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("\r", "")
        .replace("\n", "\\n")
    )


def _markdown(db: Database, project_id: int) -> str:
    project = repository.get_project(db, project_id)
    tasks = repository.all_tasks(db, project_id)
    relations = repository.project_relations(db, project_id)
    journal = repository.journal_for_project(db, project_id)
    counts = repository.task_counts(db, project_id)
    checkpoints = repository.checkpoint_latest(db, project_id, n=MAX_CHECKPOINTS)

    relations_by_task: dict[int, list[Any]] = {}
    for relation in relations:
        relations_by_task.setdefault(relation.task_id, []).append(relation)
    journal_by_task: dict[int, list[Any]] = {}
    for entry in journal:
        if entry.task_id is not None:
            journal_by_task.setdefault(entry.task_id, []).append(entry)

    lines: list[str] = [f"# Project: {project.slug} ({project.name})", ""]
    lines.append(
        f"> exported {db.utc_now()} · open {counts.get('open', 0)} · "
        f"in_progress {counts.get('in_progress', 0)} · "
        f"blocked {counts.get('blocked', 0)} · done {counts.get('done', 0)} · "
        f"closed {counts.get('closed', 0)} · cancelled {counts.get('cancelled', 0)}"
    )

    for heading, statuses in SECTIONS:
        section = [task for task in tasks if task.status in statuses]
        if not section:
            continue
        lines.extend(["", f"## {heading}", ""])
        for task in section:
            tags = [task.type, f"p{task.priority}", f"workflow={task.workflow}"]
            if task.owner:
                tags.append(f"owner={task.owner}")
            tags.append(f"seq={task.seq:g}")
            tags.append(f"status={task.status}")
            lines.append(f"### #{task.id} — {task.title}")
            lines.append("")
            lines.append(f"**Meta:** {', '.join(tags)}")
            if task.outcome:
                lines.append(f"**Outcome:** {task.outcome}")
            if task.block_reason:
                lines.append(f"**Reason:** {task.block_reason}")
            for relation in relations_by_task.get(task.id, []):
                label = RELATION_LABELS.get(relation.kind, relation.kind)
                lines.append(f"- {label}: #{relation.related_id}")
            if task.type == "story":
                for entry in repository.context_entries(db, task.id):
                    lines.append(f"- context ({entry.created_at}): {entry.body}")
            for entry in journal_by_task.get(task.id, []):
                lines.append(f"- journal ({entry.kind}, {entry.created_at}): {entry.body}")
            lines.append("")

    if checkpoints:
        lines.extend(["## Checkpoints", ""])
        for checkpoint in checkpoints:
            scope = f"task #{checkpoint.task_id}" if checkpoint.task_id else "project"
            lines.append(
                f"- {checkpoint.created_at} ({scope}) — {_first_line(checkpoint.summary)}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _ednl(db: Database, project_id: int) -> str:
    project = repository.get_project(db, project_id)
    tasks = repository.all_tasks(db, project_id)
    relations = repository.project_relations(db, project_id)
    journal = repository.journal_for_project(db, project_id)
    checkpoints = repository.checkpoint_latest(db, project_id, n=MAX_CHECKPOINTS)

    lines = [
        f"project {project.id} slug {_ednl_value(project.slug)} "
        f"name {_ednl_value(project.name)}"
    ]
    for task in tasks:
        lines.append(
            f"task {task.id} title {_ednl_value(task.title)} status {task.status} "
            f"priority {task.priority} workflow {_ednl_value(task.workflow)} seq {task.seq:g} "
            f"type {task.type} owner {_ednl_value(task.owner)} "
            f"parent {task.parent_id if task.parent_id is not None else ''}"
        )
    for relation in relations:
        lines.append(
            f"relation {relation.task_id} {relation.kind} {relation.related_id}"
        )
    for task in tasks:
        if task.type != "story":
            continue
        for entry in repository.context_entries(db, task.id):
            lines.append(
                f"context {entry.id} task {task.id} body {_ednl_value(entry.body)}"
            )
    for entry in journal:
        lines.append(
            f"journal {entry.id} task {entry.task_id if entry.task_id is not None else ''} "
            f"kind {entry.kind} body {_ednl_value(entry.body)}"
        )
    for checkpoint in checkpoints:
        lines.append(
            f"checkpoint {checkpoint.id} project {checkpoint.project_id} "
            f"summary {_ednl_value(_first_line(checkpoint.summary))}"
        )
    return "\n".join(lines) + "\n"


def export_project(
    db: Database, project_id: int, *, fmt: str = "markdown", path: str | Path | None = None
) -> str | Path:
    """Render a project as Markdown or EDNL; write to ``path`` when given."""
    if fmt not in FORMATS:
        raise ValidationError(f"fmt must be one of {', '.join(FORMATS)}")
    text = _markdown(db, project_id) if fmt == "markdown" else _ednl(db, project_id)
    if path is None:
        return text
    target = Path(path)
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target
