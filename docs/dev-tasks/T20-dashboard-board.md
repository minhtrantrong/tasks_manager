# T20 — Board UI: columns, cards, swimlanes, waiting badges

| | |
|---|---|
| Phase | M6 |
| Depends on | T19, T06, T08 |
| Unblocks | T21 |
| Size | L |
| Status | pending |

## Goal

The kanban board exactly mirrors MCP state — same fields, same ordering, computed
`waiting` as a badge, never a column (intend §8).

## Files

- `src/task_manager/dashboard/board.py` — read-side routes (moves into app.py is
  acceptable; keep a separate module for size).
- `src/task_manager/dashboard/templates/board.html` — real rendering.
- `src/task_manager/dashboard/templates/_card.html` — card partial (reused by T21's
  HTMX swaps).
- `tests/test_dashboard.py` — extend.

## Route: `GET /board`

Query params: `swimlane=none|workflow|parent` (default `none`),
`show_cancelled=0|1` (default 0).

Rendering rules:

1. **Columns** in fixed order: `open`, `in_progress`, `blocked`, `done`, `closed`;
   plus `cancelled` only when `show_cancelled=1`. **No `waiting` column — ever.**
2. **Cards** (`_card.html`) show: `#id`, title, priority (p1–p5), workflow,
   owner, lease countdown (`max(0, ceil((lease_expires_at − now)/60))` minutes,
   rendered as "lease 34m left"), a `⧗ waits #9` badge when
   `scheduler.is_waiting(task)` (dims the card via CSS class `waiting`), and the
   **last journal line** (kind + first 100 chars) — the same fields `resume`
   returns.
3. **Order within a column:** `priority ASC, seq ASC, id ASC`.
4. **Swimlanes:** when `swimlane=workflow`, group cards under a workflow subheading
   per column; when `swimlane=parent`, group story children under their parent
   story's title (top-level tasks in a `No parent` lane). Visual grouping only —
   never a status.
5. **Open column add-task form:** a collapsible inline form (title, description,
   type, workflow, priority) posting to `POST /tasks` (implemented in T21). Render
   the form; T21 wires the handler.
6. **Live refresh (polling, per open question 12):** the board body is wrapped in
   `<div hx-get="/board?swimlane=...&show_cancelled=..." hx-trigger="every 5s"
   hx-swap="innerHTML">`. No SSE.
7. All data comes from repository reads: `task_query` (status-scoped) +
   `scheduler.waiting_tasks` + last-journal per card (one batched query — see
   below). **No SQL in templates or routes.**

Performance note: fetch last-journal-lines in one query
(`SELECT ... FROM journal WHERE task_id IN (...) GROUP BY task_id HAVING id =
MAX(id)`-style) rather than N queries; fine at hundreds of tasks.

## CSS (`app.css`)

- `waiting` cards: reduced opacity + badge; leased cards: owner chip +
  countdown; priority left-border colour (p1 red … p5 grey); status column headers
  sticky. Plain CSS, no framework.

## Tests (extend `tests/test_dashboard.py`)

Seed a project with: p1 open task, p2 open task waiting on a blocked task, an
`in_progress` task leased for 30 min, a done task, a cancelled task.

1. `GET /board` renders each task in its correct column; ordering within `open`
   column is p1 before p2.
2. The waiting task shows `waits #<id>` badge and `waiting` class; no `waiting`
   column heading exists in the HTML (assert the string `>waiting<` absent from
   column headers).
3. Leased card shows owner and `lease NNm left`.
4. Cancelled task absent by default; present with `show_cancelled=1`.
5. `swimlane=workflow` and `swimlane=parent` group headings present and correct.
6. Last-journal line rendered on a task with journal entries; absent for one
   without.
7. `GET /board` runs no write SQL (reuse T19's SQL-capture assertion).

## Done when

- A human can read in-flight/stuck state from the board alone, and the board shows
  exactly what `resume` shows (intend M6/§14 consistency).
- Tests green on all CI OSes.
