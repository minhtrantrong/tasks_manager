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

## Oracles exercised

OR-04 (reap on read), OR-07 (all resume caps), N2, plan §7.

## Done when

- `pytest tests/test_resume_budget.py -q` green on all three OSes.
- ACC-C (`test_bounded_memory`) is part of the release `-k` selection.
- Case 9 proves the drop order, not just the ceiling.
