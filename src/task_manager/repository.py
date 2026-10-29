"""The single write path for task-manager (N7).

Every mutation of projects, tasks, relations, journal entries, context, session
events, and checkpoints lives in this module. All invariants are validated inside
the same transaction as the write.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from . import scheduler, transitions
from .db import Database
from .errors import (
    CycleDetected,
    LeaseConflict,
    MissingOutcome,
    MissingReason,
    NotFound,
    ValidationError,
)
from .models import (
    ContextEntry,
    Graph,
    GraphEdge,
    GraphNode,
    JournalEntry,
    Page,
    Project,
    ProjectSummary,
    Relation,
    RelationView,
    Task,
    TaskDetail,
    TaskSummary,
)

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
            story_context=[],
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
    db: Database, task: sqlite3.Row, lease_minutes: int | None
) -> int:
    if lease_minutes is None:
        return 60
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
            minutes = _resolve_lease_minutes(db, task, lease_minutes)
            _claim(conn, db, task, actor=actor, lease_minutes=minutes, now=now)
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return _task_from_row(row)
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
            return _task_from_row(row)
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
                minutes = _resolve_lease_minutes(db, task, lease_minutes)
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
            minutes = _resolve_lease_minutes(db, task, lease_minutes)
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
    """List journal entries newest-first, optionally scoped and cursor-paginated."""
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
        else:
            clauses.append("task_id IS NULL")
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
