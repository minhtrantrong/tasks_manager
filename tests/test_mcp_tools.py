"""Tests for the MCP tool surface using the SDK's in-memory session."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from task_manager.db import Database
from task_manager.server import create_server


async def _call(client, name: str, arguments: dict | None = None):
    result = await client.call_tool(name, arguments or {})
    assert result.isError is False
    return result.structuredContent


@pytest.mark.anyio
async def test_project_task_round_trip(tmp_path):
    db_path = tmp_path / "tasks.sqlite"
    Database(db_path).migrate()
    server = create_server(db_path)

    async with create_connected_server_and_client_session(server) as client:
        created = await _call(client, "project_upsert", {"slug": "demo", "name": "Demo"})
        assert created["ok"] is True
        project_id = created["data"]["id"]

        added = await _call(
            client,
            "task_add",
            {"project_id": project_id, "title": "Write tests", "priority": 2},
        )
        assert added["ok"] is True
        assert added["data"]["status"] == "open"

        queried = await _call(client, "task_query", {"project_id": project_id})
        assert queried["ok"] is True
        assert queried["data"]["total"] == 1
        assert queried["data"]["items"][0]["title"] == "Write tests"


@pytest.mark.anyio
async def test_response_shape_and_aliases(tmp_path):
    db_path = tmp_path / "tasks.sqlite"
    Database(db_path).migrate()
    server = create_server(db_path)

    async with create_connected_server_and_client_session(server) as client:
        project = await _call(client, "project_upsert", {"slug": "demo", "name": "Demo"})
        assert set(project) == {"ok", "data"}
        assert "rootPath" in project["data"]
        assert "root_path" not in project["data"]

        task = await _call(
            client,
            "task_add",
            {"project_id": project["data"]["id"], "title": "Alias check"},
        )
        assert "leaseExpiresAt" in task["data"]
        assert "lease_expires_at" not in task["data"]

        listed = await _call(client, "project_list")
        assert listed["ok"] is True
        assert isinstance(listed["data"], list)


@pytest.mark.anyio
async def test_not_found_is_structured(tmp_path):
    db_path = tmp_path / "tasks.sqlite"
    Database(db_path).migrate()
    server = create_server(db_path)

    async with create_connected_server_and_client_session(server) as client:
        result = await _call(client, "task_update", {"task_id": 999, "title": "Nope"})
        assert result == {
            "ok": False,
            "error": "NotFound",
            "message": "task 999 not found",
        }


@pytest.mark.anyio
async def test_validation_error_is_structured(tmp_path):
    db_path = tmp_path / "tasks.sqlite"
    Database(db_path).migrate()
    server = create_server(db_path)

    async with create_connected_server_and_client_session(server) as client:
        project = await _call(client, "project_upsert", {"slug": "demo", "name": "Demo"})
        result = await _call(
            client,
            "task_add",
            {"project_id": project["data"]["id"], "title": "   "},
        )
        assert result["ok"] is False
        assert result["error"] == "ValidationError"
        assert result["message"]


@pytest.mark.anyio
async def test_two_tools_sequentially_on_one_session(tmp_path):
    db_path = tmp_path / "tasks.sqlite"
    Database(db_path).migrate()
    server = create_server(db_path)

    async with create_connected_server_and_client_session(server) as client:
        project = await _call(client, "project_upsert", {"slug": "demo", "name": "Demo"})
        first = await _call(
            client, "task_add", {"project_id": project["data"]["id"], "title": "First"}
        )
        second = await _call(
            client, "task_add", {"project_id": project["data"]["id"], "title": "Second"}
        )
        assert first["data"]["id"] != second["data"]["id"]
        queried = await _call(client, "task_query", {"project_id": project["data"]["id"]})
        assert queried["data"]["total"] == 2


def test_stdio_subprocess_initialize(tmp_path):
    db_path = tmp_path / "tasks.sqlite"
    env = os.environ.copy()
    env["TASKS_DB"] = str(db_path)
    proc = subprocess.Popen(
        [sys.executable, "-m", "task_manager", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0.1"},
            },
        }
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()

        assert proc.stdout is not None
        response = None
        for _ in range(20):
            line = proc.stdout.readline()
            if not line:
                break
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if candidate.get("id") == 1:
                response = candidate
                break
        assert response is not None
        assert response["result"]["serverInfo"]["name"] == "task-manager"
        assert Path(db_path).exists()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
