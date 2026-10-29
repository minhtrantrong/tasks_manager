"""T09 / TT09 — append-only journal: caps, ordering, cursor, and absence of edits."""

from __future__ import annotations

import inspect

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


@pytest.fixture()
def task(db, project):
    return repository.task_add(db, project.id, "Journal target")


def test_add_and_list_round_trip_newest_first(db, task):
    first = repository.journal_add(
        db, task_id=task.id, kind="decision", body="chose sqlite", actor="agent-7"
    )
    second = repository.journal_add(
        db,
        task_id=task.id,
        kind="attempt",
        body="tried wal2, failed",
        actor="agent-7",
        session_ref="session-1",
    )

    entries = repository.journal_list(db, task_id=task.id)
    assert [entry.id for entry in entries] == [second.id, first.id]
    assert entries[0].kind == "attempt"
    assert entries[0].body == "tried wal2, failed"
    assert entries[0].actor == "agent-7"
    assert entries[0].session_ref == "session-1"
    assert entries[0].task_id == task.id
    assert entries[0].created_at.endswith("Z")
    assert entries[1].body == "chose sqlite"


def test_project_level_note_is_scoped_to_its_project(db, project):
    other = repository.project_upsert(db, "other", "Other")
    note = repository.journal_add(
        db, project_id=project.id, kind="note", body="shared fact"
    )
    assert note.task_id is None
    assert note.project_id == project.id

    listed = repository.journal_list(db, project_id=project.id)
    assert [entry.id for entry in listed] == [note.id]
    assert repository.journal_list(db, project_id=other.id) == []


def test_project_listing_includes_task_entries(db, project, task):
    repository.journal_add(db, task_id=task.id, kind="result", body="task entry")
    note = repository.journal_add(
        db, project_id=project.id, kind="note", body="project entry"
    )
    bodies = [entry.body for entry in repository.journal_list(db, project_id=project.id)]
    assert bodies == ["project entry", "task entry"]
    assert repository.journal_list(db, project_id=project.id)[0].id == note.id


def test_line_and_character_caps(db, task):
    six_lines = "\n".join(f"line {index}" for index in range(6))
    accepted = repository.journal_add(db, task_id=task.id, kind="note", body=six_lines)
    assert len(accepted.body.splitlines()) == 6

    seven_lines = "\n".join(f"line {index}" for index in range(7))
    with pytest.raises(ValidationError):
        repository.journal_add(db, task_id=task.id, kind="note", body=seven_lines)

    at_limit = "a" * repository.MAX_JOURNAL_BODY
    assert len(repository.journal_add(db, task_id=task.id, kind="note", body=at_limit).body) == (
        repository.MAX_JOURNAL_BODY
    )

    over_limit = "a" * 1600
    with pytest.raises(ValidationError, match="6 lines / 1500 chars"):
        repository.journal_add(db, task_id=task.id, kind="note", body=over_limit)


def test_trailing_newline_is_normalised(db, task):
    plain = repository.journal_add(
        db, task_id=task.id, kind="note", body="one\ntwo\nthree\nfour\nfive\nsix"
    )
    padded = repository.journal_add(
        db, task_id=task.id, kind="note", body="one\ntwo\nthree\nfour\nfive\nsix\n"
    )
    assert padded.body == plain.body


def test_kind_and_body_validation(db, task):
    with pytest.raises(ValidationError):
        repository.journal_add(db, task_id=task.id, kind="rant", body="nope")
    with pytest.raises(ValidationError):
        repository.journal_add(db, task_id=task.id, kind="note", body="   ")
    with pytest.raises(ValidationError):
        repository.journal_add(
            db, task_id=task.id, kind="note", body="ok", session_ref="x" * 101
        )


def test_id_resolution_rules(db, project, task):
    other = repository.project_upsert(db, "other", "Other")

    with pytest.raises(NotFound):
        repository.journal_add(db, task_id=999, kind="note", body="missing")

    with pytest.raises(ValidationError):
        repository.journal_add(db, kind="note", body="no scope")

    entry = repository.journal_add(
        db,
        task_id=task.id,
        project_id=other.id,
        kind="note",
        body="task wins",
    )
    assert entry.project_id == project.id
    assert entry.task_id == task.id


def test_before_cursor_paginates_without_gaps_or_duplicates(db, task):
    created = [
        repository.journal_add(db, task_id=task.id, kind="note", body=f"entry {index}")
        for index in range(7)
    ]

    first_page = repository.journal_list(db, task_id=task.id, limit=3)
    second_page = repository.journal_list(
        db, task_id=task.id, limit=3, before=first_page[-1].id
    )
    third_page = repository.journal_list(
        db, task_id=task.id, limit=3, before=second_page[-1].id
    )

    paged = [*first_page, *second_page, *third_page]
    assert [entry.id for entry in paged] == [entry.id for entry in reversed(created)]
    assert len({entry.id for entry in paged}) == 7


def test_limit_is_capped_at_one_hundred(db, task):
    assert repository.journal_list(db, task_id=task.id, limit=1000) == []


def test_task_get_shows_newest_journal_entry_first(db, task):
    repository.journal_add(db, task_id=task.id, kind="note", body="oldest")
    newest = repository.journal_add(db, task_id=task.id, kind="result", body="newest")

    detail = repository.task_get(db, task.id, journal_limit=1)
    assert [entry.id for entry in detail.journal] == [newest.id]
    assert detail.journal[0].body == "newest"

    full = repository.task_get(db, task.id, journal_limit=5)
    assert [entry.body for entry in full.journal] == ["newest", "oldest"]


def test_no_update_or_delete_symbol_exists():
    source = inspect.getsource(repository)
    assert not hasattr(repository, "update_journal")
    assert not hasattr(repository, "delete_journal")
    assert "UPDATE journal" not in source
    assert "DELETE FROM journal" not in source


def test_hard_delete_cascades_but_soft_cancel_keeps_entries(db, project):
    doomed = repository.task_add(db, project.id, "Doomed")
    survivor = repository.task_add(db, project.id, "Survivor")
    repository.journal_add(db, task_id=doomed.id, kind="note", body="goes away")
    repository.journal_add(db, task_id=survivor.id, kind="note", body="stays")

    repository.task_cancel(db, survivor.id, actor="tester")
    assert [entry.body for entry in repository.journal_list(db, task_id=survivor.id)] == [
        "stays"
    ]

    repository.task_delete(db, doomed.id, hard=True)
    with pytest.raises(NotFound):
        repository.journal_list(db, task_id=doomed.id)
    assert [
        entry.body for entry in repository.journal_list(db, project_id=project.id)
    ] == ["stays"]


def test_entries_survive_reopen_and_cancel(db, project):
    task = repository.task_add(db, project.id, "Lifecycle")
    started = repository.task_start(db, task.id, actor="agent-1", lease_minutes=10)
    assert started.status == "in_progress"
    repository.task_complete(db, task.id, actor="agent-1", outcome="shipped")
    repository.journal_add(db, task_id=task.id, kind="result", body="verified")

    repository.task_reopen(db, task.id, actor="agent-2", lease_minutes=10)
    repository.task_cancel(db, task.id, actor="agent-2")

    bodies = [entry.body for entry in repository.journal_list(db, task_id=task.id)]
    assert "verified" in bodies
    assert bodies[0].startswith("Prior outcome")
    assert "shipped" in bodies[0]
