"""T12 / TT12 — session events and retry-safe checkpoints."""

from __future__ import annotations

import pytest

from task_manager import repository
from task_manager.db import Database
from task_manager.errors import NotFound, ValidationError


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


@pytest.fixture()
def project(db):
    return repository.project_upsert(db, "demo", "Demo")


@pytest.mark.parametrize(
    "kind", ["session_start", "compaction", "prompt", "task_switch"]
)
def test_session_event_round_trip(db, project, kind):
    event = repository.session_event(db, project.id, kind, detail="context")
    assert event.kind == kind
    assert event.project_id == project.id
    assert event.task_id is None
    assert event.detail == "context"
    assert event.created_at.endswith("Z")


def test_session_event_accepts_task_and_rejects_unknown_kind(db, project):
    task = repository.task_add(db, project.id, "Active")
    event = repository.session_event(
        db, project.id, "task_switch", task_id=task.id, detail="switched"
    )
    assert event.task_id == task.id

    with pytest.raises(ValidationError):
        repository.session_event(db, project.id, "nap")
    with pytest.raises(NotFound):
        repository.session_event(db, 999, "prompt")
    with pytest.raises(ValidationError):
        repository.session_event(db, project.id, "prompt", detail="x" * 2001)


def test_cross_project_task_is_rejected(db, project):
    other = repository.project_upsert(db, "other", "Other")
    foreign = repository.task_add(db, other.id, "Foreign")

    with pytest.raises(ValidationError):
        repository.session_event(db, project.id, "session_start", task_id=foreign.id)
    with pytest.raises(ValidationError):
        repository.checkpoint_save(db, project.id, "summary", task_id=foreign.id)


def test_checkpoint_save_is_idempotent(db, project):
    first = repository.checkpoint_save(
        db,
        project.id,
        "first summary",
        next_actions=["do the thing", "verify the thing"],
    )
    assert first.next_actions == ["do the thing", "verify the thing"]

    repeat = repository.checkpoint_save(
        db,
        project.id,
        "first summary",
        next_actions=["do the thing", "verify the thing"],
    )
    assert repeat.id == first.id
    assert len(repository.checkpoint_latest(db, project.id, n=20)) == 1

    changed = repository.checkpoint_save(db, project.id, "second summary")
    assert changed.id != first.id
    assert len(repository.checkpoint_latest(db, project.id, n=20)) == 2


def test_checkpoint_latest_order_and_scoping(db, project):
    task = repository.task_add(db, project.id, "Scoped")
    project_one = repository.checkpoint_save(db, project.id, "project one")
    project_two = repository.checkpoint_save(db, project.id, "project two")
    task_one = repository.checkpoint_save(db, project.id, "task one", task_id=task.id)

    project_rows = repository.checkpoint_latest(db, project.id, n=2)
    assert [row.id for row in project_rows] == [project_two.id, project_one.id]

    task_rows = repository.checkpoint_latest(db, project.id, task_id=task.id)
    assert [row.id for row in task_rows] == [task_one.id]


def test_checkpoint_caps(db, project):
    sixty_lines = "\n".join(f"line {index}" for index in range(60))
    accepted = repository.checkpoint_save(db, project.id, sixty_lines)
    assert len(accepted.summary.splitlines()) == 60

    sixty_one_lines = "\n".join(f"line {index}" for index in range(61))
    with pytest.raises(ValidationError):
        repository.checkpoint_save(db, project.id, sixty_one_lines)
    with pytest.raises(ValidationError):
        repository.checkpoint_save(db, project.id, "x" * 4001)
    with pytest.raises(ValidationError):
        repository.checkpoint_save(db, project.id, "")
    with pytest.raises(ValidationError):
        repository.checkpoint_save(
            db, project.id, "summary", next_actions=["x" * 201]
        )
    with pytest.raises(ValidationError):
        repository.checkpoint_save(
            db, project.id, "summary", next_actions=[f"action {i}" for i in range(11)]
        )
    with pytest.raises(ValidationError):
        repository.checkpoint_save(db, project.id, "summary", next_actions="nope")
    with pytest.raises(ValidationError):
        repository.checkpoint_save(db, project.id, "summary", next_actions=[1])


def test_checkpoint_n_cap_and_tie_break(db, project):
    for index in range(25):
        repository.checkpoint_save(db, project.id, f"summary {index}")
    rows = repository.checkpoint_latest(db, project.id, n=100)
    assert len(rows) == repository.MAX_CHECKPOINTS
    assert [row.id for row in rows] == sorted((row.id for row in rows), reverse=True)


def test_session_events_are_append_only(db):
    import inspect

    source = inspect.getsource(repository)
    assert not hasattr(repository, "session_event_update")
    assert not hasattr(repository, "session_event_delete")
    assert "UPDATE session_events" not in source
    assert "DELETE FROM session_events" not in source


def test_compaction_count_since_checkpoint(db, project, monkeypatch):
    import task_manager.db as db_module

    clock = {"now": "2026-10-30T09:00:00.000000Z"}
    monkeypatch.setattr(db_module, "utc_now", lambda: clock["now"])

    assert repository.session_event_count_since(db, project.id, "compaction", None) == 0
    repository.session_event(db, project.id, "compaction")

    clock["now"] = "2026-10-30T09:05:00.000000Z"
    checkpoint = repository.checkpoint_save(db, project.id, "here")

    clock["now"] = "2026-10-30T09:10:00.000000Z"
    repository.session_event(db, project.id, "compaction")
    clock["now"] = "2026-10-30T09:11:00.000000Z"
    repository.session_event(db, project.id, "session_start")

    assert (
        repository.session_event_count_since(
            db, project.id, "compaction", checkpoint.created_at
        )
        == 1
    )

    clock["now"] = "2026-10-30T09:20:00.000000Z"
    fresh = repository.checkpoint_save(db, project.id, "fresh")
    assert (
        repository.session_event_count_since(
            db, project.id, "compaction", fresh.created_at
        )
        == 0
    )
