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

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`) with an in-memory MCP client session; no URL |
| Command | `python -m pytest tests/test_prompts.py tests/test_acceptance.py -q -k "prompt or cold_resume"` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt15\tasks.sqlite`; frozen clock keeps the lease at +34 min |
| Prereqs | CPython 3.12; `seed_mid_task` from `tests/seeds.py` |

## Test data

- `seed_mid_task` on a real file: task 1 `in_progress`, owner `agent-7`, lease
  +34 min, one `attempt` journal entry whose body is exactly
  `"mypy --strict fails on plugin loader; the Protocol is unbound — try narrowing to a concrete class"`;
  tasks 2 and 3 `blocked_by` 1; task 4 priority 1 and free; one checkpoint with
  `next_actions`.
- Prompt names: `start-session`, `compaction`, `end-session`.
- Prompt content assertions: `session_event`, `resume`, `task_next`, `task_start`,
  `task_get`; the rule "never open a new task while a claimed task is unfinished".
- Second render call for the purity check (byte-identical text).

## How to test

1. `python -m pytest tests/test_prompts.py tests/test_acceptance.py -q -k "prompt or cold_resume"` with the recorder running.
2. Run the prompt group alone — `-k prompt` — and save all three rendered prompts
   into `attachments/prompts.txt`.
3. Run the acceptance case alone — `-k cold_resume -v` — and save the payload into
   `attachments/resume-payload.json`.
4. Read the payload by hand and confirm the "try narrowing" instruction appears
   inside `in_progress[].last_journal.body` and in no other task's data (case 12).
5. In a real MCP client (VS Code or Claude Desktop), run the same seed once to
   prepare charter `MC-1` for TT23; keep the client transcript in
   `attachments/client-transcript.txt`.

## Expected results

| Case | Expectation |
|---|---|
| 1 | the prompt list exposes exactly `start-session`, `compaction`, `end-session`, each with a description and rendered text |
| 2 | `start-session` names the five tools and contains the no-new-task-while-claimed rule |
| 3 | `compaction` instructs `session_event(kind='compaction')` immediately and stops at the second compaction to demand `checkpoint_save` or a split |
| 4 | `end-session` instructs complete-with-outcome, block-with-reason, `checkpoint_save` and `task_release` |
| 5 | no prompt text contains an external URL |
| 6 | rendering twice returns identical text and writes nothing |
| 7–8 | the seed builds the documented shape and a new client session records `session_start` then calls `resume("demo")` |
| 9 | task 1 is `in_progress` and `last_journal.body` equals the attempt line verbatim |
| 10 | `waiting_on` contains tasks 2 and 3 with `needs: [1]`, `ready` contains task 4 and not 2/3, and `last_checkpoint.next_actions` is present |
| 11 | `task_next` returns task 4; after completing it, tasks 2 and 3 are still waiting |
| 12 | the instruction is recoverable from `in_progress[].last_journal` specifically; it appears nowhere else, and removing `last_journal` fails the case |

## Test artifacts

Folder `docs/test-reports/TT15/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 12 case rows, embedded screenshots, video link |
| `pytest.log` | the `prompt or cold_resume` run plus each group run separately |
| `screenshots/01-prompt-list.png` | the three prompts with descriptions |
| `screenshots/02-cold-resume.png` | `in_progress[].last_journal` carrying the verbatim attempt line |
| `screenshots/03-continue.png` | task 4 completed while tasks 2 and 3 remain waiting |
| `attachments/prompts.txt` | rendered text for all three prompts |
| `attachments/resume-payload.json` | the ACC-A payload used for cases 9–12 |
| `video/TT15-prompts-cold-resume.mp4` | 30 s–5 min: prompt group, cold resume, continuation walk |

## Oracles exercised

OR-03 (outcome/reason), plan §8.1, Q9 (`require_closure` default off keeps 2/3
waiting on task 1 only).

## Done when

- `pytest tests/test_prompts.py tests/test_acceptance.py -q -k "prompt or cold_resume"`
  green on all three OSes.
- ACC-A is part of the release `-k` selection.
- `docs/test-reports/TT15/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT15-prompts-cold-resume.mp4`
  recording.
