# T08 — Lease reaping + concurrency (acceptance B)

| | |
|---|---|
| Phase | M2 |
| Depends on | T07 |
| Unblocks | T13 |
| Size | M |
| Status | done |

## Goal

Expired leases are reaped so a crashed agent never permanently owns a task, and two
concurrent agents provably never execute the same task (acceptance test B).

## Files

- `src/task_manager/repository.py` — `reap_expired_leases`.
- `src/task_manager/scheduler.py` — reuse in `task_next` paths if needed.
- `tests/test_acceptance.py` — new (test B lives here).
- `tests/test_lease_reaping.py` — new.

## Implementation

```python
def reap_expired_leases(db) -> list[int]
    # UPDATE tasks SET status='open', owner=NULL, lease_expires_at=NULL, updated_at=?
    # WHERE status='in_progress' AND lease_expires_at IS NOT NULL
    #   AND lease_expires_at < utc_now()
    # returns reaped task ids (no journal entry; the health section reports them).
```

Call sites (everywhere an agent *reads* work state, per intend §9 "expired leases
are reaped to `open` on read"): `task_get`, `task_query`, `task_graph`,
`task_next`, and later `resume` (T13). `reap_expired_leases` is a write, so it
stays in `repository.py` (N7).

## Acceptance test B — `test_acceptance.py::test_no_double_work`

1. Fixture: project with a chain of 6 tasks (some `blocked_by` edges), all open,
   on a real SQLite file (not in-memory) under `tmp_path`.
2. Spawn 2 worker processes (`multiprocessing`), each running a loop:

   ```python
   while True:
       t = repository.task_next(db, project_id)
       if t is None: break
       try: repository.task_start(db, t.id, actor=me, lease_minutes=1)
       except LeaseConflict: continue
       repository.task_complete(db, t.id, actor=me, outcome="done by " + me)
   ```

3. Assert: both workers exit; every task `status='done'`; each task has exactly one
   journal `result`-equivalent completion (count outcomes); `task_relations` intact.
4. Assert no task was ever executed twice — track by having each worker write its
   actor id into the task's `outcome` (only one winner can write it).

This proves the `BEGIN IMMEDIATE` claim path is race-free across real processes on
the same file — including Windows.

## Lease reaping tests (`tests/test_lease_reaping.py`)

1. Insert (via repository) a task `in_progress` with `lease_expires_at` 1 hour in
   the past → `task_get` returns it as `open`, owner None, and
   `reap_expired_leases` reported its id.
2. Unexpired lease is untouched by reads.
3. Two processes racing `reap_expired_leases` on the same expired task: exactly one
   reap (second sees `open`, returns empty).
4. A reaped task can immediately be `task_start`-ed by a new actor.
5. `require_closure` end-to-end (ties T06/T07 together): with
   `require_closure=1`, complete blocker → dependent still waiting; `task_close`
   blocker → dependent becomes ready.

## Done when

- A crashed agent loses its lease on the next read; two concurrent agents never
  both execute the same task (intend M2 gate, acceptance B green on CI).
