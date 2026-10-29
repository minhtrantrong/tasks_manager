# TT02 — DB layer: schema, migrations, FTS5

| | |
|---|---|
| Suite | `DB` |
| Verifies | [T02](../tasks/T02-database-schema.md) |
| Phase | M0 |
| Depends on | TT00 |
| Unblocks | TT03 |
| Level | L2 |
| Size | M |
| Status | pending |

## Goal

Prove the schema is exactly the intent's schema, migrations are idempotent and
versioned, pragmas hold on every connection, and FTS5 degrades instead of failing.

## Files

- `tests/test_db.py` — new.

## Cases

1. Fresh file: `migrate()` applies `0001_initial.sql`; `user_version == 1`; the
   7 base tables, 2 FTS tables, and every index from T02 exist.
2. `migrate()` twice is a no-op: same `user_version`, no duplicate objects, no
   error.
3. Pragmas on a fresh connection: `journal_mode == "wal"`, `foreign_keys == 1`,
   `busy_timeout == 5000`, `synchronous == 1` (NORMAL).
4. FK enforcement: a task with a bogus `project_id` raises `IntegrityError`;
   deleting a project that has tasks raises (no cascade on projects).
5. Cascade: deleting a task hard-removes its journal entries, relations, and
   context rows.
6. FTS sync: after INSERT, UPDATE, and DELETE on `tasks`, `SELECT count(*)` on
   `task_fts` equals the task count and a title change is searchable.
7. FTS probe: `fts_enabled()` is True on the test interpreter; with
   `OperationalError("no such module: fts5")` forced for the FTS statements,
   `migrate()` still commits, bumps `user_version`, and `fts_enabled()` is False.
8. CHECK constraints: `status='bogus'`, `type='bogus'`, `kind='bogus'`, and
   `task_id = related_id` all raise `IntegrityError`.
9. `utc_now()` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` and is UTC
   regardless of `TZ` (set `TZ=Asia/Tokyo`, `TZ=America/New_York`).
10. Parent directory creation: constructing a `Database` at `tmp_path/a/b/c.sqlite`
    creates the tree and migrates.
11. Two connections to the same file can read and write sequentially without
    `database is locked` within `busy_timeout`.

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_db.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt02\tasks.sqlite`; `TZ` overridden per case 9 |
| Prereqs | CPython 3.12 with FTS5 in the bundled SQLite (check before running); Windows, macOS, Linux |

## Test data

- `db_path` / `db` fixtures: one fresh, migrated file per test under `tmp_path`.
- Expected objects: 7 base tables (`projects`, `tasks`, `task_relations`, `journal`,
  `task_context`, `session_events`, `checkpoints`), 2 FTS tables (`task_fts`,
  `journal_fts`) and the 8 indexes declared in `0001_initial.sql`.
- Pragma targets: `journal_mode=wal`, `foreign_keys=1`, `busy_timeout=5000`,
  `synchronous=1`.
- Invalid rows for the CHECK matrix: `status='bogus'`, `type='bogus'`,
  `kind='bogus'`, and a relation row with `task_id == related_id`.
- Forced degradation: `OperationalError("no such module: fts5")` for every FTS
  statement during `migrate()`.
- Timezone probes: `TZ=Asia/Tokyo` and `TZ=America/New_York`.
- Nested-path probe: `<tmp_path>/a/b/c.sqlite`.

## How to test

1. Prove the interpreter has FTS5:
   `python -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table t using fts5(x)'); print('fts5 ok')"`.
2. `python -m pytest tests/test_db.py -v` with the recording running — cases 1–11.
3. Dump the migrated schema for evidence:
   `sqlite3 <db> ".schema" > docs/test-reports/TT02/attachments/schema-dump.txt`
   (use the Python fallback from the report notes if the `sqlite3` CLI is absent).
4. Query the four pragmas on a fresh connection and screenshot the result.
5. Re-run the suite once with `-k "fts or trigger"` to show the FTS cases in
   isolation when reviewing the fallback path.

## Expected results

| Case | Expectation |
|---|---|
| 1 | a fresh file migrates to `user_version == 1` with every table and index present; one missing object fails the case |
| 2 | a second `migrate()` is a no-op: same `user_version`, no duplicate objects, no exception |
| 3 | a new connection reports `wal`, `1`, `5000`, `1` for the four pragmas |
| 4 | a bogus `project_id` raises `IntegrityError`; deleting a project that still has tasks also raises |
| 5 | hard-deleting a task leaves zero journal, relation, context and FTS rows behind |
| 6 | `count(task_fts) == count(tasks)` after INSERT, UPDATE and DELETE, and the new title is searchable |
| 7 | with `no such module: fts5` forced, `migrate()` still commits and bumps `user_version`, and `fts_enabled()` is `False` |
| 8 | each of the four invalid rows raises `IntegrityError` |
| 9 | `utc_now()` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` and is identical under both `TZ` values |
| 10 | `<tmp>/a/b/c.sqlite` is created with its parent tree and migrated |
| 11 | two connections alternate reads and writes with no `database is locked` inside `busy_timeout` |

## Test artifacts

Folder `docs/test-reports/TT02/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 11 case rows, embedded screenshots, video link |
| `pytest.log` | full run with the summary line and the FTS probe result |
| `screenshots/01-schema-objects.png` | the schema dump listing the 7 tables, 2 FTS tables and 8 indexes |
| `screenshots/02-pragmas.png` | the four pragma values from a fresh connection |
| `screenshots/03-fts-fallback.png` | case 7 passing with `fts_enabled() is False` |
| `attachments/schema-dump.txt` | `.schema` output of the migrated file |
| `video/TT02-db-layer.mp4` | 30 s–5 min: FTS5 probe, the suite, the schema dump, the pragma query |

## Oracles exercised

OR-08 (timestamp format), plan §7 (`busy_timeout`), N5 (Windows-safe paths).

## Done when

- `pytest tests/test_db.py -q` green on all three OSes.
- No other module contains schema DDL; the write-path lint stays green.
- `docs/test-reports/TT02/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT02-db-layer.mp4`
  recording.
