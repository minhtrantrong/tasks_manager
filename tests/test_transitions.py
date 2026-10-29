"""Tests for the lifecycle state machine, leases, and transition invariants."""

from __future__ import annotations

import inspect

import pytest

from task_manager import repository
from task_manager.db import Database
from task_manager.errors import (
    IllegalTransition,
    LeaseConflict,
    MissingOutcome,
    MissingReason,
)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


@pytest.fixture()
def project(db):
    return repository.project_upsert(db, "demo", "Demo")


def _new(db, project, title="Task"):
    return repository.task_add(db, project.id, title)


def _make(db, project, status, title="Task"):
    task = _new(db, project, title)
    if status == "open":
        return task
    if status == "in_progress":
        return repository.task_start(db, task.id, actor="agent-1")
    if status == "blocked":
        return repository.task_block(db, task.id, actor="agent-1", reason="external")
    if status == "done":
        repository.task_start(db, task.id, actor="agent-1")
        return repository.task_complete(db, task.id, actor="agent-1", outcome="verified")
    if status == "closed":
        repository.task_start(db, task.id, actor="agent-1")
        repository.task_complete(db, task.id, actor="agent-1", outcome="verified")
        return repository.task_close(db, task.id, actor="agent-1")
    if status == "cancelled":
        return repository.task_cancel(db, task.id, actor="agent-1")
    raise AssertionError(status)


def test_every_legal_edge(db, project):
    started = repository.task_start(db, _new(db, project, "start").id, actor="agent-1")
    assert started.status == "in_progress"
    assert started.owner == "agent-1"
    assert started.lease_expires_at is not None
    assert started.started_at is not None

    blocked = repository.task_block(
        db, _new(db, project, "block").id, actor="agent-1", reason="needs key"
    )
    assert blocked.status == "blocked"
    assert blocked.block_reason == "needs key"

    cancelled = repository.task_cancel(db, _new(db, project, "cancel").id, actor="agent-1")
    assert cancelled.status == "cancelled"

    released = repository.task_release(db, _make(db, project, "in_progress").id, actor="agent-1")
    assert released.status == "open"
    assert released.owner is None
    assert released.lease_expires_at is None

    blocked_from_progress = repository.task_block(
        db, _make(db, project, "in_progress").id, actor="agent-1", reason="stuck"
    )
    assert blocked_from_progress.status == "blocked"
    assert blocked_from_progress.owner is None

    completed = repository.task_complete(
        db, _make(db, project, "in_progress").id, actor="agent-1", outcome="done and tested"
    )
    assert completed.status == "done"
    assert completed.outcome == "done and tested"
    assert completed.finished_at is not None
    assert completed.owner is None
    assert completed.lease_expires_at is None

    cancelled_from_progress = repository.task_cancel(
        db, _make(db, project, "in_progress").id, actor="agent-1"
    )
    assert cancelled_from_progress.status == "cancelled"
    assert cancelled_from_progress.owner is None
    assert cancelled_from_progress.lease_expires_at is None

    unblocked = repository.task_unblock(
        db, _make(db, project, "blocked").id, actor="agent-1"
    )
    assert unblocked.status == "open"
    assert unblocked.block_reason is None

    cancelled_from_blocked = repository.task_cancel(
        db, _make(db, project, "blocked").id, actor="agent-1"
    )
    assert cancelled_from_blocked.status == "cancelled"

    closed = repository.task_close(db, _make(db, project, "done").id, actor="agent-1")
    assert closed.status == "closed"
    assert closed.outcome is not None

    reopened = repository.task_reopen(db, _make(db, project, "done").id, actor="agent-2")
    assert reopened.status == "in_progress"
    assert reopened.owner == "agent-2"
    assert reopened.outcome is None
    assert reopened.finished_at is None
    detail = repository.task_get(db, reopened.id)
    assert detail.journal[0].kind == "result"
    assert "Prior outcome" in detail.journal[0].body

    reopened_closed = repository.task_reopen(
        db, _make(db, project, "closed").id, actor="agent-2"
    )
    assert reopened_closed.status == "in_progress"

    assert (
        repository.task_cancel(db, _make(db, project, "done").id, actor="a").status
        == "cancelled"
    )
    assert (
        repository.task_cancel(db, _make(db, project, "closed").id, actor="a").status
        == "cancelled"
    )


