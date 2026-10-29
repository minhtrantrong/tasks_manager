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
