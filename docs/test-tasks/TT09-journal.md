# TT09 — Append-only journal

| | |
|---|---|
| Suite | `JN` |
| Verifies | [T09](../tasks/T09-journal.md) |
| Phase | M3 |
| Depends on | TT04 |
| Unblocks | TT11, TT13, TT17 |
| Level | L2 |
| Size | S |
| Status | pending |

## Goal

Prove the journal is memory that cannot be rewritten: append works, size is bounded,
ordering is stable, and no edit or delete path exists.

## Files

- `tests/test_journal.py` — new.

## Cases

1. Add then list on a task: entry returned newest-first with kind, body, actor, and
   a `Z` timestamp.
2. Project-level note (`task_id=None`) is stored and listed under the project; it is
   not returned by another project's listing.
3. Body boundary: exactly 6 lines accepted; 7 lines rejected; a 1600-character body
   rejected. The implementation's character limit is read from its module constant,
   asserted at limit (pass) and limit + 1 (fail), and recorded in plan §7.
4. Bare 6-line body with trailing newline is normalised the same way as without it.
5. Id resolution: missing task → `NotFound`; both task and project given → the task
   wins; neither → `ValidationError`.
6. `before` cursor pagination is gap-free and duplicate-free across three pages with
   a frozen clock (tie-break on `id DESC`).
7. `task_get` journal tail shows the most recent entry first and honours
   `journal_limit`.
8. Module scan: `repository.py` exposes no `update_journal` / `delete_journal`
   symbol, and no MCP tool or dashboard route can mutate an entry (OR-06).
9. Hard-deleting a task removes its journal rows; soft cancel keeps them.
10. Journal entries survive `task_reopen` and `task_cancel` unchanged.

## Oracles exercised

OR-06 (append-only), OR-07 (§7 caps), OR-08.

## Done when

- `pytest tests/test_journal.py -q` green on all three OSes.
- No test can construct a journal update through any public surface.
