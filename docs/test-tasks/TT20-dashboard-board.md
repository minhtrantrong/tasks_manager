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

## Test environment

| | |
|---|---|
| Surface | HTTP dashboard (`L4`) plus terminal CLI |
| Base URL | `http://127.0.0.1:8765` |
| Variants | `/board`, `/board?swimlane=workflow`, `/board?swimlane=parent`, `/board?swimlane=none`, `/board?show_cancelled=1` |
| Start | `$env:TASKS_DB="<repo>\.tmp-tt20\tasks.sqlite"; task-manager dashboard --port 8765` |
| Setup | `python -m pip install -e ".[dev,dashboard]"` |
| Prereqs | CPython 3.12; free port 8765; browser for screenshots |

## Test data

- `seed_board`: p1 `open`, p2 `open` waiting on a blocked task, a leased
  `in_progress` task (30 min left, owner `agent-7`), one `done`, one `cancelled`.
- Ordering fixture: two `open` tasks at priority 1 and 2 with increasing `seq`.
- Journal fixture: one card with a known last line, one card with no journal.
- Parity fixture: `seed_mid_task`, compared field by field against `resume`.
- Clock: frozen, then `advance(minutes=10)` for the countdown case.
- Empty project for case 9.

## How to test

1. `python -m pytest tests/test_dashboard.py -v -k board` with the recorder running.
2. Start the dashboard and capture each variant in turn, one screenshot per file:
   `/board`, `?swimlane=workflow`, `?swimlane=parent`, `?show_cancelled=1`, and an
   empty project.
3. Advance the clock 10 minutes in the test and screenshot the `lease NNm left`
   before/after pair.
4. Save the page source of the default board into `attachments/board.html`, and the
   `resume` payload used for case 10 into `attachments/resume-parity.json`.
5. Confirm by inspection that no `waiting` column heading exists (only the badge).

## Expected results

| Case | Expectation |
|---|---|
| 1 | every seeded task renders in its column, ordered `open`, `in_progress`, `blocked`, `done`, `closed` |
| 2 | within a column, priority 1 renders before priority 2, ties broken by `seq` |
| 3 | the dependent card carries a `waits #<id>` badge and a dimmed class, and the page has no `waiting` heading |
| 4 | the leased card shows owner and `lease NNm left`; advancing 10 minutes reduces it by 10 |
| 5 | `cancelled` is hidden by default, shown with `show_cancelled=1`, and never appears in another column |
| 6 | `swimlane=workflow` and `swimlane=parent` group correctly and place each task once; `none` renders a flat board |
| 7 | cards show id, title, priority, workflow, owner when leased and the last journal line; a task without journal shows no last-line element |
| 8 | every board variant performs no writes under `sql_capture` |
| 9 | an empty project renders five empty columns and a zero count without error |
| 10 | for `seed_mid_task`, the `(id, status, owner, last journal body)` tuples rendered equal those returned by `resume` |

## Test artifacts

Folder `docs/test-reports/TT20/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 10 case rows, base URL, embedded screenshots, video link |
| `pytest.log` | the `-k board` run with the summary line |
| `screenshots/01-board-default.png` | the five columns with seeded cards |
| `screenshots/02-waiting-badge.png` | the `waits #<id>` badge and dimmed card, no `waiting` column |
| `screenshots/03-lease-countdown.png` | `lease NNm left` before and after `advance(10)` |
| `screenshots/04-swimlane-workflow.png` | workflow grouping with each task placed once |
| `screenshots/05-swimlane-parent.png` | parent grouping |
| `screenshots/06-show-cancelled.png` | the cancelled card visible only in this variant |
| `attachments/board.html` | page source for the default board |
| `attachments/resume-parity.json` | the `resume` payload compared in case 10 |
| `video/TT20-dashboard-board.mp4` | 30 s–5 min: default board, badge, countdown, swimlanes, cancelled, empty project |

## Oracles exercised

OR-04 (`waiting` badge, not a column), OR-12 (board/resume parity), N8.

## Done when

- `pytest tests/test_dashboard.py -q -k board` green on all three OSes.
- Case 10 fails if the board renders a different owner or last journal line than
  `resume` reports.
- `docs/test-reports/TT20/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT20-dashboard-board.mp4`
  recording.
