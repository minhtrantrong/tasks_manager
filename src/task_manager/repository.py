"""The single write path for task-manager (N7).

Every mutation of projects, tasks, relations, journal entries, context, session
events, and checkpoints lives in this module. All invariants are validated inside
the same transaction as the write.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from . import scheduler, transitions, workflows
from .db import Database
from .errors import (
    CycleDetected,
    FtsUnavailable,
    LeaseConflict,
    MissingOutcome,
    MissingReason,
    NotFound,
    ValidationError,
)
from .models import (
    Checkpoint,
    ContextEntry,
    Graph,
    GraphEdge,
    GraphNode,
    JournalEntry,
    Page,
    Project,
    ProjectSummary,
    RecallHit,
    Relation,
    RelationView,
    SessionEvent,
    Task,
    TaskDetail,
    TaskSummary,
)

logger = logging.getLogger(__name__)

TASK_TYPES = ("task", "bug", "feature", "story", "chore")
TASK_STATUSES = ("open", "in_progress", "blocked", "done", "closed", "cancelled")
JOURNAL_KINDS = ("note", "decision", "attempt", "problem", "result")
RELATION_KINDS = ("blocked_by", "related", "discovered_during")

MAX_TITLE = 200
MAX_TEXT = 4000
MAX_LIMIT = 50


@contextmanager
def _immediate(conn: sqlite3.Connection):
    """Run a block inside ``BEGIN IMMEDIATE`` and commit or roll back."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _require_project(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise NotFound(f"project {project_id} not found")
    return row


def _require_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        raise NotFound(f"task {task_id} not found")
    return row


