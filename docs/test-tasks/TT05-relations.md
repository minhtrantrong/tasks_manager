# TT05 — Relations, cycle rejection, graph

| | |
|---|---|
| Suite | `REL` |
| Verifies | [T05](../tasks/T05-relations-graph.md) |
| Phase | M1 |
| Depends on | TT04 |
| Unblocks | TT06 |
| Level | L2 + L5 |
| Size | M |
| Status | pending |

## Goal

Prove cycles are rejected at link time — not discovered later — and that provenance
edges are never mistaken for scheduling edges.

## Files

- `tests/test_relations.py` — new.

## Cases

1. `task_link` then `task_unlink` round-trip; `task_graph` reflects the edge.
2. Self-link is rejected (`ValidationError`); the DB CHECK is a second line of
   defence.
3. Cross-project link is rejected.
4. Direct 2-cycle: A `blocked_by` B, then B `blocked_by` A → `CycleDetected` on the
   second call.
5. Transitive cycle: A→B, B→C, C→A rejected at the third insert.
6. Diamond (A blocked by B and C, both blocked by D) is legal and accepted.
7. `related` and `discovered_during` do not participate in cycle detection: A
   `related` B plus B `blocked_by` A is legal (provenance, not scheduling).
8. Duplicate `blocked_by` link rejected; the same pair with a different kind is
   accepted (PK includes `kind`).
9. `task_graph` returns every node (including isolated tasks), correct edges, and
   a `waiting` set consistent with the scheduler once TT06 lands.
10. `task_unlink` of a missing edge is a no-op; a missing task raises `NotFound`.
11. Concurrency (`L5`): two threads link A→B and B→A simultaneously on one file;
    at most one succeeds and the DB contains no 2-cycle.
12. A rejected link leaves no row behind (count unchanged, no partial transaction).

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`), in-process threads for the `L5` case; no server |
| Command | `python -m pytest tests/test_relations.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt05\tasks.sqlite`; one real file shared by the two threads |
| Prereqs | CPython 3.12; `busy_timeout=5000` active; no network |

## Test data

- Four tasks added through the repository: A, B, C, D (ids 1–4), all `open`.
- Edge kinds: `blocked_by` (scheduling), `related` and `discovered_during`
  (provenance).
- Edge sets: A→B and B→A (2-cycle); A→B, B→C, C→A (3-cycle); A→B, A→C, B→D, C→D
  (diamond); A `related` B plus B `blocked_by` A (legal); a duplicate
  `blocked_by` pair; the same pair as `related`; a missing edge; bogus task `9999`.
- Free-form text for `task_graph`: the `waiting` set must match
  `scheduler.ready_ids` once TT06 lands.
- Isolation: rejected links are asserted by comparing `task_relations` counts
  before and after.

## How to test

1. `python -m pytest tests/test_relations.py -v` with the recorder running.
2. Run the cycle group alone — `-k "cycle or self or cross_project"` — and
   screenshot the `CycleDetected` failure text (case 4/5).
3. Run the provenance group — `-k "related or discovered or diamond"` — to show
   that only `blocked_by` participates in cycle detection.
4. Dump one graph into `attachments/graph.json` via `task_graph` (nodes, edges,
   `waiting`) and compare it with the rendered board once TT06/TT20 exist.
5. Run the concurrency case at least three times: `-k concurrent --count=3`
   (or three separate runs) and note that every run asserts an outcome, never a
   timing.

## Expected results

| Case | Expectation |
|---|---|
| 1 | `task_link` then `task_unlink` round-trips and `task_graph` reflects the edge |
| 2 | a self-link raises `ValidationError`; the DB CHECK rejects a raw insert as the second line of defence |
| 3 | a cross-project link raises `ValidationError` |
| 4 | the second call of a 2-cycle raises `CycleDetected` |
| 5 | the third insert of a 3-cycle raises `CycleDetected` |
| 6 | the diamond is accepted and the graph keeps all four edges |
| 7 | `related` / `discovered_during` never trigger cycle detection: A `related` B plus B `blocked_by` A is legal |
| 8 | a duplicate `blocked_by` pair is rejected while the same pair with another kind is accepted |
| 9 | `task_graph` returns every node (including isolated tasks) with correct edges and a `waiting` set consistent with the scheduler |
| 10 | unlinking a missing edge is a no-op; a missing task raises `NotFound` |
| 11 | two threads linking A→B and B→A end with exactly one success and no 2-cycle in the database |
| 12 | every rejected link leaves the relation count unchanged |

## Test artifacts

Folder `docs/test-reports/TT05/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 12 case rows, embedded screenshots, video link |
| `pytest.log` | full run, the cycle/provenance selections, and the repeated concurrency runs |
| `screenshots/01-cycle-rejected.png` | `CycleDetected` for the 2-cycle and the 3-cycle |
| `screenshots/02-provenance-legal.png` | the `related` + `blocked_by` pair accepted and the diamond accepted |
| `screenshots/03-graph-nodes.png` | `task_graph` node/edge output including isolated tasks |
| `attachments/graph.json` | node, edge and `waiting` payload used for case 9 |
| `video/TT05-relations.mp4` | 30 s–5 min: suite, cycle group, provenance group, graph dump |

## Oracles exercised

OR-05 (acyclic, self-link free), OR-04 (`waiting` computed), N4.

## Done when

- `pytest tests/test_relations.py -q` green on all three OSes.
- The concurrency case is deterministic: it asserts an outcome, never a timing.
- `docs/test-reports/TT05/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT05-relations.mp4`
  recording.
