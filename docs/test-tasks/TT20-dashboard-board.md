# TT20 — Board rendering

| | |
|---|---|
| Suite | `DSH` |
| Verifies | [T20](../tasks/T20-dashboard-board.md) |
| Phase | M6 |
| Depends on | TT19, TT06, TT08 |
| Unblocks | TT21 |
| Level | L4 |
| Size | L |
| Status | pending |

## Goal

Prove a human can answer "what is in flight, what is stuck, and why?" from the board
alone, and that the board shows what `resume` shows.

## Files

- `tests/test_dashboard.py` — extend.

## Cases

1. Seed `seed_board` → each task renders in its correct column; column order is
   `open`, `in_progress`, `blocked`, `done`, `closed`.
2. Ordering within a column is `priority`, then `seq`: p1 renders before p2.
3. Waiting: the dependent task carries a `waits #<id>` badge and a dimmed class;
   the page contains no `waiting` column heading (assert the heading string absent).
4. Leased card: owner and `lease NNm left` are rendered; with the frozen clock
   advanced 10 minutes the countdown decreases by 10.
5. `cancelled` tasks are absent by default and present with `show_cancelled=1`;
   they never appear in another column.
6. Swimlanes: `swimlane=workflow` and `swimlane=parent` produce the expected group
   headings and place each task once; `swimlane=none` renders a flat board.
7. Card contents: id, title, priority, workflow, owner when leased, and the last
   journal line newest-first; a task with no journal shows no last-line element.
8. `GET /board` under `sql_capture` performs no writes in every variant
   (`show_cancelled`, each swimlane).
9. An empty project renders five empty columns and a zero count, no error.
10. Parity: for `seed_mid_task`, the set of `(id, status, owner, last journal body)`
    rendered on the board equals the same fields returned by `resume`.

## Oracles exercised

OR-04 (`waiting` badge, not a column), OR-12 (board/resume parity), N8.

## Done when

- `pytest tests/test_dashboard.py -q -k board` green on all three OSes.
- Case 10 fails if the board renders a different owner or last journal line than
  `resume` reports.
