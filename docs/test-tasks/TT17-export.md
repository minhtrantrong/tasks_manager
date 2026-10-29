# TT17 — Markdown and EDNL export

| | |
|---|---|
| Suite | `EXP` |
| Verifies | [T17](../tasks/T17-export.md) |
| Phase | M5 |
| Depends on | TT09 |
| Unblocks | — |
| Level | L2 |
| Size | S |
| Status | pending |

## Goal

Prove a human can review a project's full history as plain text, and that export
provably does not write.

## Files

- `tests/test_export.py` — new.

## Cases

1. Seeded project → Markdown contains every task title, every journal body, every
   block reason, and one relation line per edge.
2. EDNL round-trip: parse the emitted lines and assert every task, journal entry,
   relation, and context entry in the DB is represented exactly once.
3. Determinism: two consecutive exports are byte-identical, including with a frozen
   clock and tasks sharing a timestamp.
4. `path=` writes UTF-8 (non-ASCII title and journal body survive a read-back);
   the DB row counts and `updated_at` values are unchanged afterwards.
5. Story context appears under its story task only; children do not duplicate it.
6. Empty project exports a valid document with a header and no rows.
7. An unknown project raises `NotFound` and writes no file.
8. Export never emits an external URL and never opens a socket (N1/N8 guard).

## Oracles exercised

OR-01 (read-only), OR-08, Q6 (export on demand, no mirror).

## Done when

- `pytest tests/test_export.py -q` green on all three OSes.
- Case 3 fails if dict ordering or timestamps are non-deterministic.
