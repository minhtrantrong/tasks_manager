"""Tests for lazy lease reaping and the require_closure end-to-end rule."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from task_manager import repository, scheduler
from task_manager.db import Database

PAST = "2000-01-01T00:00:00Z"


def _expire(db: Database, task_id: int) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "UPDATE tasks SET lease_expires_at=? WHERE id=?", (PAST, task_id)
        )
    finally:
        conn.close()


def _reap_worker(db_path: str, queue) -> None:
    database = Database(Path(db_path))
    queue.put(repository.reap_expired_leases(database))


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


@pytest.fixture()
def project(db):
    return repository.project_upsert(db, "demo", "Demo")


def test_expired_lease_is_reaped_and_reported(db, project):
    task = repository.task_add(db, project.id, "Crashed")
    repository.task_start(db, task.id, actor="agent-1")
    _expire(db, task.id)

    assert repository.reap_expired_leases(db) == [task.id]
    fetched = repository.task_get(db, task.id)
    assert fetched.status == "open"
    assert fetched.owner is None
    assert fetched.lease_expires_at is None


def test_reads_reap_lazily(db, project):
    task = repository.task_add(db, project.id, "Crashed")
    repository.task_start(db, task.id, actor="agent-1")
    _expire(db, task.id)
    fetched = repository.task_get(db, task.id)
    assert fetched.status == "open"
    assert repository.reap_expired_leases(db) == []


def test_unexpired_lease_untouched(db, project):
    task = repository.task_add(db, project.id, "Running")
    started = repository.task_start(db, task.id, actor="agent-1", lease_minutes=60)
    fetched = repository.task_get(db, task.id)
    assert fetched.status == "in_progress"
    assert fetched.owner == "agent-1"
    assert fetched.lease_expires_at == started.lease_expires_at
    assert repository.reap_expired_leases(db) == []


def test_two_processes_reap_exactly_once(tmp_path):
    db_path = tmp_path / "race.sqlite"
    db = Database(db_path)
    db.migrate()
    project = repository.project_upsert(db, "demo", "Demo")
    task = repository.task_add(db, project.id, "Crashed")
    repository.task_start(db, task.id, actor="agent-1")
    _expire(db, task.id)

    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=_reap_worker, args=(str(db_path), queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    assert sorted(results) == [[], [task.id]]


def test_reaped_task_can_be_claimed_again(db, project):
    task = repository.task_add(db, project.id, "Crashed")
    repository.task_start(db, task.id, actor="agent-1")
    _expire(db, task.id)
    repository.reap_expired_leases(db)
    reclaimed = repository.task_start(db, task.id, actor="agent-2")
    assert reclaimed.status == "in_progress"
    assert reclaimed.owner == "agent-2"


def test_require_closure_end_to_end(db):
    project = repository.project_upsert(db, "demo", "Demo", require_closure=True)
    blocker = repository.task_add(db, project.id, "Blocker")
    dependent = repository.task_add(db, project.id, "Dependent", blocked_by=[blocker.id])

    repository.task_start(db, blocker.id, actor="agent-1")
    repository.task_complete(db, blocker.id, actor="agent-1", outcome="merged")
    assert scheduler.is_waiting(db, dependent.id) is True
    assert scheduler.task_next(db, project.id) is None

    repository.task_close(db, blocker.id, actor="agent-1")
    assert scheduler.is_waiting(db, dependent.id) is False
    assert scheduler.task_next(db, project.id).id == dependent.id


def test_all_read_call_sites_reap(db, project):
    task = repository.task_add(db, project.id, "Crashed")
    repository.task_start(db, task.id, actor="agent-1")

    _expire(db, task.id)
    page = repository.task_query(db, project.id)
    assert page.items[0].status == "open"

    _expire(db, task.id)
    graph = repository.task_graph(db, project.id)
    assert graph.nodes[0].status == "open"

    _expire(db, task.id)
    assert scheduler.task_next(db, project.id).id == task.id
