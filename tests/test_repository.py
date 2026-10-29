"""Tests for project and task CRUD in the repository."""

from __future__ import annotations

import inspect

import pytest

from task_manager import repository
from task_manager.db import Database, utc_now
from task_manager.errors import NotFound, ValidationError


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


@pytest.fixture()
def project(db):
    return repository.project_upsert(db, "demo", "Demo Project")


def test_project_upsert_is_idempotent(db):
    first = repository.project_upsert(db, "demo", "Demo")
    second = repository.project_upsert(db, "demo", "Demo Renamed")
    assert first.id == second.id
    assert second.name == "Demo Renamed"
    assert len(repository.project_list(db)) == 1


def test_slug_collision_updates_never_inserts(db):
    repository.project_upsert(db, "demo", "First")
    second = repository.project_upsert(db, "demo", "Second")
    assert second.slug == "demo"
    assert second.name == "Second"
    assert len(repository.project_list(db)) == 1


def test_project_upsert_rejects_empty_slug(db):
    with pytest.raises(ValidationError):
        repository.project_upsert(db, "  ", "Demo")


def test_project_archive(db):
    project = repository.project_upsert(db, "demo", "Demo")
    archived = repository.project_archive(db, project.id)
    assert archived.archived_at is not None
    assert repository.project_list(db)[0].archived is True
    with pytest.raises(NotFound):
        repository.project_archive(db, 999)


def test_task_add_defaults(db, project):
    task = repository.task_add(db, project.id, "  Do the thing  ")
    assert task.title == "Do the thing"
    assert task.type == "task"
    assert task.workflow == "simple"
    assert task.priority == 3
    assert task.status == "open"
    assert task.meta == {}


def test_seq_monotonic_and_prepend(db, project):
    first = repository.task_add(db, project.id, "First")
    second = repository.task_add(db, project.id, "Second")
    third = repository.task_add(db, project.id, "Third")
    assert first.seq < second.seq < third.seq

    prepended = repository.task_add(db, project.id, "Before all", prepend=True)
    assert prepended.seq < first.seq
    page = repository.task_query(db, project.id)
    assert page.items[0].id == prepended.id


def test_validation_matrix(db, project):
    other = repository.project_upsert(db, "other", "Other")
    story = repository.task_add(db, project.id, "Story", type="story")
    plain = repository.task_add(db, project.id, "Plain")
    other_task = repository.task_add(db, other.id, "Other task")
    other_story = repository.task_add(db, other.id, "Other story", type="story")

    invalid_calls = [
        lambda: repository.task_add(db, project.id, "   "),
        lambda: repository.task_add(db, project.id, "x" * 201),
        lambda: repository.task_add(db, project.id, "Bad priority", priority=0),
        lambda: repository.task_add(db, project.id, "Bad priority", priority=6),
        lambda: repository.task_add(db, project.id, "Bad type", type="bogus"),
        lambda: repository.task_add(db, project.id, "Bad parent", parent_id=other_story.id),
        lambda: repository.task_add(db, project.id, "Bad parent", parent_id=plain.id),
        lambda: repository.task_add(db, project.id, "Missing parent", parent_id=99999),
        lambda: repository.task_add(db, project.id, "Bad blocker", blocked_by=[other_task.id]),
        lambda: repository.task_add(db, project.id, "Bad blocker", blocked_by=[99999]),
        lambda: repository.task_update(db, plain.id, parent_id=plain.id),
        lambda: repository.task_update(db, plain.id, parent_id=other_story.id),
        lambda: repository.task_update(db, plain.id, parent_id=plain.id),
        lambda: repository.task_update(db, plain.id, priority=9),
        lambda: repository.task_update(db, plain.id, title=""),
        lambda: repository.task_update(db, 99999, title="Nope"),
    ]
    for call in invalid_calls:
        with pytest.raises((ValidationError, NotFound)):
            call()

    # A valid story parent is accepted.
    child = repository.task_add(db, project.id, "Child", parent_id=story.id)
    assert child.parent_id == story.id
    assert story.id != child.id


