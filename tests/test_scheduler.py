"""Tests for computed ready/waiting sets and task_next."""

from __future__ import annotations

import pytest

from task_manager import repository, scheduler
from task_manager.db import Database


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


def _project(db, require_closure=False):
    return repository.project_upsert(
        db, "demo", "Demo", require_closure=require_closure
    )


def _set_status(db, task_id, status):
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE id=?",
            (status, db.utc_now(), task_id),
        )
    finally:
        conn.close()


def test_no_relations_all_open_tasks_ready(db):
    project = _project(db)
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    assert {task.id for task in scheduler.ready_tasks(db, project.id)} == {
        first.id,
        second.id,
    }
    assert scheduler.waiting_tasks(db, project.id) == []
    assert scheduler.task_next(db, project.id).id == first.id


def test_blocked_by_open_task_waits(db):
    project = _project(db)
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    repository.task_link(db, first.id, second.id, "blocked_by")

    assert scheduler.is_waiting(db, first.id) is True
    assert scheduler.is_waiting(db, second.id) is False
    assert [task.id for task in scheduler.ready_tasks(db, project.id)] == [second.id]
    assert scheduler.waiting_tasks(db, project.id) == [
        {"id": first.id, "title": "A", "needs": [second.id]}
    ]
    assert scheduler.task_next(db, project.id).id == second.id


def test_done_blocker_unblocks_when_closure_not_required(db):
    project = _project(db)
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    repository.task_link(db, first.id, second.id, "blocked_by")
    _set_status(db, second.id, "done")
    assert scheduler.is_waiting(db, first.id) is False
    assert [task.id for task in scheduler.ready_tasks(db, project.id)] == [first.id]


def test_closure_required_needs_closed_blocker(db):
    project = _project(db, require_closure=True)
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    repository.task_link(db, first.id, second.id, "blocked_by")
    _set_status(db, second.id, "done")
    assert scheduler.is_waiting(db, first.id) is True
    assert scheduler.task_next(db, project.id) is None
    _set_status(db, second.id, "closed")
    assert scheduler.is_waiting(db, first.id) is False
    assert scheduler.task_next(db, project.id).id == first.id


def test_cancelled_blocker_satisfied_in_both_modes(db):
    for require_closure in (False, True):
        database = Database(db.path.parent / f"cancel-{require_closure}.sqlite")
        database.migrate()
        project = _project(database, require_closure=require_closure)
        first = repository.task_add(database, project.id, "A")
        second = repository.task_add(database, project.id, "B")
        repository.task_link(database, first.id, second.id, "blocked_by")
        repository.task_delete(database, second.id)
        assert scheduler.is_waiting(database, first.id) is False
        assert scheduler.task_next(database, project.id).id == first.id


def test_waiting_chain(db):
    project = _project(db)
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    third = repository.task_add(db, project.id, "C")
    repository.task_link(db, first.id, second.id, "blocked_by")
    repository.task_link(db, second.id, third.id, "blocked_by")
    waiting = {item["id"] for item in scheduler.waiting_tasks(db, project.id)}
    assert waiting == {first.id, second.id}
    assert [task.id for task in scheduler.ready_tasks(db, project.id)] == [third.id]


def test_blocked_status_is_orthogonal(db):
    project = _project(db)
    task = repository.task_add(db, project.id, "Blocked externally")
    _set_status(db, task.id, "blocked")
    assert scheduler.is_waiting(db, task.id) is False
    assert scheduler.ready_tasks(db, project.id) == []
    assert scheduler.waiting_tasks(db, project.id) == []


def test_task_next_ordering(db):
    project = _project(db)
    repository.task_add(db, project.id, "P2 early", priority=2)
    priority_one = repository.task_add(db, project.id, "P1", priority=1)
    repository.task_add(db, project.id, "P2 later", priority=2)
    assert scheduler.task_next(db, project.id).id == priority_one.id


def test_task_next_workflow_filter(db):
    project = _project(db)
    simple = repository.task_add(db, project.id, "Simple", workflow="simple")
    bugfix = repository.task_add(db, project.id, "Bug", workflow="bugfix")
    assert scheduler.task_next(db, project.id, workflow="bugfix").id == bugfix.id
    assert scheduler.task_next(db, project.id, workflow="simple").id == simple.id
    assert scheduler.task_next(db, project.id, workflow="spike") is None


def test_query_ready_and_waiting_match_scheduler(db):
    project = _project(db)
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    third = repository.task_add(db, project.id, "C")
    repository.task_link(db, first.id, second.id, "blocked_by")
    repository.task_link(db, third.id, second.id, "blocked_by")

    ready_ids = {task.id for task in scheduler.ready_tasks(db, project.id)}
    waiting_ids = {item["id"] for item in scheduler.waiting_tasks(db, project.id)}
    assert {
        item.id for item in repository.task_query(db, project.id, ready=True).items
    } == ready_ids
    assert {
        item.id for item in repository.task_query(db, project.id, waiting=True).items
    } == waiting_ids
    assert {
        item.id for item in repository.task_query(db, project.id, ready=False).items
    } == waiting_ids


def test_text_search_fts_and_like_fallback(db, monkeypatch):
    project = _project(db)
    title_match = repository.task_add(db, project.id, "Fix plugin loader")
    description_match = repository.task_add(
        db, project.id, "Something else", description="retry uses backoff"
    )

    assert [
        item.id for item in repository.task_query(db, project.id, text="plugin").items
    ] == [title_match.id]
    assert [
        item.id for item in repository.task_query(db, project.id, text="backoff").items
    ] == [description_match.id]

    monkeypatch.setattr(db, "fts_enabled", lambda *args, **kwargs: False)
    assert [
        item.id for item in repository.task_query(db, project.id, text="plugin").items
    ] == [title_match.id]
    assert [
        item.id for item in repository.task_query(db, project.id, text="backoff").items
    ] == [description_match.id]


def test_project_list_waiting_count(db):
    project = _project(db)
    first = repository.task_add(db, project.id, "A")
    second = repository.task_add(db, project.id, "B")
    repository.task_link(db, first.id, second.id, "blocked_by")
    summary = repository.project_list(db)[0]
    assert summary.counts["waiting"] == 1
    assert summary.counts["open"] == 2
