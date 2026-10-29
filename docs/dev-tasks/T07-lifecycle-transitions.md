# T07 — Lifecycle: state machine, transitions, leases

| | |
|---|---|
| Phase | M2 |
| Depends on | T04 |
| Unblocks | T08, T16, T21 |
| Size | L |
| Status | done |

## Goal

The full lifecycle from intend.md §5/§7.4: a single state-machine table plus
repository functions that own every status change, including lease claims.

## Files

- `src/task_manager/transitions.py` — new (pure state machine).
- `src/task_manager/repository.py` — add the Flow tool functions below.
- `src/task_manager/server.py` — register the 8 Flow tools.
- `tests/test_transitions.py` — new.

## transitions.py

A plain data table — no I/O:

```python
TRANSITIONS: dict[str, dict[str, Transition]]
# Transition = (next_status, requirements)
# requirements: frozenset of {'outcome', 'reason', 'lease'}

TRANSITIONS = {
  'open':         {'start': ('in_progress', {'lease'}),
                   'block': ('blocked', {'reason'}),
                   'cancel': ('cancelled', set())},
  'in_progress':  {'release': ('open', set()),
                   'block': ('blocked', {'reason'}),
                   'complete': ('done', {'outcome'}),
                   'cancel': ('cancelled', set())},
  'blocked':      {'unblock': ('open', set()),
                   'cancel': ('cancelled', set())},
  'done':         {'close': ('closed', set()),
                   'reopen': ('in_progress', {'lease'}),
                   'cancel': ('cancelled', set())},
  'closed':       {'reopen': ('in_progress', {'lease'}),
                   'cancel': ('cancelled', set())},
  'cancelled':    {},          # terminal
}

def assert_transition(current: str, action: str) -> Transition
    # raises IllegalTransition(f"{current} -> {action}") if absent
```

`blocked → in_progress` is expressed as `unblock` → `open` then `start` (the tool
exposes a `to='in_progress'` shortcut that composes the two).

## Repository functions (the Flow family, intend §7.4)

All use `BEGIN IMMEDIATE`, re-validate state inside the transaction, and take
`actor` (agent id) as an explicit parameter. `owner` stores the actor.

```python
def task_start(db, task_id, *, actor, lease_minutes=60) -> Task
    # - status 'in_progress' + owner==actor + lease unexpired → return as-is
    #   (idempotent retry, N3).
    # - status 'in_progress' + lease unexpired + owner!=actor → LeaseConflict.
    # - status 'in_progress' + lease expired → reap to 'open', fall through.
    # - assert_transition('open','start'); set status/owner/lease_expires_at
    #   (=utc_now + lease_minutes), started_at=utc_now (only if NULL), updated_at.
    # - run work-on start hooks (T16) AFTER commit; hook failures never roll back.

def task_release(db, task_id, *, actor=None, force=False) -> Task
    # - from 'in_progress' only; if lease unexpired and owner!=actor and not force
    #   → LeaseConflict. force=True is the dashboard takeover path (T21).
    # - → 'open', clear owner + lease_expires_at, updated_at.

def task_complete(db, task_id, *, actor, outcome) -> Task
    # - requires 'in_progress'; outcome required non-empty ≤ 500 chars else
    #   MissingOutcome; → 'done', finished_at=utc_now, clear owner+lease_expires_at.

def task_close(db, task_id, *, actor) -> Task
    # - 'done' → 'closed' only. Does NOT require require_closure (that flag only
    #   changes dependent-unblock semantics in T06).

def task_block(db, task_id, *, actor, reason) -> Task
    # - from 'open' or 'in_progress'; reason non-empty ≤ 500 chars else
    #   MissingReason; clears owner+lease if held; sets block_reason; mirrors the
    #   reason into journal (kind='problem', actor=actor) in the same transaction.

def task_unblock(db, task_id, *, actor, to='open') -> Task
    # - from 'blocked'; to ∈ {'open','in_progress'}; 'in_progress' = unblock then
    #   task_start(lease) atomically; clears block_reason.

def task_reopen(db, task_id, *, actor, lease_minutes=60) -> Task
    # - from 'done' or 'closed'; if outcome is set, append journal kind='result',
    #   body=f"Prior outcome ({finished_at}): {outcome}" BEFORE clearing it
    #   ("keeping the outcome as history"); clear outcome + finished_at, reset
    #   started_at=None; then claim lease like task_start.

def task_cancel(db, task_id, *, actor, hard=False) -> Task
    # - supersedes T03's task_delete soft path: soft → 'cancelled' from any
    #   non-terminal status, clears owner+lease; hard → DELETE row (T03 logic).
```

Invariant enforcement (N4/N7):

- Only these functions may write `status`, `owner`, `lease_expires_at`,
  `block_reason`, `outcome`. `task_update` (T03) must not touch them.
- Every status write goes through `transitions.assert_transition`.
- Requirement violations raise `MissingOutcome`/`MissingReason` — never fall back
  to a silent write.
- `updated_at` is set on every write.

## MCP tools

`task_start(task_id, actor, lease_minutes=60)`, `task_release(task_id, actor=None,
force=False)`, `task_complete(task_id, actor, outcome)`, `task_close(task_id,
actor)`, `task_block(task_id, actor, reason)`, `task_unblock(task_id, actor,
to='open')`, `task_reopen(task_id, actor, lease_minutes=60)`,
`task_cancel(task_id, actor, hard=False)` — all return the T04 `{ok, data}` shape;
errors include `LeaseConflict`, `IllegalTransition`, `MissingOutcome`,
`MissingReason`.

## Tests (`tests/test_transitions.py`)

1. Every legal edge in the table succeeds and lands on the right status with the
   right fields (e.g. complete sets `finished_at` and clears the lease).
2. Every illegal edge raises `IllegalTransition` with a message naming both
   statuses (e.g. open→complete, blocked→done, done→start).
3. `task_complete` without/blank outcome → `MissingOutcome`.
4. `task_block` without/blank reason → `MissingReason`; reason lands in the journal
   as kind `problem` in the same transaction.
5. `task_start` twice by the same actor is idempotent (same lease, no error).
6. `task_start` by a different actor while leased → `LeaseConflict`.
7. `task_release` by non-owner → `LeaseConflict`; with `force=True` succeeds.
8. `task_unblock(to='in_progress')` results in a leased `in_progress` task.
9. `task_reopen` on a task with outcome: outcome appears in journal as `result`,
   status is leased `in_progress`, `finished_at` reset.
10. `task_cancel` from `in_progress` clears the lease.
11. Full happy path: add → start → block (reason) → unblock → start → complete
    (outcome) → close; assert final state `closed` with outcome intact.
12. No function accepts a `status` parameter anywhere (a grep-level sanity check in
    the test).

## Done when

- The scheduler is correct; every status change is a named transition; a crashed
  agent's lease expires (reap itself is T08) — intend M2 gate.
- Tests green on all CI OSes.
