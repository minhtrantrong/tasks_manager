# TT12 — Session events and checkpoints

| | |
|---|---|
| Suite | `SES` |
| Verifies | [T12](../tasks/T12-sessions-checkpoints.md) |
| Phase | M4 |
| Depends on | TT04 |
| Unblocks | TT13 |
| Level | L2 |
| Size | S |
| Status | pending |

## Goal

Prove sessions and handoffs persist correctly, that `checkpoint_save` is safe to
retry, and that checkpoint scoping never leaks between task and project.

## Files

- `tests/test_sessions_checkpoints.py` — new.

## Cases

1. `session_event` round-trip for all four kinds; `task_id` is optional; the
   `kind` CHECK rejects anything else.
2. A `task_id` from another project → `ValidationError`; an unknown project →
   `NotFound`.
3. `checkpoint_save` inserts once; re-calling with identical content returns the
   same id and adds no row (N3); changing the summary inserts a second row.
4. `checkpoint_latest(n=2)` returns newest-first; task-scoped queries never return
   project-scoped rows and vice versa.
5. Caps: a 60-line summary accepted, 61 rejected; a 300-character `next_actions`
   item accepted, 301 rejected; a non-array or non-string item rejected.
6. `checkpoint_latest(n=100)` returns at most 20.
7. Ordering with a frozen clock is stable: equal `created_at` values tie-break on
   `id DESC`.
8. Tasks in another project cannot see a checkpoint through `checkpoint_latest`.
9. `session_events` are append-only: no update or delete surface exists.

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_sessions_checkpoints.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt12\tasks.sqlite`; frozen clock for ordering |
| Prereqs | CPython 3.12; no network |

## Test data

- Project `demo` with tasks 1 and 2, plus project `other` with task 3 (cross-project
  scoping cases).
- Session-event kinds: `session_start`, `compaction`, `prompt`, `task_switch`; one
  event with `task_id=None`; one invalid kind `"bogus"`.
- Checkpoint payload: `summary="handoff: narrowing the loader Protocol"`,
  `next_actions=["draft the narrowing patch", "rerun mypy --strict"]`.
- Caps: a 60-line summary (accepted) and a 61-line summary (rejected); a
  300-character `next_actions` item (accepted) and a 301-character item
  (rejected); a non-array and a non-string item (both rejected).
- Ordering: three checkpoints saved under one frozen instant; `n=2` and `n=100`.

## How to test

1. `python -m pytest tests/test_sessions_checkpoints.py -v` with the recorder
   running.
2. Run the events group — `-k "event or kind"` — capturing the four-kind round-trip
   and the CHECK rejection.
3. Run the idempotency group — `-k "checkpoint"` — showing the repeated save
   returning the same id with one row.
4. Run the cap group — `-k "cap or limit or order"` — showing 60/61 lines,
   300/301 characters and `n=100 → 20`.
5. Save the checkpoint rows (id, project, task, created_at) into
   `attachments/checkpoint-rows.json`.

## Expected results

| Case | Expectation |
|---|---|
| 1 | `session_event` round-trips all four kinds, accepts a `None` task, and the CHECK rejects any other kind |
| 2 | a `task_id` from another project raises `ValidationError`; an unknown project raises `NotFound` |
| 3 | `checkpoint_save` inserts once; an identical re-call returns the same id and adds no row; a changed summary inserts a second row |
| 4 | `checkpoint_latest(n=2)` is newest-first; task-scoped and project-scoped queries never see each other's rows |
| 5 | 60-line summary accepted, 61 rejected; 300-character action accepted, 301 rejected; non-array and non-string items rejected |
| 6 | `checkpoint_latest(n=100)` returns at most 20 |
| 7 | with a frozen clock the order is stable and equal timestamps tie-break on `id DESC` |
| 8 | a task in another project cannot see a checkpoint through `checkpoint_latest` |
| 9 | session events are append-only: no update or delete surface exists |

## Test artifacts

Folder `docs/test-reports/TT12/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 9 case rows, embedded screenshots, video link |
| `pytest.log` | full run plus the events and checkpoint selections |
| `screenshots/01-session-events.png` | the four-kind round-trip and the rejected kind |
| `screenshots/02-checkpoint-idempotent.png` | one row after a repeated identical save |
| `screenshots/03-caps.png` | 60/61 lines, 300/301 characters, `n=100 → 20` |
| `attachments/checkpoint-rows.json` | checkpoint ids/scopes used in cases 3–8 |
| `video/TT12-sessions-checkpoints.mp4` | 30 s–5 min: suite, events group, idempotency, caps |

## Oracles exercised

OR-07 (60 lines, 300 chars, n ≤ 20), OR-10 (`checkpoint_save`), OR-08.

## Done when

- `pytest tests/test_sessions_checkpoints.py -q` green on all three OSes.
- Repeated `checkpoint_save` in a loop leaves exactly one row.
- `docs/test-reports/TT12/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT12-sessions-checkpoints.mp4`
  recording.
