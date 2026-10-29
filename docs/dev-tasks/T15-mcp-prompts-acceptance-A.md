# T15 — MCP prompts (the rituals) + acceptance A

| | |
|---|---|
| Phase | M4 |
| Depends on | T13, T14 |
| Unblocks | T18 |
| Size | M |
| Status | done |

## Goal

Ship the session protocols of intend.md §9 as MCP **prompts** — `start-session`,
`compaction`, `end-session` — and prove the flagship claim with acceptance test A
(cold resume).

## Files

- `src/task_manager/prompts.py` — new.
- `src/task_manager/server.py` — register the three prompts.
- `tests/test_acceptance.py` — add `test_cold_resume`.

## prompts.py

Register via FastMCP (`@mcp.prompt()`), each returning the instruction text. The
text must encode the §9 rules verbatim in spirit:

**`start-session`**

```
1. Call session_event(kind='session_start') for the active project.
2. Call resume(project).
3. If a task is in_progress and the lease is yours or expired, continue it:
   read its journal tail and story context; do not restart it.
4. Otherwise call task_next(project) and task_start it.
5. Never open a new task while a claimed task is unfinished, unless it is blocked.
6. Before acting on a ready task, read its description/design via task_get.
```

**`compaction`**

```
1. Call session_event(kind='compaction') immediately.
2. If this is the second compaction since the last checkpoint, STOP and either:
   - checkpoint_save(summary=where you are, next_actions=[concrete next steps]),
     then continue, or
   - split the current task (task_update the current task's scope; task_add the
     remainder as a new task) and checkpoint.
3. Write a journal 'decision' or 'attempt' entry capturing the current state before
   continuing.
```

**`end-session`**

```
1. task_complete anything finished (outcome required: what changed, how verified).
2. task_block anything stuck (reason required: the specific external factor).
3. checkpoint_save(project, summary ≤ 60 lines, next_actions).
4. task_release any lease you are not keeping.
```

## Acceptance test A — `test_acceptance.py::test_cold_resume`

Seed (via repository, in a real SQLite file):

- project `demo`;
- task 1 `in_progress`, owner `agent-7`, lease +34 min, with a journal `attempt`:
  "mypy --strict fails on plugin loader; the Protocol is unbound — try narrowing to
  a concrete class";
- tasks 2 and 3 `open`, each `blocked_by` task 1;
- task 4 `open`, priority 1, no deps;
- a checkpoint with `summary` + `next_actions`.

Test (via an in-memory MCP client session):

1. Call `session_event(session_start)` then `resume("demo")`.
2. Assert the briefing contains: task 1 in `in_progress` whose `last_journal.body`
   is the attempt line above; `waiting_on` = tasks 2 and 3 with `needs=[1]`;
   `ready` contains task 4; `last_checkpoint` present with `next_actions`.
3. Simulate the continuation: `task_next` returns task 4 (not 2/3); start + complete
   task 4; assert tasks 2 and 3 are still waiting.
4. The key assertion: the agent knows **what not to retry** — the only source of the
   "try narrowing" instruction is the journal via `resume`; assert the body is
   present verbatim and no other task carries it.

## Tests (`tests/test_prompts.py`)

1. Each prompt is registered and its text mentions its tools (`session_event`,
   `resume`, `checkpoint_save`, …).
2. Prompt text fits the intent's rules (assert on key phrases such as "never open a
   new task while a claimed task is unfinished").

## Done when

- A cold agent resumes correctly from one call — including knowing what not to
  retry — via the shipped rituals (intend M4 gate, acceptance A green on CI).
