"""T11 / TT11 — recall over tasks + journal with an FTS5 path and a LIKE fallback."""

from __future__ import annotations

import pytest

from task_manager import repository
from task_manager.db import Database
from task_manager.errors import FtsUnavailable, ValidationError


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


@pytest.fixture()
def project(db):
    return repository.project_upsert(db, "demo", "Demo")


def _disable_fts(monkeypatch):
    monkeypatch.setattr(
        Database, "fts_enabled", lambda self, conn=None: False, raising=True
    )


def test_journal_hit_found_by_multi_term_query(db, project):
    task = repository.task_add(db, project.id, "Retry policy")
    repository.journal_add(
        db,
        task_id=task.id,
        kind="attempt",
        body="retry uses backoff 2^n",
        actor="agent-7",
    )

    hits = repository.recall(db, "backoff retry")
    assert hits, "expected a journal hit"
    journal_hits = [hit for hit in hits if hit.source == "journal"]
    assert journal_hits[0].task_id == task.id
    assert journal_hits[0].project_id == project.id
    assert "backoff" in journal_hits[0].snippet
    assert journal_hits[0].created_at.endswith("Z")


def test_task_found_by_title_and_by_description(db, project):
    titled = repository.task_add(db, project.id, "Plugin loader crash")
    described = repository.task_add(
        db, project.id, "Unrelated title", description="narrowing the Protocol fixes it"
    )

    by_title = repository.recall(db, "plugin loader")
    assert {hit.task_id for hit in by_title if hit.source == "task"} == {titled.id}

    by_description = repository.recall(db, "narrowing protocol")
    assert {hit.task_id for hit in by_description if hit.source == "task"} == {
        described.id
    }


def test_project_scoping(db, project):
    other = repository.project_upsert(db, "other", "Other")
    mine = repository.task_add(db, project.id, "Shared needle here")
    theirs = repository.task_add(db, other.id, "Shared needle there")

    scoped = repository.recall(db, "needle", project_id=project.id)
    assert {hit.task_id for hit in scoped} == {mine.id}

    unscoped = repository.recall(db, "needle")
    assert {hit.task_id for hit in unscoped} == {mine.id, theirs.id}

    repository.project_archive(db, other.id)
    archived = repository.recall(db, "needle")
    assert {hit.task_id for hit in archived} == {mine.id}


def test_limit_and_journal_ordering(db, project):
    for index in range(3):
        task = repository.task_add(db, project.id, f"Deploy step {index}")
        repository.journal_add(
            db, task_id=task.id, kind="note", body=f"deploy attempt {index}"
        )

    hits = repository.recall(db, "deploy", limit=2)
    assert len(hits) == 2
    assert [hit.source for hit in hits] == ["journal", "journal"]

    mixed = repository.recall(db, "deploy", limit=20)
    sources = [hit.source for hit in mixed]
    assert sources == sorted(sources, key=lambda value: value != "journal")
    assert len(mixed) <= repository.MAX_RECALL_LIMIT


def test_hostile_queries_never_raise(db, project):
    task = repository.task_add(db, project.id, "Quotes and operators")
    repository.journal_add(db, task_id=task.id, kind="note", body='say "hello" NEAR')

    for query in ['"hello"', "*", "(hello)", "-hello", "NEAR", "NEAR(hello)", '"', "***"]:
        assert isinstance(repository.recall(db, query), list)


def test_blank_query_rejected(db):
    for query in ("", "   ", "\n\t"):
        with pytest.raises(ValidationError):
            repository.recall(db, query)


def test_like_fallback_finds_the_same_material(db, project, monkeypatch):
    task = repository.task_add(db, project.id, "Retry policy")
    repository.journal_add(
        db, task_id=task.id, kind="attempt", body="retry uses backoff 2^n"
    )
    _disable_fts(monkeypatch)

    assert repository.search_backend(db) == "like"
    hits = repository.recall(db, "backoff retry")
    assert [hit.source for hit in hits] == ["journal"]
    assert hits[0].task_id == task.id
    assert "backoff" in hits[0].snippet

    task_hits = repository.recall(db, "retry policy")
    assert {hit.task_id for hit in task_hits if hit.source == "task"} == {task.id}


def test_require_fts_raises_when_unavailable(db, project, monkeypatch):
    repository.task_add(db, project.id, "Anything")
    _disable_fts(monkeypatch)
    with pytest.raises(FtsUnavailable):
        repository.recall(db, "anything", require_fts=True)


def test_backend_reports_fts_when_available(db):
    assert repository.search_backend(db) == "fts"


def test_relevance_on_a_large_project(db, project):
    tasks = [
        repository.task_add(db, project.id, f"Filler task {index}") for index in range(50)
    ]
    needle = tasks[17]
    repository.journal_add(
        db,
        task_id=needle.id,
        kind="problem",
        body="the api key rotation hook is missing",
    )

    hits = repository.recall(db, "api key", limit=5)
    top_ids = [hit.task_id for hit in hits[:3]]
    assert needle.id in top_ids


def test_cancelled_task_hits_carry_status(db, project):
    task = repository.task_add(db, project.id, "Cancelled needle")
    repository.task_cancel(db, task.id, actor="tester")

    hits = repository.recall(db, "cancelled needle")
    assert hits
    assert hits[0].task_id == task.id
    assert hits[0].status == "cancelled"


def test_hard_deleted_task_leaves_no_hit(db, project):
    task = repository.task_add(db, project.id, "Ephemeral needle")
    repository.journal_add(db, task_id=task.id, kind="note", body="ephemeral needle")
    repository.task_delete(db, task.id, hard=True)

    assert repository.recall(db, "ephemeral") == []
