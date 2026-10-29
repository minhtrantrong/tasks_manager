# T11 — recall: FTS5 search with LIKE fallback

| | |
|---|---|
| Phase | M3 |
| Depends on | T09 |
| Unblocks | — |
| Size | S |
| Status | pending |

## Goal

`recall` answers "did we already try this?" from tasks + journal, never from chat
history (intend §7.5, §14).

## Files

- `src/task_manager/repository.py` — `recall`.
- `src/task_manager/server.py` — register 1 tool.
- `tests/test_recall.py` — new.

## Repository function

```python
def recall(db, query, *, project_id=None, limit=10) -> list[RecallHit]
# RecallHit: {source: 'task'|'journal', task_id: int|None, project_id,
#             title: str|None, snippet: str, created_at: str}
```

Behaviour:

1. Blank query → `ValidationError`.
2. **FTS path** (`db.fts_enabled()`): wrap the query as an FTS5 phrase —
   `'"' + query.replace('"', '""') + '"'` (safe: never allow raw MATCH syntax).
   - Journal hits: `SELECT rowid, snippet(journal_fts, 0, '…', '…', '…', 12) FROM
     journal_fts WHERE journal_fts MATCH ? ORDER BY rowid DESC LIMIT ?` → join to
     `journal` for task_id/project_id/created_at.
   - Task hits: same over `task_fts` with `snippet(task_fts, ...)`, joined to
     `tasks` for title/created_at.
   - Merge journal hits first (newest reasoning is the most valuable), then task
     hits; cap at `limit` (≤ 20 hard cap).
3. **Fallback path** (no FTS5): `WHERE LOWER(body) LIKE '%'||LOWER(?)||'%'` over
   journal and `title`/`description` over tasks; same merge and caps. Raise
   `FtsUnavailable` **only** if the caller explicitly passed `require_fts=True`
   (default False — degrade silently, N5).
4. `project_id` scopes both sources.

## MCP tool

- `recall(query, project_id=None, limit=10, require_fts=False)` → `{ok, data}`.
  On fallback, include `"search_backend": "fts"|"like"` in the data so agents know
  hit quality.

## Tests (`tests/test_recall.py`)

1. Journal body "retry uses backoff 2^n" is found by query `backoff retry`; snippet
   contains the matched text; hit has the task id.
2. Task found by title and by description.
3. `project_id` scoping: hits in another project are absent.
4. `limit` respected; journal hits precede task hits for the same query.
5. Query with `"` quotes does not break or inject FTS syntax (returns no crash;
   behaves as phrase).
6. Blank query → `ValidationError`.
7. Fallback: monkeypatch `fts_enabled` → False; same queries return results via
   LIKE with `search_backend="like"`.
8. `require_fts=True` with FTS unavailable → `FtsUnavailable`.
9. 50-task seeded fixture: `recall("api key")` finds the one task whose journal
   mentions it (relevance sanity, not ordering perfection).

## Done when

- Recall answers the canonical "did we try this already?" from the journal (intend
  M3 gate), and degrades gracefully without FTS5.
- Tests green on all CI OSes.
