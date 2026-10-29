"""T19 / T20 / T21 — dashboard: skeleton, board rendering, and mutations."""

from __future__ import annotations

import importlib
import os
import re
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from task_manager import repository, resume
from task_manager.cli import main
from task_manager.dashboard.app import (
    BOARD_COLUMNS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    LOOPBACK_HOSTS,
    PACKAGE_DIR,
    create_app,
)
from task_manager.db import Database

WRITE_SQL = re.compile(r"(?i)^\s*(insert\s+into|update\s+\w|delete\s+from)\b")


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "tasks.sqlite"
    Database(path).migrate()
    return path


@pytest.fixture()
def client(db_path):
    return TestClient(create_app(db_path))


@pytest.fixture()
def sql_capture(monkeypatch):
    statements: list[str] = []
    real_connect = sqlite3.connect

    def spy(database, *args, **kwargs):
        connection = real_connect(database, *args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", spy)
    return statements


def _seed(db_path, title="Skeleton task", status_column="open"):
    db = Database(db_path)
    project = repository.project_upsert(db, "demo", "Demo")
    task = repository.task_add(db, project.id, title)
    return db, project, task


def test_health_and_redirect(client):
    home = client.get("/", follow_redirects=False)
    assert home.status_code in (302, 307)
    assert home.headers["location"] == "/board"

    assert client.get("/health").json() == {"ok": True}


def test_board_has_the_five_status_columns(client):
    response = client.get("/board")
    assert response.status_code == 200
    html = response.text
    for status in BOARD_COLUMNS:
        assert f'data-status="{status}"' in html
        assert status in html
    assert ">waiting<" not in html


def test_static_assets_are_served(client):
    script = client.get("/static/htmx.min.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "htmx" in script.text

    style = client.get("/static/app.css")
    assert style.status_code == 200
    assert "text/css" in style.headers["content-type"]
    assert ".card" in style.text


def _column_html(html: str, status: str) -> str:
    match = re.search(
        rf'<section class="column" data-status="{status}">(.*?)</section>', html, re.S
    )
    assert match is not None, f"column {status} missing"
    return match.group(1)


def test_seeded_task_appears_under_its_column(db_path, client):
    _seed(db_path, titled := "Skeleton task")
    html = client.get("/board").text
    assert titled in html
    assert titled in _column_html(html, "open")


def test_no_external_urls_in_templates_or_assets():
    roots = [PACKAGE_DIR / "templates", PACKAGE_DIR / "static"]
    pattern = re.compile(r"https?://")
    offenders = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name == "VENDORED.md":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                offenders.append(str(path))
    assert offenders == []


def test_board_rendering_executes_no_writes(db_path, client, sql_capture):
    _seed(db_path)
    sql_capture.clear()
    response = client.get("/board")
    assert response.status_code == 200
    writes = [statement for statement in sql_capture if WRITE_SQL.match(statement)]
    assert writes == []
    assert any("SELECT" in statement.upper() for statement in sql_capture)


def test_default_bind_is_loopback():
    assert DEFAULT_HOST == "127.0.0.1"
    assert DEFAULT_PORT == 8765
    assert "0.0.0.0" not in LOOPBACK_HOSTS


def test_titles_are_escaped(db_path, client):
    _seed(db_path, "<script>alert(1)</script>")
    html = client.get("/board").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_importing_the_dashboard_writes_nothing(db_path):
    db = Database(db_path)
    before = _counts(db)
    sys.modules.pop("task_manager.dashboard.app", None)
    importlib.import_module("task_manager.dashboard.app")
    assert _counts(db) == before


def _counts(db: Database) -> dict[str, int]:
    conn = db.connect()
    try:
        return {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("projects", "tasks", "journal", "checkpoints")
        }
    finally:
        conn.close()


def test_cli_refuses_non_loopback_hosts(capsys):
    assert main(["dashboard", "--host", "0.0.0.0"]) == 2
    captured = capsys.readouterr()
    assert "refusing to bind" in captured.err


def test_cli_reports_a_missing_dashboard_extra(monkeypatch, capsys, db_path):
    monkeypatch.setenv("TASKS_DB", str(db_path))
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    assert main(["dashboard"]) == 2
    captured = capsys.readouterr()
    assert "dashboard extra is not installed" in captured.err
    assert "Traceback" not in captured.err


def test_serve_subcommand_still_exists():
    from task_manager.cli import build_parser

    args = build_parser().parse_args(["serve"])
    assert args.command == "serve"
    assert os.path.sep in str(Path(PACKAGE_DIR))


# ---------------------------------------------------------------------------
# T20 — board rendering
# ---------------------------------------------------------------------------


def _seed_board(db_path):
    db = Database(db_path)
    project = repository.project_upsert(db, "demo", "Demo")
    story = repository.task_add(db, project.id, "Story lane", type="story", priority=5)
    child = repository.task_add(
        db, project.id, "Story child", parent_id=story.id, priority=4
    )
    top = repository.task_add(db, project.id, "Top priority", priority=1)
    repository.journal_add(
        db, task_id=top.id, kind="note", body="first journal line"
    )
    blocker = repository.task_add(db, project.id, "Blocked blocker", priority=3)
    repository.task_block(db, blocker.id, actor="agent-1", reason="needs a key")
    waiting = repository.task_add(db, project.id, "Waiting work", priority=2)
    repository.task_link(db, waiting.id, blocker.id, "blocked_by")
    leased = repository.task_add(
        db, project.id, "Leased work", priority=2, workflow="feature"
    )
    repository.task_start(db, leased.id, actor="agent-7", lease_minutes=30)
    done = repository.task_add(db, project.id, "Finished work")
    repository.task_start(db, done.id, actor="agent-2")
    repository.task_complete(db, done.id, actor="agent-2", outcome="all green")
    cancelled = repository.task_add(db, project.id, "Cancelled work")
    repository.task_cancel(db, cancelled.id, actor="agent-1")
    return {
        "db": db,
        "project": project,
        "story": story,
        "child": child,
        "top": top,
        "blocker": blocker,
        "waiting": waiting,
        "leased": leased,
        "done": done,
        "cancelled": cancelled,
    }


def test_every_task_renders_in_its_own_column(db_path, client):
    _seed_board(db_path)
    html = client.get("/board").text

    assert "Top priority" in _column_html(html, "open")
    assert "Waiting work" in _column_html(html, "open")
    assert "Blocked blocker" in _column_html(html, "blocked")
    assert "Leased work" in _column_html(html, "in_progress")
    assert "Finished work" in _column_html(html, "done")
    assert "Cancelled work" not in html

    for status in BOARD_COLUMNS:
        assert _column_html(html, status)


def test_column_ordering_is_priority_then_seq(db_path, client):
    _seed_board(db_path)
    html = client.get("/board").text
    open_column = _column_html(html, "open")
    assert open_column.index("Top priority") < open_column.index("Waiting work")


def test_waiting_is_a_badge_not_a_column(db_path, client):
    ids = _seed_board(db_path)
    html = client.get("/board").text

    waiting_column = _column_html(html, "open")
    assert f"waits #{ids['blocker'].id}" in waiting_column
    assert 'class="card priority-2 waiting"' in waiting_column
    assert ">waiting<" not in html
    assert 'data-status="waiting"' not in html


def test_leased_card_shows_owner_and_countdown(db_path, client):
    ids = _seed_board(db_path)
    html = client.get("/board").text
    in_progress = _column_html(html, "in_progress")
    assert "owner agent-7" in in_progress
    assert re.search(r"lease (2[89]|30)m left", in_progress)
    assert "Leased work" in in_progress
    assert str(ids["leased"].id) in in_progress


def test_cancelled_tasks_hidden_until_requested(db_path, client):
    _seed_board(db_path)
    assert "Cancelled work" not in client.get("/board").text

    shown = client.get("/board?show_cancelled=1").text
    assert "Cancelled work" in _column_html(shown, "cancelled")


def test_swimlanes_group_cards(db_path, client):
    _seed_board(db_path)
    by_workflow = client.get("/board?swimlane=workflow").text
    assert 'class="swimlane-heading"' in by_workflow
    assert ">feature<" in by_workflow
    assert ">simple<" in by_workflow

    by_parent = client.get("/board?swimlane=parent").text
    assert ">Story lane<" in by_parent
    assert ">No parent<" in by_parent
    story_lane = by_parent.split(">Story lane<")[1].split("swimlane-heading")[0]
    assert "Story child" in story_lane

    flat = client.get("/board?swimlane=none").text
    assert 'class="swimlane-heading"' not in flat


def _card_for(html: str, title: str) -> str:
    for chunk in html.split("<article")[1:]:
        card = chunk.split("</article>")[0]
        if title in card:
            return card
    raise AssertionError(f"card {title!r} not found")


def test_last_journal_line_rendering(db_path, client):
    _seed_board(db_path)
    html = client.get("/board").text

    top_card = _card_for(html, "Top priority")
    assert "first journal line" in top_card
    assert "card-journal" in top_card
    assert "note" in top_card

    waiting_card = _card_for(html, "Waiting work")
    assert "card-journal" not in waiting_card


def test_empty_board_renders_five_empty_columns(db_path, client):
    Database(db_path)  # migrated, no project rows
    html = client.get("/board").text
    assert html.count('class="column"') == 5
    assert "(0)" in html
    assert "nothing here" in html


def test_board_variants_execute_no_writes(db_path, client, sql_capture):
    _seed_board(db_path)
    for url in (
        "/board",
        "/board?show_cancelled=1",
        "/board?swimlane=workflow",
        "/board?swimlane=parent",
    ):
        sql_capture.clear()
        assert client.get(url).status_code == 200
        writes = [statement for statement in sql_capture if WRITE_SQL.match(statement)]
        assert writes == [], (url, writes)


def test_board_matches_resume_for_in_progress_cards(db_path, client):
    ids = _seed_board(db_path)
    db = ids["db"]
    html = client.get("/board").text
    briefing = resume.build_resume(db, ids["project"].id)

    for item in briefing["in_progress"]:
        card_marker = f'id="task-{item["id"]}"'
        card = html.split(card_marker)[1].split("</article>")[0]
        assert item["owner"] in card
        if item["last_journal"]:
            assert item["last_journal"]["body"] in card
        assert f"lease {item['lease_left_min']}m left" in card

    waiting_ids = {item["id"] for item in briefing["waiting_on"]}
    assert ids["waiting"].id in waiting_ids


# ---------------------------------------------------------------------------
# T21 — mutations, detail panel, graph, takeover
# ---------------------------------------------------------------------------


def _walk_http(client, task_id):
    sequence = [
        {"action": "start"},
        {"action": "block", "reason": "waiting on a decision"},
        {"action": "unblock"},
        {"action": "start"},
        {"action": "complete", "outcome": "done and verified"},
        {"action": "close"},
    ]
    for step in sequence:
        response = client.post(
            "/transitions", json={"task_id": task_id, **step, "actor": "human"}
        )
        assert response.status_code == 200, response.text


async def _walk_mcp(mcp_client, task_id):
    sequence = [
        ("task_start", {"actor": "human"}),
        ("task_block", {"actor": "human", "reason": "waiting on a decision"}),
        ("task_unblock", {"actor": "human"}),
        ("task_start", {"actor": "human"}),
        ("task_complete", {"actor": "human", "outcome": "done and verified"}),
        ("task_close", {"actor": "human"}),
    ]
    for tool, arguments in sequence:
        result = await mcp_client.call_tool(tool, {"task_id": task_id, **arguments})
        assert result.structuredContent["ok"] is True, result.structuredContent


def _state_by_title(db_path):
    db = Database(db_path)
    project = repository.project_list(db)[0]
    return {
        task.title: (task.status, task.owner, task.outcome, task.block_reason)
        for task in repository.all_tasks(db, project.id)
    }


@pytest.mark.anyio
async def test_http_walk_matches_mcp_walk(tmp_path):
    from mcp.shared.memory import create_connected_server_and_client_session

    from task_manager.server import create_server

    http_path = tmp_path / "http.sqlite"
    mcp_path = tmp_path / "mcp.sqlite"
    for path in (http_path, mcp_path):
        db = Database(path)
        db.migrate()
        project = repository.project_upsert(db, "demo", "Demo")
        repository.task_add(db, project.id, "Walked task")
        repository.task_add(db, project.id, "Bystander")

    client = TestClient(create_app(http_path))
    _walk_http(client, 1)

    server = create_server(mcp_path)
    async with create_connected_server_and_client_session(server) as mcp_client:
        await _walk_mcp(mcp_client, 1)

    assert _state_by_title(http_path) == _state_by_title(mcp_path)
    assert _state_by_title(http_path)["Walked task"][0] == "closed"


@pytest.mark.anyio
async def test_illegal_actions_match_the_mcp_payloads(tmp_path):
    from mcp.shared.memory import create_connected_server_and_client_session

    from task_manager.server import create_server

    db_path = tmp_path / "tasks.sqlite"
    db = Database(db_path)
    db.migrate()
    project = repository.project_upsert(db, "demo", "Demo")
    open_task = repository.task_add(db, project.id, "Open task")
    leased = repository.task_add(db, project.id, "Leased task")
    repository.task_start(db, leased.id, actor="agent-7", lease_minutes=30)

    client = TestClient(create_app(db_path))
    server = create_server(db_path)

    http_cases = [
        ({"task_id": open_task.id, "action": "complete"}, "task_complete", {"outcome": ""}),
        ({"task_id": open_task.id, "action": "block"}, "task_block", {"reason": ""}),
        ({"task_id": open_task.id, "action": "close"}, "task_close", {}),
        ({"task_id": leased.id, "action": "start"}, "task_start", {}),
    ]

    async with create_connected_server_and_client_session(server) as mcp_client:
        for http_body, tool, extra in http_cases:
            http_response = client.post("/transitions", json={**http_body, "actor": "human"})
            assert http_response.status_code == 422, http_response.text
            mcp_result = await mcp_client.call_tool(
                tool, {"task_id": http_body["task_id"], "actor": "human", **extra}
            )
            assert http_response.json() == mcp_result.structuredContent
            assert http_response.json()["ok"] is False


def test_refusals_are_non_destructive(db_path, client):
    db = Database(db_path)
    project = repository.project_upsert(db, "demo", "Demo")
    task = repository.task_add(db, project.id, "Refused task")
    before = repository.task_get(db, task.id)

    response = client.post(
        "/transitions", json={"task_id": task.id, "action": "complete"}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "MissingOutcome"
    after = repository.task_get(db, task.id)
    assert (after.status, after.owner, after.outcome) == (
        before.status,
        before.owner,
        before.outcome,
    )


def test_takeover_on_a_leased_task(db_path, client):
    db = Database(db_path)
    project = repository.project_upsert(db, "demo", "Demo")
    leased = repository.task_add(db, project.id, "Agent work")
    repository.task_start(db, leased.id, actor="agent-7", lease_minutes=30)

    refused = client.post(
        "/transitions",
        json={"task_id": leased.id, "action": "start", "actor": "human"},
    )
    assert refused.status_code == 422
    assert refused.json()["error"] == "LeaseConflict"

    taken = client.post(f"/tasks/{leased.id}/takeover")
    assert taken.status_code == 200
    assert "owner human" in taken.text
    assert repository.task_get(db, leased.id).owner == "human"

    moved = client.post(
        "/transitions", json={"task_id": leased.id, "action": "start", "actor": "human"}
    )
    assert moved.status_code == 200


def test_create_task_from_the_board(db_path, client):
    db = Database(db_path)
    project = repository.project_upsert(db, "demo", "Demo")

    created = client.post(
        "/tasks",
        json={
            "project_id": project.id,
            "title": "Created from the board",
            "description": "via HTTP",
            "type": "feature",
            "workflow": "feature",
            "priority": 2,
        },
    )
    assert created.status_code == 201
    assert "Created from the board" in created.text

    html = client.get("/board").text
    assert "Created from the board" in _column_html(html, "open")


def test_create_task_validation_returns_the_form_with_a_banner(db_path, client):
    db = Database(db_path)
    repository.project_upsert(db, "demo", "Demo")

    response = client.post("/tasks", json={"title": "   "})
    assert response.status_code == 422
    assert "toast" in response.text
    assert "title must be a non-empty string" in response.text
    assert response.headers["HX-Retarget"] == "closest details"


def test_journal_route_is_append_only(db_path, client):
    db = Database(db_path)
    project = repository.project_upsert(db, "demo", "Demo")
    task = repository.task_add(db, project.id, "Journalled")

    created = client.post(
        f"/tasks/{task.id}/journal", json={"kind": "note", "body": "from the UI"}
    )
    assert created.status_code == 201

    detail = client.get(f"/tasks/{task.id}").text
    assert "from the UI" in detail

    entry = repository.journal_list(db, task_id=task.id)[0]
    assert client.put(f"/tasks/{task.id}/journal/{entry.id}").status_code in (404, 405)
    assert client.delete(f"/tasks/{task.id}/journal/{entry.id}").status_code in (404, 405)
    assert len(repository.journal_list(db, task_id=task.id)) == 1


def test_detail_panel_shows_everything_task_get_returns(db_path, client):
    db = Database(db_path)
    project = repository.project_upsert(db, "demo", "Demo")
    story = repository.task_add(db, project.id, "Story", type="story")
    repository.context_append(db, story.id, body="inherited fact")
    task = repository.task_add(
        db,
        project.id,
        "Detailed task",
        description="the spec",
        design="the approach",
        parent_id=story.id,
    )
    blocker = repository.task_add(db, project.id, "Blocker")
    repository.task_link(db, task.id, blocker.id, "blocked_by")
    repository.journal_add(db, task_id=task.id, kind="decision", body="chose option B")

    html = client.get(f"/tasks/{task.id}").text
    assert "the spec" in html
    assert "the approach" in html
    assert "chose option B" in html
    assert f"#{blocker.id}" in html
    assert "blocked_by" in html
    assert "waiting" in html
    assert "inherited fact" in html
    assert "Story context" in html
    assert f"/tasks/{story.id}" in html


def test_graph_view_lists_nodes_edges_and_waiting(db_path, client):
    db = Database(db_path)
    project = repository.project_upsert(db, "demo", "Demo")
    first = repository.task_add(db, project.id, "Graph root")
    second = repository.task_add(db, project.id, "Graph child")
    repository.task_link(db, second.id, first.id, "blocked_by")

    html = client.get("/graph").text
    assert f"node-{first.id}" in html
    assert f"node-{second.id}" in html
    assert f"edge-{second.id}-{first.id}-blocked_by" in html
    assert "node-waiting" in html


def test_graph_route_is_read_only(db_path, client, sql_capture):
    db = Database(db_path)
    project = repository.project_upsert(db, "demo", "Demo")
    repository.task_add(db, project.id, "Graph task")
    sql_capture.clear()
    assert client.get("/graph").status_code == 200
    assert [s for s in sql_capture if WRITE_SQL.match(s)] == []


def test_mutation_routes_write_only_through_repository(db_path, client, sql_capture):
    import inspect

    db = Database(db_path)
    project = repository.project_upsert(db, "demo", "Demo")
    task = repository.task_add(db, project.id, "Route write")
    source = " ".join(inspect.getsource(repository).split())

    sql_capture.clear()
    client.post(
        "/transitions", json={"task_id": task.id, "action": "start", "actor": "human"}
    )
    client.post(
        "/transitions", json={"task_id": task.id, "action": "block", "reason": "why"}
    )
    client.post("/tasks", json={"title": "Second route task", "project_id": project.id})
    client.post(f"/tasks/{task.id}/journal", json={"kind": "note", "body": "hi"})

    writes = [statement for statement in sql_capture if WRITE_SQL.match(statement)]
    assert writes, "expected the mutations to write"

    operation = re.compile(r"(?i)^\s*(INSERT INTO|UPDATE|DELETE FROM)\s+(\w+)")
    for statement in writes:
        match = operation.match(statement)
        assert match is not None, statement
        signature = f"{match.group(1).upper()} {match.group(2)}"
        assert signature.upper() in source.upper(), statement


def test_unknown_action_is_a_validation_error(db_path, client):
    Database(db_path).migrate()
    response = client.post("/transitions", json={"task_id": 1, "action": "teleport"})
    assert response.status_code == 422
    assert response.json()["error"] == "ValidationError"

