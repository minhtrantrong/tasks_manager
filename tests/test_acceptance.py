"""Acceptance tests: B (no double work) and A (cold resume)."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from task_manager import repository
from task_manager.dashboard.app import create_app
from task_manager.db import Database
from task_manager.errors import IllegalTransition, LeaseConflict
from task_manager.server import create_server


def _worker(db_path: str, project_id: int, actor: str, queue) -> None:
    database = Database(Path(db_path))
    try:
        while True:
            task = repository.task_next(database, project_id)
            if task is None:
                break
            try:
                repository.task_start(database, task.id, actor=actor, lease_minutes=1)
            except LeaseConflict:
                continue
            except IllegalTransition:
                # Another worker finished it between task_next and task_start.
                continue
            repository.task_complete(
                database, task.id, actor=actor, outcome="done by " + actor
            )
        queue.put(("ok", actor))
    except BaseException as exc:  # pragma: no cover - surfaced by the assertion
        queue.put(("error", f"{type(exc).__name__}: {exc}"))


def test_no_double_work(tmp_path):
    db_path = tmp_path / "acceptance_b.sqlite"
    db = Database(db_path)
    db.migrate()
    project = repository.project_upsert(db, "demo", "Demo")

    chain = [
        repository.task_add(db, project.id, f"Chain {index}", priority=2)
        for index in range(3)
    ]
    repository.task_link(db, chain[1].id, chain[0].id, "blocked_by")
    repository.task_link(db, chain[2].id, chain[1].id, "blocked_by")
    independent = [
        repository.task_add(db, project.id, f"Independent {index}", priority=1)
        for index in range(3)
    ]
    seeded_edges = repository.task_graph(db, project.id).edges

    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    actors = ["worker-a", "worker-b"]
    processes = [
        context.Process(target=_worker, args=(str(db_path), project.id, actor, queue))
        for actor in actors
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=120) for _ in processes]
    for process in processes:
        process.join(timeout=120)
        assert process.exitcode == 0

    assert all(result[0] == "ok" for result in results), results

    tasks = [*chain, *independent]
    for task in tasks:
        fetched = repository.task_get(db, task.id)
        assert fetched.status == "done"
        assert fetched.outcome in {f"done by {actor}" for actor in actors}
        assert fetched.outcome.count("done by") == 1

    graph = repository.task_graph(db, project.id)
    assert graph.edges == seeded_edges
    assert len(graph.edges) == 2


# ---------------------------------------------------------------------------
# Acceptance A — cold resume
# ---------------------------------------------------------------------------

ATTEMPT = (
    "mypy --strict fails on plugin loader; the Protocol is unbound — "
    "try narrowing to a concrete class"
)


async def _call(client, name: str, arguments: dict | None = None):
    result = await client.call_tool(name, arguments or {})
    assert result.isError is False
    return result.structuredContent


def _seed_mid_task(db: Database):
    """One leased task with a valuable journal line, two dependents, one free task."""
    project = repository.project_upsert(db, "demo", "Demo")
    leased = repository.task_add(db, project.id, "Fix plugin loader crash", priority=2)
    repository.task_start(db, leased.id, actor="agent-7", lease_minutes=34)
    repository.journal_add(
        db, task_id=leased.id, kind="attempt", body=ATTEMPT, actor="agent-7"
    )
    dependents = []
    for index in range(2):
        task = repository.task_add(db, project.id, f"Dependent {index}", priority=3)
        repository.task_link(db, task.id, leased.id, "blocked_by")
        dependents.append(task)
    ready = repository.task_add(db, project.id, "Independent quick win", priority=1)
    repository.checkpoint_save(
        db,
        project.id,
        "tried the protocol binding; it is unbound",
        next_actions=["narrow to a concrete class", "re-run mypy --strict"],
    )
    return project, leased, dependents, ready


@pytest.mark.anyio
async def test_cold_resume(tmp_path):
    db_path = tmp_path / "acceptance_a.sqlite"
    db = Database(db_path)
    db.migrate()
    project, leased, dependents, ready = _seed_mid_task(db)
    server = create_server(db_path)

    async with create_connected_server_and_client_session(server) as client:
        started = await _call(
            client, "session_event", {"project_id": project.id, "kind": "session_start"}
        )
        assert started["ok"] is True

        briefing = (await _call(client, "resume", {"project": "demo"}))["data"]

    in_progress = {item["id"]: item for item in briefing["in_progress"]}
    assert leased.id in in_progress
    assert in_progress[leased.id]["owner"] == "agent-7"
    assert in_progress[leased.id]["last_journal"]["kind"] == "attempt"
    assert in_progress[leased.id]["last_journal"]["body"] == ATTEMPT
    assert 32 <= in_progress[leased.id]["lease_left_min"] <= 34

    waiting = {item["id"]: item for item in briefing["waiting_on"]}
    for dependent in dependents:
        assert dependent.id in waiting
        assert waiting[dependent.id]["needs"] == [leased.id]

    assert ready.id in {item["id"] for item in briefing["ready"]}
    assert not {dependent.id for dependent in dependents} & {
        item["id"] for item in briefing["ready"]
    }

    assert briefing["last_checkpoint"]["summary"]
    assert briefing["last_checkpoint"]["next_actions"] == [
        "narrow to a concrete class",
        "re-run mypy --strict",
    ]

    # The instruction lives on the in-progress task, not on any other task.
    for entry in briefing["blocked"] + briefing["waiting_on"] + briefing["ready"]:
        assert ATTEMPT not in str(entry)

    async with create_connected_server_and_client_session(server) as client:
        next_task = (await _call(client, "task_next", {"project_id": project.id}))["data"]
        assert next_task["id"] == ready.id

        await _call(
            client, "task_start", {"task_id": ready.id, "actor": "agent-9"}
        )
        completed = await _call(
            client,
            "task_complete",
            {"task_id": ready.id, "actor": "agent-9", "outcome": "shipped the quick win"},
        )
        assert completed["data"]["status"] == "done"

        after = (await _call(client, "resume", {"project": "demo"}))["data"]

    assert {item["id"] for item in after["waiting_on"]} == {
        dependent.id for dependent in dependents
    }
    assert ready.id not in {item["id"] for item in after["in_progress"]}
    assert leased.id in {item["id"] for item in after["in_progress"]}


# ---------------------------------------------------------------------------
# Acceptance D — one write path
# ---------------------------------------------------------------------------


def _seed_parity(db_path) -> int:
    """Two identical copies are seeded by calling this twice."""
    db = Database(db_path)
    db.migrate()
    project = repository.project_upsert(db, "demo", "Demo")
    seed = [
        repository.task_add(db, project.id, f"Seed {index}", priority=3)
        for index in range(4)
    ]
    repository.task_link(db, seed[1].id, seed[0].id, "blocked_by")
    story = repository.task_add(db, project.id, "Seed story", type="story")
    repository.task_add(db, project.id, "Seed child", parent_id=story.id)
    return project.id


def _ids_by_title(db_path) -> dict[str, int]:
    db = Database(db_path)
    project = repository.project_list(db)[0]
    return {task.title: task.id for task in repository.all_tasks(db, project.id)}


def _snapshot(db_path):
    db = Database(db_path)
    project = repository.project_list(db)[0]
    tasks = repository.all_tasks(db, project.id)
    titles = {task.id: task.title for task in tasks}
    relations = sorted(
        (titles[relation.task_id], titles[relation.related_id], relation.kind)
        for relation in repository.project_relations(db, project.id)
    )
    journal = sorted(
        (titles.get(entry.task_id), entry.kind, entry.actor)
        for entry in repository.journal_for_project(db, project.id)
    )
    rows = sorted(
        (
            task.title,
            task.type,
            task.status,
            task.owner,
            task.outcome,
            task.block_reason,
            task.parent_id is not None,
        )
        for task in tasks
    )
    return rows, relations, journal


_TRANSITION_WALK = (
    {"action": "start"},
    {"action": "block", "reason": "waiting on a decision"},
    {"action": "unblock"},
    {"action": "start"},
    {"action": "complete", "outcome": "implemented and verified"},
    {"action": "close"},
)

_MCP_WALK = (
    ("task_start", {}),
    ("task_block", {"reason": "waiting on a decision"}),
    ("task_unblock", {}),
    ("task_start", {}),
    ("task_complete", {"outcome": "implemented and verified"}),
    ("task_close", {}),
)


def _drive_http(client, db_path, project_id):
    for title, priority in (("Board A", 2), ("Board B", 1)):
        created = client.post(
            "/tasks",
            json={"title": title, "priority": priority, "project_id": project_id},
        )
        assert created.status_code == 201, created.text

    ids = _ids_by_title(db_path)
    linked = client.post(
        f"/tasks/{ids['Board B']}/links",
        json={"related_id": ids["Board A"], "kind": "blocked_by"},
    )
    assert linked.status_code == 201, linked.text

    for step in _TRANSITION_WALK:
        response = client.post(
            "/transitions", json={"task_id": ids["Board A"], **step, "actor": "human"}
        )
        assert response.status_code == 200, response.text

    for step in ({"action": "start"}, {"action": "complete", "outcome": "b done"}):
        response = client.post(
            "/transitions", json={"task_id": ids["Board B"], **step, "actor": "human"}
        )
        assert response.status_code == 200, response.text


async def _drive_mcp(mcp_client, db_path, project_id):
    for title, priority in (("Board A", 2), ("Board B", 1)):
        result = await mcp_client.call_tool(
            "task_add",
            {"project_id": project_id, "title": title, "priority": priority},
        )
        assert result.structuredContent["ok"] is True

    ids = _ids_by_title(db_path)
    linked = await mcp_client.call_tool(
        "task_link",
        {
            "task_id": ids["Board B"],
            "related_id": ids["Board A"],
            "kind": "blocked_by",
        },
    )
    assert linked.structuredContent["ok"] is True

    for tool, extra in _MCP_WALK:
        result = await mcp_client.call_tool(
            tool, {"task_id": ids["Board A"], "actor": "human", **extra}
        )
        assert result.structuredContent["ok"] is True, result.structuredContent

    for tool, extra in (("task_start", {}), ("task_complete", {"outcome": "b done"})):
        result = await mcp_client.call_tool(
            tool, {"task_id": ids["Board B"], "actor": "human", **extra}
        )
        assert result.structuredContent["ok"] is True, result.structuredContent


def _assert_transition_invariants(db_path):
    from task_manager import transitions as machine

    db = Database(db_path)
    project = repository.project_list(db)[0]
    tasks = repository.all_tasks(db, project.id)
    assert tasks
    for task in tasks:
        assert task.status in machine.TRANSITIONS
        if task.status in ("done", "closed"):
            assert task.outcome, f"{task.title} finished without an outcome"
        if task.status == "blocked":
            assert task.block_reason, f"{task.title} blocked without a reason"
        if task.status in ("open", "cancelled", "done", "closed", "blocked"):
            assert task.owner is None and task.lease_expires_at is None
        if task.status == "in_progress":
            assert task.owner and task.lease_expires_at


@pytest.mark.anyio
async def test_one_write_path(tmp_path):
    http_path = tmp_path / "http.sqlite"
    mcp_path = tmp_path / "mcp.sqlite"
    for path in (http_path, mcp_path):
        _seed_parity(path)

    project_id = repository.project_list(Database(http_path))[0].id
    client = TestClient(create_app(http_path))
    server = create_server(mcp_path)

    async with create_connected_server_and_client_session(server) as mcp_client:
        # 1. an illegal drop is refused with exactly the MCP payload.
        refusal = client.post(
            "/transitions",
            json={"task_id": _ids_by_title(http_path)["Seed 0"], "action": "complete"},
        )
        mcp_refusal = await mcp_client.call_tool(
            "task_complete",
            {"task_id": _ids_by_title(mcp_path)["Seed 0"], "actor": "human", "outcome": ""},
        )
        assert refusal.status_code == 422
        assert refusal.json() == mcp_refusal.structuredContent
        assert refusal.json()["error"] == "MissingOutcome"

        # 2. the identical sequence over each surface.
        _drive_http(client, http_path, project_id)
        await _drive_mcp(mcp_client, mcp_path, project_id)

    # 3. no state an MCP client could not have produced.
    _assert_transition_invariants(http_path)
    _assert_transition_invariants(mcp_path)

    # 4. the two final snapshots are equal row-for-row (timestamps excluded).
    assert _snapshot(http_path) == _snapshot(mcp_path)

    db = Database(http_path)
    final = {task.title: task for task in repository.all_tasks(db, project_id)}
    assert final["Board A"].status == "closed"
    assert final["Board B"].status == "done"
    assert final["Board A"].outcome == "implemented and verified"

    # 5. no journal edit/delete route exists on the board.
    a_id = final["Board A"].id
    entry = repository.journal_list(db, task_id=a_id)[0]
    assert client.put(f"/tasks/{a_id}/journal/{entry.id}").status_code in (404, 405)
    assert client.delete(f"/tasks/{a_id}/journal/{entry.id}").status_code in (404, 405)
