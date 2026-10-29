"""T17 / TT17 — Markdown and EDNL export that provably does not write."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import task_manager.db as db_module
from task_manager import export, repository
from task_manager.db import Database
from task_manager.errors import NotFound, ValidationError


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


@pytest.fixture()
def project(db):
    return repository.project_upsert(db, "demo", "Demo project")


def _seed(db, project):
    leased = repository.task_add(
        db, project.id, "Fix plugin loader", description="spec text", workflow="bugfix"
    )
    repository.task_start(db, leased.id, actor="agent-7", lease_minutes=30)
    repository.journal_add(
        db, task_id=leased.id, kind="attempt", body="mypy fails on loader\nsecond line"
    )

    blocked = repository.task_add(db, project.id, "Blocked task", priority=1)
    repository.task_block(db, blocked.id, actor="agent-1", reason="needs an API key")

    relation_target = repository.task_add(db, project.id, "Upstream work")
    follower = repository.task_add(db, project.id, "Follower")
    repository.task_link(db, follower.id, relation_target.id, "blocked_by")
    repository.task_link(db, follower.id, leased.id, "related")

    story = repository.task_add(db, project.id, "Story", type="story")
    repository.context_append(db, story.id, body="sibling fact")
    repository.task_add(db, project.id, "Story child", parent_id=story.id)

    done = repository.task_add(db, project.id, "Finished work")
    repository.task_start(db, done.id, actor="agent-2")
    repository.task_complete(db, done.id, actor="agent-2", outcome="all green")

    repository.checkpoint_save(
        db, project.id, "handoff line\nmore detail", next_actions=["next step"]
    )
    return {
        "leased": leased,
        "blocked": blocked,
        "follower": follower,
        "relation_target": relation_target,
        "story": story,
        "done": done,
    }


def test_markdown_contains_everything(db, project):
    ids = _seed(db, project)
    text = export.export_project(db, project.id)

    for task in repository.all_tasks(db, project.id):
        assert f"#{task.id} — {task.title}" in text
    for entry in repository.journal_for_project(db, project.id):
        assert entry.body in text
    assert "needs an API key" in text
    assert f"blocked by: #{ids['relation_target'].id}" in text
    assert f"related: #{ids['leased'].id}" in text
    assert "sibling fact" in text
    assert "all green" in text
    assert "handoff line" in text
    assert text.startswith("# Project: demo (Demo project)")


def test_ednl_round_trip_covers_every_row_exactly_once(db, project):
    _seed(db, project)
    text = export.export_project(db, project.id, fmt="ednl")
    lines = [line for line in text.splitlines() if line.strip()]

    kinds = [line.split()[0] for line in lines]
    tasks = repository.all_tasks(db, project.id)
    relations = repository.project_relations(db, project.id)
    journal = repository.journal_for_project(db, project.id)

    assert kinds.count("project") == 1
    assert kinds.count("task") == len(tasks)
    assert kinds.count("relation") == len(relations)
    assert kinds.count("journal") == len(journal)
    assert kinds.count("checkpoint") == 1

    task_ids = [
        int(line.split()[1]) for line in lines if line.startswith("task ")
    ]
    assert sorted(task_ids) == sorted(task.id for task in tasks)
    assert len(set(task_ids)) == len(task_ids)

    journal_ids = [int(line.split()[1]) for line in lines if line.startswith("journal ")]
    assert sorted(journal_ids) == sorted(entry.id for entry in journal)

    relation_lines = [line for line in lines if line.startswith("relation ")]
    assert len(relation_lines) == len(relations)
    assert relation_lines[0].startswith(f"relation {relations[0].task_id}")
    assert "\\n" in next(line for line in lines if line.startswith("journal ") and "mypy" in line)


def test_output_is_deterministic(db, project, monkeypatch):
    _seed(db, project)
    frozen = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        db_module, "utc_now", lambda: frozen.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )

    first_md = export.export_project(db, project.id)
    second_md = export.export_project(db, project.id)
    assert first_md == second_md
    assert export.export_project(db, project.id, fmt="ednl") == export.export_project(
        db, project.id, fmt="ednl"
    )


def test_path_writes_utf8_and_export_is_read_only(db, project, tmp_path, monkeypatch):
    frozen = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        db_module, "utc_now", lambda: frozen.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )
    task = repository.task_add(db, project.id, "Títle with ünicode — dash")
    repository.journal_add(db, task_id=task.id, kind="note", body="héllo wörld")
    before_counts = _table_counts(db)
    before_updated = {item.id: item.updated_at for item in repository.all_tasks(db, project.id)}

    target = tmp_path / "out" / "project.md"
    written = export.export_project(db, project.id, path=target)

    assert Path(written) == target
    assert target.read_text(encoding="utf-8") == export.export_project(db, project.id)
    assert "héllo wörld" in target.read_text(encoding="utf-8")

    assert _table_counts(db) == before_counts
    assert {
        item.id: item.updated_at for item in repository.all_tasks(db, project.id)
    } == before_updated


def _table_counts(db):
    conn = db.connect()
    try:
        return {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "projects",
                "tasks",
                "task_relations",
                "journal",
                "task_context",
                "session_events",
                "checkpoints",
            )
        }
    finally:
        conn.close()


def test_story_context_appears_only_under_the_story(db, project):
    story = repository.task_add(db, project.id, "Story", type="story")
    repository.context_append(db, story.id, body="only on the story")
    child = repository.task_add(db, project.id, "Story child", parent_id=story.id)

    text = export.export_project(db, project.id)
    assert text.count("only on the story") == 1
    story_block = text.split(f"### #{story.id}")
    assert "only on the story" in story_block[1]
    child_block = text.split(f"### #{child.id}")
    assert "only on the story" not in child_block[1]


def test_empty_project_is_a_valid_document(db, project):
    text = export.export_project(db, project.id)
    assert text.startswith("# Project: demo")
    assert "###" not in text
    assert text.endswith("\n")
    ednl = export.export_project(db, project.id, fmt="ednl")
    assert ednl.strip() == "project 1 slug demo name Demo project"


def test_unknown_project_raises_and_writes_nothing(db, tmp_path):
    target = tmp_path / "nope.md"
    with pytest.raises(NotFound):
        export.export_project(db, 999, path=target)
    assert not target.exists()
    with pytest.raises(NotFound):
        export.export_project(db, 999, fmt="ednl")


def test_invalid_format_rejected(db, project):
    with pytest.raises(ValidationError):
        export.export_project(db, project.id, fmt="pdf")


def test_export_contains_no_urls(db, project):
    _seed(db, project)
    for fmt in ("markdown", "ednl"):
        text = export.export_project(db, project.id, fmt=fmt)
        assert "http://" not in text
        assert "https://" not in text
