# TT00 — Test infrastructure: fixtures, seeds, markers

| | |
|---|---|
| Suite | — (harness used by every suite) |
| Verifies | plan §4.3 (markers), §5 (fixtures, seeds, determinism) |
| Phase | M0 |
| Depends on | T01 (pytest, ruff, CI), T02 (migrated DB, clock seam) |
| Unblocks | every other TT |
| Level | L1–L4 |
| Size | M |
| Status | pending |

## Goal

Make every later test cheap to write and deterministic to run: one way to get a
migrated database, one way to freeze time, one way to count SQL statements, and
canonical seeds shared by acceptance tests. The harness is itself tested.

## Files

- `tests/conftest.py` — fixtures below.
- `tests/seeds.py` — `seed_mid_task`, `seed_chain6`, `seed_large`, `seed_parity`,
  `seed_board` (shapes in plan §5.2).
- `tests/test_fixtures.py` — harness self-tests.
- `pyproject.toml` — add `[tool.pytest.ini_options]`: `testpaths`, marker
  registration, `addopts = "--timeout=120"` (plan §16 D-9).
- `.github/workflows/ci.yml` — add the optional `test-floor` job (plan §16 D-4);
  only if the Python 3.10 floor is kept.

## Fixtures

| Fixture | Contract |
|---|---|
| `db_path` | path under `tmp_path`, never repo-relative, never under `$HOME` |
| `db` | `Database(db_path)` with `migrate()` applied once |
| `clock` | frozen UTC instant; `advance(minutes)` moves it; patches `task_manager.db.utc_now` |
| `project` | project row created through `project_upsert` |
| `mcp` | connected in-memory MCP client session, closed at teardown |
| `board` | `TestClient` bound to the same `db_path` as `db` |
| `git_repo` | `tmp_path` repo from `git init`; skipped when `git` is unavailable |
| `sql_capture` | proxy connection recording every executed statement with its SQL text |

## Cases

1. `db` fixture yields a migrated database: `user_version == 1`, all 7 tables and
   both FTS tables present; teardown closes connections so `tmp_path` is removable
   on Windows (WAL/SHM files gone).
2. `clock` seam works through the repository: with time frozen, `task_add` stamps
   `created_at` and `updated_at` with exactly the frozen value. This case fails if
   `repository.py` does `from .db import utc_now` instead of `db.utc_now()`
   (plan §5.3).
3. `advance(minutes=60)` moves lease expiry: a 60-minute lease started at `t0` is
   expired after `advance(61)` and unexpired after `advance(59)`.
4. `mcp` fixture round-trips `project_upsert` → `task_add` → `task_query`; the
   session is closed afterwards (no leaked task group).
5. `board` fixture shares state with `db`: a task added through the repository is
   visible on `GET /board` without restarting the app.
6. `sql_capture` distinguishes reads from writes: a repository write records at
   least one `INSERT`/`UPDATE`; `task_get` records none.
7. Each seed builds its documented shape and returns the ids it created:
   `seed_mid_task` (1 leased task, 2 dependents, 1 free priority-1 task),
   `seed_chain6` (6 open tasks, edges intact), `seed_large` (50+ tasks, ≥8 blocked
   with reasons, 2 compactions after the checkpoint, 1 stale task),
   `seed_parity` (two identical projects), `seed_board` (one task per column state).
8. Marker registration: `pytest --markers` lists all markers in plan §4.3, and
   `pytest -m unit --collect-only` selects a non-empty set without warnings.
9. Isolation guard (autouse): every test that constructs a `Database` uses a path
   under `tmp_path`; no test can read or write `~/.tasks_manager/tasks.sqlite`.
