"""The session rituals of intend §9, shipped as MCP prompts.

Prompts are the part of the protocol that tools cannot enforce: they tell an
agent *when* to resume, *when* to checkpoint, and *how* to end a session
cleanly. They are pure data — rendering one never touches the database.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

START_SESSION = """\
Start a work session on this project and continue where the previous agent stopped.

1. Call session_event(kind='session_start') for the active project.
2. Call resume(project).
3. If a task is in_progress and the lease is yours or expired, continue it:
   read its journal tail and story context; do not restart it.
4. Otherwise call task_next(project) and task_start it.
5. Never open a new task while a claimed task is unfinished, unless it is blocked.
6. Before acting on a ready task, read its description/design via task_get.

The journal is memory: read the latest entry before deciding what to try, and
record what you learn as you go.
"""

COMPACTION = """\
Your context is about to be compacted. Preserve the reasoning before it is lost.

1. Call session_event(kind='compaction') immediately.
2. If this is the second compaction since the last checkpoint, STOP and either:
   - checkpoint_save(summary=where you are, next_actions=[concrete next steps]),
     then continue, or
   - split the current task (task_update the current task's scope; task_add the
     remainder as a new task) and checkpoint.
3. Write a journal 'decision' or 'attempt' entry capturing the current state before
   continuing.

A compaction that leaves no trail is work that will be redone.
"""

END_SESSION = """\
End the session cleanly so the next agent can start without re-derivation.

1. task_complete anything finished (outcome required: what changed, how verified).
2. task_block anything stuck (reason required: the specific external factor).
3. checkpoint_save(project, summary ≤ 60 lines, next_actions).
4. task_release any lease you are not keeping.

Leave the project in a state you would be happy to inherit.
"""

PROMPTS: dict[str, dict[str, str]] = {
    "start-session": {
        "description": "Begin a session: record it, resume, then continue or claim.",
        "text": START_SESSION,
    },
    "compaction": {
        "description": "Preserve reasoning at the second compaction since a checkpoint.",
        "text": COMPACTION,
    },
    "end-session": {
        "description": "Close out work: complete, block, checkpoint, release.",
        "text": END_SESSION,
    },
}


def prompt_texts() -> dict[str, str]:
    """The prompt bodies keyed by name (used by tests and documentation)."""
    return {name: payload["text"] for name, payload in PROMPTS.items()}


def register_prompts(server: FastMCP) -> None:
    """Register the three rituals on ``server``."""
    for name, payload in PROMPTS.items():

        def _render(text: str = payload["text"]) -> str:
            return text

        _render.__doc__ = payload["description"]
        server.prompt(name=name, description=payload["description"])(_render)


def prompt_names() -> list[str]:
    """Stable ordering used by documentation and tests."""
    return list(PROMPTS)


def as_dict() -> dict[str, Any]:
    """Metadata view (name → description)."""
    return {name: payload["description"] for name, payload in PROMPTS.items()}
