# TT22 — Acceptance D and the write-path lint

| | |
|---|---|
| Suite | `LINT`, `ACC-D` |
| Verifies | [T22](../tasks/T22-acceptance-D-final.md), [test-plan §8.4](../test-plan.md) |
| Phase | M6 |
| Depends on | TT21 |
| Unblocks | TT23 |
| Level | L0 + L4 |
| Size | M |
| Status | pending |

## Goal

Make N7 mechanically enforced so a violation cannot merge, and prove the board can
produce no state an MCP client could not have produced.

## Files

- `tests/test_write_path_lint.py` — new.
- `tests/test_acceptance.py` — add `test_one_write_path`.

## Cases — write-path lint (`L0`)

1. Scan `src/task_manager/**/*.py` for write statements
   (`insert into`, `update <table>`, `delete from`); every hit is in
   `repository.py` or `db.py`; a hit elsewhere fails with file and line.
2. Sanity: the scanner finds at least one write in `repository.py` and one in
   `db.py`, proving it is not vacuous.
3. Negative fixture: a temporary module containing `UPDATE tasks SET status='done'`
   is reported at the right line.
4. Refinement of T22's "regex over file text": comments and docstrings are ignored
   via `ast`/`tokenize`, so prose mentioning `DELETE FROM tasks` does not fail the
   lint, while an executable string literal does.
5. Pragma guard: the connection factory executes `PRAGMA journal_mode` at most once
   per connection, and never per statement.
6. The lint runs in CI as its own job and blocks merge.

## Cases — acceptance D (`L4` + `L3`)

7. Seed `seed_parity`: two identical copies of a mixed project (open, leased,
   blocked, done, cancelled, one story with a child).
8. Drive one copy entirely over HTTP: create tasks, link, start, block, unblock,
   start, complete, close.
9. Each illegal drag during the run is refused with the same `error` and `message`
   as the identical MCP call (payload equality, not string matching on prose).
10. `done` without outcome and `blocked` without reason are refused on both
    surfaces.
11. Replay the identical sequence through the MCP client on the second copy; final
    snapshots are equal row-for-row on tasks, relations, and journal kinds/actors
    (timestamps normalised).
12. Every final row satisfies `TRANSITIONS`: replay each task's status history
    (from journal + fields) and assert no state an MCP client could not have
    produced.
13. Journal routes `PUT`/`DELETE` return 404/405 (routes absent).

## Oracles exercised

OR-01, OR-02, OR-03, OR-12, plan §8.4.

## Done when

- `pytest tests/test_write_path_lint.py tests/test_acceptance.py -q -k "write_path or one_write_path"`
  green on all three OSes.
- ACC-D is part of the release `-k` selection.
- Removing a guard from any write route makes case 9 or 11 fail.
