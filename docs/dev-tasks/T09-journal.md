# T09 — Journal: journal_add / journal_list

| | |
|---|---|
| Phase | M3 |
| Depends on | T04 |
| Unblocks | T11, T13, T17 |
| Size | S |
| Status | done |

## Goal

Append-only reasoning log per task (or per project), with server-enforced size caps
(intend §5, §7.5, §9).

## Files

- `src/task_manager/repository.py` — add the two functions.
- `src/task_manager/server.py` — register 2 tools.
- `tests/test_journal.py` — new.

## Repository functions

```python
def journal_add(db, *, task_id=None, project_id=None, kind, body,
                actor=None, session_ref=None) -> JournalEntry
def journal_list(db, *, task_id=None, project_id=None, limit=20, offset=0,
                 before=None) -> list[JournalEntry]
```

Rules:

| Rule | Error |
|---|---|
| exactly one of `task_id`/`project_id` given | `ValidationError` |
| both given → `project_id` is ignored (derived from the task) | — |
| task/project must exist | `NotFound` |
| `kind` ∈ `('note','decision','attempt','problem','result')` | `ValidationError` |
| body non-empty after strip | `ValidationError` |
| body ≤ 6 lines (`len(body.splitlines()) <= 6`) and ≤ 1500 chars total | `ValidationError` ("journal entry exceeds 6 lines / 1500 chars") |
| `session_ref` ≤ 100 chars if given | `ValidationError` |

`journal_list` is reverse-chronological (`ORDER BY id DESC`), returns `limit`
entries (cap 100 even if caller asks for more), `before=<entry_id>` acts as a
cursor for pagination. Newest-first in the UI and in `task_get`'s journal tail.

**Append-only (intend §13):** there is no update, no delete, and no edit function.
Do not add one, even private. Hard task deletion cascades journal rows via the
schema (T02) — that is the only path by which entries disappear.

## MCP tools

- `journal_add(task_id=None, project_id=None, kind, body, actor=None,
  session_ref=None)` → `{ok, data}`.
- `journal_list(task_id=None, project_id=None, limit=20, offset=0, before=None)`
  → `{ok, data: {items, ...}}`.

## Tests (`tests/test_journal.py`)

1. Add + list round-trip; newest first.
2. Project-level note (`task_id=None`) works and lists under the project.
3. Body of 7 lines rejected; body of exactly 6 lines accepted; 1600-char body
   rejected.
4. Missing task → `NotFound`; both ids → task wins; neither id → `ValidationError`.
5. `before` cursor paginates without gaps or duplicates.
6. `task_get` journal tail shows the most recent entry first (integration with T03).
7. No `update_journal`/`delete_journal` symbol exists in `repository.py` (assert
   via `hasattr`/module scan in the test).
8. Hard-deleting a task removes its journal rows (cascade).

## Done when

- "Did we try this?" can be answered from journal data (T11 builds the query);
  caps enforced server-side, not by convention (intend M3 gate).
- Tests green on all CI OSes.
