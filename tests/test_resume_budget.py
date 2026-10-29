"""T13 / TT13 — resume assembly, truncation, and acceptance C (bounded memory)."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

import task_manager.db as db_module
from task_manager import repository, resume, scheduler
from task_manager.db import Database
from task_manager.errors import NotFound


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


@pytest.fixture()
def project(db):
    return repository.project_upsert(db, "demo", "Demo")


def _freeze(monkeypatch, moment: datetime) -> None:
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    monkeypatch.setattr(db_module, "utc_now", lambda: stamp)


def _seed_large(db, project, monkeypatch):
    """The acceptance C fixture: 50+ tasks, blocked/waiting/ready, 2 compactions."""
    ids: dict[str, list[int]] = {"in_progress": [], "blocked": [], "ready": [], "waiting": []}
    now = datetime.now(timezone.utc)

    # Four in-progress tasks with journals; one of them is stale (8 days old).
    for index in range(4):
        task = repository.task_add(db, project.id, f"Leased work {index}", priority=2)
        repository.task_start(db, task.id, actor=f"agent-{index}", lease_minutes=90)
        repository.journal_add(
            db,
            task_id=task.id,
            kind="attempt",
            body=f"attempt {index}: retry uses backoff 2^n",
            actor=f"agent-{index}",
        )
        ids["in_progress"].append(task.id)

    stale_task = repository.task_add(db, project.id, "Stale leased work", priority=2)
    _freeze(monkeypatch, now - timedelta(days=8))
    repository.task_start(db, stale_task.id, actor="agent-stale", lease_minutes=12000)
    repository.journal_add(
        db, task_id=stale_task.id, kind="problem", body="waiting on upstream", actor="agent-stale"
    )
    _freeze(monkeypatch, now)

    # Eight blocked tasks with reasons.
    for index in range(8):
        task = repository.task_add(db, project.id, f"Blocked work {index}", priority=3)
        repository.task_block(
            db, task.id, actor="agent-1", reason=f"needs decision {index}"
        )
        ids["blocked"].append(task.id)

    # Waiting chain: two tasks blocked by the first (still open) task.
    blocker = repository.task_add(db, project.id, "Upstream blocker", priority=1)
    for index in range(2):
        waiting = repository.task_add(db, project.id, f"Waiting task {index}", priority=3)
        repository.task_link(db, waiting.id, blocker.id, "blocked_by")
        ids["waiting"].append(waiting.id)

    # Enough independent ready tasks to need the cap.
    for index in range(14):
        task = repository.task_add(db, project.id, f"Ready work {index}", priority=4)
        ids["ready"].append(task.id)

    # Filler for the 50+ task claim.
    for index in range(30):
        task = repository.task_add(db, project.id, f"Filler {index}", priority=5)
        repository.task_cancel(db, task.id, actor="seeder")

    # One story with context and a child.
    story = repository.task_add(db, project.id, "Story", type="story", priority=1)
    repository.context_append(db, story.id, body="sibling fact one", actor="agent-1")
    repository.context_append(db, story.id, body="sibling fact two", actor="agent-1")
    repository.task_add(db, project.id, "Story child", parent_id=story.id, priority=2)

    repository.checkpoint_save(
        db,
        project.id,
        "handoff summary\nline two",
        next_actions=["run the failing test", "narrow the protocol"],
    )
    for index in range(2):
        _freeze(monkeypatch, now + timedelta(minutes=index + 1))
        repository.session_event(db, project.id, "compaction")
    _freeze(monkeypatch, now + timedelta(minutes=2))

    ids["stale"] = stale_task.id
    ids["blocker"] = blocker.id
    return ids


def test_bounded_memory_acceptance_c(db, project, monkeypatch):
    ids = _seed_large(db, project, monkeypatch)
    payload = resume.build_resume(db, project.id)
    text = json.dumps(payload, ensure_ascii=False)

    assert len(text) <= resume.MAX_PAYLOAD_CHARS
    assert math.ceil(len(text) / 4) <= resume.MAX_ESTIMATED_TOKENS

    assert payload["project"]["slug"] == "demo"
    assert payload["project"]["in_progress"] == 5
    assert payload["project"]["blocked"] == 8
    assert payload["project"]["waiting"] == 2

    assert payload["last_checkpoint"]["next_actions"] == [
        "run the failing test",
        "narrow the protocol",
    ]
    assert payload["last_checkpoint"]["summary"].startswith("handoff summary")

    assert len(payload["in_progress"]) == 5
    first = payload["in_progress"][0]
    assert first["owner"] == "agent-0"
    assert first["last_journal"]["kind"] == "attempt"
    assert "retry uses backoff 2^n" in first["last_journal"]["body"]
    assert 88 <= first["lease_left_min"] <= 90

    assert [entry["id"] for entry in payload["blocked"]] == ids["blocked"]
    assert all(entry["reason"] for entry in payload["blocked"])

    assert {entry["id"] for entry in payload["waiting_on"]} >= set(ids["waiting"])
    waiter = next(
        entry for entry in payload["waiting_on"] if entry["id"] == ids["waiting"][0]
    )
    assert waiter["needs"] == [ids["blocker"]]

    assert len(payload["ready"]) <= resume.MAX_READY
    ready_ids = {task.id for task in scheduler.ready_tasks(db, project.id)}
    assert {entry["id"] for entry in payload["ready"]} <= ready_ids
    assert ids["waiting"][0] not in {entry["id"] for entry in payload["ready"]}

    assert payload["story_context"][0]["entries"] == [
        "sibling fact one",
        "sibling fact two",
    ]

    assert len(payload["recent"]) <= resume.MAX_RECENT
    assert all(entry["task_id"] is not None for entry in payload["recent"])

    assert payload["health"]["stale"] == [ids["stale"]]
    assert payload["health"]["compactions_since_checkpoint"] == 2
    assert payload["health"]["lease_expired"] == []


def test_checkpoint_summary_is_truncated(db, project):
    repository.checkpoint_save(db, project.id, "z" * 4000)
    payload = resume.build_resume(db, project.id)
    summary = payload["last_checkpoint"]["summary"]
    assert summary.endswith("…")
    assert len(summary) <= resume.MAX_CHECKPOINT_SUMMARY + 1


def test_next_actions_capped_at_five(db, project):
    repository.checkpoint_save(
        db, project.id, "summary", next_actions=[f"action {index}" for index in range(10)]
    )
    payload = resume.build_resume(db, project.id)
    assert payload["last_checkpoint"]["next_actions"] == [
        f"action {index}" for index in range(5)
    ]


def test_lease_left_min_math(db, project):
    task = repository.task_add(db, project.id, "Lease math")
    repository.task_start(db, task.id, actor="agent-1", lease_minutes=20)
    payload = resume.build_resume(db, project.id)
    entry = next(item for item in payload["in_progress"] if item["id"] == task.id)
    assert 19 <= entry["lease_left_min"] <= 20


def test_expired_lease_is_reaped_and_reported(db, project, monkeypatch):
    task = repository.task_add(db, project.id, "Expiring")
    repository.task_start(db, task.id, actor="agent-1", lease_minutes=20)

    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    _freeze(monkeypatch, future)
    payload = resume.build_resume(db, project.id)

    assert task.id not in {item["id"] for item in payload["in_progress"]}
    assert payload["health"]["lease_expired"] == [task.id]
    assert repository.task_get(db, task.id).status == "open"


def test_empty_project_produces_a_valid_briefing(db, project):
    payload = resume.build_resume(db, project.id)
    assert payload["project"] == {
        "slug": "demo",
        "open": 0,
        "waiting": 0,
        "blocked": 0,
        "in_progress": 0,
        "done": 0,
    }
    assert payload["last_checkpoint"] == {}
    for key in ("in_progress", "blocked", "waiting_on", "ready", "story_context", "recent"):
        assert payload[key] == []
    assert payload["health"] == {
        "stale": [],
        "compactions_since_checkpoint": 0,
        "lease_expired": [],
    }
    assert all(value is not None for value in payload.values())


def test_slug_and_id_return_the_same_payload(db, project):
    repository.task_add(db, project.id, "Task")
    by_id = resume.build_resume(db, repository.resolve_project_id(db, project.id))
    by_slug = resume.build_resume(db, repository.resolve_project_id(db, "demo"))
    assert json.dumps(by_id, sort_keys=True) == json.dumps(by_slug, sort_keys=True)

    with pytest.raises(NotFound):
        repository.resolve_project_id(db, "missing")
    with pytest.raises(NotFound):
        repository.resolve_project_id(db, 999)


def test_staleness_boundary(db, project, monkeypatch):
    now = datetime.now(timezone.utc)
    fresh = repository.task_add(db, project.id, "Exactly seven days")
    repository.task_start(db, fresh.id, actor="agent-1", lease_minutes=12000)
    _freeze(monkeypatch, now - timedelta(days=7))
    repository.journal_add(db, task_id=fresh.id, kind="note", body="seven days old")

    _freeze(monkeypatch, now)
    payload = resume.build_resume(db, project.id)
    assert fresh.id not in payload["health"]["stale"]

    old = repository.task_add(db, project.id, "Older than seven days")
    repository.task_start(db, old.id, actor="agent-2", lease_minutes=12000)
    _freeze(monkeypatch, now - timedelta(days=7, seconds=1))
    repository.journal_add(db, task_id=old.id, kind="note", body="eight-ish days old")

    _freeze(monkeypatch, now)
    payload = resume.build_resume(db, project.id)
    assert payload["health"]["stale"] == [old.id]


def test_compactions_reset_after_a_new_checkpoint(db, project, monkeypatch):
    now = datetime.now(timezone.utc)
    _freeze(monkeypatch, now)
    repository.session_event(db, project.id, "compaction")
    _freeze(monkeypatch, now + timedelta(minutes=1))
    repository.checkpoint_save(db, project.id, "checkpoint")
    assert resume.build_resume(db, project.id)["health"]["compactions_since_checkpoint"] == 0

    _freeze(monkeypatch, now + timedelta(minutes=2))
    repository.session_event(db, project.id, "compaction")
    assert resume.build_resume(db, project.id)["health"]["compactions_since_checkpoint"] == 1

    _freeze(monkeypatch, now + timedelta(minutes=3))
    repository.checkpoint_save(db, project.id, "newer checkpoint")
    assert resume.build_resume(db, project.id)["health"]["compactions_since_checkpoint"] == 0


def test_recent_and_reason_and_context_truncation(db, project, monkeypatch):
    now = datetime.now(timezone.utc)
    _freeze(monkeypatch, now)
    task = repository.task_add(db, project.id, "Long bodies")
    repository.task_start(db, task.id, actor="agent-1", lease_minutes=60)
    repository.journal_add(db, task_id=task.id, kind="attempt", body="j" * 300)

    blocked = repository.task_add(db, project.id, "Long reason")
    repository.task_block(db, blocked.id, actor="agent-1", reason="r" * 500)

    story = repository.task_add(db, project.id, "Story", type="story")
    repository.context_append(db, story.id, body="c" * 400)
    repository.task_add(db, project.id, "Child", parent_id=story.id)

    payload = resume.build_resume(db, project.id)
    entry = next(item for item in payload["in_progress"] if item["id"] == task.id)
    assert len(entry["last_journal"]["body"]) == resume.MAX_LAST_JOURNAL + 1
    assert entry["last_journal"]["body"].endswith("…")

    reason = payload["blocked"][0]["reason"]
    assert len(reason) == resume.MAX_BLOCK_REASON + 1

    context = payload["story_context"][0]["entries"][0]
    assert len(context) == resume.MAX_STORY_ENTRY_CHARS + 1

    recent_bodies = [item["body"] for item in payload["recent"]]
    assert recent_bodies
    assert all(len(body) <= resume.MAX_RECENT_BODY + 1 for body in recent_bodies)


def test_drop_order_prefers_smaller_but_sufficient():
    payload = {
        "project": {"slug": "demo"},
        "last_checkpoint": {},
        "in_progress": [{"id": index, "padding": "x" * 400} for index in range(6)],
        "blocked": [{"id": index, "padding": "x" * 400} for index in range(6)],
        "waiting_on": [{"id": index, "padding": "x" * 200} for index in range(10)],
        "ready": [{"id": index, "padding": "x" * 200} for index in range(10)],
        "story_context": [
            {"story_id": index, "entries": ["y" * 200] * 3} for index in range(3)
        ],
        "recent": [{"body": "z" * 120} for _ in range(8)],
        "health": {"stale": [], "compactions_since_checkpoint": 0, "lease_expired": []},
    }
    assert not resume._fits(payload)
    shrunk = resume._shrink_to_budget(payload)
    assert resume._fits(shrunk)
    assert shrunk["recent"] == []
    assert shrunk["in_progress"] and shrunk["blocked"]
    assert shrunk["waiting_on"] == payload["waiting_on"] or shrunk["ready"] == []
