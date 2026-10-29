# T06 — Scheduler read side: ready/waiting, task_next, query filters

| | |
|---|---|
| Phase | M1 |
| Depends on | T05 |
| Unblocks | T08, T13, T20 |
| Size | M |
| Status | done |

## Goal

The computed `waiting` flag, the ready predicate, `task_next`, and the
`waiting`/`ready`/text filters in `task_query` (intend §7.2/§7.4 read side).

## Files

- `src/task_manager/scheduler.py` — new.
- `src/task_manager/repository.py` — implement `task_query` waiting/ready/text and
  `project_list` waiting counts (replacing T03 stubs).
- `src/task_manager/server.py` — register `task_next`.
- `tests/test_scheduler.py` — new.

## scheduler.py contract

```python
def is_terminal(status: str) -> bool          # status in ('done','closed','cancelled')

def is_waiting(db, task_id) -> bool
    # True iff a 'blocked_by' edge points at a task whose status is NOT terminal,
    # AND (project.require_closure == 0 or that blocker is not 'done').
    # I.e. a waiting blocker must be: done (when require_closure=0), or
    # closed (when require_closure=1). Cancelled/dropped blockers count as
    # satisfied in both modes.

def ready_predicate(db, project_id) -> str
    # SQL fragment/function used by task_query(ready=True) and task_next:
    #   status='open' AND NOT is_waiting(task)

def ready_tasks(db, project_id, *, workflow=None, limit=None) -> list[TaskSummary]
    # ready tasks ordered priority ASC, seq ASC, id ASC

def task_next(db, project_id, *, workflow=None) -> TaskSummary | None
    # If workflow given: first ready task of that workflow (seq ASC, priority ASC);
    # else the single highest-priority ready task.

def waiting_tasks(db, project_id) -> list[dict]
    # tasks where is_waiting() → {id, title, needs: [blocker ids not terminal]}
```

`is_waiting` needs the project's `require_closure` — read it once per call via
`SELECT require_closure FROM projects WHERE id = (SELECT project_id FROM tasks WHERE id=?)`.
Do **not** materialise `waiting` as a column anywhere — computed only (§5, §13 of
intend).

Cancelled blockers satisfy the edge in both modes (a dropped thread never deadlocks
the graph).

## repository.py changes

- `task_query`: implement `waiting` (bool filter via `is_waiting`) and `ready`
  (bool filter via `ready_predicate`). Implement `text` search: if
  `db.fts_enabled()` → `JOIN task_fts ON task_fts.rowid = tasks.id WHERE task_fts
  MATCH ?` with the query wrapped as an FTS5 phrase (`'"' + query.replace('"', '""')
  + '"'`); else `LOWER(title) LIKE '%'||LOWER(?)||'%' OR LOWER(description) LIKE ...`.
- `project_list`: fill the `waiting` count from `waiting_tasks` (per project, one
  extra query per project is fine at this scale).

## MCP tool

- `task_next(project_id, workflow=None)` → `{ok, data: task_or_null}`.

## Tests (`tests/test_scheduler.py`)

1. No relations → all open tasks ready.
2. A→B `blocked_by`, B open → A waiting, B ready.
3. B completed (`done`) with `require_closure=0` → A becomes ready.
4. B `done` with `require_closure=1` → A still waiting; B `closed` → A ready.
5. B `cancelled` → A ready in both modes.
6. Waiting chain A→B→C: C open → A and B waiting.
7. `blocked` is orthogonal: an open task blocked by nothing that is `status='blocked'`
   is not ready (status ≠ open), but its `blocked` status is a *status*, not waiting.
8. `task_next` picks priority 1 over priority 2; tie broken by `seq` then `id`.
9. `task_next(workflow='bugfix')` ignores ready tasks of other workflows.
10. `task_query(ready=True)` matches `ready_tasks` exactly; `waiting=True` matches
    `waiting_tasks` exactly.
11. `task_query(text=...)` FTS path finds by title and by description; LIKE fallback
    tested by monkeypatching `fts_enabled` to False.

## Done when

- Ready/waiting sets are correct across the matrix above; `task_next` never returns
  a waiting task (intend M1 gate).
- Tests green on all CI OSes.
