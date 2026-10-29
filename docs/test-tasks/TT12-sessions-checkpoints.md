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

## Oracles exercised

OR-07 (60 lines, 300 chars, n ≤ 20), OR-10 (`checkpoint_save`), OR-08.

## Done when

- `pytest tests/test_sessions_checkpoints.py -q` green on all three OSes.
- Repeated `checkpoint_save` in a loop leaves exactly one row.
