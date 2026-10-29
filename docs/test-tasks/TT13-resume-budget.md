# TT13 — `resume` assembly and acceptance C (bounded memory)

| | |
|---|---|
| Suite | `RES`, `ACC-C` |
| Verifies | [T13](../tasks/T13-resume.md), [test-plan §8.3](../test-plan.md) |
| Phase | M4 |
| Depends on | TT08, TT09, TT12 |
| Unblocks | TT15 |
| Level | L2 + serialization |
| Size | M |
| Status | pending |

## Goal

Prove the flagship call is both sufficient and bounded: everything needed to
continue, nothing that blows the context budget.

## Files

- `tests/test_resume_budget.py` — new, containing `test_bounded_memory` (name fixed
  per plan §16 D-2).

## Cases

1. Shape: payload keys match intend §7.7 (`project`, `last_checkpoint`,
   `in_progress`, `blocked`, `waiting_on`, `ready`, `story_context`, `recent`,
   `health`), and no key is `None`.
2. Budget on `seed_large` (50+ tasks): `len(json.dumps(payload, ensure_ascii=False))
   <= 5200` and `ceil(len/4) <= 1300`.
3. Sufficiency: `in_progress` carries `last_journal`; `blocked` carries reasons;
   `waiting_on` carries `needs`; `ready` ≤10 and only truly ready; `last_checkpoint`
   carries `next_actions`.
4. Health: `stale` contains the seeded stale task and not a task with a fresh
   journal entry; `compactions_since_checkpoint == 2`; `lease_expired` lists ids
   reaped during this call.
5. Staleness boundary: journal exactly 7 days old is not stale; 7 days + 1 second is.
6. Compaction counting: compactions before the latest checkpoint are not counted;
   a new checkpoint resets the count to 0.
7. Truncation: a 4000-character checkpoint summary returns ≤500 + `…`; journal
   bodies truncate at 200, `recent` at 120, reasons at 200, `next_actions` at 5.
8. Caps: `waiting_on` ≤10, `recent` ≤8, `story_context` ≤3 stories × ≤3 entries.
9. Degradation order: seed enough oversized data to exceed the ceiling, then assert
   `recent` shrinks first, then `story_context`, then `ready` — and that
   `in_progress`, `blocked`, `waiting_on`, `last_checkpoint` survive untouched.
10. `lease_left_min`: a lease expiring in 20 minutes reports 20 ±1; an expired lease
    is reaped, absent from `in_progress`, and present in `health.lease_expired`.
11. Empty project returns zero counts and empty lists without crashing.
12. `resume("demo")` and `resume(project_id)` return byte-identical payloads;
    an unknown slug raises `NotFound`.
13. Reaping is applied on this path: a stale `in_progress` lease is reaped by
    `resume`, proving the read-path contract of plan §9.

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_resume_budget.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt13\tasks.sqlite`; frozen clock for staleness and lease maths |
| Prereqs | CPython 3.12; `seed_large` available from `tests/seeds.py` |

## Test data

- `seed_large`: 50+ tasks across all statuses, ~8 `blocked` with reasons, waiting
  chains, 2 compactions after the latest checkpoint, one stale task (>7 days), one
  checkpoint with `next_actions`.
- Truncation fixtures: a 4000-character checkpoint summary, journal bodies over
  200 characters, `recent` titles over 120, `blocked` reasons over 200, and
  `next_actions` with 6 items.
- Cap fixtures: `waiting_on` with 12 entries, `recent` with 10, `story_context`
  with 4 stories × 4 entries.
- Staleness boundary: a journal entry exactly 7 days old (not stale) and one at
  7 days + 1 second (stale).
- Lease fixtures: `+20 min` (reported as 20 ±1) and an expired lease that must be
  reaped during the call.
- Identity: `resume("demo")` and `resume(project_id)`; unknown slug `"nope"`.
- Degradation fixture: a seed sized to exceed the ceiling so `recent`,
  `story_context` and `ready` must be dropped in that order.

## How to test

1. `python -m pytest tests/test_resume_budget.py -v` with the recorder running.
2. Run the shape group — `-k "shape or empty or identity"` — showing every key
   present and non-`None`.
3. Run the budget group — `-k "budget or bounded_memory"` — and record both
   measured values (`len(json.dumps(...))`, `ceil(len/4)`) in the report and in
   `attachments/budget.txt`.
4. Run the degradation group — `-k "degrad or truncat"` — and screenshot the
   section sizes before/after each drop, proving the order.
5. Save the exact payload for `seed_large` into `attachments/resume-payload.json`
   so a reviewer can re-measure the ceiling.

## Expected results

| Case | Expectation |
|---|---|
| 1 | the payload has exactly the intend §7.7 keys and no key is `None` |
| 2 | on `seed_large`, the serialised payload is ≤5200 characters and ≤1300 estimated tokens |
| 3 | `in_progress` carries `last_journal`, `blocked` carries reasons, `waiting_on` carries `needs`, `ready` has ≤10 truly ready tasks, `last_checkpoint` carries `next_actions` |
| 4 | `health.stale` contains the seeded stale task only, `compactions_since_checkpoint == 2`, and `health.lease_expired` lists the ids reaped during the call |
| 5 | a journal entry exactly 7 days old is not stale; 7 days + 1 second is |
| 6 | compactions before the latest checkpoint are not counted; a new checkpoint resets the count to 0 |
| 7 | the checkpoint summary truncates to ≤500 + `…`, journal bodies at 200, `recent` at 120, reasons at 200, `next_actions` at 5 items |
| 8 | `waiting_on` ≤10, `recent` ≤8, `story_context` ≤3 stories × ≤3 entries |
| 9 | over the ceiling, `recent` shrinks first, then `story_context`, then `ready`, while `in_progress`, `blocked`, `waiting_on` and `last_checkpoint` survive unchanged |
| 10 | a lease expiring in 20 minutes reports 20 ±1; an expired lease is reaped, absent from `in_progress`, present in `health.lease_expired` |
| 11 | an empty project returns zero counts and empty lists |
| 12 | `resume("demo")` and `resume(project_id)` are byte-identical; an unknown slug raises `NotFound` |
| 13 | `resume` reaps a stale `in_progress` lease, proving the reap-on-read contract |

## Test artifacts

Folder `docs/test-reports/TT13/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 13 case rows, both measured budget values, embedded screenshots, video link |
| `pytest.log` | full run plus the shape, budget and degradation selections |
| `screenshots/01-resume-shape.png` | every payload key present and non-`None` on `seed_large` |
| `screenshots/02-budget-ceiling.png` | character and token measurements against 5200 / 1300 |
| `screenshots/03-degradation-order.png` | `recent` → `story_context` → `ready` shrinking in order |
| `attachments/resume-payload.json` | the measured `seed_large` payload |
| `attachments/budget.txt` | raw size/token numbers per run |
| `video/TT13-resume-budget.mp4` | 30 s–5 min: suite, shape, budget, degradation order |

## Oracles exercised

OR-04 (reap on read), OR-07 (all resume caps), N2, plan §7.

## Done when

- `pytest tests/test_resume_budget.py -q` green on all three OSes.
- ACC-C (`test_bounded_memory`) is part of the release `-k` selection.
- Case 9 proves the drop order, not just the ceiling.
- `docs/test-reports/TT13/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT13-resume-budget.mp4`
  recording.
