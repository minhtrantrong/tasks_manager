"""Computed ready/waiting sets and the next-task selector.

``waiting`` is never materialised as a column: it is derived from the
``blocked_by`` edges and the project's ``require_closure`` setting on every read.
"""

from __future__ import annotations

import sqlite3

from .db import Database
from .errors import NotFound
from .models import TaskSummary

TERMINAL_STATUSES = ("done", "closed", "cancelled")


def is_terminal(status: str) -> bool:
    """Return True for statuses that need no further work."""
    return status in TERMINAL_STATUSES


def _blocker_condition(task_alias: str = "t") -> str:
    """SQL condition for a blocker that is *not* satisfied yet.

    Cancelled blockers are satisfied in both modes. ``done`` blocks dependents
    only when the project requires closure; ``closed`` always satisfies.
    """
    return (
        "(b.status IN ('open','in_progress','blocked') OR "
        f"((SELECT require_closure FROM projects p WHERE p.id={task_alias}.project_id)=1 "
        "AND b.status='done'))"
    )


def _waiting_exists_sql(task_alias: str = "t") -> str:
    return (
        "EXISTS (SELECT 1 FROM task_relations r JOIN tasks b ON b.id=r.related_id "
        f"WHERE r.task_id={task_alias}.id AND r.kind='blocked_by' "
        f"AND {_blocker_condition(task_alias)})"
    )


def _is_waiting_conn(conn: sqlite3.Connection, task_id: int) -> bool:
    row = conn.execute(
        f"SELECT {_waiting_exists_sql('t')} AS waiting FROM tasks t WHERE t.id=?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"task {task_id} not found")
    return bool(row["waiting"])


def is_waiting(db: Database, task_id: int) -> bool:
    """True iff a non-satisfied ``blocked_by`` blocker exists."""
    conn = db.connect()
    try:
        return _is_waiting_conn(conn, task_id)
    finally:
        conn.close()


def ready_predicate(db: Database, project_id: int | None) -> str:
    """SQL fragment for ready tasks, assuming the tasks table is aliased ``t``."""
    return f"(t.status='open' AND NOT {_waiting_exists_sql('t')})"


def _summary_rows(
    db: Database, project_id: int, *, workflow: str | None, limit: int | None, order: str
) -> list[TaskSummary]:
    clauses = ["t.project_id=?", ready_predicate(db, project_id)]
    params: list[object] = [project_id]
    if workflow is not None:
        clauses.append("t.workflow=?")
        params.append(workflow)
    sql = f"SELECT t.* FROM tasks t WHERE {' AND '.join(clauses)} ORDER BY {order}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    conn = db.connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [
            TaskSummary(
                id=row["id"],
                title=row["title"],
                type=row["type"],
                workflow=row["workflow"],
                status=row["status"],
                priority=row["priority"],
                seq=row["seq"],
                owner=row["owner"],
                updated_at=row["updated_at"],
                parent_id=row["parent_id"],
                lease_expires_at=row["lease_expires_at"],
            )
            for row in rows
        ]
    finally:
        conn.close()


def ready_tasks(
    db: Database, project_id: int, *, workflow: str | None = None, limit: int | None = None
) -> list[TaskSummary]:
    """Ready tasks ordered priority ASC, seq ASC, id ASC."""
    return _summary_rows(
        db, project_id, workflow=workflow, limit=limit, order="t.priority, t.seq, t.id"
    )


def task_next(db: Database, project_id: int, *, workflow: str | None = None) -> TaskSummary | None:
    """Pick the next executable task (never a waiting one)."""
    from . import repository

    repository.reap_expired_leases(db)
    if workflow is not None:
        tasks = _summary_rows(
            db,
            project_id,
            workflow=workflow,
            limit=1,
            order="t.seq, t.priority, t.id",
        )
    else:
        tasks = ready_tasks(db, project_id, limit=1)
    return tasks[0] if tasks else None


def waiting_tasks(db: Database, project_id: int) -> list[dict]:
    """Tasks blocked by an unsatisfied dependency, with the blocker ids."""
    conn = db.connect()
    try:
        project = conn.execute(
            "SELECT id FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if project is None:
            raise NotFound(f"project {project_id} not found")
        rows = conn.execute(
            f"SELECT t.id, t.title, {_waiting_exists_sql('t')} AS waiting "
            "FROM tasks t WHERE t.project_id=? ORDER BY t.priority, t.seq, t.id",
            (project_id,),
        ).fetchall()
        result: list[dict] = []
        for row in rows:
            if not row["waiting"]:
                continue
            needs = conn.execute(
                "SELECT b.id FROM task_relations r "
                "JOIN tasks b ON b.id=r.related_id "
                "JOIN tasks t ON t.id=r.task_id "
                "WHERE r.task_id=? AND r.kind='blocked_by' "
                f"AND {_blocker_condition('t')} ORDER BY b.id",
                (row["id"],),
            ).fetchall()
            result.append(
                {"id": row["id"], "title": row["title"], "needs": [item["id"] for item in needs]}
            )
        return result
    finally:
        conn.close()
