"""T15 — the three session rituals are registered MCP prompts and stay pure."""

from __future__ import annotations

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from task_manager import prompts, repository
from task_manager.db import Database
from task_manager.server import create_server


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "tasks.sqlite"
    Database(path).migrate()
    return path


def _text(result) -> str:
    return "\n".join(message.content.text for message in result.messages)


@pytest.mark.anyio
async def test_prompts_are_listed_with_descriptions(db_path):
    server = create_server(db_path)
    async with create_connected_server_and_client_session(server) as client:
        listed = await client.list_prompts()
        names = {prompt.name for prompt in listed.prompts}
        assert names == {"start-session", "compaction", "end-session"}
        assert all(prompt.description for prompt in listed.prompts)

        for name in names:
            result = await client.get_prompt(name)
            assert _text(result).strip()


@pytest.mark.anyio
async def test_start_session_names_its_tools_and_the_rule(db_path):
    server = create_server(db_path)
    async with create_connected_server_and_client_session(server) as client:
        text = _text(await client.get_prompt("start-session"))

    for tool in ("session_event", "resume", "task_next", "task_start", "task_get"):
        assert tool in text
    assert "never open a new task while a claimed task is unfinished" in text.lower()
    assert "session_start" in text


@pytest.mark.anyio
async def test_compaction_stops_at_the_second_compaction(db_path):
    server = create_server(db_path)
    async with create_connected_server_and_client_session(server) as client:
        text = _text(await client.get_prompt("compaction"))

    assert "session_event(kind='compaction')" in text
    assert "second compaction since the last checkpoint" in text
    assert "checkpoint_save" in text
    assert "task_update" in text and "task_add" in text
    assert "journal" in text


@pytest.mark.anyio
async def test_end_session_ritual(db_path):
    server = create_server(db_path)
    async with create_connected_server_and_client_session(server) as client:
        text = _text(await client.get_prompt("end-session"))

    assert "task_complete" in text and "outcome required" in text
    assert "task_block" in text and "reason required" in text
    assert "checkpoint_save" in text
    assert "task_release" in text


@pytest.mark.anyio
async def test_prompts_contain_no_external_urls(db_path):
    server = create_server(db_path)
    async with create_connected_server_and_client_session(server) as client:
        for name in prompts.prompt_names():
            text = _text(await client.get_prompt(name))
            assert "http://" not in text
            assert "https://" not in text


@pytest.mark.anyio
async def test_prompts_are_pure(db_path):
    db = Database(db_path)
    repo_dir = db_path.parent
    before = sorted(path.name for path in repo_dir.iterdir())
    server = create_server(db_path)
    async with create_connected_server_and_client_session(server) as client:
        first = _text(await client.get_prompt("start-session"))
        second = _text(await client.get_prompt("start-session"))
        await client.get_prompt("compaction")
        await client.get_prompt("end-session")

    assert first == second
    assert sorted(path.name for path in repo_dir.iterdir()) == before
    assert repository.project_list(db) == []


def test_prompt_metadata_matches_registered_text():
    assert set(prompts.prompt_texts()) == {"start-session", "compaction", "end-session"}
    assert all(description for description in prompts.as_dict().values())
    for text in prompts.prompt_texts().values():
        assert "https://" not in text and "http://" not in text
