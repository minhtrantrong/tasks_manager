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

## Oracles exercised

OR-08 (timestamp format), plan §7 (`busy_timeout`), N5 (Windows-safe paths).

## Done when

- `pytest tests/test_db.py -q` green on all three OSes.
- No other module contains schema DDL; the write-path lint stays green.