def test_illegal_edges_name_both_statuses(db, project):
    open_task = _new(db, project, "open")
    with pytest.raises(IllegalTransition) as excinfo:
        repository.task_complete(db, open_task.id, actor="a", outcome="x")
    assert "open" in str(excinfo.value) and "complete" in str(excinfo.value)

    blocked_task = _make(db, project, "blocked")
    with pytest.raises(IllegalTransition) as excinfo:
        repository.task_close(db, blocked_task.id, actor="a")
    assert "blocked" in str(excinfo.value) and "close" in str(excinfo.value)

    done_task = _make(db, project, "done")
    with pytest.raises(IllegalTransition) as excinfo:
        repository.task_start(db, done_task.id, actor="a")
    assert "done" in str(excinfo.value) and "start" in str(excinfo.value)

    with pytest.raises(IllegalTransition):
        repository.task_release(db, open_task.id, actor="a")
    with pytest.raises(IllegalTransition):
        repository.task_unblock(db, open_task.id, actor="a")
    with pytest.raises(IllegalTransition):
        repository.task_block(db, done_task.id, actor="a", reason="x")
    cancelled = _make(db, project, "cancelled")
    with pytest.raises(IllegalTransition):
        repository.task_cancel(db, cancelled.id, actor="a")


def test_complete_requires_outcome(db, project):
    task = _make(db, project, "in_progress")
    with pytest.raises(MissingOutcome):
        repository.task_complete(db, task.id, actor="a", outcome="")
    with pytest.raises(MissingOutcome):
        repository.task_complete(db, task.id, actor="a", outcome="   ")
    with pytest.raises(MissingOutcome):
        repository.task_complete(db, task.id, actor="a", outcome="x" * 501)


def test_block_requires_reason_and_journals_it(db, project):
    task = _new(db, project, "block")
    with pytest.raises(MissingReason):
        repository.task_block(db, task.id, actor="a", reason="")
    with pytest.raises(MissingReason):
        repository.task_block(db, task.id, actor="a", reason="   ")
    blocked = repository.task_block(db, task.id, actor="agent-7", reason="waiting on API key")
    assert blocked.status == "blocked"
    detail = repository.task_get(db, task.id)
    assert detail.journal[0].kind == "problem"
    assert detail.journal[0].body == "waiting on API key"
    assert detail.journal[0].actor == "agent-7"


def test_start_is_idempotent_for_same_actor(db, project):
    task = _new(db, project, "idempotent")
    first = repository.task_start(db, task.id, actor="agent-1", lease_minutes=30)
    second = repository.task_start(db, task.id, actor="agent-1", lease_minutes=30)
    assert first.lease_expires_at == second.lease_expires_at
    assert second.owner == "agent-1"


def test_start_conflict_for_other_actor(db, project):
    task = _new(db, project, "conflict")
    repository.task_start(db, task.id, actor="agent-1")
    with pytest.raises(LeaseConflict):
        repository.task_start(db, task.id, actor="agent-2")


def test_release_ownership_and_force(db, project):
    task = _make(db, project, "in_progress")
    with pytest.raises(LeaseConflict):
        repository.task_release(db, task.id, actor="agent-2")
    released = repository.task_release(db, task.id, actor="agent-2", force=True)
    assert released.status == "open"
    assert released.owner is None


def test_unblock_to_in_progress_leases(db, project):
    task = _make(db, project, "blocked")
    unblocked = repository.task_unblock(
        db, task.id, actor="agent-9", to="in_progress"
    )
    assert unblocked.status == "in_progress"
    assert unblocked.owner == "agent-9"
    assert unblocked.lease_expires_at is not None
    assert unblocked.block_reason is None


def test_cancel_from_in_progress_clears_lease(db, project):
    task = _make(db, project, "in_progress")
    cancelled = repository.task_cancel(db, task.id, actor="agent-1")
    assert cancelled.status == "cancelled"
    assert cancelled.owner is None
    assert cancelled.lease_expires_at is None


def test_full_happy_path(db, project):
    task = _new(db, project, "Full path")
    assert repository.task_start(db, task.id, actor="a").status == "in_progress"
    assert (
        repository.task_block(db, task.id, actor="a", reason="need input").status
        == "blocked"
    )
    assert repository.task_unblock(db, task.id, actor="a").status == "open"
    assert repository.task_start(db, task.id, actor="a").status == "in_progress"
    assert (
        repository.task_complete(db, task.id, actor="a", outcome="shipped").status == "done"
    )
    final = repository.task_close(db, task.id, actor="a")
    assert final.status == "closed"
    assert final.outcome == "shipped"


def test_no_lifecycle_function_accepts_status():
    lifecycle = [
        repository.task_start,
        repository.task_release,
        repository.task_complete,
        repository.task_close,
        repository.task_block,
        repository.task_unblock,
        repository.task_reopen,
        repository.task_cancel,
        repository.task_update,
    ]
    for function in lifecycle:
        assert "status" not in inspect.signature(function).parameters
