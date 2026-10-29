# T12 — session_event, checkpoint_save, checkpoint_latest

| | |
|---|---|
| Phase | M4 |
| Depends on | T04 |
| Unblocks | T13 |
| Size | S |
| Status | pending |

## Goal

The session record and the handoff snapshot — the raw material `resume` (T13)
assembles (intend §7.6, §9).

## Files

- `src/task_manager/repository.py` — 3 functions.
- `src/task_manager/server.py` — register 3 tools.
- `tests/test_sessions_checkpoints.py` — new.

## Repository functions

```python
def session_event(db, project_id, kind, *, task_id=None, detail=None) -> SessionEvent
def checkpoint_save(db, project_id, summary, *, task_id=None,
                    next_actions=None) -> Checkpoint
def checkpoint_latest(db, project_id, *, task_id=None, n=5) -> list[Checkpoint]
```

Rules:

| Rule | Error |
|---|---|
| `kind` ∈ `('session_start','compaction','prompt','task_switch')` | `ValidationError` |
| project/task exist; `task_id` (if given) belongs to that project | `NotFound` / `ValidationError` |
| `summary` non-empty, ≤ 60 lines, ≤ 4000 chars | `ValidationError` |
| `next_actions`: list of strings, each ≤ 200 chars, ≤ 10 items; stored as a JSON array in the `next_actions` TEXT column | `ValidationError` |
| `detail` ≤ 2000 chars | `ValidationError` |

**`checkpoint_save` idempotency (N3):** before inserting, SELECT the latest row for
`(project_id, task_id)`; if it exists **and** `summary` and `next_actions` are
identical → return that row unchanged (same id). Otherwise INSERT. Retrying the
same save therefore never creates duplicates; a genuinely new save always creates a
new row.

`checkpoint_latest` returns the `n` newest checkpoints (newest first) for the
project, or for `(project, task)` when `task_id` is given. Cap `n` ≤ 20.

## MCP tools

- `session_event(project_id, kind, task_id=None, detail=None)`
- `checkpoint_save(project_id, summary, task_id=None, next_actions=None)`
- `checkpoint_latest(project_id, task_id=None, n=5)`

All return the T04 `{ok, data}` shape.

## Tests (`tests/test_sessions_checkpoints.py`)

1. `session_event` round-trip for all four kinds; `task_id` optional.
2. Cross-project `task_id` → `ValidationError`.
3. `checkpoint_save` inserts; re-calling with identical content returns the same id
   and does not add a row; changing the summary inserts a second row.
4. `checkpoint_latest(n=2)` returns newest-first; task-scoped vs project-scoped
   queries don't leak each other's rows.
5. Summary with 61 lines rejected; next_actions with an 300-char item rejected;
   valid 60-line summary accepted.
6. `checkpoint_latest` respects the n-cap (n=100 → 20).

## Done when

- Sessions and checkpoints persist correctly and `checkpoint_save` is safe to
  retry (N3); tests green on all CI OSes.
