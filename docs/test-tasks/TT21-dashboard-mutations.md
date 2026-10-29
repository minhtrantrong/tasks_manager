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

## Test environment

| | |
|---|---|
| Surface | HTTP dashboard (`L4`) mutations plus terminal CLI |
| Base URL | `http://127.0.0.1:8765` |
| Routes | `POST /transitions` (`{"task_id": 1, "action": "start", "actor": "human"}`), `POST /tasks`, `POST /tasks/{id}/takeover`, `POST /tasks/{id}/links`, `POST /tasks/{id}/journal`, `GET /tasks/{id}`, `GET /graph` |
| Start | `$env:TASKS_DB="<repo>\.tmp-tt21\tasks.sqlite"; task-manager dashboard --port 8765` |
| Setup | `python -m pip install -e ".[dev,dashboard]"` |
| Prereqs | CPython 3.12; free port 8765; browser for drag-and-drop evidence |

## Test data

- Two identical seeds for the parity walk: one driven over HTTP, one over MCP.
- Leased task owned by `agent-7` (unexpired) for the takeover and `LeaseConflict`
  cases.
- Refusal payloads: complete without outcome, block without reason, close from
  `open`, start while leased by another actor.
- Create-task payload: `{"title": "Fix loader crash", "priority": 1}` plus an
  invalid variant with a blank title.
- Journal payload: `{"kind": "note", "body": "board note from the human"}`.
- Link payload: `{"related_id": 2, "kind": "blocked_by"}` plus a cycle attempt.

## How to test

1. `python -m pytest tests/test_dashboard.py -v -k "mutation or transition or takeover or link or journal or detail or graph"` with the recorder running.
2. Start the dashboard, perform the legal walk by dragging/using the buttons:
   start → block (reason) → unblock → start → complete (outcome) → close; capture
   the board after each step and one screenshot of the final state.
3. Perform each illegal drag and capture the refusal payload; the response must
   match a live MCP call of the same operation.
4. Take over the `agent-7` task through the takeover route and show the card
   changing owner.
5. Open `GET /tasks/{id}` and `GET /graph`, capture both, and save the page source
   into `attachments/`.
6. Call `PUT` and `DELETE` on `/tasks/{id}/journal/{entry_id}` and record the
   404/405 responses.

## Expected results

| Case | Expectation |
|---|---|
| 1 | the HTTP walk ends in the same DB rows as the MCP-driven walk on an identical seed |
| 2 | illegal drags return MCP-identical `error` and `message`: `MissingOutcome`, `MissingReason`, `IllegalTransition`, `LeaseConflict` |
| 3 | each refusal leaves the row unchanged and includes the server's reason |
| 4 | takeover succeeds on the `agent-7` task, sets owner to the human actor, and a later transition succeeds where it previously conflicted |
| 5 | `POST /tasks` makes the task appear in `open` on the next `GET /board`, and validation failures return the `task_add` payload |
| 6 | a journal `POST` is visible in `GET /tasks/{id}`; `PUT` and `DELETE` return 404/405 |
| 7 | the detail panel contains description/design, relations, waiting state, children, story context and the journal timeline |
| 8 | `/graph` contains every node and edge, marks waiting nodes, and performs no writes |
| 9 | every POST route's writes originate from repository calls in the allowlist — no route issues SQL |
| 10 | a cycle attempt on `/tasks/{id}/links` returns `CycleDetected`, identical to MCP |

## Test artifacts

Folder `docs/test-reports/TT21/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 10 case rows, base URL, embedded screenshots, video link |
| `pytest.log` | the mutation selection with the summary line |
| `screenshots/01-legal-walk.png` | the final board after start → block → unblock → start → complete → close |
| `screenshots/02-refusal-payloads.png` | the four refusals with their `error`/`message` |
| `screenshots/03-takeover.png` | the card owner changing from `agent-7` to the human actor |
| `screenshots/04-detail-panel.png` | `/tasks/{id}` with relations, waiting state, children, context and journal |
| `screenshots/05-graph.png` | `/graph` with every node/edge and waiting markers |
| `attachments/refusals.json` | HTTP and MCP payloads compared in case 2 |
| `attachments/final-rows.json` | task/relation/journal rows after the walk, used in case 1 |
| `video/TT21-dashboard-mutations.mp4` | 30 s–5 min: the walk, each refusal, takeover, detail panel, graph |

## Oracles exercised

OR-01, OR-06, OR-12, Q10 (takeover), plan §8.4.

## Done when

- `pytest tests/test_dashboard.py -q` green on all three OSes.
- Every refusal payload in case 2 is compared against a live MCP call, not a
  hard-coded string.
- `docs/test-reports/TT21/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT21-dashboard-mutations.mp4`
  recording.
