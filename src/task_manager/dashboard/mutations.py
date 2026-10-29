"""Write routes for the dashboard: the same functions the MCP tools call.

No route here contains SQL and no route writes ``status``: every mutation is a
:mod:`task_manager.repository` call inside its own transaction, so cycles,
illegal transitions, missing outcomes/reasons, and lease conflicts are refused
with exactly the payload the MCP tool returns.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import repository, scheduler
from ..db import Database
from ..errors import NotFound, TaskManagerError, ValidationError
from ..transitions import TRANSITIONS
from .board import build_board, build_card, default_project_id

router = APIRouter()

ACTIONS = {status: sorted(actions) for status, actions in TRANSITIONS.items()}


async def read_payload(request: Request) -> dict[str, Any]:
    """Accept JSON or an (htmx) form body and return a plain dict."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        data = await request.json()
        return data if isinstance(data, dict) else {}
    form = await request.form()
    payload: dict[str, Any] = {}
    for key in form.keys():
        values = form.getlist(key)
        payload[key] = values if len(values) > 1 else values[0]
    return payload


def _int(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be an integer") from None


def _optional_int(value: Any, field: str) -> int | None:
    if value in (None, ""):
        return None
    return _int(value, field)


def _id_list(value: Any, field: str) -> list[int]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    return [_int(item, field) for item in values]


def error_payload(exc: TaskManagerError, status_code: int = 422) -> JSONResponse:
    """The MCP error contract, verbatim: ``{ok, error, message}``."""
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": type(exc).__name__, "message": str(exc)},
    )


def _templates(request: Request):
    return request.app.state.templates


def _db(request: Request) -> Database:
    return Database(request.app.state.db_path)


def _render(request: Request, name: str, context: dict[str, Any], **kwargs) -> Response:
    return _templates(request).TemplateResponse(request, name, context, **kwargs)


def _render_board(request: Request, db: Database) -> HTMLResponse:
    return _render(request, "_board_body.html", build_board(db))


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------


@router.post("/tasks")
async def create_task(request: Request) -> Response:
    db = _db(request)
    payload = await read_payload(request)
    project_id = default_project_id(db)
    requested = _optional_int(payload.get("project_id"), "project_id")
    if requested is not None:
        project_id = requested

    context: dict[str, Any] = {"form": payload, "project_id": project_id}
    if project_id is None:
        context["error"] = "create a project before adding tasks"
        return _error_form(request, context)

    try:
        task = repository.task_add(
            db,
            project_id,
            str(payload.get("title") or ""),
            description=(payload.get("description") or None),
            type=str(payload.get("type") or "task"),
            workflow=str(payload.get("workflow") or "simple"),
            priority=_int(payload.get("priority", 3), "priority"),
            parent_id=_optional_int(payload.get("parent_id"), "parent_id"),
            blocked_by=_id_list(payload.get("blocked_by"), "blocked_by"),
        )
    except TaskManagerError as exc:
        context["error"] = str(exc)
        return _error_form(request, context)

    return _render(request, "_card.html", {"card": build_card(db, task)}, status_code=201)


def _error_form(request: Request, context: dict[str, Any]) -> Response:
    response = _render(request, "_add_task.html", context, status_code=422)
    response.headers["HX-Retarget"] = "closest details"
    response.headers["HX-Reswap"] = "outerHTML"
    return response


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def _action_start(db: Database, task_id: int, payload: dict[str, Any], actor: str) -> Any:
    return repository.task_start(
        db,
        task_id,
        actor=actor,
        lease_minutes=_optional_int(payload.get("lease_minutes"), "lease_minutes"),
    )


def _action_release(db: Database, task_id: int, payload: dict[str, Any], actor: str) -> Any:
    return repository.task_release(db, task_id, actor=actor)


def _action_complete(db: Database, task_id: int, payload: dict[str, Any], actor: str) -> Any:
    return repository.task_complete(
        db, task_id, actor=actor, outcome=str(payload.get("outcome") or "")
    )


def _action_close(db: Database, task_id: int, payload: dict[str, Any], actor: str) -> Any:
    return repository.task_close(db, task_id, actor=actor)


def _action_block(db: Database, task_id: int, payload: dict[str, Any], actor: str) -> Any:
    return repository.task_block(
        db, task_id, actor=actor, reason=str(payload.get("reason") or "")
    )


def _action_unblock(db: Database, task_id: int, payload: dict[str, Any], actor: str) -> Any:
    return repository.task_unblock(db, task_id, actor=actor)


def _action_reopen(db: Database, task_id: int, payload: dict[str, Any], actor: str) -> Any:
    return repository.task_reopen(
        db,
        task_id,
        actor=actor,
        lease_minutes=_optional_int(payload.get("lease_minutes"), "lease_minutes"),
    )


