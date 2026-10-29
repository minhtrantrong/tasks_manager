# TT15 — MCP prompts and acceptance A (cold resume)

| | |
|---|---|
| Suite | `PRM`, `ACC-A` |
| Verifies | [T15](../tasks/T15-mcp-prompts-acceptance-A.md), [test-plan §8.1](../test-plan.md) |
| Phase | M4 |
| Depends on | TT13, TT14 |
| Unblocks | TT18 |
| Level | L3 |
| Size | M |
| Status | pending |

## Goal

Ship the §9 rituals as prompts and prove the flagship claim: a cold agent resumes
correctly from one call, including knowing what not to retry.

## Files

- `tests/test_prompts.py` — new.
- `tests/test_acceptance.py` — add `test_cold_resume`.

## Cases — prompts (`L3`)

1. Prompt list exposes exactly `start-session`, `compaction`, `end-session`, each
   with a description and a rendered text.
2. `start-session` names `session_event`, `resume`, `task_next`, `task_start`, and
   `task_get`; it contains the rule "never open a new task while a claimed task is
   unfinished".
3. `compaction` instructs `session_event(kind='compaction')` immediately and stops
   at the second compaction since the last checkpoint to require
   `checkpoint_save` or a task split.
4. `end-session` instructs complete-with-outcome, block-with-reason,
   `checkpoint_save`, and `task_release`.
5. No prompt text contains an external URL (N8 guard reused).
6. Prompts are pure: rendering twice returns identical text and writes nothing.

## Cases — acceptance A

7. Seed `seed_mid_task` on a real file: task 1 `in_progress` owned by `agent-7`
   with lease +34 min and the attempt "mypy --strict fails on plugin loader; the
   Protocol is unbound — try narrowing to a concrete class"; tasks 2 and 3
   `blocked_by` 1; task 4 priority 1 and free; one checkpoint with `next_actions`.
8. New in-memory client session → `session_event(session_start)` →
   `resume("demo")`.
9. Assert task 1 is `in_progress` and `last_journal.body` equals the attempt line
   verbatim.
10. Assert `waiting_on` contains tasks 2 and 3 with `needs: [1]`, `ready` contains
    task 4 and not 2/3, and `last_checkpoint.next_actions` is present.
11. Continue: `task_next` returns task 4; start and complete it; tasks 2 and 3 are
    still waiting.
12. Anti-false-pass: the "try narrowing" instruction must be recoverable from
    `in_progress[].last_journal` specifically; surfacing it only under `recent`
    fails. The line must not appear in any other task's data. Removing
    `last_journal` from `resume` must make the test fail.

## Oracles exercised

OR-03 (outcome/reason), plan §8.1, Q9 (`require_closure` default off keeps 2/3
waiting on task 1 only).

## Done when

- `pytest tests/test_prompts.py tests/test_acceptance.py -q -k "prompt or cold_resume"`
  green on all three OSes.
- ACC-A is part of the release `-k` selection.
