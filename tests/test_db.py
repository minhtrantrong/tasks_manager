"""Tests for the database layer: schema, migrations, pragmas, FTS5."""

from __future__ import annotations

import sqlite3

import pytest

from task_manager.db import Database, utc_now


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


def _project(conn, slug="demo", name="Demo", require_closure=0):
    now = utc_now()
    cur = conn.execute(
        "INSERT INTO projects(slug, name, require_closure, created_at) VALUES (?, ?, ?, ?)",
        (slug, name, require_closure, now),
    )
    return cur.lastrowid


def _task(conn, project_id, title="Task", status="open", seq=1.0):
    now = utc_now()
    cur = conn.execute(
        "INSERT INTO tasks(project_id, seq, title, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, seq, title, status, now, now),
    )
    return cur.lastrowid


def test_migration_creates_all_tables_and_indexes(db):
    conn = db.connect()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for expected in (
            "projects",
            "tasks",
            "task_relations",
            "journal",
            "task_context",
            "session_events",
            "checkpoints",
            "task_fts",
            "journal_fts",
        ):
            assert expected in tables
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        for expected in (
            "idx_tasks_board",
            "idx_tasks_parent",
            "idx_tasks_lease",
            "idx_journal_task",
            "idx_journal_project",
            "idx_relations_target",
            "idx_session_events",
            "idx_checkpoints",
        ):
            assert expected in indexes
    finally:
        conn.close()


def test_migrate_is_idempotent(db):
    db.migrate()
    db.migrate()
    conn = db.connect()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    finally:
        conn.close()


def test_pragmas(db):
    conn = db.connect()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_foreign_key_enforcement(db):
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            _task(conn, 999999)

        project_id = _project(conn)
        _task(conn, project_id)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    finally:
        conn.close()


def test_cascade_deletes_task_history(db):
    conn = db.connect()
    try:
        project_id = _project(conn)
        task_id = _task(conn, project_id, "A")
        other_id = _task(conn, project_id, "B", seq=2.0)
        conn.execute(
            "INSERT INTO task_relations(task_id, related_id, kind) VALUES (?, ?, 'blocked_by')",
            (task_id, other_id),
        )
        conn.execute(
            "INSERT INTO journal(task_id, project_id, kind, body, created_at) "
            "VALUES (?, ?, 'note', 'hello', ?)",
            (task_id, project_id, utc_now()),
        )
        conn.execute(
            "INSERT INTO task_context(task_id, body, created_at) VALUES (?, 'fact', ?)",
            (task_id, utc_now()),
        )
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        assert conn.execute("SELECT count(*) FROM journal").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM task_context").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM task_relations").fetchone()[0] == 0
    finally:
        conn.close()


def test_fts_sync(db):
    conn = db.connect()
    try:
        project_id = _project(conn)
        first = _task(conn, project_id, "First task")
        second = _task(conn, project_id, "Second task", seq=2.0)
        assert conn.execute("SELECT count(*) FROM task_fts").fetchone()[0] == 2

        conn.execute("UPDATE tasks SET title='Renamed task' WHERE id=?", (first,))
        assert conn.execute("SELECT count(*) FROM task_fts").fetchone()[0] == 2
        hits = conn.execute(
            "SELECT rowid FROM task_fts WHERE task_fts MATCH ?", ("Renamed",)
        ).fetchall()
        assert [row[0] for row in hits] == [first]

        conn.execute("DELETE FROM tasks WHERE id=?", (second,))
        assert conn.execute("SELECT count(*) FROM task_fts").fetchone()[0] == 1
    finally:
        conn.close()


def test_fts_enabled_and_graceful_skip(tmp_path, monkeypatch):
    db = Database(tmp_path / "fts.sqlite")
    db.migrate()
    conn = db.connect()
    try:
        assert db.fts_enabled(conn) is True
    finally:
        conn.close()

    real_execute = Database._execute

    def fake_execute(self, conn, statement):
        if "using fts5" in statement.lower():
            raise sqlite3.OperationalError("no such module: fts5")
        return real_execute(self, conn, statement)

    monkeypatch.setattr(Database, "_execute", fake_execute)
    no_fts = Database(tmp_path / "nofts.sqlite")
    no_fts.migrate()
    conn = no_fts.connect()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert no_fts.fts_enabled(conn) is False
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    finally:
        conn.close()


def test_check_constraints(db):
    conn = db.connect()
    try:
        project_id = _project(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks(project_id, seq, title, status, created_at, updated_at) "
                "VALUES (?, 1.0, 'bad', 'bogus', ?, ?)",
                (project_id, utc_now(), utc_now()),
            )
        first = _task(conn, project_id, "A")
        second = _task(conn, project_id, "B", seq=2.0)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO task_relations(task_id, related_id, kind) VALUES (?, ?, 'bogus')",
                (first, second),
            )
    finally:
        conn.close()
