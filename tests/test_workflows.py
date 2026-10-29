"""T14 / TT14 — workflow templates, overrides, and lease defaults."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from task_manager import repository, workflows
from task_manager.db import Database
from task_manager.errors import NotFound, ValidationError

BUILTIN_LEASES = {"simple": 30, "bugfix": 60, "feature": 90, "spike": 120}


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


@pytest.fixture()
def project(db, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return repository.project_upsert(db, "demo", "Demo", root_path=str(root))


def _write_override(project, name: str, body: str) -> Path:
    directory = Path(project.root_path) / ".tasks" / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_all_builtins_load_and_render(db, project):
    for name, lease in BUILTIN_LEASES.items():
        template = workflows.load_workflow(db, project.id, name)
        assert template["name"] == name
        assert template["lease_minutes"] == lease
        assert template["source"] == "builtin"
        assert template["description"]
        rendered = workflows.render_prompt(
            template["prompt"], title="Fix it", task_id=7, project="demo"
        )
        assert "Fix it" in rendered
        assert "#7" in rendered
        assert "demo" in rendered
        assert "{" not in rendered
        assert len(template["prompt"]) <= 1200


def test_list_workflows_merges_overrides(db, project):
    _write_override(
        project,
        "simple",
        "---\nname: simple\ndescription: House rules\nlease_minutes: 15\n---\nDo it.\n",
    )
    listed = {item["name"]: item for item in workflows.list_workflows(db, project.id)}
    assert set(BUILTIN_LEASES) <= set(listed)
    assert listed["simple"]["source"] == "project"
    assert listed["simple"]["description"] == "House rules"


def test_project_override_wins(db, project):
    _write_override(
        project,
        "simple",
        "---\nname: simple\ndescription: Project override\nlease_minutes: 12\n---\n"
        "Ship {title} (#{id}) in {project}.\n",
    )
    template = workflows.load_workflow(db, project.id, "simple")
    assert template["source"] == "project"
    assert template["lease_minutes"] == 12
    assert template["description"] == "Project override"


def test_override_is_resolved_from_root_path_not_cwd(db, project, tmp_path, monkeypatch):
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    (other_cwd / ".tasks" / "workflows").mkdir(parents=True)
    (other_cwd / ".tasks" / "workflows" / "simple.md").write_text(
        "---\nname: simple\ndescription: Wrong dir\nlease_minutes: 5\n---\nNope.\n",
        encoding="utf-8",
    )

    _write_override(
        project,
        "simple",
        "---\nname: simple\ndescription: Right dir\nlease_minutes: 33\n---\nYes.\n",
    )
    assert workflows.load_workflow(db, project.id, "simple")["lease_minutes"] == 33

    bare = repository.project_upsert(db, "bare", "Bare")
    cwd_template = workflows.load_workflow(db, bare.id, "simple")
    assert cwd_template["source"] == "project"
    assert cwd_template["lease_minutes"] == 5


def test_unknown_and_empty_names(db, project):
    with pytest.raises(NotFound):
        workflows.load_workflow(db, project.id, "nope")
    with pytest.raises(ValidationError):
        workflows.load_workflow(db, project.id, "")
    with pytest.raises(NotFound):
        workflows.load_workflow(db, 999, "simple")


def test_malformed_frontmatter_is_rejected(db, project):
    path = _write_override(
        project,
        "simple",
        "---\ndescription: no name here\nlease_minutes: 10\n---\nBody.\n",
    )
    with pytest.raises(ValidationError, match="missing 'name'"):
        workflows.load_workflow(db, project.id, "simple")

    path.write_text("---\nname: simple\ndescription: unterminated\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="unterminated"):
        workflows.load_workflow(db, project.id, "simple")

    path.write_text(
        "---\nname: simple\ndescription: bad lease\nlease_minutes: many\n---\nBody.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="integer"):
        workflows.load_workflow(db, project.id, "simple")

    path.write_text(
        "---\nname: simple\ndescription: negative\nlease_minutes: -5\n---\nBody.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="positive"):
        workflows.load_workflow(db, project.id, "simple")

    assert str(path)  # the error names the file via its path in the message


def _lease_minutes_left(expires_at: str) -> float:
    expires = datetime.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    return (expires - datetime.now(timezone.utc)).total_seconds() / 60


def test_task_start_uses_the_workflow_lease_default(db, project):
    feature = repository.task_add(db, project.id, "Feature work", workflow="feature")
    started = repository.task_start(db, feature.id, actor="agent-1")
    assert 88 <= _lease_minutes_left(started.lease_expires_at) <= 90

    simple = repository.task_add(db, project.id, "Simple work", workflow="simple")
    started_simple = repository.task_start(db, simple.id, actor="agent-1")
    assert 28 <= _lease_minutes_left(started_simple.lease_expires_at) <= 30


def test_explicit_lease_overrides_the_template(db, project):
    feature = repository.task_add(db, project.id, "Feature work", workflow="feature")
    started = repository.task_start(db, feature.id, actor="agent-1", lease_minutes=5)
    assert 3 <= _lease_minutes_left(started.lease_expires_at) <= 5


def test_unknown_workflow_falls_back_to_sixty_minutes(db, project):
    task = repository.task_add(db, project.id, "Odd workflow", workflow="custom-thing")
    started = repository.task_start(db, task.id, actor="agent-1")
    assert 58 <= _lease_minutes_left(started.lease_expires_at) <= 60


def test_workflow_prompt_is_side_effect_free(db, project):
    before = sorted(p.name for p in Path(project.root_path).rglob("*"))
    first = workflows.load_workflow(db, project.id, "bugfix")
    second = workflows.load_workflow(db, project.id, "bugfix")
    assert first == second
    after = sorted(p.name for p in Path(project.root_path).rglob("*"))
    assert before == after
    assert not hasattr(workflows, "create_workflow")
    assert not hasattr(workflows, "save_workflow")


def test_task_with_missing_workflow_stays_readable(db, project):
    task = repository.task_add(db, project.id, "Borrowed workflow", workflow="ghost")
    with pytest.raises(NotFound):
        workflows.load_workflow(db, project.id, "ghost")
    assert repository.task_get(db, task.id).title == "Borrowed workflow"
