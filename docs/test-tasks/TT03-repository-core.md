# TT03 — Repository: config, projects, task CRUD

| | |
|---|---|
| Suite | `REP` |
| Verifies | [T03](../tasks/T03-repository-projects-tasks.md) |
| Phase | M0 |
| Depends on | TT00, TT02 |
| Unblocks | TT04 |
| Level | L1 (config) + L2 (repository) |
| Size | L |
| Status | pending |

## Goal

Prove the N7 chokepoint behaves: config resolves in the documented order, every
input rule rejects with `ValidationError`, sequencing is stable, and soft/hard delete
preserve or purge history exactly as specified.

## Files

- `tests/test_repository.py` — new.

## Cases

### Config resolution (`L1`)

1. `$TASKS_DB` wins over `.tasks/config.json` and over the default path.
2. `.tasks/config.json` in the cwd wins over the default; `slug` and `root_path`
   are read from it.
3. With neither, the default is `~/.tasks_manager/tasks.sqlite` and `root_path`
   is the cwd (monkeypatched `HOME`/`USERPROFILE`).
4. Identity across cwds (plan §11.2 Q1): the same config file read from the repo
   root and from a nested directory yields one project slug and one `project_upsert`
   row.
5. Malformed config JSON raises a typed error naming the file, not a bare
   `JSONDecodeError`.

### Projects (`L2`)

6. `project_upsert` creates, then updates the same row on a second call with a new
   name — one row, same id (N3).
7. `project_list` counts match seeded state; `project_archive` sets `archived_at`
   and is `NotFound` for a bogus id.

### Tasks (`L2`)

8. `task_add` defaults: `type='task'`, `workflow='simple'`, `priority=3`,
   `status='open'`; `meta` stored as compact JSON; timestamps from the frozen clock.
9. `seq` is monotonic per project; `prepend=True` sorts before the existing first
   task; default ordering is `priority ASC, seq ASC, id ASC`.
10. Validation matrix, one case each: blank title, 200-char title accepted /
    201 rejected, `description` 4000 accepted / 4001 rejected, priority 0 and 6,
    bogus `type`, bogus `workflow`, cross-project parent, parent that is not a
    story, self-parent, cross-project `blocked_by`, self in `blocked_by`.
11. `task_update` patches only the fields given; it cannot change `status`, `owner`,
    `lease_expires_at`, `outcome`, or `block_reason` (no such parameters exist);
    `updated_at` advances while `created_at` does not.
12. `task_query` filters: status, type, workflow, parent, task id, and text (LIKE
    path); `total` is the unpaged count; `offset` paging has no gaps or duplicates;
    `limit=1000` returns at most 50 (plan §7).
13. `task_get` returns relations in both directions, children, nearest story
    context (or `[]`), and the last `journal_limit` entries newest-first.
14. `task_delete(hard=False)` sets `cancelled`, clears owner/lease, keeps journal
    and relations; `hard=True` removes the task and cascades journal, relations,
    context, and FTS rows.
