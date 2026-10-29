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

## Oracles exercised

OR-05 (acyclic, self-link free), OR-04 (`waiting` computed), N4.

## Done when

- `pytest tests/test_relations.py -q` green on all three OSes.
- The concurrency case is deterministic: it asserts an outcome, never a timing.
