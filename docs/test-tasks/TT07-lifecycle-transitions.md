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

## Oracles exercised

OR-02 (no status input), OR-03 (outcome/reason + journal mirror), OR-09 (lease
atomicity), N3, N4.

## Done when

- `pytest tests/test_transitions.py -q` green on all three OSes.
- Removing any row from `TRANSITIONS` makes at least one case fail.
