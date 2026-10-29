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

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`) with `multiprocessing.get_context("spawn")`; no server |
| Command | `python -m pytest tests/test_lease_reaping.py tests/test_acceptance.py -q -m "integration or concurrency"` |
| Setup | `python -m pip install -e ".[dev]"`; `tests/workers.py` importable as a module |
| Env | one real SQLite file under `tmp_path` shared by both workers; `TASKS_DB` unset inside the tests |
| Prereqs | CPython 3.12; `spawn` start method (required on Windows); ≤60 s wall clock for ACC-B |

## Test data

- `seed_chain6`: 6 open tasks with real `blocked_by` edges on a real file.
- Expired lease: `lease_expires_at = utc_now() - 1 hour`, owner `agent-7`.
- Boundary leases: exactly `utc_now()` (must reap) and `utc_now() + 1 s` (must not).
- Two workers from `tests/workers.py`, started with `spawn`, looping
  `task_next` → `task_start` → `task_complete` and treating `LeaseConflict` as
  "next task".
- Actor names `agent-a` and `agent-b`; assertions read outcomes from the DB, not
  from stdout.
- Mutation check (review only): `BEGIN IMMEDIATE` removed from `task_start`.

## How to test

1. `python -m pytest tests/test_lease_reaping.py tests/test_acceptance.py -q -m "integration or concurrency"` with the recorder running.
2. Run the reaping group alone — `-k "reap or boundary"` — and screenshot the
   expired/at-boundary/unexpired triple (case 3).
3. Run the acceptance case alone — `-k no_double_work -v` — and time it; record the
   elapsed time in the report. It must stay under 60 s.
4. Repeat `-k no_double_work` three times in a row. A flake here is an S1
   concurrency defect, never test noise — log it as a defect instead of retrying.
5. Save worker stdout as `attachments/worker-claims.log` and the relation rows
   before/after as `attachments/relations-before-after.json`.
6. Run the suite on Windows specifically, so the `spawn` path is exercised.

## Expected results

| Case | Expectation |
|---|---|
| 1 | a task leased one hour in the past reads back as `open` with `owner=None`, and `reap_expired_leases` reports its id |
| 2 | an unexpired lease is untouched by `task_get`, `task_query`, `task_graph`, `task_next` (and `resume` once TT13 lands) |
| 3 | a lease expiring exactly at `utc_now()` is reaped; one second later it is not |
| 4 | two processes racing `reap_expired_leases` report the id exactly once; the loser sees `open` and returns empty |
| 5 | a reaped task can be started immediately by a new actor |
| 6 | reaping writes no journal entry but does advance `updated_at` |
| 7–9 | both spawned workers exit inside the timeout, every task reaches `done`, each `outcome` names exactly one actor, relations are unchanged, and no task has two completion entries |
| 10 | the single-threaded two-actor harness produces a `LeaseConflict`, proving the loop is not silently serialized |
| 11 | the documented mutation (removing `BEGIN IMMEDIATE`) makes case 9 fail — proved once in review and recorded in the test docstring, not in CI |
| ACC-B | `test_no_double_work` passes on all three OSes in under 60 s with no retries and no sleeps |

## Test artifacts

Folder `docs/test-reports/TT08/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 11 case rows plus ACC-B, elapsed time, embedded screenshots, video link |
| `pytest.log` | the `-m "integration or concurrency"` run and the three repeated ACC-B runs |
| `screenshots/01-reap-boundary.png` | expired, exactly-at-`now`, and one-second-later lease results |
| `screenshots/02-acceptance-b.png` | `test_no_double_work` passing with its elapsed time |
| `screenshots/03-worker-outcomes.png` | both actors' `outcome` values, one per task |
| `attachments/worker-claims.log` | worker stdout for both processes |
| `attachments/relations-before-after.json` | relation rows proving the graph is unchanged |
| `video/TT08-lease-reaping-double-work.mp4` | 30 s–5 min: reaping boundary run and the ACC-B run with both workers |

## Oracles exercised

OR-09 (lease atomicity), N3, N4, plan §8.2.

## Done when

- `pytest tests/test_lease_reaping.py tests/test_acceptance.py -q -m "integration or concurrency"`
  green on all three OSes, including Windows `spawn`.
- ACC-B completes in under 60 s per OS.
- No retry, no `sleep`-based synchronisation, no fork-only assumptions.
- `docs/test-reports/TT08/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT08-lease-reaping-double-work.mp4`
  recording.
