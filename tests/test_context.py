"""T10 / TT10 — story context: append caps, retention, and inheritance."""

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


@pytest.fixture()
def story(db, project):
    return repository.task_add(db, project.id, "Story", type="story")


def test_append_requires_a_story(db, project, story):
    entry = repository.context_append(db, story.id, body="shared fact", actor="agent-1")
    assert entry.body == "shared fact"
    assert entry.task_id == story.id
    assert entry.actor == "agent-1"

    plain = repository.task_add(db, project.id, "Plain task")
    with pytest.raises(ValidationError, match="story tasks"):
        repository.context_append(db, plain.id, body="not allowed")

    with pytest.raises(NotFound):
        repository.context_append(db, 999, body="missing")


def test_child_inherits_story_context_oldest_first(db, project, story):
    repository.context_append(db, story.id, body="first fact")
    repository.context_append(db, story.id, body="second fact")
    child = repository.task_add(db, project.id, "Child", parent_id=story.id)

    detail = repository.task_get(db, child.id)
    assert [entry.body for entry in detail.story_context] == [
        "first fact",
        "second fact",
    ]
    assert detail.story_context[0].id < detail.story_context[1].id


def test_grandchild_uses_nearest_story(db, project, story):
    repository.context_append(db, story.id, body="root story fact")
    middle = repository.task_add(db, project.id, "Middle story", type="story", parent_id=story.id)
    repository.context_append(db, middle.id, body="middle story fact")
    grandchild = repository.task_add(db, project.id, "Grandchild", parent_id=middle.id)

    detail = repository.task_get(db, grandchild.id)
    assert [entry.body for entry in detail.story_context] == ["middle story fact"]


def test_plain_parent_still_walks_up_to_the_story(db, project, story):
    repository.context_append(db, story.id, body="inherited via grandparent")
    child = repository.task_add(db, project.id, "Child", parent_id=story.id)
    # The API refuses non-story parents, so build the grandchild link directly.
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO tasks(project_id, parent_id, seq, title, type, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'task', ?, ?)",
            (project.id, child.id, 99.0, "Grandchild", db.utc_now(), db.utc_now()),
        )
        grandchild_id = conn.execute(
            "SELECT id FROM tasks WHERE title='Grandchild'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert [
        entry.body for entry in repository.story_context(db, grandchild_id)
    ] == ["inherited via grandparent"]


def test_body_boundaries(db, story):
    at_limit = "x" * repository.MAX_CONTEXT_BODY
    assert repository.context_append(db, story.id, body=at_limit).body == at_limit

    with pytest.raises(ValidationError):
        repository.context_append(db, story.id, body="x" * (repository.MAX_CONTEXT_BODY + 1))
    with pytest.raises(ValidationError):
        repository.context_append(db, story.id, body="   ")


def test_retention_evicts_the_oldest(db, story):
    for index in range(repository.MAX_CONTEXT_ENTRIES):
        repository.context_append(db, story.id, body=f"fact {index}")
    newest = repository.context_append(db, story.id, body="fact 20")

    entries = repository.context_entries(db, story.id)
    assert len(entries) == repository.MAX_CONTEXT_ENTRIES
    assert entries[-1].id == newest.id
    assert entries[-1].body == "fact 20"
    assert "fact 0" not in {entry.body for entry in entries}
    assert "fact 1" in {entry.body for entry in entries}


def test_story_context_scope_and_empty(db, project, story):
    other_story = repository.task_add(db, project.id, "Other story", type="story")
    repository.context_append(db, story.id, body="mine")
    repository.context_append(db, other_story.id, body="theirs")

    assert [entry.body for entry in repository.story_context(db, story.id)] == ["mine"]

    orphan = repository.task_add(db, project.id, "Orphan")
    assert repository.story_context(db, orphan.id) == []


def test_payload_is_bounded_and_deterministic(db, story):
    for index in range(repository.MAX_CONTEXT_ENTRIES):
        repository.context_append(
            db, story.id, body=f"{index:02d} " + ("y" * 390)
        )

    first = repository.story_context(db, story.id, limit=repository.MAX_CONTEXT_ENTRIES)
    second = repository.story_context(db, story.id, limit=repository.MAX_CONTEXT_ENTRIES)
    assert [entry.id for entry in first] == [entry.id for entry in second]
    assert len(first) < repository.MAX_CONTEXT_ENTRIES
    assert sum(len(entry.body) for entry in first) <= repository.MAX_CONTEXT_RESPONSE


def test_task_get_context_limit_returns_newest_entries(db, project, story):
    repository.context_append(db, story.id, body="oldest")
    repository.context_append(db, story.id, body="middle")
    repository.context_append(db, story.id, body="newest")
    child = repository.task_add(db, project.id, "Child", parent_id=story.id)

    detail = repository.task_get(db, child.id, context_limit=2)
    assert [entry.body for entry in detail.story_context] == ["middle", "newest"]


def test_hard_delete_cascades_context(db, project, story):
    repository.context_append(db, story.id, body="keep me")
    child = repository.task_add(db, project.id, "Child", parent_id=story.id)

    repository.task_delete(db, child.id, hard=True)
    assert len(repository.context_entries(db, story.id)) == 1

    repository.task_delete(db, story.id, hard=True)
    assert repository.context_entries(db, story.id) == []
