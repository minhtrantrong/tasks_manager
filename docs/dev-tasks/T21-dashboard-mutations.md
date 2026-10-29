# T21 — Board mutations, task detail, graph view, lease takeover

| | |
|---|---|
| Phase | M6 |
| Depends on | T20, T07 |
| Unblocks | T22 |
| Size | L |
| Status | pending |

## Goal

The board becomes a control surface that can never disagree with MCP: every drag
and form calls the same repository transition functions (intend §8 "one write
path", open questions 10/11).

## Files

- `src/task_manager/dashboard/mutations.py` — write routes (or extend `board.py`).
- `src/task_manager/dashboard/templates/task_detail.html` — detail panel.
- `src/task_manager/dashboard/templates/graph.html` — graph view.
- `tests/test_dashboard.py` — extend.

## Routes

**`POST /tasks`** — create (the T20 open-column form's target). Body: title,
description, type, workflow, priority, parent_id, blocked_by[].
Calls `repository.task_add` with `actor="human"`. On success returns the new
card's HTML (the `_card.html` partial) for HTMX insertion; on validation failure
returns the form with an error banner.

**`POST /transitions`** — the single mutation endpoint. Body:
`{task_id, action, outcome?, reason?, actor="human"}` where action ∈
`start | release | complete | close | block | unblock | reopen | cancel`.
Dispatch table maps each action to the exact repository function from T07
(`start`→`task_start`, `release`→`task_release`, `complete`→`task_complete` with
the `outcome` field, `block`→`task_block` with `reason`, `close`→`task_close`,
`unblock`→`task_unblock`, `reopen`→`task_reopen`, `cancel`→`task_cancel`).

Responses:

- Success → 200, re-rendered board body (so the card lands in its new column).
- Failure → **422 with the identical error payload the MCP tool returns**:
  `{"ok": false, "error": "MissingOutcome", "message": "..."}`. The frontend
  snaps the card back and shows `message` in a toast — the server's reason, never
  a client guess (illegal drop rule from §8).

**`POST /tasks/{id}/takeover`** — lease takeover (open question 10). One click,
atomic from the user's perspective: `repository.task_release(force=True)` then
`repository.task_start(actor="human")`; returns the card. A takeover must be the
only way a leased card changes hands — `POST /transitions` on a leased task with
`actor="human"` gets `LeaseConflict`, exactly like MCP.

**`POST /tasks/{id}/journal`** — append-only journal from the UI (kind + body).
Calls `repository.journal_add`. **No edit/delete journal route exists** — the
append-only rule is enforced by absence, not by hiding buttons (§8).

**`GET /tasks/{id}`** — detail panel rendering everything `task_get` returns:
description, design, outcome/reason, relations with ready/waiting state, children,
story context, journal timeline (newest first), plus the action buttons mapped to
the transition table above.

**`GET /graph`** — read-only DAG view: `repository.task_graph` + waiting set.
Render with plain HTML/CSS (absolutely-positioned columns or a simple SVG with
status colour coding) — no JS libraries. Waiting nodes visually marked.

## Rules

- No route may contain SQL or call `sqlite3` — repository only (N7).
- No route may write `status` directly — only via the T07 functions.
- Error messages must be byte-identical to the MCP tools' messages (they come from
  the same exceptions — assert this in tests, don't rephrase).

## Tests (extend `tests/test_dashboard.py`)

Seed: project with open/in_progress(done-ready)/blocked/done tasks + one task
leased by `agent-7`.

1. `POST /transitions` legal walk: start → block(with reason) → unblock → start →
   complete(with outcome) → close, all via HTTP; final DB state matches an
   MCP-driven walk of the same sequence on an identical seed (compare rows).
2. Illegal drags refused with MCP-identical payloads: complete without outcome →
   `MissingOutcome`; block without reason → `MissingReason`; close from open →
   `IllegalTransition`; start a leased task as human → `LeaseConflict`.
3. `POST /tasks/{id}/takeover` on the `agent-7` task succeeds and the card shows
   owner `human`; before takeover, `/transitions` on it fails with `LeaseConflict`.
4. `POST /tasks` creates a task and it appears in the open column on the next
   `GET /board`.
5. Journal: POST adds an entry, it shows in `GET /tasks/{id}`; `PUT
   /tasks/{id}/journal/{entry_id}` and `DELETE /tasks/{id}/journal/{entry_id}`
   return 404/405 (routes must not exist).
6. `GET /graph` contains every node and edge; waiting node marked.
7. No route executes raw SQL: reuse the SQL-capture connection assertion across
   all mutation routes.

## Done when

- A human can run the whole project from the browser; illegal board actions are
  refused with the server's reason, identical to MCP (intend M6 gate, §8).
- Tests green on all CI OSes.
