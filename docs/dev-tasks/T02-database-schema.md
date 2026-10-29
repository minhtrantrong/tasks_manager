# T02 — DB layer: schema, migration runner, FTS5

| | |
|---|---|
| Phase | M0 |
| Depends on | T01 |
| Unblocks | T03 |
| Size | M |
| Status | pending |

## Goal

The full intend.md §6 schema in a versioned migration, a connection factory with the
required pragmas, and a graceful FTS5 capability probe.

## Context

This is the only task that owns `*.sql`. Later tasks must not hand-edit schema —
they add migrations instead. FTS5 is probed (not assumed) so `recall` can degrade on
builds without it (N5).

## Files

- `src/task_manager/migrations/0001_initial.sql` — the entire schema below, verbatim.
- `src/task_manager/db.py` — replaces the T01 stub.

## Schema (goes into 0001_initial.sql)

All seven tables + indexes from intend.md §6, exactly as specified:

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE projects(
  id            INTEGER PRIMARY KEY,
  slug          TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  description   TEXT,
  root_path     TEXT,
  require_closure INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  archived_at   TEXT
);

CREATE TABLE tasks(
  id            INTEGER PRIMARY KEY,
  project_id    INTEGER NOT NULL REFERENCES projects(id),
  parent_id     INTEGER REFERENCES tasks(id),
  seq           REAL NOT NULL,
  title         TEXT NOT NULL,
  description   TEXT,
  design        TEXT,
  type          TEXT NOT NULL DEFAULT 'task'
                CHECK (type IN ('task','bug','feature','story','chore')),
  workflow      TEXT NOT NULL DEFAULT 'simple',
  status        TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','in_progress','blocked','done','closed','cancelled')),
  priority      INTEGER NOT NULL DEFAULT 3,
  meta          TEXT NOT NULL DEFAULT '{}',
  owner         TEXT,
  lease_expires_at TEXT,
  block_reason  TEXT,
  outcome       TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  started_at    TEXT,
  finished_at   TEXT
);

CREATE TABLE task_relations(
  task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  related_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL
                CHECK (kind IN ('blocked_by','related','discovered_during')),
  PRIMARY KEY (task_id, related_id, kind),
  CHECK (task_id <> related_id)
);

CREATE TABLE journal(
  id            INTEGER PRIMARY KEY,
  task_id       INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
  project_id    INTEGER NOT NULL REFERENCES projects(id),
  kind          TEXT NOT NULL
                CHECK (kind IN ('note','decision','attempt','problem','result')),
  body          TEXT NOT NULL,
  actor         TEXT,
  session_ref   TEXT,
  created_at    TEXT NOT NULL
);

CREATE TABLE task_context(
  id            INTEGER PRIMARY KEY,
  task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  body          TEXT NOT NULL,
  actor         TEXT,
  created_at    TEXT NOT NULL
);

CREATE TABLE session_events(
  id            INTEGER PRIMARY KEY,
  project_id    INTEGER NOT NULL REFERENCES projects(id),
  task_id       INTEGER REFERENCES tasks(id),
  kind          TEXT NOT NULL
                CHECK (kind IN ('session_start','compaction','prompt','task_switch')),
  detail        TEXT,
  created_at    TEXT NOT NULL
);

CREATE TABLE checkpoints(
  id            INTEGER PRIMARY KEY,
  project_id    INTEGER NOT NULL REFERENCES projects(id),
  task_id       INTEGER REFERENCES tasks(id),
  summary       TEXT NOT NULL,
  next_actions  TEXT,
  created_at    TEXT NOT NULL
);

CREATE INDEX idx_tasks_board       ON tasks(project_id, status, priority, seq);
CREATE INDEX idx_tasks_parent      ON tasks(parent_id);
CREATE INDEX idx_tasks_lease       ON tasks(owner, lease_expires_at);
CREATE INDEX idx_journal_task      ON journal(task_id, id);
CREATE INDEX idx_journal_project   ON journal(project_id, id);
CREATE INDEX idx_relations_target  ON task_relations(related_id, kind);
CREATE INDEX idx_session_events    ON session_events(project_id, id);
CREATE INDEX idx_checkpoints       ON checkpoints(project_id, task_id, id);
```

(`idx_journal_project` and `idx_checkpoints` are additions for project-level notes
and latest-checkpoint lookups; everything else matches intend.md §6.)

FTS5, appended at the end of the same file:

```sql
CREATE VIRTUAL TABLE task_fts USING fts5(title, description, content='tasks', content_rowid='id');
CREATE TRIGGER tasks_ai AFTER INSERT ON tasks BEGIN
  INSERT INTO task_fts(rowid, title, description) VALUES (new.id, new.title, new.description);
