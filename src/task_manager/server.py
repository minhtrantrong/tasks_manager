"""FastMCP server exposing task-manager as thin adapters over the repository."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from . import repository
from .config import load_config
from .db import Database
from .errors import TaskManagerError

logger = logging.getLogger(__name__)


def _serialise(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True)
    if isinstance(value, list):
        return [_serialise(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialise(item) for key, item in value.items()}
    return value


def _invoke(function, *args, **kwargs) -> dict[str, Any]:
    """Run a repository call and map domain errors to the structured contract."""
    try:
        return {"ok": True, "data": _serialise(function(*args, **kwargs))}
    except TaskManagerError as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def _register(server: FastMCP, db_provider) -> None:
    """Register every tool on ``server``; ``db_provider`` returns a Database."""

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    @server.tool()
    def project_upsert(
        slug: str,
        name: str,
        root_path: str | None = None,
        description: str | None = None,
        require_closure: bool = False,
    ) -> dict[str, Any]:
        """Create or fetch a project by slug (idempotent).

        Side effects: inserts or updates one projects row. Returns
        ``{"ok": true, "data": project}`` or ``{"ok": false, "error", "message"}``.
        """
        return _invoke(
            repository.project_upsert,
            db_provider(),
            slug,
            name,
            root_path=root_path,
            description=description,
            require_closure=require_closure,
        )

    @server.tool()
    def project_list() -> dict[str, Any]:
        """List projects with status counts. Read-only."""
        return _invoke(repository.project_list, db_provider())

    @server.tool()
    def project_archive(project_id: int) -> dict[str, Any]:
        """Archive a project without deleting it.

        Side effects: sets ``archived_at``. Returns the T04 structured result.
        """
        return _invoke(repository.project_archive, db_provider(), project_id)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    @server.tool()
    def task_add(
        project_id: int,
        title: str,
        description: str | None = None,
        design: str | None = None,
        type: str = "task",
        workflow: str = "simple",
        priority: int = 3,
        parent_id: int | None = None,
        blocked_by: list[int] | None = None,
        prepend: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a task, optionally linking ``blocked_by`` tasks.

        Side effects: inserts one task and zero or more relations. Returns the
        structured ``{ok, data}`` result; validation failures are returned as
        ``{ok: false, error, message}`` and never raised.
        """
        return _invoke(
            repository.task_add,
            db_provider(),
            project_id,
            title,
            description=description,
            design=design,
            type=type,
            workflow=workflow,
            priority=priority,
            parent_id=parent_id,
            blocked_by=blocked_by,
            prepend=prepend,
            meta=meta,
        )

    @server.tool()
    def task_update(
        task_id: int,
        title: str | None = None,
        description: str | None = None,
        design: str | None = None,
        priority: int | None = None,
        workflow: str | None = None,
        parent_id: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Patch task fields. Never changes status, owner, or lease.

        Side effects: updates one tasks row. Returns the T04 structured result.
        """
        return _invoke(
            repository.task_update,
            db_provider(),
            task_id,
            title=title,
            description=description,
            design=design,
            priority=priority,
            workflow=workflow,
            parent_id=parent_id,
            meta=meta,
        )

    @server.tool()
    def task_get(
        task_id: int, journal_limit: int = 5, context_limit: int = 10
    ) -> dict[str, Any]:
        """Fetch one task with relations, children, context, and journal tail. Read-only."""
        return _invoke(
            repository.task_get,
            db_provider(),
            task_id,
            journal_limit=journal_limit,
            context_limit=context_limit,
        )

    @server.tool()
    def task_query(
        project_id: int | None = None,
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
    ) -> dict[str, Any]:
        """Query tasks with one filter tool (capped and paginated). Read-only."""
        return _invoke(
            repository.task_query,
            db_provider(),
            project_id,
            task_id=task_id,
            workflow=workflow,
            parent_id=parent_id,
            type=type,
            status=status,
            text=text,
            waiting=waiting,
            ready=ready,
            limit=limit,
            offset=offset,
        )

    @server.tool()
    def task_delete(task_id: int, hard: bool = False) -> dict[str, Any]:
        """Soft-cancel a task by default; ``hard=True`` purges the row.

        Side effects: updates status to ``cancelled`` or deletes the task and
        its cascaded history. Returns the T04 structured result.
        """
        return _invoke(repository.task_delete, db_provider(), task_id, hard=hard)

    # ------------------------------------------------------------------
    # Relations
    # ------------------------------------------------------------------

    @server.tool()
    def task_link(task_id: int, related_id: int, kind: str) -> dict[str, Any]:
        """Add a ``blocked_by`` / ``related`` / ``discovered_during`` edge.

        Side effects: inserts one relation; rejects self-links, duplicates, and
        cycles with the T04 structured error contract.
        """
        return _invoke(repository.task_link, db_provider(), task_id, related_id, kind)

    @server.tool()
    def task_unlink(task_id: int, related_id: int, kind: str) -> dict[str, Any]:
        """Remove a relation (idempotent when the edge is absent).

        Side effects: deletes one relation if present. Returns ``data: null``.
        """
        return _invoke(repository.task_unlink, db_provider(), task_id, related_id, kind)

    @server.tool()
    def task_graph(project_id: int) -> dict[str, Any]:
        """Return the project DAG as nodes, edges, and the waiting set. Read-only."""
        return _invoke(repository.task_graph, db_provider(), project_id)

    @server.tool()
    def task_next(project_id: int, workflow: str | None = None) -> dict[str, Any]:
        """Return the next ready task, or ``data: null`` when none is ready. Read-only."""
        from . import scheduler

        return _invoke(scheduler.task_next, db_provider(), project_id, workflow=workflow)

    # ------------------------------------------------------------------
    # Flow / lifecycle
    # ------------------------------------------------------------------

    @server.tool()
    def task_start(
        task_id: int, actor: str, lease_minutes: int | None = None
    ) -> dict[str, Any]:
        """Claim a task atomically (``open`` → ``in_progress`` + lease).

        Side effects: sets status, owner, and lease. A conflicting lease returns
        ``LeaseConflict`` via the structured error contract.
        """
        return _invoke(
            repository.task_start,
            db_provider(),
            task_id,
            actor=actor,
            lease_minutes=lease_minutes,
        )

    @server.tool()
    def task_release(
        task_id: int, actor: str | None = None, force: bool = False
    ) -> dict[str, Any]:
        """Release an ``in_progress`` task back to ``open``.

        Side effects: clears owner and lease. Non-owners get ``LeaseConflict``
        unless ``force=True``.
        """
        return _invoke(
            repository.task_release,
            db_provider(),
            task_id,
            actor=actor,
            force=force,
        )

    @server.tool()
    def task_complete(task_id: int, actor: str, outcome: str) -> dict[str, Any]:
        """Complete a task; ``outcome`` is required (what changed and how verified).

        Side effects: sets status ``done``, records the outcome, clears the lease.
        """
        return _invoke(
            repository.task_complete, db_provider(), task_id, actor=actor, outcome=outcome
        )

    @server.tool()
    def task_close(task_id: int, actor: str) -> dict[str, Any]:
        """Accept a ``done`` task (``done`` → ``closed``). Side effect: status update."""
        return _invoke(repository.task_close, db_provider(), task_id, actor=actor)

    @server.tool()
    def task_block(task_id: int, actor: str, reason: str) -> dict[str, Any]:
        """Block a task on an external factor; ``reason`` is required and journalled."""
        return _invoke(
            repository.task_block, db_provider(), task_id, actor=actor, reason=reason
        )

    @server.tool()
    def task_unblock(
        task_id: int, actor: str, to: str = "open", lease_minutes: int | None = None
    ) -> dict[str, Any]:
        """Unblock to ``open`` (or directly to a leased ``in_progress``)."""
        return _invoke(
            repository.task_unblock,
            db_provider(),
            task_id,
            actor=actor,
            to=to,
            lease_minutes=lease_minutes,
        )

    @server.tool()
    def task_reopen(
        task_id: int, actor: str, lease_minutes: int | None = None
    ) -> dict[str, Any]:
        """Reopen a done/closed task, preserving its outcome in the journal."""
        return _invoke(
            repository.task_reopen,
            db_provider(),
            task_id,
            actor=actor,
            lease_minutes=lease_minutes,
        )

    @server.tool()
    def task_cancel(task_id: int, actor: str, hard: bool = False) -> dict[str, Any]:
        """Cancel a task (soft by default); ``hard=True`` purges it."""
        return _invoke(
            repository.task_cancel, db_provider(), task_id, actor=actor, hard=hard
        )

    # ------------------------------------------------------------------
    # Journal (append-only)
    # ------------------------------------------------------------------

    @server.tool()
    def journal_add(
        kind: str,
        body: str,
        task_id: int | None = None,
        project_id: int | None = None,
        actor: str | None = None,
        session_ref: str | None = None,
    ) -> dict[str, Any]:
        """Append one journal entry to a task or project (append-only).

        Side effects: inserts one journal row. Entries are capped at 6 lines /
        1500 chars server-side; invalid input returns the structured error.
        """
        return _invoke(
            repository.journal_add,
            db_provider(),
            task_id=task_id,
            project_id=project_id,
            kind=kind,
            body=body,
            actor=actor,
            session_ref=session_ref,
        )

    @server.tool()
    def journal_list(
        task_id: int | None = None,
        project_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
        before: int | None = None,
    ) -> dict[str, Any]:
        """List journal entries newest-first, capped and cursor-paginated. Read-only."""
        return _invoke(
            _journal_page,
            task_id=task_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
            before=before,
        )

    def _journal_page(
        *,
        task_id: int | None = None,
        project_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
        before: int | None = None,
    ) -> dict[str, Any]:
        items = repository.journal_list(
            db_provider(),
            task_id=task_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
            before=before,
        )
        return {
            "items": items,
            "offset": max(0, int(offset)),
            "limit": max(1, min(int(limit), 100)),
            "before": before,
        }


def create_server(db_path: Path) -> FastMCP:
    """Create a server bound to ``db_path``."""
    server = FastMCP("task-manager")
    _register(server, lambda: Database(db_path))
    return server


# Module-level singleton (used by callers that rely on the default config).
mcp = FastMCP("task-manager")
_register(mcp, lambda: Database(load_config().db_path))
