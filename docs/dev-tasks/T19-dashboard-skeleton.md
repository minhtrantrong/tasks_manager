# T19 — Dashboard skeleton: FastAPI app + vendored assets

| | |
|---|---|
| Phase | M6 |
| Depends on | T04 |
| Unblocks | T20 |
| Size | M |
| Status | done |

## Goal

The opt-in HTTP mode exists: same process, same repository, `127.0.0.1`, zero
external requests (intend §8, N8).

## Files

- `src/task_manager/dashboard/__init__.py`
- `src/task_manager/dashboard/app.py` — FastAPI app factory.
- `src/task_manager/dashboard/templates/base.html` + `board.html` (stub columns).
- `src/task_manager/dashboard/static/app.css` + `static/htmx.min.js` (vendored).
- `src/task_manager/cli.py` — implement `dashboard` (replace T01 stub).
- `tests/test_dashboard.py` — new.

## app.py contract

```python
def create_app(db_path: Path) -> FastAPI
```

- `FastAPI(title="task-manager dashboard")`; the DB is opened per request via the
  same `Database` from `db.py` — **no new data-access code**.
- Routes (v1 skeleton):
  - `GET /` → redirect to `/board`;
  - `GET /board` → renders `board.html` with real columns (stub content for now:
    each status column exists, cards rendered by T20);
  - `GET /health` → `{"ok": true}`;
  - `StaticFiles` mount at `/static` from `dashboard/static`.
- Runs with `uvicorn`, host `127.0.0.1`, default port `8765`.
- The stdio `serve` subcommand is untouched and must keep working.

## Vendored assets (N8)

- Download **htmx 2.0.x minified** once, commit the file to
  `static/htmx.min.js`, and record the version in a `static/VENDORED.md`
  (`asset: htmx, version: 2.0.x, license: BSD-0-Clause, source: <url for auditing
  only>`). No build step, no CDN.
- `base.html` references only `/static/...` paths and uses
  `hx-boost`/polling attributes needed by T20.

## cli.py `dashboard` subcommand

`task-manager dashboard [--host 127.0.0.1] [--port 8765]` — resolve `Config.db_path`
(T03), `migrate()`, then `uvicorn.run(create_app(db_path), host, port)`. Never
binds anything but loopback by default; refuse `--host` values that aren't
loopback unless `--allow-external` is explicitly passed.

## Tests (`tests/test_dashboard.py`)

1. `TestClient` (httpx): `/` redirects, `/board` 200 and contains five status
   column headings (`open`, `in_progress`, `blocked`, `done`, `closed`), `/health`
   ok.
2. Static assets served with 200 (`/static/htmx.min.js`, `/static/app.css`).
3. `GET /board` with a seeded DB shows one seeded task under its column (basic
   smoke before T20's full rendering).
4. **No external URLs:** scan all files under `dashboard/templates` and
   `dashboard/static` (excluding `VENDORED.md`) for `https?://` — assert none
   (N8). This test is the CI guardrail against CDN drift.
5. Board rendering performs reads only: capture SQL executed during `GET /board`
   (wrap the connection) and assert no `INSERT/UPDATE/DELETE` statements run.

## Done when

- `task-manager dashboard` serves a board skeleton over localhost with vendored
  assets and no external requests; `serve` still works.
- Tests green on all CI OSes.