END;
CREATE TRIGGER tasks_ad AFTER DELETE ON tasks BEGIN
  INSERT INTO task_fts(task_fts, rowid, title, description) VALUES ('delete', old.id, old.title, old.description);
END;
CREATE TRIGGER tasks_au AFTER UPDATE ON tasks BEGIN
  INSERT INTO task_fts(task_fts, rowid, title, description) VALUES ('delete', old.id, old.title, old.description);
  INSERT INTO task_fts(rowid, title, description) VALUES (new.id, new.title, new.description);
END;

CREATE VIRTUAL TABLE journal_fts USING fts5(body, content='journal', content_rowid='id');
CREATE TRIGGER journal_ai AFTER INSERT ON journal BEGIN
  INSERT INTO journal_fts(rowid, body) VALUES (new.id, new.body);
END;
CREATE TRIGGER journal_ad AFTER DELETE ON journal BEGIN
  INSERT INTO journal_fts(journal_fts, rowid, body) VALUES ('delete', old.id, old.body);
END;
```

(External-content FTS5 means the repository inserts normally; triggers keep FTS in
sync. Journal bodies are never updated — append-only — so no `journal_au` trigger.)

## db.py contract

```python
def utc_now() -> str                       # datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

class Database:
    def __init__(self, path: Path): ...
    def connect(self) -> sqlite3.Connection
        # PRAGMA journal_mode=WAL; foreign_keys=ON; busy_timeout=5000; synchronous=NORMAL
        # row_factory = sqlite3.Row; ensure parent dir exists (mkdir parents)
    def migrate(self) -> None
        # PRAGMA user_version based: execute migrations/NNNN_*.sql with N > current
        # version, in order, inside one transaction each; bump user_version after each.
    def fts_enabled(self, conn: sqlite3.Connection | None = None) -> bool
        # True iff 'task_fts' exists in sqlite_master
```

Migration runner details:
- Load SQL files with `importlib.resources` (package data), sorted by filename.
- If an FTS5 `CREATE VIRTUAL TABLE` statement raises `sqlite3.OperationalError`
  (e.g. `no such module: fts5`), log a warning, **skip the FTS statements**, and
  still commit the migration + bump `user_version`. The server must start without
  FTS (N5); `fts_enabled()` then returns False and `recall` (T11) degrades to LIKE.
  Implement by executing each statement separately and catching that one error only
  for statements containing `fts5`.

## Tests (`tests/test_db.py`)

1. Fresh DB in `tmp_path`: `migrate()` runs, `user_version` = 1, all 7 tables + 2
   FTS tables + indexes exist.
2. `migrate()` twice is a no-op (idempotent).
3. Pragmas verified: `journal_mode` WAL, `foreign_keys` 1.
4. FK enforcement: inserting a task with a bogus `project_id` raises
   `sqlite3.IntegrityError`; deleting a project with tasks raises (no cascade on
   projects).
5. Cascade: deleting a task hard-removes its journal + relations + context rows.
6. FTS sync: after INSERT/UPDATE/DELETE on `tasks`, `task_fts` rows match
   (`SELECT count(*) FROM task_fts` equals task count).
7. `fts_enabled()` True on this Python (3.12 stdlib ships FTS5); the skip path is
   covered by monkeypatching to raise `OperationalError` and asserting the server
   still migrates and `fts_enabled()` is False.
8. CHECK constraints: `status='bogus'` and `kind='bogus'` inserts raise
   `IntegrityError`.

## Done when

- Schema, indexes, and FTS5 land verbatim and all tests above pass on all CI OSes.
- No other module has touched SQL; `repository.py` remains a stub (T03 fills it).