10. `pytest-timeout` is active: a deliberately sleeping test in `test_fixtures.py`
    with `timeout=1` fails with a timeout error (proves the plugin is wired).

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_fixtures.py -v` |
| Setup | `python -m pip install -e ".[dev]"` plus `pytest-timeout` |
| Env | `TASKS_DB` unset; `HOME` / `USERPROFILE` redirected into `tmp_path`; `git` on `PATH` for `git_repo` |
| Prereqs | CPython 3.12 on Windows, macOS and Linux; SQLite with FTS5 |

## Test data

- No external data or fixtures on disk: every fixture builds its state under
  `tmp_path`, and nothing may read `~/.tasks_manager/tasks.sqlite`.
- Seeds from `tests/seeds.py`, with the shapes case 7 asserts: `seed_mid_task`
  (1 leased task, 2 dependents, 1 free priority-1 task), `seed_chain6` (6 open
  tasks, edges intact), `seed_large` (50+ tasks, >=8 blocked with reasons,
  2 compactions after the checkpoint, 1 stale task), `seed_parity` (two identical
  projects), `seed_board` (one task per column state).
- Fixed references for the assertions: `user_version = 1`; 7 base tables;
  `task_fts` and `journal_fts`; the frozen instant injected by `clock`
  (compare against `clock.now`, never a wall-clock value); a 60-minute lease.
- Markers to register: `unit`, `integration`, `protocol`, `dashboard`,
  `concurrency`, `acceptance`, `packaging`, `slow`.
- Timeout probe: a deliberately sleeping test marked `slow`, run only through
  `-k timeout_probe` with `timeout=1`.

## How to test

1. `python -m pip install -e ".[dev]"`, then confirm `pytest-timeout` is loaded:
   `python -m pytest --trace-config -q 2>&1 | Select-String pytest_timeout`
   (`grep pytest_timeout` on macOS/Linux).
2. Start the screen recording, then `python -m pytest tests/test_fixtures.py -v`
   with `-m "not slow"` — cases 1–9 must pass and nothing may remain locked.
3. `python -m pytest --markers` — capture the output showing all eight markers
   (case 8).
4. `python -m pytest -m unit --collect-only -q` — non-empty selection and no
   `PytestUnknownMarkWarning`.
5. `python -m pytest tests/test_fixtures.py -k timeout_probe -q` — this run is
   expected to **fail** with `Failed: Timeout >1.0s`; keep the exit code in the
   report as proof the plugin is wired (case 10).
6. Reproduce each seed and save its ids/shape into `attachments/seed-shapes.txt`
   (case 7 evidence).

## Expected results

| Case | Expectation |
|---|---|
| 1 | `db` reports `user_version == 1` with all 7 base tables and both FTS tables; teardown closes connections so `tmp_path` deletes cleanly on Windows (no `-wal`/`-shm` left) |
| 2 | with time frozen, `task_add` stamps `created_at` and `updated_at` with exactly the frozen value; the case fails if `repository.py` binds `utc_now` at import |
| 3 | a 60-minute lease is expired after `advance(61)` and still valid after `advance(59)` |
| 4 | `project_upsert` → `task_add` → `task_query` round-trips through `mcp`, and the session closes without a leaked task group |
| 5 | a task written through the repository is visible on `GET /board` through `board` without restarting the app |
| 6 | a repository write records at least one `INSERT`/`UPDATE` in `sql_capture`; `task_get` records none |
| 7 | every seed returns the documented ids/shape; a missing task, edge, or compaction count fails the case |
| 8 | `pytest --markers` lists all eight markers, and `-m unit` selects at least one test with no unknown-mark warning |
| 9 | any test that constructs a `Database` outside `tmp_path` fails on the autouse isolation guard |
| 10 | the sleep probe fails with a pytest-timeout error, proving the plugin — not a slow machine — ended it |

## Test artifacts

Folder `docs/test-reports/TT00/` — layout, naming and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 10 case rows, embedded screenshots, video link |
| `pytest.log` | `pytest tests/test_fixtures.py -v` plus the `-m unit --collect-only` run |
| `screenshots/01-fixtures-green.png` | the passing summary for cases 1–9 |
| `screenshots/02-markers.png` | `pytest --markers` listing all eight markers |
| `screenshots/03-timeout-probe.png` | the probe failing with `Timeout >1.0s` and exit code 1 |
| `attachments/seed-shapes.txt` | id/status/edge dump for each seed, used to check case 7 |
| `video/TT00-test-infrastructure.mp4` | 30 s–5 min: install check, the fixture run, the marker listing, the timeout probe |

## Oracles exercised

OR-01 (`sql_capture` shape), OR-08 (frozen clock yields `...Z` timestamps).

## Done when

- `pytest tests/test_fixtures.py -q` green on Windows, macOS, and Linux.
- Every later task file in this directory can import its fixtures without adding
  new global machinery.
- No test calls `time.sleep` except the single timeout probe in case 10.
- `docs/test-reports/TT00/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT00-test-infrastructure.mp4`
  recording.
