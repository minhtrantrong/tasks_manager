# TT19 — Dashboard skeleton and offline rule

| | |
|---|---|
| Suite | `DSH` |
| Verifies | [T19](../tasks/T19-dashboard-skeleton.md) |
| Phase | M6 |
| Depends on | TT04 |
| Unblocks | TT20 |
| Level | L4 |
| Size | M |
| Status | pending |

## Goal

Prove the board exists, serves only local assets, reads without writing, and cannot
be reached from another host by default.

## Files

- `tests/test_dashboard.py` — new.

## Cases

1. `GET /` redirects to `/board`; `GET /board` returns 200 and contains the five
   status column headings (`open`, `in_progress`, `blocked`, `done`, `closed`);
   `GET /health` returns 200 with an ok payload.
2. Static assets `/static/htmx.min.js` and `/static/app.css` return 200 with the
   expected content types.
3. Seeded DB: one task appears under its column (smoke before TT20).
4. N8 scan: every file under `dashboard/templates` and `dashboard/static` (except
   `VENDORED.md`) contains no `http://` or `https://` reference.
5. Read-only rendering: `GET /board` under `sql_capture` executes zero
   `INSERT`/`UPDATE`/`DELETE` statements.
6. Bind address: the app's default host is `127.0.0.1` and the CLI passes no
   `0.0.0.0`; assert from the app factory/CLI defaults, not by binding a port.
7. Escaping: a task title containing `<script>alert(1)</script>` renders escaped,
   and the raw tag is absent from the HTML.
8. Starting the dashboard does not disturb `serve`: importing the dashboard app
   opens no socket and writes no DB row.
9. `task-manager dashboard` exits with a clear error (not a traceback) if the
   `dashboard` extra is missing (`fastapi` import blocked).

## Test environment

| | |
|---|---|
| Surface | HTTP dashboard (`L4`) plus terminal CLI |
| Base URL | `http://127.0.0.1:8765` |
| Start | `$env:TASKS_DB="<repo>\.tmp-tt19\tasks.sqlite"; task-manager dashboard --host 127.0.0.1 --port 8765` |
| Routes | `GET /` (302 → `/board`), `GET /board`, `GET /health`, `/static/htmx.min.js`, `/static/app.css` |
| Setup | `python -m pip install -e ".[dev,dashboard]"` |
| Prereqs | CPython 3.12; a free port 8765; a browser for screenshots |

## Test data

- `seed_board` (one task per column state) written through the repository into the
  same `TASKS_DB` file the app reads.
- Escaping fixture: a task titled `<script>alert(1)</script>`.
- Asset expectations: `htmx.min.js` served as `text/javascript`,
  `app.css` as `text/css`.
- Empty-state fixture: a migrated database with no project, for the first-paint
  check.

## How to test

1. `python -m pytest tests/test_dashboard.py -v -k "skeleton or asset or escaping or bind or read_only"` with the recorder running.
2. Start the dashboard with the command above and open
   `http://127.0.0.1:8765/board`; confirm the five column headings.
3. Check the redirect and health endpoint over HTTP:
   `curl -s -i http://127.0.0.1:8765/` and
   `curl -s -D docs/test-reports/TT19/attachments/api-headers.txt http://127.0.0.1:8765/health`.
4. Capture the board with the headless-browser command from
   [test-reports/README.md](../test-reports/README.md) §2, saving
   `screenshots/01-board-columns.png`.
5. Screenshot the `<script>` card to prove escaping, and the static-asset response
   headers.
6. Stop the server with `Ctrl+C` and confirm the process exited cleanly.

## Expected results

| Case | Expectation |
|---|---|
| 1 | `GET /` redirects to `/board`; `/board` returns 200 with the five status headings; `/health` returns ok |
| 2 | both static assets return 200 with the expected content types |
| 3 | the seeded task appears under its column |
| 4 | no template or static file except `VENDORED.md` contains `http://` or `https://` |
| 5 | `GET /board` under `sql_capture` executes zero `INSERT`/`UPDATE`/`DELETE` |
| 6 | the app factory's default host is `127.0.0.1` and the CLI never passes `0.0.0.0` |
| 7 | the `<script>` title renders escaped and the raw tag is absent from the HTML |
| 8 | importing the dashboard app opens no socket and writes no DB row |
| 9 | with `fastapi` import blocked, `task-manager dashboard` exits with a clear message, not a traceback |

## Test artifacts

Folder `docs/test-reports/TT19/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 9 case rows, base URL and port, embedded screenshots, video link |
| `pytest.log` | the dashboard skeleton selection with the summary line |
| `screenshots/01-board-columns.png` | `/board` with the five column headings and the seeded card |
| `screenshots/02-health-static.png` | `/health` response and a 200 static asset with its content type |
| `screenshots/03-escaped-title.png` | the `<script>` title rendered as text |
| `attachments/api-headers.txt` | response headers for `/health` |
| `attachments/board.html` | saved page source proving no raw `<script>alert(1)</script>` |
| `video/TT19-dashboard-skeleton.mp4` | 30 s–5 min: start the dashboard, `/` redirect, `/board`, `/health`, static assets |

## Oracles exercised

OR-01 (GET writes nothing), OR-11 (no external requests, localhost binding), N8.

## Done when

- `pytest tests/test_dashboard.py -q` green on all three OSes.
- Case 4 fails if any template gains a CDN link.
- `docs/test-reports/TT19/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT19-dashboard-skeleton.mp4`
  recording.
