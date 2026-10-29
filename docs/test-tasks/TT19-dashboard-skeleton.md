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

## Oracles exercised

OR-01 (GET writes nothing), OR-11 (no external requests, localhost binding), N8.

## Done when

- `pytest tests/test_dashboard.py -q` green on all three OSes.
- Case 4 fails if any template gains a CDN link.
