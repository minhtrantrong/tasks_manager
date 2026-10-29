"""Read-side board rendering: the same state the MCP tools report, for eyes.

Every field comes from :mod:`task_manager.repository` and
:mod:`task_manager.scheduler`; this module contains no SQL and performs no
writes. ``waiting`` is rendered as a badge on a dimmed card — never a column.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import repository, scheduler
from ..db import Database

BOARD_COLUMNS = ("open", "in_progress", "blocked", "done", "closed")
SWIMLANES = ("none", "workflow", "parent")
MAX_CARDS = 200
JOURNAL_PREVIEW = 100
NO_PARENT_LANE = "No parent"

router = APIRouter()


def _short(text: str, limit: int = JOURNAL_PREVIEW) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "…"


def default_project_id(db: Database) -> int | None:
    """The project a newly added board task belongs to (first non-archived)."""
    projects = repository.project_list(db)
    active = [project for project in projects if not project.archived]
    if active:
        return active[0].id
    return projects[0].id if projects else None


def _waiting_map(db: Database) -> dict[int, list[int]]:
    waiting: dict[int, list[int]] = {}
    for project in repository.project_list(db):
        for item in scheduler.waiting_tasks(db, project.id):
            waiting[item["id"]] = item["needs"]
    return waiting


def _lane_name(card: dict[str, Any], swimlane: str) -> str:
    if swimlane == "workflow":
        return card["workflow"]
    return card["parent_title"] or NO_PARENT_LANE


def _lane_sort_key(name: str) -> tuple[int, str]:
    return (1 if name == NO_PARENT_LANE else 0, name.lower())


def build_board(
    db: Database, *, swimlane: str = "none", show_cancelled: bool = False
) -> dict[str, Any]:
    """Everything ``board.html`` needs; ``waiting`` is computed, never stored."""
    swimlane = swimlane if swimlane in SWIMLANES else "none"
    statuses = list(BOARD_COLUMNS) + (["cancelled"] if show_cancelled else [])

    waiting = _waiting_map(db)
    now = db.utc_now()
    titles: dict[int, str] = {}
    for project in repository.project_list(db):
        for task in repository.all_tasks(db, project.id):
            titles[task.id] = task.title

    pages = {
        status: repository.task_query(db, None, status=status, limit=MAX_CARDS)
        for status in statuses
    }
    journals = repository.last_journal_by_task(
        db,
        [
            task.id
            for page in pages.values()
            for task in page.items
        ],
    )

    columns: list[dict[str, Any]] = []
    for status in statuses:
        cards: list[dict[str, Any]] = []
        for task in pages[status].items:
            entry = journals.get(task.id)
            cards.append(
                {
                    "id": task.id,
                    "title": task.title,
                    "type": task.type,
                    "priority": task.priority,
                    "workflow": task.workflow,
                    "owner": task.owner,
                    "status": task.status,
                    "parent_id": task.parent_id,
                    "parent_title": titles.get(task.parent_id),
                    "waiting": task.id in waiting,
                    "waits_on": waiting.get(task.id, []),
                    "lease_left": repository.lease_left_minutes(
                        task.lease_expires_at, now
                    ),
                    "last_journal": (
                        {"kind": entry.kind, "body": _short(entry.body)}
                        if entry is not None
                        else None
                    ),
                }
            )

        lanes: list[dict[str, Any]] = []
        if swimlane != "none":
            grouped: dict[str, list[dict[str, Any]]] = {}
            for card in cards:
                grouped.setdefault(_lane_name(card, swimlane), []).append(card)
            lanes = [
                {"name": name, "cards": grouped[name]}
                for name in sorted(grouped, key=_lane_sort_key)
            ]

        columns.append(
            {
                "status": status,
                "count": len(cards),
                "cards": cards,
                "lanes": lanes,
            }
        )

    return {
        "columns": columns,
        "swimlane": swimlane,
        "show_cancelled": show_cancelled,
        "project_id": default_project_id(db),
    }


def build_card(db: Database, task: Any) -> dict[str, Any]:
    """One card's view-model for a single task (used by mutation responses)."""
    now = db.utc_now()
    entry = repository.last_journal_by_task(db, [task.id]).get(task.id)
    waiting = _waiting_map(db)
    parent_id = getattr(task, "parent_id", None)
    parent_title = repository.task_title(db, parent_id) if parent_id else None
    return {
        "id": task.id,
        "title": task.title,
        "type": task.type,
        "priority": task.priority,
        "workflow": task.workflow,
        "owner": task.owner,
        "status": task.status,
        "parent_id": parent_id,
        "parent_title": parent_title,
        "waiting": task.id in waiting,
        "waits_on": waiting.get(task.id, []),
        "lease_left": repository.lease_left_minutes(task.lease_expires_at, now),
        "last_journal": (
            {"kind": entry.kind, "body": _short(entry.body)} if entry is not None else None
        ),
    }


@router.get("/board", response_class=HTMLResponse)
def board(
    request: Request, swimlane: str = "none", show_cancelled: int = 0
) -> HTMLResponse:
    db = Database(request.app.state.db_path)
    context = build_board(db, swimlane=swimlane, show_cancelled=bool(show_cancelled))
    template = (
        "_board_body.html"
        if request.headers.get("HX-Request") == "true"
        else "board.html"
    )
    return request.app.state.templates.TemplateResponse(request, template, context)
