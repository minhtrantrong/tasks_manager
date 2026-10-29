# T05 — Relations: task_link / task_unlink / task_graph

| | |
|---|---|
| Phase | M1 |
| Depends on | T04 |
| Unblocks | T06 |
| Size | M |
| Status | done |

## Goal

The DAG is real: typed edges with in-transaction cycle rejection and a graph view
tool (intend §7.3).

## Files

- `src/task_manager/repository.py` — add relation functions.
- `src/task_manager/server.py` — register 3 tools.
- `tests/test_relations.py` — new.

## Repository functions

```python
def task_link(db, task_id, related_id, kind) -> Relation
def task_unlink(db, task_id, related_id, kind) -> None
def task_graph(db, project_id) -> Graph
```

Rules (each violation raises the named error):

| Rule | Error |
|---|---|
| `task_id` or `related_id` missing | `NotFound` |
| `task_id == related_id` | `ValidationError` (schema CHECK backs it) |
| tasks in different projects | `ValidationError` |
| `kind` not in `('blocked_by','related','discovered_during')` | `ValidationError` |
| duplicate `(task_id, related_id, kind)` | `ValidationError` ("already linked") |
| linking creates a cycle over `blocked_by` edges | `CycleDetected` |

**Cycle detection (only `blocked_by` edges are scheduling-relevant):**

Adding `task_id --blocked_by--> related_id` is illegal iff `related_id` is already
reachable from `task_id` following existing `blocked_by` edges (i.e. `related_id`
transitively blocks `task_id`). Implement a DFS/BFS over
`SELECT related_id FROM task_relations WHERE task_id=? AND kind='blocked_by'`,
starting from `related_id`, searching for `task_id`. Run it **inside the same
transaction** as the INSERT (`BEGIN IMMEDIATE` for the link) so two concurrent
links cannot both skip the check (N4).

`task_graph` returns:

```json
{
  "project_id": 1,
  "nodes": [{"id": 5, "title": "...", "status": "open", "priority": 1, "seq": 1.0,
             "type": "task", "workflow": "simple"}],
  "edges": [{"from": 5, "to": 9, "kind": "blocked_by"}],
  "waiting": [5]          // ids where is_waiting() is true (from T06; empty until then)
}
```

Nodes ordered `priority ASC, seq ASC, id ASC`. All project tasks included,
including `cancelled`/`closed`.

## MCP tools

- `task_link(task_id, related_id, kind)` → `{ok, data}` with the edge.
- `task_unlink(task_id, related_id, kind)` → `{ok, data: null}`; unlink of a missing
  edge is a no-op success (idempotent), missing task is `NotFound`.
- `task_graph(project_id)` → `{ok, data}`.

Errors follow the T04 contract (`{"ok": False, "error": "CycleDetected", ...}`).

## Tests (`tests/test_relations.py`)

1. Simple link + unlink round-trip.
2. Self-link rejected.
3. Cross-project link rejected.
4. Direct 2-cycle: link A→B then B→A `blocked_by` → `CycleDetected`.
5. Transitive cycle: A→B, B→C, C→A rejected at the third insert.
6. Diamond (A←B, A←C, B and C both → D) is legal.
7. `related` and `discovered_during` do not participate in cycle checks (they are
   provenance, not scheduling).
8. Duplicate link rejected; duplicate with different kind is fine (PK includes kind).
9. `task_graph` returns all nodes, correct edges, `waiting` empty pre-T06.
10. Unlink missing edge → ok; missing task → `NotFound`.
11. Concurrency: two threads race to create A→B and B→A simultaneously on the same
    DB; at most one succeeds (assert the DB never contains a 2-cycle).

## Done when

- Cycles are rejected at link time with `CycleDetected`, never discovered later
  (intend M1 gate).
- Tests green on all CI OSes.
