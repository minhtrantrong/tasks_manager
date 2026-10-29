# T10 — Story context: context_append + inheritance

| | |
|---|---|
| Phase | M3 |
| Depends on | T04 |
| Unblocks | T13, T20 |
| Size | S |
| Status | done |

## Goal

Short curated facts propagate from a parent story to its children (intend §5,
§7.5, §9 "facts a sibling task will need go to context_append").

## Files

- `src/task_manager/repository.py` — `context_append` + `story_context` helper;
  wire the real helper into `task_get` (replacing the T03 placeholder).
- `src/task_manager/server.py` — register 1 tool.
- `tests/test_context.py` — new.

## Repository functions

```python
def context_append(db, task_id, *, body, actor=None) -> ContextEntry
def story_context(db, task_id, *, limit=10) -> list[ContextEntry]
```

Rules:

| Rule | Error |
|---|---|
| task exists | `NotFound` |
| task `type == 'story'` (context lives on stories only) | `ValidationError` ("context entries attach to story tasks") |
| body non-empty, ≤ 400 chars | `ValidationError` |

`story_context(task_id)`:

- If the task itself is a story → its own entries.
- Else walk `parent_id` upward until a story is found → that story's entries.
- No story ancestor → `[]` (a task with no story parent has no context).
- Return the `limit` most recent entries, oldest-first, each ≤ 400 chars already.
- Cap total response at ~2000 chars: stop adding entries once the running total
  would exceed it.

**Cap (curated budget, §5):** each story keeps at most **20** context entries.
On append past 20, delete the oldest entry in the same transaction before
inserting. Context is a curated budget, not an append-only log — this is the one
deliberate exception to append-only semantics (journal remains append-only).

`task_get` must include `story_context` via this helper (children read it
automatically).

## MCP tool

- `context_append(task_id, body, actor=None)` → `{ok, data}`.

## Tests (`tests/test_context.py`)

1. Append to a story succeeds; to a plain `task` raises `ValidationError`.
2. Child task's `task_get` includes the parent story's entries (oldest-first).
3. Grandchild inherits from the nearest story ancestor (story → child → grandchild;
   grandchild's `task_get` shows the story's entries).
4. A child whose parent is not a story and whose grandparent is → inherits from the
   grandparent.
5. Body > 400 chars rejected; 400 exactly accepted.
6. 21st append evicts the oldest (20 retained, newest present).
7. `story_context` on a story returns its own entries; on a task with no story
   ancestor returns `[]`.
8. Total-return cap: a story with many large entries returns a bounded payload
   (≤ ~2000 chars).

## Done when

- Story context propagates to descendants through `task_get` with caps enforced
  (intend M3 gate).
- Tests green on all CI OSes.