def _action_cancel(db: Database, task_id: int, payload: dict[str, Any], actor: str) -> Any:
    return repository.task_cancel(db, task_id, actor=actor)


DISPATCH = {
    "start": _action_start,
    "release": _action_release,
    "complete": _action_complete,
    "close": _action_close,
    "block": _action_block,
    "unblock": _action_unblock,
    "reopen": _action_reopen,
    "cancel": _action_cancel,
}


@router.post("/transitions")
async def transition(request: Request) -> Response:
    db = _db(request)
    payload = await read_payload(request)
    action = str(payload.get("action") or "").strip()
    handler = DISPATCH.get(action)
    if handler is None:
        return error_payload(ValidationError(f"unknown action '{action}'"))

    try:
        task_id = _int(payload.get("task_id"), "task_id")
        handler(db, task_id, payload, str(payload.get("actor") or "human"))
    except TaskManagerError as exc:
        return error_payload(exc)
    return _render_board(request, db)


@router.post("/tasks/{task_id}/takeover")
def takeover(task_id: int, request: Request) -> Response:
    db = _db(request)
    try:
        repository.task_release(db, task_id, actor="human", force=True)
        task = repository.task_start(db, task_id, actor="human")
    except TaskManagerError as exc:
        return error_payload(exc)
    return _render(request, "_card.html", {"card": build_card(db, task)})


# ---------------------------------------------------------------------------
# Links and journal
# ---------------------------------------------------------------------------


@router.post("/tasks/{task_id}/links")
async def add_link(task_id: int, request: Request) -> Response:
    db = _db(request)
    payload = await read_payload(request)
    try:
        relation = repository.task_link(
            db,
            task_id,
            _int(payload.get("related_id"), "related_id"),
            str(payload.get("kind") or ""),
        )
    except TaskManagerError as exc:
        return error_payload(exc)
    return JSONResponse(status_code=201, content={"ok": True, "data": relation.model_dump()})


@router.post("/tasks/{task_id}/journal")
async def add_journal(task_id: int, request: Request) -> Response:
    db = _db(request)
    payload = await read_payload(request)
    try:
        entry = repository.journal_add(
            db,
            task_id=task_id,
            kind=str(payload.get("kind") or ""),
            body=str(payload.get("body") or ""),
            actor=str(payload.get("actor") or "human"),
        )
    except TaskManagerError as exc:
        return error_payload(exc)
    return _render(
        request, "_journal_items.html", {"entries": [entry]}, status_code=201
    )


# ---------------------------------------------------------------------------
# Detail and graph (read-only)
# ---------------------------------------------------------------------------


@router.get("/tasks/{task_id}")
def task_detail(task_id: int, request: Request) -> Response:
    db = _db(request)
    try:
        detail = repository.task_get(db, task_id, journal_limit=50, context_limit=50)
    except TaskManagerError as exc:
        return error_payload(exc, status_code=404 if isinstance(exc, NotFound) else 422)

    relations = [
        {
            "related_id": relation.related_id,
            "kind": relation.kind,
            "target_status": relation.target_status,
            "satisfied": scheduler.is_terminal(relation.target_status),
        }
        for relation in detail.relations
    ]
    context = {
        "task": detail,
        "waiting": scheduler.is_waiting(db, task_id),
        "relations": relations,
        "actions": ACTIONS.get(detail.status, []),
        "children": detail.children,
        "story_context": detail.story_context,
        "journal": detail.journal,
    }
    return _render(request, "task_detail.html", context)


@router.get("/graph")
def graph(request: Request, project_id: int | None = None) -> Response:
    db = _db(request)
    chosen = project_id if project_id is not None else default_project_id(db)
    if chosen is None:
        return _render(
            request,
            "graph.html",
            {"project": None, "nodes": [], "edges": [], "waiting": set()},
        )
    try:
        data = repository.task_graph(db, chosen)
        project = repository.get_project(db, chosen)
    except TaskManagerError as exc:
        return error_payload(exc, status_code=404 if isinstance(exc, NotFound) else 422)

    waiting = set(data.waiting)
    nodes = [
        {
            "id": node.id,
            "title": node.title,
            "status": node.status,
            "priority": node.priority,
            "workflow": node.workflow,
            "waiting": node.id in waiting,
        }
        for node in data.nodes
    ]
    edges = [
        {"from_id": edge.from_id, "to_id": edge.to_id, "kind": edge.kind}
        for edge in data.edges
    ]
    return _render(
        request,
        "graph.html",
        {"project": project, "nodes": nodes, "edges": edges, "waiting": waiting},
    )
