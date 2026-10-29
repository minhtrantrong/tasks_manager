# TT08 — Lease reaping and acceptance B (no double work)

| | |
|---|---|
| Suite | `LEASE`, `ACC-B` |
| Verifies | [T08](../tasks/T08-lease-reaping-concurrency.md), [test-plan §8.2](../test-plan.md) |
| Phase | M2 |
| Depends on | TT07 |
| Unblocks | TT13, TT20 |
| Level | L2 + L5 |
| Size | M |
| Status | pending |

## Goal

Prove a crashed agent loses its lease on the next read, and that two real processes
never execute the same task.

## Files

- `tests/test_lease_reaping.py` — new.
- `tests/test_acceptance.py` — new, `test_no_double_work`.
- `tests/workers.py` — module-level worker loop (required for `spawn` on Windows).

## Cases — reaping (`L2`)

1. A task `in_progress` with `lease_expires_at` one hour in the past is returned by
   `task_get` as `open`, owner `None`; `reap_expired_leases` reports its id.
2. An unexpired lease is untouched by any read path (`task_get`, `task_query`,
   `task_graph`, `task_next`, and `resume` once TT13 lands).
3. Boundary: a lease expiring exactly at `utc_now()` is reaped (`<` comparison), one
   second later is not.
4. Two processes race `reap_expired_leases` on the same expired task: exactly one
   reports the id; the second sees `open` and returns empty.
5. A reaped task can be started immediately by a new actor.
6. Reaping writes no journal entry (health reporting is TT13's job) but does update
   `updated_at`.

## Cases — acceptance B (`L5`)

7. Fixture: `seed_chain6` on a real file under `tmp_path`.
8. Two workers from `tests/workers.py`, started with
   `multiprocessing.get_context("spawn")`, loop `task_next` → `task_start` →
   `task_complete`, treating `LeaseConflict` as "next task".
9. Assertions: both workers exit inside the timeout; every task reaches `done`;
   each task's `outcome` names exactly one actor; `task_relations` unchanged; no
   task has two completion journal entries.
10. Assert the run is not silently serialized by a global lock: assert at least one
    `LeaseConflict` path or interleaved claim is possible — verified by running the
    same loop with two simulated actors against a single-threaded harness, which
    must produce a conflict (mutation check, not a timing assertion).
11. Anti-false-pass: temporarily removing `BEGIN IMMEDIATE` from `task_start` must
    make case 9 fail; this is proved once during review via a mutation run and
    documented in the test docstring, not executed in CI.

## Oracles exercised

OR-09 (lease atomicity), N3, N4, plan §8.2.

## Done when

- `pytest tests/test_lease_reaping.py tests/test_acceptance.py -q -m "integration or concurrency"`
  green on all three OSes, including Windows `spawn`.
- ACC-B completes in under 60 s per OS.
- No retry, no `sleep`-based synchronisation, no fork-only assumptions.
