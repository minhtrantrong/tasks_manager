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

## Oracles exercised

OR-01 (`sql_capture` shape), OR-08 (frozen clock yields `...Z` timestamps).

## Done when

- `pytest tests/test_fixtures.py -q` green on Windows, macOS, and Linux.
- Every later task file in this directory can import its fixtures without adding
  new global machinery.
- No test calls `time.sleep` except the single timeout probe in case 10.
