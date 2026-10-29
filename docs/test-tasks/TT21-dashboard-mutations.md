# TT21 — Dashboard mutations, detail, graph, takeover

| | |
|---|---|
| Suite | `DSH` |
| Verifies | [T21](../tasks/T21-dashboard-mutations.md) |
| Phase | M6 |
| Depends on | TT20, TT07 |
| Unblocks | TT22 |
| Level | L4 |
| Size | L |
| Status | pending |

## Goal

Prove a drag is the same operation as the MCP tool — same success state, same refusal
payload — and that a human cannot silently steal leased work.

## Files

- `tests/test_dashboard.py` — extend.
- `tests/test_acceptance.py` — helpers reused by TT22.

## Cases

1. Legal walk over HTTP: start → block (reason) → unblock → start → complete
   (outcome) → close; final DB rows match an MCP-driven walk of the same sequence on
   an identical seed.
2. Illegal drags refused with MCP-identical `error` and `message`:
   complete without outcome → `MissingOutcome`; block without reason →
   `MissingReason`; close from `open` → `IllegalTransition`; start a task leased by
   another actor → `LeaseConflict`.
3. Refusal is non-destructive: after each illegal drop the row is unchanged and the
   response contains the server's reason.
4. Takeover: `POST /tasks/{id}/takeover` succeeds on an `agent-7` task, sets owner to
   the human actor, and afterwards a transition succeeds; before takeover the same
   transition fails with `LeaseConflict`.
5. `POST /tasks` creates a task that appears in the `open` column on the next
   `GET /board`; validation failures return the same error payload as `task_add`.
6. Journal UI: `POST` adds an entry visible in `GET /tasks/{id}`; `PUT` and `DELETE`
   on `/tasks/{id}/journal/{entry_id}` return 404/405 because the routes do not
   exist.
7. Detail panel `GET /tasks/{id}` contains everything `task_get` returns:
   description/design, relations, computed waiting state, children, story context,
   journal timeline.
8. `GET /graph` contains every node and edge and marks waiting nodes; it performs no
   writes.
9. No raw SQL in any mutation route: repeat the `sql_capture` assertion across every
   POST route and assert the only writes originate from repository calls (statement
   text appears in the repository allowlist).
10. Link route: `POST /tasks/{id}/links` calls `task_link`; a cycle attempt is
    refused with `CycleDetected`, identical to MCP.

## Oracles exercised

OR-01, OR-06, OR-12, Q10 (takeover), plan §8.4.

## Done when

- `pytest tests/test_dashboard.py -q` green on all three OSes.
- Every refusal payload in case 2 is compared against a live MCP call, not a
  hard-coded string.
