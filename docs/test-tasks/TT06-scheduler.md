# TT06 — Scheduler read side: ready, waiting, `task_next`

| | |
|---|---|
| Suite | `SCH` |
| Verifies | [T06](../tasks/T06-scheduler-read-side.md) |
| Phase | M1 |
| Depends on | TT05 |
| Unblocks | TT20 |
| Level | L1 (predicates) + L2 (queries) |
| Size | M |
| Status | pending |

## Goal

Prove "what can I do now?" is a query with exactly one meaning, and that `waiting`
is orthogonal to `blocked`.

## Files

- `tests/test_scheduler.py` — new.

## Cases

1. No relations: every `open` task is ready.
2. A `blocked_by` B, B `open` → A waiting, B ready.
3. B `done`, `require_closure=0` → A ready.
4. B `done`, `require_closure=1` → A still waiting; after `task_close` B, A ready.
5. B `cancelled` → A ready in both closure modes.
6. Chain A→B→C with C `open`: A and B waiting, C ready.
7. Orthogonality: an `open` task with no blockers is ready even when another task is
   `status='blocked'`; a `blocked` task is never returned by `task_next`.
8. `task_next` picks priority 1 over 2; ties break by `seq`, then `id`; an empty
   project returns `None`; a fully terminal project returns `None`.
9. `task_next(workflow='bugfix')` never returns a ready task from another workflow.
10. `task_query(ready=True)` equals the scheduler's ready set exactly;
    `task_query(waiting=True)` equals the waiting set exactly (same ids, same order).
11. Text filtering uses FTS when available and LIKE when `fts_enabled()` is
    monkeypatched to False; both find by title and by description.
12. Row cap: a 60-task project returns at most `limit`, and `total` is honest.
13. `task_next` never returns a task whose lease is held by another actor after TT08
    lands (cross-check case; marked skipped until TT08).

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_scheduler.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt06\tasks.sqlite`; frozen clock for determinism |
| Prereqs | CPython 3.12; FTS5 for case 11, monkeypatched absence for its fallback half |

## Test data

- Chain A→B→C (A `blocked_by` B, B `blocked_by` C), all `open`.
- `require_closure` fixtures: the same chain under `0` and `1`, plus B `done` and
  B `cancelled` variants.
- Mixed project: one `open` free task, one `blocked` task, one priority-1 and one
  priority-2 task with increasing `seq`, and two tasks sharing `seq` to exercise
  the `id` tie-break.
- Large project: 60 tasks for the row-cap case (case 12).
- Workflow split: `bugfix` and `simple` tasks in one project for
  `task_next(workflow='bugfix')`.
- Text filter: title `"Fix loader crash"` and a description containing
  `"plugin loader"`; `fts_enabled()` monkeypatched `False` for the LIKE half.
- Empty and fully terminal projects for `task_next` returning `None`.

## How to test

1. `python -m pytest tests/test_scheduler.py -v` with the recorder running.
2. Run the predicate group — `-k "ready or waiting or closure"` — and screenshot
   the ready/waiting sets.
3. Run `-k "next"` to capture ordering and the two `None` cases.
4. Run `-k "fts or like"` to show both search backends returning the same ids.
5. Save the ready and waiting id lists for one project into
   `attachments/ready-set.json` (case 10 evidence).

## Expected results

| Case | Expectation |
|---|---|
| 1 | with no relations, every `open` task is ready |
| 2 | A `blocked_by` B with B `open` ⇒ A waiting, B ready |
| 3 | B `done` with `require_closure=0` ⇒ A ready |
| 4 | B `done` with `require_closure=1` ⇒ A still waiting; after `task_close` on B, A becomes ready |
| 5 | B `cancelled` ⇒ A ready in both closure modes |
| 6 | chain A→B→C with C `open` ⇒ A and B waiting, C ready |
| 7 | an `open` blocker-free task is ready even when another task is `blocked`; `task_next` never returns a `blocked` task |
| 8 | `task_next` prefers priority 1 over 2, breaks ties on `seq` then `id`, and returns `None` for empty or fully terminal projects |
| 9 | `task_next(workflow='bugfix')` never returns a task from another workflow |
| 10 | `task_query(ready=True)` and `task_query(waiting=True)` equal the scheduler's sets exactly — same ids, same order |
| 11 | title and description are both found through FTS and through LIKE when `fts_enabled()` is monkeypatched `False` |
| 12 | a 60-task project returns at most `limit` rows and an honest `total` |
| 13 | the lease cross-check is skipped with a reason until TT08 lands, then asserts `task_next` skips a lease held by another actor |

## Test artifacts

Folder `docs/test-reports/TT06/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 13 case rows (case 13 marked skipped until TT08), embedded screenshots, video link |
| `pytest.log` | full run plus the predicate, `next` and `fts/like` selections |
| `screenshots/01-ready-vs-waiting.png` | A/B/C states with the ready and waiting sets |
| `screenshots/02-task-next-ordering.png` | priority, `seq`, `id` ordering and both `None` cases |
| `screenshots/03-row-cap.png` | the 60-task project truncated to `limit` with an honest `total` |
| `attachments/ready-set.json` | ready/waiting id lists compared in case 10 |
| `video/TT06-scheduler.mp4` | 30 s–5 min: suite, predicate group, `next` group, FTS/LIKE comparison |

## Oracles exercised

OR-04 (`waiting` computed, never stored), OR-07 (caps), N2.

## Done when

- `pytest tests/test_scheduler.py -q` green on all three OSes.
- Cases 3–5 are also exercised end-to-end by TT08/5 with `require_closure`.
- `docs/test-reports/TT06/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT06-scheduler.mp4`
  recording.