def _parse_meta(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _normalise_meta(meta: dict[str, Any] | None) -> str | None:
    if meta is None:
        return None
    if not isinstance(meta, dict):
        raise ValidationError("meta must be a JSON object")
    return json.dumps(meta, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _task_from_row(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        project_id=row["project_id"],
        parent_id=row["parent_id"],
        seq=row["seq"],
        title=row["title"],
        description=row["description"],
        design=row["design"],
        type=row["type"],
        workflow=row["workflow"],
        status=row["status"],
        priority=row["priority"],
        meta=_parse_meta(row["meta"]),
        owner=row["owner"],
        lease_expires_at=row["lease_expires_at"],
        block_reason=row["block_reason"],
        outcome=row["outcome"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _summary_from_row(row: sqlite3.Row) -> TaskSummary:
    return TaskSummary(
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


def _project_from_row(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        description=row["description"],
        root_path=row["root_path"],
        require_closure=bool(row["require_closure"]),
        created_at=row["created_at"],
        archived_at=row["archived_at"],
    )


def _journal_from_row(row: sqlite3.Row) -> JournalEntry:
    return JournalEntry(
        id=row["id"],
        task_id=row["task_id"],
        project_id=row["project_id"],
        kind=row["kind"],
        body=row["body"],
        actor=row["actor"],
        session_ref=row["session_ref"],
        created_at=row["created_at"],
    )


def _context_from_row(row: sqlite3.Row) -> ContextEntry:
    return ContextEntry(
        id=row["id"],
        task_id=row["task_id"],
        body=row["body"],
        actor=row["actor"],
        created_at=row["created_at"],
    )


def _validate_title(title: str) -> str:
    if not isinstance(title, str) or not title.strip():
        raise ValidationError("title must be a non-empty string")
    cleaned = title.strip()
    if len(cleaned) > MAX_TITLE:
        raise ValidationError(f"title must be at most {MAX_TITLE} characters")
    return cleaned


def _validate_optional_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string or null")
    if len(value) > MAX_TEXT:
        raise ValidationError(f"{field} must be at most {MAX_TEXT} characters")
    return value


def _validate_choice(value: str, field: str, choices: Iterable[str]) -> str:
    allowed = tuple(choices)
    if value not in allowed:
        raise ValidationError(f"{field} must be one of {', '.join(allowed)}")
    return value


def _validate_priority(priority: int) -> int:
    if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 5:
        raise ValidationError("priority must be an integer between 1 and 5")
    return priority


def _validate_workflow(workflow: str) -> str:
    if not isinstance(workflow, str) or not workflow.strip():
        raise ValidationError("workflow must be a non-empty string")
    if len(workflow) > 100:
        raise ValidationError("workflow must be at most 100 characters")
    return workflow


def _validate_parent(
    conn: sqlite3.Connection,
    project_id: int,
    parent_id: int,
    *,
    task_id: int | None = None,
) -> None:
    if task_id is not None and parent_id == task_id:
        raise ValidationError("a task cannot be its own parent")
    parent = conn.execute(
        "SELECT project_id, type FROM tasks WHERE id=?", (parent_id,)
    ).fetchone()
    if parent is None:
        raise ValidationError(f"parent task {parent_id} does not exist")
    if parent["project_id"] != project_id:
        raise ValidationError("parent task must belong to the same project")
    if parent["type"] != "story":
        raise ValidationError("parent task must have type='story'")
    if task_id is not None:
        # Walk the ancestor chain to prevent parent cycles.
        seen = {task_id}
        cursor = parent_id
        while cursor is not None:
            if cursor in seen:
                raise ValidationError("parent assignment would create a cycle")
            seen.add(cursor)
            row = conn.execute("SELECT parent_id FROM tasks WHERE id=?", (cursor,)).fetchone()
            cursor = row["parent_id"] if row else None


def _validate_blocked_by(
    conn: sqlite3.Connection, project_id: int, blocked_by: Iterable[int] | None
) -> list[int]:
    if blocked_by is None:
        return []
    if isinstance(blocked_by, int):
        ids = [blocked_by]
    else:
        try:
            ids = list(blocked_by)
        except TypeError as exc:
            raise ValidationError("blocked_by must be a list of task ids") from exc
    result: list[int] = []
    for related_id in ids:
        if isinstance(related_id, bool) or not isinstance(related_id, int):
            raise ValidationError("blocked_by must contain task ids")
        row = conn.execute(
            "SELECT project_id FROM tasks WHERE id=?", (related_id,)
        ).fetchone()
        if row is None:
            raise ValidationError(f"blocked_by task {related_id} does not exist")
        if row["project_id"] != project_id:
            raise ValidationError("blocked_by tasks must belong to the same project")
        if related_id not in result:
            result.append(related_id)
    return result


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def project_upsert(
    db: Database,
    slug: str,
    name: str,
    *,
    root_path: str | None = None,
    description: str | None = None,
    require_closure: bool = False,
) -> Project:
    """Create a project, or update the existing project with this slug (N3)."""
    if not isinstance(slug, str) or not slug.strip():
        raise ValidationError("slug must be a non-empty string")
    slug = slug.strip()
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("name must be a non-empty string")
    name = name.strip()
    if len(name) > MAX_TITLE:
        raise ValidationError(f"name must be at most {MAX_TITLE} characters")
    description = _validate_optional_text(description, "description")
    root_value = str(root_path) if root_path is not None else None

    conn = db.connect()
    try:
        with _immediate(conn):
            existing = conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
            if existing is not None:
                conn.execute(
                    "UPDATE projects SET name=?, root_path=COALESCE(?, root_path), "
                    "description=COALESCE(?, description), "
                    "require_closure=CASE WHEN ? THEN 1 ELSE require_closure END WHERE id=?",
                    (name, root_value, description, int(require_closure), existing["id"]),
                )
                row = conn.execute(
                    "SELECT * FROM projects WHERE id=?", (existing["id"],)
                ).fetchone()
                return _project_from_row(row)

            cursor = conn.execute(
                "INSERT INTO projects(slug, name, description, root_path, require_closure, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (slug, name, description, root_value, int(require_closure), db.utc_now()),
            )
            row = conn.execute(
                "SELECT * FROM projects WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            return _project_from_row(row)
    finally:
        conn.close()


def project_list(db: Database) -> list[ProjectSummary]:
    """List projects with status counts (waiting is filled in by T06)."""
    conn = db.connect()
    try:
        projects = conn.execute("SELECT * FROM projects ORDER BY name, id").fetchall()
        result: list[ProjectSummary] = []
        for project in projects:
            counts = {
                "open": 0,
                "waiting": 0,
                "blocked": 0,
                "in_progress": 0,
                "done": 0,
            }
            rows = conn.execute(
                "SELECT status, count(*) AS n FROM tasks WHERE project_id=? GROUP BY status",
                (project["id"],),
            ).fetchall()
            for row in rows:
                if row["status"] in counts:
                    counts[row["status"]] = row["n"]
            counts["waiting"] = len(scheduler.waiting_tasks(db, project["id"]))
            result.append(
                ProjectSummary(
                    id=project["id"],
                    slug=project["slug"],
                    name=project["name"],
                    counts=counts,
                    archived=project["archived_at"] is not None,
                )
            )
        return result
    finally:
        conn.close()


def project_archive(db: Database, project_id: int) -> Project:
    """Mark a project archived."""
    conn = db.connect()
    try:
        with _immediate(conn):
            _require_project(conn, project_id)
            conn.execute(
                "UPDATE projects SET archived_at=? WHERE id=?", (db.utc_now(), project_id)
            )
            row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            return _project_from_row(row)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def task_add(
    db: Database,
    project_id: int,
    title: str,
    *,
    description: str | None = None,
    design: str | None = None,
    type: str = "task",
    workflow: str = "simple",
    priority: int = 3,
    parent_id: int | None = None,
    blocked_by: list[int] | None = None,
    prepend: bool = False,
    meta: dict[str, Any] | None = None,
) -> Task:
    """Insert a task and any ``blocked_by`` relations in one transaction."""
    title = _validate_title(title)
    description = _validate_optional_text(description, "description")
    design = _validate_optional_text(design, "design")
    _validate_choice(type, "type", TASK_TYPES)
    workflow = _validate_workflow(workflow)
    _validate_priority(priority)
    meta_text = _normalise_meta(meta) or "{}"
    now = db.utc_now()

    conn = db.connect()
    try:
        with _immediate(conn):
            _require_project(conn, project_id)
            if parent_id is not None:
                _validate_parent(conn, project_id, parent_id)
            blockers = _validate_blocked_by(conn, project_id, blocked_by)

            if prepend:
                row = conn.execute(
                    "SELECT COALESCE(MIN(seq), 1) AS value FROM tasks WHERE project_id=?",
                    (project_id,),
                ).fetchone()
                seq = row["value"] - 1
            else:
                row = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS value FROM tasks WHERE project_id=?",
                    (project_id,),
                ).fetchone()
                seq = row["value"] + 1

            cursor = conn.execute(
                "INSERT INTO tasks(project_id, parent_id, seq, title, description, design, "
                "type, workflow, status, priority, meta, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)",
                (
                    project_id,
                    parent_id,
                    seq,
                    title,
                    description,
                    design,
                    type,
                    workflow,
                    priority,
                    meta_text,
                    now,
                    now,
                ),
            )
            task_id = cursor.lastrowid
            for related_id in blockers:
                conn.execute(
                    "INSERT INTO task_relations(task_id, related_id, kind) "
                    "VALUES (?, ?, 'blocked_by')",
                    (task_id, related_id),
                )
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return _task_from_row(row)
    finally:
        conn.close()


def task_update(
    db: Database,
    task_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    design: str | None = None,
    priority: int | None = None,
    workflow: str | None = None,
    parent_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> Task:
    """Patch task fields. Status/owner/lease are never touched here (T07 owns them)."""
    if title is not None:
        title = _validate_title(title)
    if description is not None:
        description = _validate_optional_text(description, "description")
    if design is not None:
        design = _validate_optional_text(design, "design")
    if priority is not None:
        _validate_priority(priority)
    if workflow is not None:
        workflow = _validate_workflow(workflow)
    meta_text = _normalise_meta(meta)

    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            if parent_id is not None:
                _validate_parent(conn, task["project_id"], parent_id, task_id=task_id)

            sets: list[str] = []
            params: list[Any] = []
            for column, value in (
                ("title", title),
                ("description", description),
                ("design", design),
                ("priority", priority),
                ("workflow", workflow),
                ("parent_id", parent_id),
                ("meta", meta_text),
            ):
                if value is not None:
                    sets.append(f"{column}=?")
                    params.append(value)
            sets.append("updated_at=?")
            params.append(db.utc_now())
            params.append(task_id)
            conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params)
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return _task_from_row(row)
    finally:
        conn.close()


def task_get(
    db: Database, task_id: int, *, journal_limit: int = 5, context_limit: int = 10
) -> TaskDetail:
    """Return one task with relations, children, story context, and journal tail."""
    journal_limit = max(0, min(int(journal_limit), 100))
    context_limit = max(0, min(int(context_limit), 50))
    reap_expired_leases(db)
    conn = db.connect()
    try:
        task = _require_task(conn, task_id)
        relations = conn.execute(
            "SELECT r.task_id, r.related_id, r.kind, t.status AS target_status "
            "FROM task_relations r "
            "JOIN tasks t ON t.id = CASE WHEN r.task_id=? THEN r.related_id ELSE r.task_id END "
            "WHERE r.task_id=? OR (r.related_id=? AND r.kind='blocked_by') "
            "ORDER BY r.kind, t.id",
            (task_id, task_id, task_id),
        ).fetchall()
        relation_views = [
            RelationView(
                related_id=row["related_id"] if row["task_id"] == task_id else row["task_id"],
                kind=row["kind"],
                target_status=row["target_status"],
            )
            for row in relations
        ]
        children = conn.execute(
            "SELECT * FROM tasks WHERE parent_id=? ORDER BY priority, seq, id",
            (task_id,),
        ).fetchall()
        journal = conn.execute(
            "SELECT * FROM journal WHERE task_id=? ORDER BY id DESC LIMIT ?",
            (task_id, journal_limit),
        ).fetchall()
        detail = TaskDetail(
            **_task_from_row(task).model_dump(),
            relations=relation_views,
            children=[_summary_from_row(row) for row in children],
            story_context=_story_context_conn(conn, task_id, context_limit),
            journal=[_journal_from_row(row) for row in journal],
        )
        return detail
    finally:
        conn.close()


def task_query(
    db: Database,
    project_id: int | None = None,
    *,
    task_id: int | None = None,
    workflow: str | None = None,
    parent_id: int | None = None,
    type: str | None = None,
    status: str | list[str] | None = None,
    text: str | None = None,
    waiting: bool | None = None,
    ready: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> Page[TaskSummary]:
    """One filter tool for tasks, capped and paginated."""
    if type is not None:
        _validate_choice(type, "type", TASK_TYPES)
    if status is not None:
        statuses = [status] if isinstance(status, str) else list(status)
        for value in statuses:
            _validate_choice(value, "status", TASK_STATUSES)
    else:
        statuses = []

    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))

    reap_expired_leases(db)
    conn = db.connect()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        join = ""
        if project_id is not None:
            clauses.append("t.project_id=?")
            params.append(project_id)
        if task_id is not None:
            clauses.append("t.id=?")
            params.append(task_id)
        if workflow is not None:
            clauses.append("t.workflow=?")
            params.append(workflow)
        if parent_id is not None:
            clauses.append("t.parent_id=?")
            params.append(parent_id)
        if type is not None:
            clauses.append("t.type=?")
            params.append(type)
        if statuses:
            clauses.append(f"t.status IN ({', '.join('?' for _ in statuses)})")
            params.extend(statuses)
        if waiting is not None:
            expression = scheduler._waiting_exists_sql("t")
            clauses.append(expression if waiting else f"NOT {expression}")
        if ready is not None:
            expression = scheduler.ready_predicate(db, project_id)
            clauses.append(expression if ready else f"NOT {expression}")
        if text:
            if db.fts_enabled(conn):
                join = " JOIN task_fts ON task_fts.rowid = t.id"
                clauses.append("task_fts MATCH ?")
                params.append('"' + text.replace('"', '""') + '"')
            else:
                clauses.append(
                    "(LOWER(t.title) LIKE ? OR LOWER(COALESCE(t.description, '')) LIKE ?)"
                )
                needle = f"%{text.lower()}%"
                params.extend([needle, needle])

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        total = conn.execute(
            f"SELECT count(*) FROM tasks t{join}{where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT t.* FROM tasks t{join}{where} "
            "ORDER BY t.priority, t.seq, t.id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return Page[TaskSummary](
            items=[_summary_from_row(row) for row in rows],
            total=total,
            offset=offset,
            limit=limit,
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Lifecycle / leases
# ---------------------------------------------------------------------------

MAX_REASON = 500
MAX_OUTCOME = 500


def _validate_actor(actor: str) -> str:
    if not isinstance(actor, str) or not actor.strip():
        raise ValidationError("actor must be a non-empty string")
    return actor.strip()


def _lease_expiry(minutes: int) -> str:
    moment = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _lease_expired(task: sqlite3.Row, now: str) -> bool:
    expires = task["lease_expires_at"]
    return expires is None or expires <= now


def _resolve_lease_minutes(
    conn: sqlite3.Connection,
    db: Database,
    task: sqlite3.Row,
    lease_minutes: int | None,
) -> int:
    if lease_minutes is None:
        project = conn.execute(
            "SELECT root_path FROM projects WHERE id=?", (task["project_id"],)
        ).fetchone()
        return workflows.default_lease_minutes(project, task["workflow"])
    if (
        isinstance(lease_minutes, bool)
        or not isinstance(lease_minutes, int)
        or lease_minutes <= 0
    ):
        raise ValidationError("lease_minutes must be a positive integer")
    return lease_minutes


def _insert_journal(
    conn: sqlite3.Connection,
    *,
    task_id: int | None,
    project_id: int,
    kind: str,
    body: str,
    actor: str | None,
    created_at: str,
    session_ref: str | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO journal(task_id, project_id, kind, body, actor, session_ref, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (task_id, project_id, kind, body, actor, session_ref, created_at),
    )
    return cursor.lastrowid


def _claim(
    conn: sqlite3.Connection,
    db: Database,
    task: sqlite3.Row,
    *,
    actor: str,
    lease_minutes: int,
    now: str,
) -> None:
    """Set an in-progress lease on ``task`` (caller already validated the edge)."""
    conn.execute(
        "UPDATE tasks SET status='in_progress', owner=?, lease_expires_at=?, "
        "started_at=COALESCE(started_at, ?), updated_at=? WHERE id=?",
        (actor, _lease_expiry(lease_minutes), now, now, task["id"]),
    )


def _run_hook(phase: str, db: Database, project: sqlite3.Row, task: Task) -> None:
    """Run an optional git hook after a transition committed; never raise."""
    from . import hooks

    try:
        resolved = _project_from_row(project)
        if not hooks.hooks_for(resolved).enabled:
            return
        if phase == "start":
            hooks.on_task_start(db, resolved, task)
        else:
            hooks.on_task_complete(db, resolved, task)
    except Exception:  # pragma: no cover - hooks may never fail a transition
        logger.warning("work-on hook (%s) for task %s failed", phase, task.id)


def task_start(
    db: Database, task_id: int, *, actor: str, lease_minutes: int | None = None
) -> Task:
    """Atomically claim a task: ``open`` → ``in_progress`` plus a lease."""
    actor = _validate_actor(actor)
    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            now = db.utc_now()
            if task["status"] == "in_progress":
                if not _lease_expired(task, now):
                    if task["owner"] == actor:
                        return _task_from_row(task)
                    raise LeaseConflict(
                        f"task {task_id} is leased by {task['owner']} until "
                        f"{task['lease_expires_at']}"
                    )
                # Expired lease: reap to open, then fall through to a fresh claim.
                conn.execute(
                    "UPDATE tasks SET status='open', owner=NULL, lease_expires_at=NULL, "
                    "updated_at=? WHERE id=?",
                    (now, task_id),
                )
                task = _require_task(conn, task_id)
            transitions.assert_transition(task["status"], "start")
            minutes = _resolve_lease_minutes(conn, db, task, lease_minutes)
            _claim(conn, db, task, actor=actor, lease_minutes=minutes, now=now)
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            project = _require_project(conn, task["project_id"])
            result = _task_from_row(row)
        _run_hook("start", db, project, result)
        return result
    finally:
        conn.close()


def task_release(
    db: Database, task_id: int, *, actor: str | None = None, force: bool = False
) -> Task:
    """Return an ``in_progress`` task to ``open`` and clear its lease."""
    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            transitions.assert_transition(task["status"], "release")
            now = db.utc_now()
            if not force and not _lease_expired(task, now) and task["owner"] != actor:
                raise LeaseConflict(
                    f"task {task_id} is leased by {task['owner']} until "
                    f"{task['lease_expires_at']}"
                )
            conn.execute(
                "UPDATE tasks SET status='open', owner=NULL, lease_expires_at=NULL, "
                "updated_at=? WHERE id=?",
                (now, task_id),
            )
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return _task_from_row(row)
    finally:
        conn.close()


def task_complete(db: Database, task_id: int, *, actor: str, outcome: str) -> Task:
    """Complete an ``in_progress`` task; ``outcome`` is required."""
    actor = _validate_actor(actor)
    if not isinstance(outcome, str) or not outcome.strip():
        raise MissingOutcome("task_complete requires a non-empty outcome")
    outcome = outcome.strip()
    if len(outcome) > MAX_OUTCOME:
        raise MissingOutcome(f"outcome must be at most {MAX_OUTCOME} characters")

    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            transitions.assert_transition(task["status"], "complete")
            now = db.utc_now()
            conn.execute(
                "UPDATE tasks SET status='done', outcome=?, finished_at=?, owner=NULL, "
                "lease_expires_at=NULL, updated_at=? WHERE id=?",
                (outcome, now, now, task_id),
            )
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            project = _require_project(conn, task["project_id"])
            result = _task_from_row(row)
        _run_hook("complete", db, project, result)
        return result
    finally:
        conn.close()


def task_close(db: Database, task_id: int, *, actor: str) -> Task:
    """Accept a ``done`` task (``done`` → ``closed``)."""
    _validate_actor(actor)
    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            transitions.assert_transition(task["status"], "close")
            conn.execute(
                "UPDATE tasks SET status='closed', updated_at=? WHERE id=?",
                (db.utc_now(), task_id),
            )
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return _task_from_row(row)
    finally:
        conn.close()


def task_block(db: Database, task_id: int, *, actor: str, reason: str) -> Task:
    """Block a task on an external factor; the reason is mirrored into the journal."""
    actor = _validate_actor(actor)
    if not isinstance(reason, str) or not reason.strip():
        raise MissingReason("task_block requires a non-empty reason")
    reason = reason.strip()
    if len(reason) > MAX_REASON:
        raise MissingReason(f"reason must be at most {MAX_REASON} characters")

    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            transitions.assert_transition(task["status"], "block")
            now = db.utc_now()
            conn.execute(
                "UPDATE tasks SET status='blocked', block_reason=?, owner=NULL, "
                "lease_expires_at=NULL, updated_at=? WHERE id=?",
                (reason, now, task_id),
            )
            _insert_journal(
                conn,
                task_id=task_id,
                project_id=task["project_id"],
                kind="problem",
                body=reason,
                actor=actor,
                created_at=now,
            )
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return _task_from_row(row)
    finally:
        conn.close()


def task_unblock(
    db: Database, task_id: int, *, actor: str, to: str = "open", lease_minutes: int | None = None
) -> Task:
    """Unblock a task to ``open``, or straight to a leased ``in_progress``."""
    actor = _validate_actor(actor)
    if to not in ("open", "in_progress"):
        raise ValidationError("to must be 'open' or 'in_progress'")
    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            transitions.assert_transition(task["status"], "unblock")
            now = db.utc_now()
            conn.execute(
                "UPDATE tasks SET status='open', block_reason=NULL, updated_at=? WHERE id=?",
                (now, task_id),
            )
            if to == "in_progress":
                transitions.assert_transition("open", "start")
                minutes = _resolve_lease_minutes(conn, db, task, lease_minutes)
                _claim(conn, db, task, actor=actor, lease_minutes=minutes, now=now)
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return _task_from_row(row)
    finally:
        conn.close()


def task_reopen(
    db: Database, task_id: int, *, actor: str, lease_minutes: int | None = None
) -> Task:
    """Reopen a ``done``/``closed`` task, keeping its prior outcome as history."""
    actor = _validate_actor(actor)
    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            transitions.assert_transition(task["status"], "reopen")
            now = db.utc_now()
            if task["outcome"]:
                _insert_journal(
                    conn,
                    task_id=task_id,
                    project_id=task["project_id"],
                    kind="result",
                    body=f"Prior outcome ({task['finished_at']}): {task['outcome']}",
                    actor=actor,
                    created_at=now,
                )
            conn.execute(
                "UPDATE tasks SET outcome=NULL, finished_at=NULL, started_at=NULL, "
                "updated_at=? WHERE id=?",
                (now, task_id),
            )
            task = _require_task(conn, task_id)
            minutes = _resolve_lease_minutes(conn, db, task, lease_minutes)
            _claim(conn, db, task, actor=actor, lease_minutes=minutes, now=now)
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return _task_from_row(row)
    finally:
        conn.close()


def task_cancel(db: Database, task_id: int, *, actor: str, hard: bool = False) -> Task:
    """Cancel a task (soft by default); ``hard=True`` purges it and its history."""
    actor = _validate_actor(actor)
    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            result = _task_from_row(task)
            if hard:
                conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
                return result
            transitions.assert_transition(task["status"], "cancel")
            conn.execute(
                "UPDATE tasks SET status='cancelled', owner=NULL, lease_expires_at=NULL, "
                "updated_at=? WHERE id=?",
                (db.utc_now(), task_id),
            )
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return _task_from_row(row)
    finally:
        conn.close()


def task_next(
    db: Database, project_id: int, *, workflow: str | None = None
) -> TaskSummary | None:
    """Convenience wrapper around :func:`scheduler.task_next` (reaps first)."""
    return scheduler.task_next(db, project_id, workflow=workflow)


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

MAX_JOURNAL_BODY = 1500
MAX_JOURNAL_LINES = 6
MAX_SESSION_REF = 100


def _validate_journal_body(body: str) -> str:
    if not isinstance(body, str) or not body.strip():
        raise ValidationError("journal body must be a non-empty string")
    if len(body.splitlines()) > MAX_JOURNAL_LINES or len(body) > MAX_JOURNAL_BODY:
        raise ValidationError("journal entry exceeds 6 lines / 1500 chars")
    return body.strip()


def _resolve_journal_scope(
    conn: sqlite3.Connection, task_id: int | None, project_id: int | None
) -> tuple[int | None, int]:
    if task_id is None and project_id is None:
        raise ValidationError("journal requires either task_id or project_id")
    if task_id is not None:
        task = _require_task(conn, task_id)
        return task_id, task["project_id"]
    assert project_id is not None
    _require_project(conn, project_id)
    return None, project_id


def journal_add(
    db: Database,
    *,
    task_id: int | None = None,
    project_id: int | None = None,
    kind: str,
    body: str,
    actor: str | None = None,
    session_ref: str | None = None,
) -> JournalEntry:
    """Append one journal entry (append-only; no edit or delete exists)."""
    _validate_choice(kind, "kind", JOURNAL_KINDS)
    body = _validate_journal_body(body)
    if session_ref is not None and len(session_ref) > MAX_SESSION_REF:
        raise ValidationError("session_ref must be at most 100 characters")
    if actor is not None and not isinstance(actor, str):
        raise ValidationError("actor must be a string or null")

    conn = db.connect()
    try:
        with _immediate(conn):
            resolved_task_id, resolved_project_id = _resolve_journal_scope(
                conn, task_id, project_id
            )
            entry_id = _insert_journal(
                conn,
                task_id=resolved_task_id,
                project_id=resolved_project_id,
                kind=kind,
                body=body,
                actor=actor,
                session_ref=session_ref,
                created_at=db.utc_now(),
            )
            row = conn.execute("SELECT * FROM journal WHERE id=?", (entry_id,)).fetchone()
            return _journal_from_row(row)
    finally:
        conn.close()


def journal_list(
    db: Database,
    *,
    task_id: int | None = None,
    project_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
    before: int | None = None,
) -> list[JournalEntry]:
    """List journal entries newest-first, optionally scoped and cursor-paginated.

    With ``task_id`` the listing is that task's log; with only ``project_id`` it
    is the whole project log (task entries and project-level notes alike).
    """
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    conn = db.connect()
    try:
        resolved_task_id, resolved_project_id = _resolve_journal_scope(
            conn, task_id, project_id
        )
        clauses = ["project_id=?"]
        params: list[Any] = [resolved_project_id]
        if resolved_task_id is not None:
            clauses.append("task_id=?")
            params.append(resolved_task_id)
        if before is not None:
            clauses.append("id < ?")
            params.append(before)
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT * FROM journal WHERE {' AND '.join(clauses)} "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [_journal_from_row(row) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Story context
# ---------------------------------------------------------------------------

MAX_CONTEXT_BODY = 400
MAX_CONTEXT_ENTRIES = 20
MAX_CONTEXT_RESPONSE = 2000
MAX_CONTEXT_LIMIT = 50


def _validate_context_body(body: str) -> str:
    if not isinstance(body, str) or not body.strip():
        raise ValidationError("context body must be a non-empty string")
    cleaned = body.strip()
    if len(cleaned) > MAX_CONTEXT_BODY:
        raise ValidationError(
            f"context body must be at most {MAX_CONTEXT_BODY} characters"
        )
    return cleaned


def _story_ancestor(
    conn: sqlite3.Connection, task_id: int
) -> sqlite3.Row | None:
    """Return the task if it is a story, else its nearest story ancestor."""
    row = conn.execute(
        "SELECT id, type, parent_id FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"task {task_id} not found")
    seen: set[int] = set()
    cursor = row
    while cursor is not None:
        if cursor["type"] == "story":
            return cursor
        if cursor["id"] in seen:
            return None
        seen.add(cursor["id"])
        if cursor["parent_id"] is None:
            return None
        cursor = conn.execute(
            "SELECT id, type, parent_id FROM tasks WHERE id=?", (cursor["parent_id"],)
        ).fetchone()
    return None


def _story_context_conn(
    conn: sqlite3.Connection, task_id: int, limit: int = 10
) -> list[ContextEntry]:
    limit = max(0, min(int(limit), MAX_CONTEXT_LIMIT))
    story = _story_ancestor(conn, task_id)
    if story is None or limit == 0:
        return []
    rows = conn.execute(
        "SELECT * FROM task_context WHERE task_id=? ORDER BY id DESC LIMIT ?",
        (story["id"], limit),
    ).fetchall()
    entries = [_context_from_row(row) for row in reversed(rows)]
    bounded: list[ContextEntry] = []
    total = 0
    for entry in entries:
        projected = total + len(entry.body) + (1 if bounded else 0)
        if projected > MAX_CONTEXT_RESPONSE:
            break
        bounded.append(entry)
        total = projected
    return bounded


def story_context(db: Database, task_id: int, *, limit: int = 10) -> list[ContextEntry]:
    """Context of the nearest story ancestor (or the task itself), oldest-first."""
    conn = db.connect()
    try:
        return _story_context_conn(conn, task_id, limit)
    finally:
        conn.close()


def context_append(
    db: Database, task_id: int, *, body: str, actor: str | None = None
) -> ContextEntry:
    """Append a curated fact to a story's context, evicting the oldest past 20."""
    body = _validate_context_body(body)
    if actor is not None and not isinstance(actor, str):
        raise ValidationError("actor must be a string or null")

    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            if task["type"] != "story":
                raise ValidationError("context entries attach to story tasks")
            stored = conn.execute(
                "SELECT count(*) FROM task_context WHERE task_id=?", (task_id,)
            ).fetchone()[0]
            excess = stored - MAX_CONTEXT_ENTRIES + 1
            if excess > 0:
                conn.execute(
                    "DELETE FROM task_context WHERE id IN ("
                    "SELECT id FROM task_context WHERE task_id=? ORDER BY id ASC LIMIT ?)",
                    (task_id, excess),
                )
            cursor = conn.execute(
                "INSERT INTO task_context(task_id, body, actor, created_at) VALUES (?, ?, ?, ?)",
                (task_id, body, actor, db.utc_now()),
            )
            row = conn.execute(
                "SELECT * FROM task_context WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            return _context_from_row(row)
    finally:
        conn.close()


def context_entries(db: Database, task_id: int) -> list[ContextEntry]:
    """Every stored context entry for ``task_id``, oldest-first (read-only)."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM task_context WHERE task_id=? ORDER BY id ASC", (task_id,)
        ).fetchall()
        return [_context_from_row(row) for row in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Recall ("did we already try this?")
# ---------------------------------------------------------------------------

MAX_RECALL_LIMIT = 20


def search_backend(db: Database) -> str:
    """The backend ``recall`` would use right now: ``fts`` or ``like``."""
    return "fts" if db.fts_enabled() else "like"


def _search_tokens(query: str) -> list[str]:
    """Split a user query into literals that are safe to quote for FTS5.

    Anything that is not a word character is dropped, so no FTS5 operator
    syntax can ever reach ``MATCH``; the tokens are ANDed, which keeps
    "backoff retry" a useful multi-term query rather than an exact phrase.
    """
    return re.findall(r"\w+", query, re.UNICODE)


def _match_expression(tokens: list[str]) -> str:
    return " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def _like_snippet(text: str, tokens: list[str], width: int = 80) -> str:
    """A short window around the earliest match, with ellipses."""
    lowered = text.lower()
    index = -1
    for token in tokens:
        found = lowered.find(token)
        if found != -1 and (index == -1 or found < index):
            index = found
    if index == -1:
        index = 0
    start = max(0, index - width // 3)
    end = min(len(text), start + width)
    snippet = " ".join(text[start:end].split())
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


def _recall_journal_fts(
    conn: sqlite3.Connection, expression: str, project_id: int | None, limit: int
) -> list[RecallHit]:
    clauses = ["journal_fts MATCH ?"]
    params: list[Any] = [expression]
    if project_id is not None:
        clauses.append("j.project_id=?")
        params.append(project_id)
    else:
        clauses.append("p.archived_at IS NULL")
    params.append(limit)
    rows = conn.execute(
        "SELECT j.id, j.task_id, j.project_id, j.created_at, t.title, t.status, "
        "snippet(journal_fts, 0, '…', '…', '…', 12) AS snippet "
        "FROM journal_fts "
        "JOIN journal j ON j.id = journal_fts.rowid "
        "JOIN projects p ON p.id = j.project_id "
        "LEFT JOIN tasks t ON t.id = j.task_id "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY journal_fts.rowid DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        RecallHit(
            source="journal",
            task_id=row["task_id"],
            project_id=row["project_id"],
            title=row["title"],
            snippet=row["snippet"],
            created_at=row["created_at"],
            status=row["status"],
        )
        for row in rows
    ]


def _recall_journal_like(
    conn: sqlite3.Connection,
    tokens: list[str],
    project_id: int | None,
    limit: int,
) -> list[RecallHit]:
    clauses = ["LOWER(j.body) LIKE ?" for _ in tokens]
    params: list[Any] = [f"%{token.lower()}%" for token in tokens]
    if project_id is not None:
        clauses.append("j.project_id=?")
        params.append(project_id)
    else:
        clauses.append("p.archived_at IS NULL")
    params.append(limit)
    rows = conn.execute(
        "SELECT j.id, j.task_id, j.project_id, j.created_at, j.body, t.title, t.status "
        "FROM journal j "
        "JOIN projects p ON p.id = j.project_id "
        "LEFT JOIN tasks t ON t.id = j.task_id "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY j.id DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        RecallHit(
            source="journal",
            task_id=row["task_id"],
            project_id=row["project_id"],
            title=row["title"],
            snippet=_like_snippet(row["body"], tokens),
            created_at=row["created_at"],
            status=row["status"],
        )
        for row in rows
    ]


def _recall_tasks_fts(
    conn: sqlite3.Connection, expression: str, project_id: int | None, limit: int
) -> list[RecallHit]:
    clauses = ["task_fts MATCH ?"]
    params: list[Any] = [expression]
    if project_id is not None:
        clauses.append("t.project_id=?")
        params.append(project_id)
    else:
        clauses.append("p.archived_at IS NULL")
    params.append(limit)
    rows = conn.execute(
        "SELECT t.id, t.project_id, t.title, t.status, t.created_at, "
        "snippet(task_fts, -1, '…', '…', '…', 12) AS snippet "
        "FROM task_fts "
        "JOIN tasks t ON t.id = task_fts.rowid "
        "JOIN projects p ON p.id = t.project_id "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY task_fts.rowid DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        RecallHit(
            source="task",
            task_id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            snippet=row["snippet"],
            created_at=row["created_at"],
            status=row["status"],
        )
        for row in rows
    ]


def _recall_tasks_like(
    conn: sqlite3.Connection,
    tokens: list[str],
    project_id: int | None,
    limit: int,
) -> list[RecallHit]:
    clauses = [
        "(LOWER(t.title) LIKE ? OR LOWER(COALESCE(t.description, '')) LIKE ?)"
        for _ in tokens
    ]
    params: list[Any] = []
    for token in tokens:
        needle = f"%{token.lower()}%"
        params.extend([needle, needle])
    if project_id is not None:
        clauses.append("t.project_id=?")
        params.append(project_id)
    else:
        clauses.append("p.archived_at IS NULL")
    params.append(limit)
    rows = conn.execute(
        "SELECT t.id, t.project_id, t.title, t.status, t.created_at, t.description "
        "FROM tasks t JOIN projects p ON p.id = t.project_id "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY t.id DESC LIMIT ?",
        params,
    ).fetchall()
    return [
        RecallHit(
            source="task",
            task_id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            snippet=_like_snippet(
                " ".join(part for part in (row["title"], row["description"]) if part),
                tokens,
            ),
            created_at=row["created_at"],
            status=row["status"],
        )
        for row in rows
    ]


def recall(
    db: Database,
    query: str,
    *,
    project_id: int | None = None,
    limit: int = 10,
    require_fts: bool = False,
) -> list[RecallHit]:
    """Search tasks and journal entries; journal hits come first, newest first."""
    if not isinstance(query, str) or not query.strip():
        raise ValidationError("recall requires a non-empty query")
    limit = max(1, min(int(limit), MAX_RECALL_LIMIT))
    tokens = _search_tokens(query)

    conn = db.connect()
    try:
        if project_id is not None:
            _require_project(conn, project_id)
        fts = db.fts_enabled(conn)
        if not fts and require_fts:
            raise FtsUnavailable("FTS5 is required but not available")
        if not tokens:
            return []
        expression = _match_expression(tokens)
        if fts:
            hits = _recall_journal_fts(conn, expression, project_id, limit)
            remaining = limit - len(hits)
            if remaining > 0:
                hits.extend(_recall_tasks_fts(conn, expression, project_id, remaining))
            return hits
        hits = _recall_journal_like(conn, tokens, project_id, limit)
        remaining = limit - len(hits)
        if remaining > 0:
            hits.extend(_recall_tasks_like(conn, tokens, project_id, remaining))
        return hits
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sessions & checkpoints
# ---------------------------------------------------------------------------

SESSION_EVENT_KINDS = ("session_start", "compaction", "prompt", "task_switch")
MAX_SUMMARY_LINES = 60
MAX_SUMMARY = 4000
MAX_NEXT_ACTION = 200
MAX_NEXT_ACTIONS = 10
MAX_SESSION_DETAIL = 2000
MAX_CHECKPOINTS = 20


def _session_event_from_row(row: sqlite3.Row) -> SessionEvent:
    return SessionEvent(
        id=row["id"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        kind=row["kind"],
        detail=row["detail"],
        created_at=row["created_at"],
    )


def _parse_next_actions(text: str | None) -> list[str]:
    if not text:
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _checkpoint_from_row(row: sqlite3.Row) -> Checkpoint:
    return Checkpoint(
        id=row["id"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        summary=row["summary"],
        next_actions=_parse_next_actions(row["next_actions"]),
        created_at=row["created_at"],
    )


def _validate_task_scope(
    conn: sqlite3.Connection, project_id: int, task_id: int
) -> sqlite3.Row:
    task = _require_task(conn, task_id)
    if task["project_id"] != project_id:
        raise ValidationError(f"task {task_id} does not belong to project {project_id}")
    return task


def session_event(
    db: Database,
    project_id: int,
    kind: str,
    *,
    task_id: int | None = None,
    detail: str | None = None,
) -> SessionEvent:
    """Record one append-only session event against a project (and task)."""
    _validate_choice(kind, "kind", SESSION_EVENT_KINDS)
    if detail is not None:
        if not isinstance(detail, str):
            raise ValidationError("detail must be a string or null")
        if len(detail) > MAX_SESSION_DETAIL:
            raise ValidationError(
                f"detail must be at most {MAX_SESSION_DETAIL} characters"
            )

    conn = db.connect()
    try:
        with _immediate(conn):
            _require_project(conn, project_id)
            if task_id is not None:
                _validate_task_scope(conn, project_id, task_id)
            cursor = conn.execute(
                "INSERT INTO session_events(project_id, task_id, kind, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, task_id, kind, detail, db.utc_now()),
            )
            row = conn.execute(
                "SELECT * FROM session_events WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            return _session_event_from_row(row)
    finally:
        conn.close()


def _validate_summary(summary: str) -> str:
    if not isinstance(summary, str) or not summary.strip():
        raise ValidationError("checkpoint summary must be a non-empty string")
    if len(summary.splitlines()) > MAX_SUMMARY_LINES:
        raise ValidationError(
            f"checkpoint summary must be at most {MAX_SUMMARY_LINES} lines"
        )
    if len(summary) > MAX_SUMMARY:
        raise ValidationError(
            f"checkpoint summary must be at most {MAX_SUMMARY} characters"
        )
    return summary.strip()


def _normalise_next_actions(next_actions: Iterable[str] | None) -> list[str]:
    if next_actions is None:
        return []
    if isinstance(next_actions, str) or not isinstance(next_actions, Iterable):
        raise ValidationError("next_actions must be a list of strings")
    actions: list[str] = []
    for item in next_actions:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError("next_actions must contain non-empty strings")
        if len(item) > MAX_NEXT_ACTION:
            raise ValidationError(
                f"next_actions items must be at most {MAX_NEXT_ACTION} characters"
            )
        actions.append(item.strip())
    if len(actions) > MAX_NEXT_ACTIONS:
        raise ValidationError(
            f"next_actions must contain at most {MAX_NEXT_ACTIONS} items"
        )
    return actions


def checkpoint_save(
    db: Database,
    project_id: int,
    summary: str,
    *,
    task_id: int | None = None,
    next_actions: Iterable[str] | None = None,
) -> Checkpoint:
    """Store a handoff checkpoint; identical retries return the existing row."""
    summary = _validate_summary(summary)
    actions = _normalise_next_actions(next_actions)
    payload = json.dumps(actions, ensure_ascii=False) if actions else None

    conn = db.connect()
    try:
        with _immediate(conn):
            _require_project(conn, project_id)
            if task_id is not None:
                _validate_task_scope(conn, project_id, task_id)
            if task_id is None:
                latest = conn.execute(
                    "SELECT * FROM checkpoints WHERE project_id=? AND task_id IS NULL "
                    "ORDER BY id DESC LIMIT 1",
                    (project_id,),
                ).fetchone()
            else:
                latest = conn.execute(
                    "SELECT * FROM checkpoints WHERE project_id=? AND task_id=? "
                    "ORDER BY id DESC LIMIT 1",
                    (project_id, task_id),
                ).fetchone()
            if (
                latest is not None
                and latest["summary"] == summary
                and _parse_next_actions(latest["next_actions"]) == actions
            ):
                return _checkpoint_from_row(latest)
            cursor = conn.execute(
                "INSERT INTO checkpoints(project_id, task_id, summary, next_actions, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, task_id, summary, payload, db.utc_now()),
            )
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            return _checkpoint_from_row(row)
    finally:
        conn.close()


def checkpoint_latest(
    db: Database, project_id: int, *, task_id: int | None = None, n: int = 5
) -> list[Checkpoint]:
    """Newest checkpoints for a project (task_id IS NULL) or for one task."""
    n = max(1, min(int(n), MAX_CHECKPOINTS))
    conn = db.connect()
    try:
        _require_project(conn, project_id)
        if task_id is None:
            rows = conn.execute(
                "SELECT * FROM checkpoints WHERE project_id=? AND task_id IS NULL "
                "ORDER BY id DESC LIMIT ?",
                (project_id, n),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM checkpoints WHERE project_id=? AND task_id=? "
                "ORDER BY id DESC LIMIT ?",
                (project_id, task_id, n),
            ).fetchall()
        return [_checkpoint_from_row(row) for row in rows]
    finally:
        conn.close()


def session_event_count_since(
    db: Database, project_id: int, kind: str, since: str | None
) -> int:
    """Count session events of ``kind`` created strictly after ``since``."""
    conn = db.connect()
    try:
        _require_project(conn, project_id)
        if since is None:
            row = conn.execute(
                "SELECT count(*) FROM session_events WHERE project_id=? AND kind=?",
                (project_id, kind),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT count(*) FROM session_events "
                "WHERE project_id=? AND kind=? AND created_at > ?",
                (project_id, kind, since),
            ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def reap_expired_leases(db: Database) -> list[int]:
    """Return expired ``in_progress`` tasks to ``open``; return the reaped ids."""
    now = db.utc_now()
    conn = db.connect()
    try:
        with _immediate(conn):
            rows = conn.execute(
                "SELECT id FROM tasks WHERE status='in_progress' "
                "AND lease_expires_at IS NOT NULL AND lease_expires_at < ?",
                (now,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                conn.execute(
                    "UPDATE tasks SET status='open', owner=NULL, lease_expires_at=NULL, "
                    "updated_at=? WHERE status='in_progress' AND lease_expires_at IS NOT NULL "
                    "AND lease_expires_at < ?",
                    (now, now),
                )
            return ids
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


def _would_create_blocking_cycle(
    conn: sqlite3.Connection, task_id: int, related_id: int
) -> bool:
    """True if adding ``task_id blocked_by related_id`` closes a cycle."""
    stack = [related_id]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if current == task_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        rows = conn.execute(
            "SELECT related_id FROM task_relations WHERE task_id=? AND kind='blocked_by'",
            (current,),
        ).fetchall()
        stack.extend(row["related_id"] for row in rows)
    return False


def task_link(
    db: Database, task_id: int, related_id: int, kind: str
) -> Relation:
    """Create a typed relation, rejecting self-links, duplicates, and cycles."""
    _validate_choice(kind, "kind", RELATION_KINDS)
    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            related = _require_task(conn, related_id)
            if task_id == related_id:
                raise ValidationError("a task cannot be linked to itself")
            if task["project_id"] != related["project_id"]:
                raise ValidationError("linked tasks must belong to the same project")
            existing = conn.execute(
                "SELECT 1 FROM task_relations WHERE task_id=? AND related_id=? AND kind=?",
                (task_id, related_id, kind),
            ).fetchone()
            if existing is not None:
                raise ValidationError("tasks are already linked with this kind")
            if kind == "blocked_by" and _would_create_blocking_cycle(
                conn, task_id, related_id
            ):
                raise CycleDetected(
                    f"linking task {task_id} blocked_by {related_id} creates a cycle"
                )
            conn.execute(
                "INSERT INTO task_relations(task_id, related_id, kind) VALUES (?, ?, ?)",
                (task_id, related_id, kind),
            )
            return Relation(task_id=task_id, related_id=related_id, kind=kind)
    finally:
        conn.close()


def task_unlink(db: Database, task_id: int, related_id: int, kind: str) -> None:
    """Remove a relation. Removing a missing edge is a successful no-op."""
    _validate_choice(kind, "kind", RELATION_KINDS)
    conn = db.connect()
    try:
        with _immediate(conn):
            _require_task(conn, task_id)
            _require_task(conn, related_id)
            conn.execute(
                "DELETE FROM task_relations WHERE task_id=? AND related_id=? AND kind=?",
                (task_id, related_id, kind),
            )
    finally:
        conn.close()


def task_graph(db: Database, project_id: int) -> Graph:
    """Return all project tasks, typed edges, and the computed waiting set."""
    reap_expired_leases(db)
    conn = db.connect()
    try:
        _require_project(conn, project_id)
        nodes = conn.execute(
            "SELECT * FROM tasks WHERE project_id=? ORDER BY priority, seq, id",
            (project_id,),
        ).fetchall()
        edges = conn.execute(
            "SELECT r.task_id, r.related_id, r.kind FROM task_relations r "
            "JOIN tasks t ON t.id = r.task_id WHERE t.project_id=? "
            "ORDER BY r.task_id, r.related_id, r.kind",
            (project_id,),
        ).fetchall()
        return Graph(
            project_id=project_id,
            nodes=[
                GraphNode(
                    id=row["id"],
                    title=row["title"],
                    status=row["status"],
                    priority=row["priority"],
                    seq=row["seq"],
                    type=row["type"],
                    workflow=row["workflow"],
                )
                for row in nodes
            ],
            edges=[
                GraphEdge(
                    from_id=row["task_id"], to_id=row["related_id"], kind=row["kind"]
                )
                for row in edges
            ],
            waiting=[item["id"] for item in scheduler.waiting_tasks(db, project_id)],
        )
    finally:
        conn.close()


def task_delete(db: Database, task_id: int, *, hard: bool = False) -> Task:
    """Soft-cancel by default; ``hard=True`` permanently deletes the row."""
    conn = db.connect()
    try:
        with _immediate(conn):
            task = _require_task(conn, task_id)
            result = _task_from_row(task)
            if hard:
                conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            else:
                conn.execute(
                    "UPDATE tasks SET status='cancelled', owner=NULL, lease_expires_at=NULL, "
                    "updated_at=? WHERE id=?",
                    (db.utc_now(), task_id),
                )
            return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read-side helpers for resume / export / dashboard (no writes)
# ---------------------------------------------------------------------------


def get_project(db: Database, project_id: int) -> Project:
    """Fetch one project by id."""
    conn = db.connect()
    try:
        return _project_from_row(_require_project(conn, project_id))
    finally:
        conn.close()


def resolve_project_id(db: Database, ref: str | int) -> int:
    """Resolve a project slug or numeric id to an id."""
    if isinstance(ref, bool) or not isinstance(ref, (int, str)):
        raise ValidationError("project must be a slug or a project id")
    conn = db.connect()
    try:
        if isinstance(ref, int):
            _require_project(conn, ref)
            return ref
        slug = ref.strip()
        if not slug:
            raise ValidationError("project must be a slug or a project id")
        row = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()
        if row is None:
            raise NotFound(f"project '{slug}' not found")
        return int(row["id"])
    finally:
        conn.close()


def task_counts(db: Database, project_id: int) -> dict[str, int]:
    """Task counts by status for one project (all statuses, zero-filled)."""
    counts = dict.fromkeys(TASK_STATUSES, 0)
    conn = db.connect()
    try:
        _require_project(conn, project_id)
        rows = conn.execute(
            "SELECT status, count(*) AS total FROM tasks WHERE project_id=? GROUP BY status",
            (project_id,),
        ).fetchall()
        for row in rows:
            counts[row["status"]] = int(row["total"])
        return counts
    finally:
        conn.close()


def all_tasks(db: Database, project_id: int) -> list[Task]:
    """Every task of a project ordered ``priority, seq, id``."""
    conn = db.connect()
    try:
        _require_project(conn, project_id)
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id=? ORDER BY priority, seq, id",
            (project_id,),
        ).fetchall()
        return [_task_from_row(row) for row in rows]
    finally:
        conn.close()


def tasks_with_status(db: Database, project_id: int, status: str) -> list[Task]:
    """Tasks of one status ordered ``priority, seq, id``."""
    _validate_choice(status, "status", TASK_STATUSES)
    conn = db.connect()
    try:
        _require_project(conn, project_id)
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id=? AND status=? "
            "ORDER BY priority, seq, id",
            (project_id, status),
        ).fetchall()
        return [_task_from_row(row) for row in rows]
    finally:
        conn.close()


def last_journal_by_task(
    db: Database, task_ids: Iterable[int]
) -> dict[int, JournalEntry]:
    """Map each task id to its newest journal entry (one batched query)."""
    ids = [int(task_id) for task_id in task_ids]
    if not ids:
        return {}
    placeholders = ", ".join("?" for _ in ids)
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT j.* FROM journal j JOIN ("
            f"SELECT task_id, MAX(id) AS id FROM journal WHERE task_id IN ({placeholders}) "
            "GROUP BY task_id) latest ON latest.id = j.id",
            ids,
        ).fetchall()
        return {row["task_id"]: _journal_from_row(row) for row in rows}
    finally:
        conn.close()


def journal_recent(db: Database, project_id: int, limit: int = 8) -> list[JournalEntry]:
    """The newest journal entries of a project, task-scoped ones included."""
    limit = max(1, min(int(limit), 100))
    conn = db.connect()
    try:
        _require_project(conn, project_id)
        rows = conn.execute(
            "SELECT * FROM journal WHERE project_id=? ORDER BY id DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [_journal_from_row(row) for row in rows]
    finally:
        conn.close()


def journal_for_project(db: Database, project_id: int) -> list[JournalEntry]:
    """Every journal entry of a project, oldest-first (export)."""
    conn = db.connect()
    try:
        _require_project(conn, project_id)
        rows = conn.execute(
            "SELECT * FROM journal WHERE project_id=? ORDER BY id ASC", (project_id,)
        ).fetchall()
        return [_journal_from_row(row) for row in rows]
    finally:
        conn.close()


def project_relations(db: Database, project_id: int) -> list[Relation]:
    """Every relation whose source task belongs to the project, ordered."""
    conn = db.connect()
    try:
        _require_project(conn, project_id)
        rows = conn.execute(
            "SELECT r.task_id, r.related_id, r.kind FROM task_relations r "
            "JOIN tasks t ON t.id = r.task_id WHERE t.project_id=? "
            "ORDER BY r.task_id, r.kind, r.related_id",
            (project_id,),
        ).fetchall()
        return [
            Relation(task_id=row["task_id"], related_id=row["related_id"], kind=row["kind"])
            for row in rows
        ]
    finally:
        conn.close()


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse the UTC ISO-8601 timestamps this project writes."""
    if not value:
        return None
    for pattern in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def task_title(db: Database, task_id: int) -> str | None:
    """The title of one task, or ``None`` when it no longer exists."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT title FROM tasks WHERE id=?", (task_id,)).fetchone()
        return row["title"] if row is not None else None
    finally:
        conn.close()


def lease_left_minutes(expires_at: str | None, now: str | None = None) -> int | None:
    """Whole minutes left on a lease, floored at zero (``None`` when unleased)."""
    expires = parse_timestamp(expires_at)
    if expires is None:
        return None
    current = parse_timestamp(now) if now else datetime.now(timezone.utc)
    if current is None:
        current = datetime.now(timezone.utc)
    return max(0, math.ceil((expires - current).total_seconds() / 60))


def stories_with_context(
    db: Database,
    project_id: int,
    *,
    max_stories: int = 3,
    max_entries: int = 3,
) -> list[dict[str, Any]]:
    """Stories that hold context and have children, with their newest entries."""
    conn = db.connect()
    try:
        _require_project(conn, project_id)
        rows = conn.execute(
            "SELECT t.id FROM tasks t WHERE t.project_id=? AND t.type='story' "
            "AND EXISTS (SELECT 1 FROM task_context c WHERE c.task_id=t.id) "
            "AND EXISTS (SELECT 1 FROM tasks child WHERE child.parent_id=t.id) "
            "ORDER BY t.priority, t.seq, t.id LIMIT ?",
            (project_id, max_stories),
        ).fetchall()
        stories: list[dict[str, Any]] = []
        for row in rows:
            entries = conn.execute(
                "SELECT body FROM task_context WHERE task_id=? ORDER BY id DESC LIMIT ?",
                (row["id"], max_entries),
            ).fetchall()
            stories.append(
                {
                    "story_id": row["id"],
                    "entries": [item["body"] for item in reversed(entries)],
                }
            )
        return stories
    finally:
        conn.close()
