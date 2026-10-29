# TT11 — `recall`: FTS5 with LIKE fallback

| | |
|---|---|
| Suite | `RCL` |
| Verifies | [T11](../tasks/T11-recall.md) |
| Phase | M3 |
| Depends on | TT09 |
| Unblocks | — |
| Level | L2 |
| Size | S |
| Status | pending |

## Goal

Prove "did we already try this?" is answerable from stored memory on every build,
including one without FTS5.

## Files

- `tests/test_recall.py` — new.

## Cases

1. Journal body "retry uses backoff 2^n" is found by the query `backoff retry`; the
   snippet contains the matched text and the hit carries the task id.
2. A task is found by title and, separately, by description.
3. `project_id` scoping: hits in another project are absent; omitting the project
   searches all non-archived projects.
4. `limit` is respected (5 returns ≤5) and journal hits precede task hits for the
   same query.
5. FTS syntax safety: queries containing `"`, `*`, `(`, `-`, `NEAR`, and an
   all-operator string return results or an empty list — never an `OperationalError`.
6. Blank or whitespace-only query → `ValidationError`.
7. Fallback: with `fts_enabled` monkeypatched False, the same three queries return
   results and `search_backend == "like"`; with FTS available it is `"fts"`.
8. `require_fts=True` with FTS unavailable → `FtsUnavailable`; the server still runs
   (no import-time failure).
9. Relevance sanity on `seed_large`: `recall("api key")` returns the one task whose
   journal mentions it, inside the top 3.
10. A hit for a soft-cancelled task is still returned but flagged with its status;
    a hard-deleted task leaves no hit (FTS triggers removed it).

## Oracles exercised

OR-07 (limit), N5 (graceful degradation), plan §13.1 (FTS gap).

## Done when

- `pytest tests/test_recall.py -q` green on all three OSes, including the
  monkeypatched fallback path.
- No test asserts on FTS ranking order beyond the top-3 sanity check.
