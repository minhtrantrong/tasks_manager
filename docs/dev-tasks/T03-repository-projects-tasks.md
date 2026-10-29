# T03 — Repository: config, errors, projects, task CRUD

| | |
|---|---|
| Phase | M0 |
| Depends on | T02 |
| Unblocks | T04 |
| Size | L |
| Status | pending |

## Goal

The first repository slice — the only module allowed to write rows. Implements
config resolution, the typed error set, Pydantic result models, and projects + task
CRUD with all validation.

## Context

This file becomes the N7 chokepoint. Get the signatures and validation matrix right
now; later tasks only add functions.

## Files

- `src/task_manager/errors.py` — replaces stub.
- `src/task_manager/config.py` — replaces stub.
- `src/task_manager/models.py` — new (Pydantic models returned by the repository).
- `src/task_manager/repository.py` — replaces stub.

## errors.py

```python
class TaskManagerError(Exception): pass
class NotFound(TaskManagerError): pass
class ValidationError(TaskManagerError): pass
class IllegalTransition(TaskManagerError): pass   # used from T07
class LeaseConflict(TaskManagerError): pass       # used from T07
class CycleDetected(TaskManagerError): pass       # used from T05
class MissingOutcome(TaskManagerError): pass      # used from T07
class MissingReason(TaskManagerError): pass       # used from T07
class FtsUnavailable(TaskManagerError): pass      # used from T11
```

Define all of them now even though some are first raised by later tasks.

## config.py

Resolution order (first hit wins):

1. `$TASKS_DB` — explicit DB path.
2. `.tasks/config.json` in the current working directory — per-repo override;
   read `{"slug": ..., "root_path": ...}`.
3. `~/.tasks_manager/tasks.sqlite` — the default.

```python
@dataclass
class Config:
    db_path: Path          # resolved as above
    root_path: Path | None # cwd when no config file; config's root_path otherwise
    slug: str | None       # from .tasks/config.json if present

def load_config(cwd: Path | None = None) -> Config
```

`slug`/`root_path` from the config file feed `project_upsert` defaults.

## models.py

Pydantic models, one per aggregate (camelCase JSON aliases so MCP tool output reads
like the intent's payloads):

- `Project(id, slug, name, description, root_path, require_closure, created_at, archived_at)`
- `ProjectSummary(id, slug, name, counts: {open, waiting, blocked, in_progress, done}, archived)`
- `Task(id, project_id, parent_id, seq, title, description, design, type, workflow, status, priority, meta, owner, lease_expires_at, block_reason, outcome, created_at, updated_at, started_at, finished_at)`
- `TaskSummary` — id, title, type, workflow, status, priority, seq, owner, updated_at
- `TaskDetail(Task fields + relations: list[{related_id, kind, target_status}], children: list[TaskSummary], story_context: list[ContextEntry], journal: list[JournalEntry])`
- `JournalEntry` and `ContextEntry` (plain: id, kind/—, body, actor, created_at)
- `Page(items: list[T], total: int, offset: int, limit: int)`

## repository.py — functions and rules

```python
# Projects
def project_upsert(db, slug, name, *, root_path=None, description=None,
                   require_closure=False) -> Project
    # SELECT by slug → update name/root_path if provided and return; else INSERT.
    # Idempotent (N3). Empty slug → ValidationError.

def project_list(db) -> list[ProjectSummary]
    # open = status 'open'; waiting = computed (stub returns 0 until T06; keep the
    # field but fill from scheduler.is_waiting once T06 lands).

def project_archive(db, project_id) -> Project   # set archived_at; NotFound if missing

# Tasks
def task_add(db, project_id, title, *, description=None, design=None, type="task",
             workflow="simple", priority=3, parent_id=None, blocked_by=None,
             prepend=False, meta=None) -> Task
def task_update(db, task_id, *, title=None, description=None, design=None,
                priority=None, workflow=None, parent_id=None, meta=None) -> Task
    # NEVER touches status/owner/lease (those are T07's transitions).
def task_get(db, task_id, *, journal_limit=5, context_limit=10) -> TaskDetail
def task_query(db, project_id=None, *, task_id=None, workflow=None, parent_id=None,
               type=None, status=None, text=None, waiting=None, ready=None,
               limit=20, offset=0) -> Page[TaskSummary]
    # waiting/ready filters are implemented in T06; accept the params now and raise
    # NotImplementedError if passed until T06 lands.
def task_delete(db, task_id, *, hard=False) -> Task
```

Validation matrix (raises `ValidationError` unless stated):

| Field | Rule |
|---|---|
| title | non-empty after strip, ≤ 200 chars |
| description / design | ≤ 4000 chars, may be None |
| type / workflow / status | must be in the schema CHECK lists |
| priority | int 1–5 (1 highest) |
| parent_id | must exist **in the same project** and have `type='story'`; never self |
| blocked_by | list of task ids; each must exist in the same project; handled by `task_link` in T05 — in T03, if non-empty, insert `blocked_by` relations directly with the same same-project/self-link checks |
| meta | JSON object if provided; stored as compact JSON text |

Sequencing: `seq = COALESCE(MAX(seq), 0) + 1` over the project; `prepend=True` →
`MIN(seq) - 1`. Default task ordering everywhere: `priority ASC, seq ASC, id ASC`.

`task_delete`: `hard=False` (default) sets `status='cancelled'`, clears owner/lease,
sets `updated_at`, preserves all history. Allowed from any status. `hard=True`
executes `DELETE FROM tasks WHERE id=?` (cascades via FKs and FTS triggers).

`task_get` return shape: task fields + `relations` (this task → others, and others
→ this task with `blocked_by`), `children`, `story_context` (T10 fills real
inheritance; T03 returns the nearest story's own entries or empty), `journal` (last
`journal_limit`, newest first).

All timestamps via `db.utc_now()`. Every write uses the connection the caller
opened; the repository never opens its own connection (T04 wires the `Database`).

## Tests (`tests/test_repository.py`)

1. `project_upsert` creates then updates the same row (idempotent).
2. Slug collision on a different name updates, never inserts.
3. `task_add` defaults: type `task`, workflow `simple`, priority 3, status `open`.
4. `seq` monotonic; `prepend=True` sorts before earlier tasks.
5. Validation matrix: each invalid input (empty title, priority 0/6, bogus type,
   cross-project parent, parent not a story, self-parent, cross-project `blocked_by`)
   raises `ValidationError`.
6. `task_update` cannot change status (attempt is silently ignored — status is not
   a parameter).
7. `task_query` filters: status, type, workflow, parent, text (LIKE path since FTS
   filtering lands in T06/T11), pagination cap (`limit` never exceeds 50 even if
   caller passes more) and `total` correctness.
8. `task_delete` soft → status `cancelled`, history intact; `hard=True` → rows gone
   (task + relations + journal cascaded).
9. `task_get` returns relations, children, and journal tail correctly.

## Done when

- All functions and rules above implemented; tests green on all CI OSes.
- `repository.py` is the only module (besides `db.py` and migrations) containing
  write SQL.
