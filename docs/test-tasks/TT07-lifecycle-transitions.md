# TT07 — Lifecycle: state machine and requirements

| | |
|---|---|
| Suite | `TR` |
| Verifies | [T07](../tasks/T07-lifecycle-transitions.md) |
| Phase | M2 |
| Depends on | TT04 |
| Unblocks | TT08, TT16, TT21 |
| Level | L1 (table) + L2 (repository) |
| Size | L |
| Status | pending |

## Goal

Prove no status can move except through a named transition, and that `done` without
an outcome or `blocked` without a reason is impossible at every surface.

## Files

- `tests/test_transitions.py` — new.

## Cases

1. Every legal edge in `TRANSITIONS` succeeds and lands on the expected status with
   the expected fields: `complete` sets `finished_at` and clears owner/lease;
   `release` clears both; `block` sets `block_reason`; `close` keeps outcome.
2. Exhaustive negative matrix: for every `(status, action)` pair absent from
   `TRANSITIONS`, `assert_transition` raises `IllegalTransition` naming both
   status and action. The loop covers all 6 statuses × 8 actions.
3. `task_complete` with a missing, blank, whitespace-only, or 501-character outcome
   → `MissingOutcome`; 500 characters accepted.
4. `task_block` with a missing, blank, or 501-character reason → `MissingReason`;
   the reason is mirrored into `journal` as kind `problem` with the same
   `created_at`, in the same transaction.
5. `task_start` twice by the same actor is idempotent: same owner, same
   `lease_expires_at`, no error, `started_at` unchanged (N3).
6. `task_start` by a different actor on an unexpired lease → `LeaseConflict`;
   after the lease expires, the same call succeeds and the previous owner is
   replaced.
7. `task_release` by a non-owner → `LeaseConflict`; `force=True` succeeds and is the
   documented takeover path.
8. `task_unblock(to='in_progress')` produces a leased `in_progress` task, and
   `block_reason` is cleared.
9. `task_reopen` from `done` with an outcome appends a `result` journal entry
   containing the prior outcome and `finished_at`, then clears both, resets
   `started_at`, and takes a lease.
10. `task_cancel` from `in_progress` clears owner/lease; from `done` preserves the
    outcome; from `cancelled` no action is legal (terminal).
11. Happy path end-to-end: add → start → block → unblock → start → complete →
    close; final status `closed` with outcome intact and one `problem` journal entry.
12. `updated_at` changes on every transition while `created_at` does not.
13. No public function accepts `status`, `owner`, or `lease_expires_at` as an input
    argument (signature scan over `repository.py`).
14. A failed transition (e.g. `MissingOutcome`) leaves status, owner, and lease
    unchanged.

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_transitions.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt07\tasks.sqlite`; frozen clock fixes `lease_expires_at` |
| Prereqs | CPython 3.12; no network |

## Test data

- Status set (6): `open`, `in_progress`, `blocked`, `done`, `closed`, `cancelled`.
- Action set (8): `start`, `release`, `block`, `unblock`, `complete`, `close`,
  `reopen`, `cancel` — the full 6 × 8 matrix, with `TRANSITIONS` as the oracle.
  Today's legal pairs: open/start, open/block, open/cancel, in_progress/release,
  in_progress/block, in_progress/complete, in_progress/cancel, blocked/unblock,
  blocked/cancel, done/close, done/reopen, done/cancel, closed/reopen,
  closed/cancel.
- Outcomes: `"done: narrowed the Protocol to a concrete class"` (valid),
  `""`, `"   "`, `"x" * 500` (accepted), `"x" * 501` (rejected).
- Reasons: `"mypy --strict fails on plugin loader"` (valid), blank,
  whitespace-only, `"r" * 500`, `"r" * 501`.
- Actors: `agent-7` (owner), `agent-9` (competitor), `human` (force takeover).
- Lease fixtures: `+60 min` (unexpired) and an expired lease produced by
  `clock.advance(61)`.

## How to test

1. `python -m pytest tests/test_transitions.py -v` with the recorder running.
2. Run the state-machine table group — `-k "table or illegal"` — and screenshot the
   exhaustive negative matrix output (case 2).
3. Run the requirement group — `-k "outcome or reason or missing"` — showing the
   500/501 boundary and the journal mirror.
4. Run the lease group — `-k "start or release or lease"` — showing idempotency,
   `LeaseConflict`, and the forced takeover.
5. Run the end-to-end walk — `-k happy_path` — and save the resulting row and
   journal entries into `attachments/happy-path-rows.json`.
6. Run the signature scan — `-k signature` — proving no public function accepts
   `status`, `owner` or `lease_expires_at`.

## Expected results

| Case | Expectation |
|---|---|
| 1 | every legal edge lands on the expected status: `complete` sets `finished_at` and clears owner/lease, `release` clears both, `block` sets `block_reason`, `close` keeps the outcome |
| 2 | for every `(status, action)` pair absent from `TRANSITIONS`, `assert_transition` raises `IllegalTransition` naming both sides |
| 3 | `task_complete` with a missing, blank, whitespace-only or 501-character outcome raises `MissingOutcome`; 500 characters is accepted |
| 4 | `task_block` with a missing, blank or 501-character reason raises `MissingReason`; the valid reason is mirrored to `journal` as `problem` with the same `created_at` in the same transaction |
| 5 | a second `task_start` by the same actor is idempotent: same owner, same `lease_expires_at`, `started_at` unchanged, no error |
| 6 | a different actor hits `LeaseConflict` on an unexpired lease; after expiry the same call succeeds and replaces the owner |
| 7 | release by a non-owner raises `LeaseConflict`; `force=True` succeeds as the documented takeover path |
| 8 | `task_unblock(to='in_progress')` yields a leased `in_progress` task with `block_reason` cleared |
| 9 | `task_reopen` from `done` appends a `result` journal entry naming the prior outcome and `finished_at`, clears both, resets `started_at`, and takes a lease |
| 10 | `task_cancel` from `in_progress` clears owner/lease, from `done` preserves the outcome, and from `cancelled` has no legal action |
| 11 | the happy path add → start → block → unblock → start → complete → close ends `closed` with the outcome intact and exactly one `problem` journal entry |
| 12 | `updated_at` changes on every transition while `created_at` never does |
| 13 | no public function in `repository.py` accepts `status`, `owner` or `lease_expires_at` |
| 14 | a failed transition leaves status, owner and lease untouched |

## Test artifacts

Folder `docs/test-reports/TT07/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 14 case rows, embedded screenshots, video link |
| `pytest.log` | full run plus the table, requirement and lease selections |
| `screenshots/01-legal-walk.png` | the happy-path walk with the final `closed` row |
| `screenshots/02-illegal-matrix.png` | the exhaustive negative matrix passing, one row per absent pair |
| `screenshots/03-outcome-boundary.png` | 500 accepted / 501 rejected plus the `problem` journal mirror |
| `attachments/happy-path-rows.json` | task row plus journal entries after the walk |
| `video/TT07-lifecycle-transitions.mp4` | 30 s–5 min: legal table, illegal matrix, requirement boundaries, the walk |

## Oracles exercised

OR-02 (no status input), OR-03 (outcome/reason + journal mirror), OR-09 (lease
atomicity), N3, N4.

## Done when

- `pytest tests/test_transitions.py -q` green on all three OSes.
- Removing any row from `TRANSITIONS` makes at least one case fail.
- `docs/test-reports/TT07/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT07-lifecycle-transitions.mp4`
  recording.