def test_task_update_never_changes_status(db, project):
    task = repository.task_add(db, project.id, "Task")
    signature = inspect.signature(repository.task_update)
    assert "status" not in signature.parameters
    updated = repository.task_update(db, task.id, title="Renamed")
    assert updated.title == "Renamed"
    assert updated.status == "open"


def test_task_update_meta_and_parent(db, project):
    story = repository.task_add(db, project.id, "Story", type="story")
    task = repository.task_add(db, project.id, "Task")
    updated = repository.task_update(db, task.id, parent_id=story.id, meta={"a": 1})
    assert updated.parent_id == story.id
    assert updated.meta == {"a": 1}


def test_task_query_filters_and_pagination(db, project):
    story = repository.task_add(db, project.id, "Story", type="story", workflow="feature")
    repository.task_add(db, project.id, "Bug one", type="bug", workflow="bugfix", priority=1)
    repository.task_add(db, project.id, "Feature one", type="feature", workflow="feature")
    child = repository.task_add(
        db, project.id, "Child task", parent_id=story.id, description="needle in description"
    )

    by_status = repository.task_query(db, project.id, status="open")
    assert by_status.total == 4
    by_type = repository.task_query(db, project.id, type="bug")
    assert by_type.total == 1
    assert by_type.items[0].title == "Bug one"
    by_workflow = repository.task_query(db, project.id, workflow="feature")
    assert by_workflow.total == 2
    by_parent = repository.task_query(db, project.id, parent_id=story.id)
    assert [item.id for item in by_parent.items] == [child.id]
    by_text = repository.task_query(db, project.id, text="needle")
    assert [item.id for item in by_text.items] == [child.id]
    by_title = repository.task_query(db, project.id, text="BUG ONE")
    assert by_title.total == 1

    first_page = repository.task_query(db, project.id, limit=2, offset=0)
    second_page = repository.task_query(db, project.id, limit=2, offset=2)
    assert first_page.total == 4
    assert second_page.total == 4
    assert len(first_page.items) == 2
    assert len(second_page.items) == 2
    assert not {item.id for item in first_page.items} & {item.id for item in second_page.items}
    assert repository.task_query(db, project.id, limit=500).limit == 50

    # Default ordering is priority ASC, seq ASC, id ASC.
    ordered = repository.task_query(db, project.id).items
    assert ordered[0].priority == 1


def test_task_delete_soft_and_hard(db, project):
    task = repository.task_add(db, project.id, "Soft")
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO journal(task_id, project_id, kind, body, created_at) "
            "VALUES (?, ?, 'note', 'history', ?)",
            (task.id, project.id, utc_now()),
        )
    finally:
        conn.close()

    cancelled = repository.task_delete(db, task.id)
    assert cancelled.id == task.id
    fetched = repository.task_get(db, task.id)
    assert fetched.status == "cancelled"
    assert len(fetched.journal) == 1

    other = repository.task_add(db, project.id, "Hard")
    repository.task_delete(db, other.id, hard=True)
    with pytest.raises(NotFound):
        repository.task_get(db, other.id)


def test_task_get_relations_children_and_journal(db, project):
    story = repository.task_add(db, project.id, "Story", type="story")
    blocker = repository.task_add(db, project.id, "Blocker")
    task = repository.task_add(db, project.id, "Main", parent_id=story.id, blocked_by=[blocker.id])
    conn = db.connect()
    try:
        for index in range(3):
            conn.execute(
                "INSERT INTO journal(task_id, project_id, kind, body, created_at) "
                "VALUES (?, ?, 'note', ?, ?)",
                (task.id, project.id, f"entry {index}", utc_now()),
            )
    finally:
        conn.close()

    detail = repository.task_get(db, task.id, journal_limit=2)
    assert detail.parent_id == story.id
    assert [child.id for child in detail.children] == []
    assert {rel.kind for rel in detail.relations} == {"blocked_by"}
    assert detail.relations[0].related_id == blocker.id
    assert len(detail.journal) == 2
    assert detail.journal[0].body == "entry 2"

    story_detail = repository.task_get(db, story.id)
    assert [child.id for child in story_detail.children] == [task.id]
