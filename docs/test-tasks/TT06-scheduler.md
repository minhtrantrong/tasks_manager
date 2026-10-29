# TT06 — Scheduler read side: ready, waiting, `task_next`

| | |
|---|---|
| Suite | `SCH` |
| Verifies | [T06](../tasks/T06-scheduler-read-side.md) |
| Phase | M1 |
| Depends on | TT05 |
| Unblocks | TT20 |
| Level | L1 (predicates) + L2 (queries) |
| Size | M |
| Status | pending |

## Goal

Prove "what can I do now?" is a query with exactly one meaning, and that `waiting`
is orthogonal to `blocked`.

## Files

- `tests/test_scheduler.py` — new.

## Cases

1. No relations: every `open` task is ready.
2. A `blocked_by` B, B `open` → A waiting, B ready.
3. B `done`, `require_closure=0` → A ready.
4. B `done`, `require_closure=1` → A still waiting; after `task_close` B, A ready.
5. B `cancelled` → A ready in both closure modes.
6. Chain A→B→C with C `open`: A and B waiting, C ready.
7. Orthogonality: an `open` task with no blockers is ready even when another task is
   `status='blocked'`; a `blocked` task is never returned by `task_next`.
8. `task_next` picks priority 1 over 2; ties break by `seq`, then `id`; an empty
   project returns `None`; a fully terminal project returns `None`.
9. `task_next(workflow='bugfix')` never returns a ready task from another workflow.
10. `task_query(ready=True)` equals the scheduler's ready set exactly;
    `task_query(waiting=True)` equals the waiting set exactly (same ids, same order).
11. Text filtering uses FTS when available and LIKE when `fts_enabled()` is
    monkeypatched to False; both find by title and by description.
12. Row cap: a 60-task project returns at most `limit`, and `total` is honest.
13. `task_next` never returns a task whose lease is held by another actor after TT08
    lands (cross-check case; marked skipped until TT08).

## Oracles exercised

OR-04 (`waiting` computed, never stored), OR-07 (caps), N2.

## Done when

- `pytest tests/test_scheduler.py -q` green on all three OSes.
- Cases 3–5 are also exercised end-to-end by TT08/5 with `require_closure`.
