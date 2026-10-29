"""Assembly of the ``resume`` briefing — the one call that restarts work.

Token budget (N2): the briefing is serialised with ``json.dumps`` and measured
in characters. ``ceil(len(payload) / 4)`` is the token estimate — the classic
char/4 heuristic stands in for a tokenizer so the server stays dependency-free.
The hard ceilings are 5200 characters and 1300 estimated tokens (~1200 target
plus headroom); every list is structurally capped first and, if the payload is
still too large, entries are dropped in the documented order: ``recent`` →
``story_context`` → ``ready`` → ``waiting_on`` → ``blocked`` → ``in_progress``.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from . import repository, scheduler
from .db import Database

MAX_PAYLOAD_CHARS = 5200
MAX_ESTIMATED_TOKENS = 1300

MAX_CHECKPOINT_SUMMARY = 500
MAX_CHECKPOINT_ACTIONS = 5
MAX_LAST_JOURNAL = 200
MAX_BLOCK_REASON = 200
MAX_WAITING = 10
MAX_READY = 10
MAX_STORY_STORIES = 3
MAX_STORY_ENTRIES = 3
MAX_STORY_ENTRY_CHARS = 200
MAX_RECENT = 8
MAX_RECENT_BODY = 120
MAX_IN_PROGRESS = 20
MAX_BLOCKED = 20
STALE_AFTER = timedelta(days=7)


def _flatten(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str | None, limit: int) -> str:
    cleaned = _flatten(text or "")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "…"


def _parse_timestamp(value: str | None) -> datetime | None:
    return repository.parse_timestamp(value)


def _lease_left_min(expires_at: str | None, now: datetime) -> int | None:
    return repository.lease_left_minutes(
        expires_at, now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    )


def _is_stale(entry: Any, now: datetime) -> bool:
    if entry is None:
        return True
    created = _parse_timestamp(entry.created_at)
    if created is None:
        return True
    return (now - created) > STALE_AFTER


def _checkpoint_section(checkpoint: Any) -> dict[str, Any] | None:
    if checkpoint is None:
        return None
    return {
        "at": checkpoint.created_at,
        "summary": _truncate(checkpoint.summary, MAX_CHECKPOINT_SUMMARY),
        "next_actions": [
            _truncate(action, MAX_LAST_JOURNAL)
            for action in checkpoint.next_actions[:MAX_CHECKPOINT_ACTIONS]
        ],
    }


def _estimate_tokens(payload: dict[str, Any]) -> tuple[int, int]:
    text = json.dumps(payload, ensure_ascii=False)
    return len(text), math.ceil(len(text) / 4)


def _fits(payload: dict[str, Any]) -> bool:
    chars, tokens = _estimate_tokens(payload)
    return chars <= MAX_PAYLOAD_CHARS and tokens <= MAX_ESTIMATED_TOKENS


def _shrink_to_budget(payload: dict[str, Any]) -> dict[str, Any]:
    drop_order = ("recent", "story_context", "ready", "waiting_on", "blocked", "in_progress")
    while not _fits(payload):
        for key in drop_order:
            if payload[key]:
                payload[key].pop()
                break
        else:  # nothing left to drop
            break
    return payload


def build_resume(db: Database, project_id: int) -> dict[str, Any]:
    """Assemble the bounded briefing for ``project_id``."""
    project = repository.get_project(db, project_id)
    now_iso = db.utc_now()
    now = _parse_timestamp(now_iso) or datetime.now(timezone.utc)

    lease_expired = repository.reap_expired_leases(db)

    counts = repository.task_counts(db, project_id)
    waiting = scheduler.waiting_tasks(db, project_id)
    ready = scheduler.ready_tasks(db, project_id, limit=MAX_READY)
    in_progress_tasks = repository.tasks_with_status(db, project_id, "in_progress")[
        :MAX_IN_PROGRESS
    ]
    blocked_tasks = repository.tasks_with_status(db, project_id, "blocked")[:MAX_BLOCKED]
    last_journals = repository.last_journal_by_task(
        db, [task.id for task in in_progress_tasks]
    )

    in_progress: list[dict[str, Any]] = []
    stale: list[int] = []
    for task in in_progress_tasks:
        entry = last_journals.get(task.id)
        in_progress.append(
            {
                "id": task.id,
                "title": task.title,
                "workflow": task.workflow,
                "owner": task.owner,
                "lease_left_min": _lease_left_min(task.lease_expires_at, now),
                "last_journal": (
                    {
                        "kind": entry.kind,
                        "body": _truncate(entry.body, MAX_LAST_JOURNAL),
                    }
                    if entry is not None
                    else None
                ),
            }
        )
        if _is_stale(entry, now):
            stale.append(task.id)

    blocked = [
        {
            "id": task.id,
            "title": task.title,
            "reason": _truncate(task.block_reason, MAX_BLOCK_REASON),
        }
        for task in blocked_tasks
    ]

    waiting_on = [
        {"id": item["id"], "title": item["title"], "needs": item["needs"]}
        for item in waiting[:MAX_WAITING]
    ]

    ready_section = [
        {
            "id": task.id,
            "title": task.title,
            "workflow": task.workflow,
            "priority": task.priority,
        }
        for task in ready[:MAX_READY]
    ]

    story_context = [
        {
            "story_id": story["story_id"],
            "entries": [
                _truncate(body, MAX_STORY_ENTRY_CHARS) for body in story["entries"]
            ],
        }
        for story in repository.stories_with_context(
            db,
            project_id,
            max_stories=MAX_STORY_STORIES,
            max_entries=MAX_STORY_ENTRIES,
        )
    ]

    recent = [
        {
            "kind": entry.kind,
            "body": _truncate(entry.body, MAX_RECENT_BODY),
            "task_id": entry.task_id,
            "at": entry.created_at,
        }
        for entry in repository.journal_recent(db, project_id, limit=MAX_RECENT)
    ]

    checkpoints = repository.checkpoint_latest(db, project_id, n=1)
    checkpoint = checkpoints[0] if checkpoints else None
    compactions = repository.session_event_count_since(
        db,
        project_id,
        "compaction",
        checkpoint.created_at if checkpoint is not None else None,
    )

    payload: dict[str, Any] = {
        "project": {
            "slug": project.slug,
            "open": counts.get("open", 0),
            "waiting": len(waiting),
            "blocked": counts.get("blocked", 0),
            "in_progress": counts.get("in_progress", 0),
            "done": counts.get("done", 0),
        },
        "last_checkpoint": _checkpoint_section(checkpoint) or {},
        "in_progress": in_progress,
        "blocked": blocked,
        "waiting_on": waiting_on,
        "ready": ready_section,
        "story_context": story_context,
        "recent": recent,
        "health": {
            "stale": stale,
            "compactions_since_checkpoint": compactions,
            "lease_expired": lease_expired,
        },
    }
    return _shrink_to_budget(payload)
