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

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_journal.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt09\tasks.sqlite`; frozen clock for tie-breaks |
| Prereqs | CPython 3.12; FTS5 optional (journal search is TT11) |

## Test data

- Valid body: the 6-line attempt
  `"tried X\nnoticed Y\nnext Z\nblocked by W\nretry after V\nsee PR 42"`.
- Invalid bodies: the same text with a 7th line, and `"a" * 1600`.
- Trailing-newline variant: the valid 6-line body plus a final `\n`.
- Project-level note: `{"task_id": null, "kind": "note", "body": "project kickoff"}`.
- Resolution inputs: an existing task id, a missing id `9999`, both task and
  project given, and neither.
- Pagination: 7 entries written under a frozen clock, paged 3/3/1 with the `before`
  cursor; `journal_limit=2` for the `task_get` tail.
- Kinds: `note`, `decision`, `attempt`, `problem`, `result`.

## How to test

1. `python -m pytest tests/test_journal.py -v` with the recorder running.
2. Run the ordering/pagination group — `-k "paging or tail"` — and screenshot the
   three pages with no gap or duplicate.
3. Run the cap group — `-k "body"` — showing 6 lines accepted, 7 rejected, and the
   module's character limit passing at limit and failing at limit + 1.
4. Run the surface group — `-k "no_mutation or scan"` — proving no update/delete
   symbol, tool or route exists (OR-06).
5. Save the three pages of entries into `attachments/journal-pages.json`.

## Expected results

| Case | Expectation |
|---|---|
| 1 | an added entry is listed newest-first with kind, body, actor and a `Z` timestamp |
| 2 | a project-level note is listed under its project and never under another |
| 3 | 6 lines accepted, 7 rejected, 1600 characters rejected; the module constant passes at limit and fails at limit + 1 |
| 4 | a 6-line body with a trailing newline normalises identically to one without |
| 5 | missing task → `NotFound`; task + project → the task wins; neither → `ValidationError` |
| 6 | `before` pagination across three pages is gap-free and duplicate-free with the `id DESC` tie-break |
| 7 | `task_get` shows the newest entry first and honours `journal_limit` |
| 8 | no `update_journal` / `delete_journal` symbol exists, and no MCP tool or route can mutate an entry |
| 9 | hard delete removes the task's journal rows; soft cancel keeps them |
| 10 | entries survive `task_reopen` and `task_cancel` byte-identically |

## Test artifacts

Folder `docs/test-reports/TT09/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 10 case rows, embedded screenshots, video link |
| `pytest.log` | full run plus the paging and cap selections |
| `screenshots/01-journal-tail.png` | newest-first tail with `journal_limit=2` |
| `screenshots/02-body-cap.png` | 6-line pass, 7-line fail, character limit ±1 |
| `screenshots/03-no-mutation-surface.png` | the symbol/tool/route scan finding no journal mutation path |
| `attachments/journal-pages.json` | the three cursor pages used in case 6 |
| `video/TT09-journal.mp4` | 30 s–5 min: suite, paging group, cap group, mutation scan |

## Oracles exercised

OR-06 (append-only), OR-07 (§7 caps), OR-08.

## Done when

- `pytest tests/test_journal.py -q` green on all three OSes.
- No test can construct a journal update through any public surface.
- `docs/test-reports/TT09/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT09-journal.mp4`
  recording.