15. An unknown id raises `NotFound`; a validation failure leaves no partial row.

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser; config cases drive the process cwd |
| Command | `python -m pytest tests/test_repository.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | each config case sets its own `TASKS_DB` / `HOME` / `USERPROFILE` inside `monkeypatch` |
| Prereqs | CPython 3.12; a writable `tmp_path`; no network |

## Test data

- `.tasks/config.json` success case:
  `{"db_path": ".tasks/tasks.sqlite", "slug": "demo", "root_path": "."}`
- Malformed config for case 5: `{"slug": "demo",` (unterminated object).
- Conflict case: `TASKS_DB=<tmp>/env.sqlite` plus the config file above — the env
  path must win.
- Length boundaries: title `"x" * 200` (accepted) / `"x" * 201` (rejected);
  description `"d" * 4000` / `"d" * 4001`; `limit=1000` returning at most 50.
- Enum boundaries: `priority` `0` and `6` rejected, `1` and `5` accepted; bogus
  `type` and `workflow` names.
- Graph boundaries: cross-project parent, parent that is a `task` not a `story`,
  self-parent, cross-project `blocked_by`, self in `blocked_by`, bogus id `9999`.
- Ordering fixture: three tasks with priorities 2/1/1 and increasing `seq`, plus one
  `prepend=True` task.
- Frozen clock for `created_at` / `updated_at` assertions.

## How to test

1. `python -m pytest tests/test_repository.py -v` with the recorder running.
2. Run the config group alone to show cwd handling:
   `python -m pytest tests/test_repository.py -v -k "config or identity"`.
3. Run the validation matrix alone and screenshot the failing cases' ids:
   `python -m pytest tests/test_repository.py -v -k "validation or boundary"`.
4. Re-run with `-k "ordering or query"` to capture the `seq`/paging behaviour.
5. Copy the generated validation table from the test parameter ids into
   `attachments/validation-matrix.csv` so a reviewer can check coverage against
   T03's matrix row by row.

## Expected results

| Case | Expectation |
|---|---|
| 1–3 | `$TASKS_DB` wins over `.tasks/config.json` and the default; the config file wins over the default and supplies `slug` / `root_path`; with neither, the default is `~/.tasks_manager/tasks.sqlite` and `root_path` is the cwd |
| 4 | the same config read from the repo root and from a nested directory yields one slug and one `project_upsert` row |
| 5 | malformed JSON raises a typed `ValidationError` that names the file, never a bare `JSONDecodeError` |
| 6 | two `project_upsert` calls with a changed name leave one row with the same id |
| 7 | `project_list` counts match the seed; `project_archive` sets `archived_at` and raises `NotFound` for a bogus id |
| 8 | `task_add` defaults are `type='task'`, `workflow='simple'`, `priority=3`, `status='open'`; `meta` is compact JSON; timestamps come from the frozen clock |
| 9 | `seq` increases per project; `prepend=True` sorts first; default order is `priority ASC, seq ASC, id ASC` |
| 10 | every validation row rejects with `ValidationError` and the two limit values behave exactly at the boundary (200/4000/priority 1–5 accepted; 201/4001/0/6 rejected) |
| 11 | `task_update` changes only the supplied fields, cannot change `status`/`owner`/`lease_expires_at`/`outcome`/`block_reason`, and advances `updated_at` only |
| 12 | every filter returns the expected ids; `total` is the unpaged count; `offset` paging has no gaps or duplicates; `limit=1000` yields at most 50 |
| 13 | `task_get` returns relations in both directions, children, nearest story context (or `[]`), and `journal_limit` entries newest-first |
| 14 | soft delete sets `cancelled` and keeps journal/relations; hard delete removes the task and cascades journal, relations, context and FTS rows |
| 15 | an unknown id raises `NotFound`; a failed validation leaves no partial row |

## Test artifacts

Folder `docs/test-reports/TT03/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 15 case rows (grouped 1–3), embedded screenshots, video link |
| `pytest.log` | full run plus the three targeted `-k` runs |
| `screenshots/01-config-precedence.png` | the config group passing with the env-var case named |
| `screenshots/02-validation-matrix.png` | the 14-row validation matrix collected (`--collect-only -q -k validation`) |
| `screenshots/03-ordering-paging.png` | the ordering/query group passing |
| `attachments/validation-matrix.csv` | one row per input rule with limit / limit+1 |
| `video/TT03-repository-core.mp4` | 30 s–5 min: suite, config group, validation matrix, ordering group |

## Oracles exercised

OR-02 (no status parameter), OR-03 (`outcome`/`block_reason` untouched by update),
OR-08, OR-10 (`project_upsert`), plan §7 (title/description/priority/limit caps).

## Done when

- `pytest tests/test_repository.py -q` green on all three OSes.
- Every validation row in T03's matrix has a case that fails if the rule is removed.
- `docs/test-reports/TT03/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT03-repository-core.mp4`
  recording.
