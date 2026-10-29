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

## Oracles exercised

OR-02 (no status parameter), OR-03 (`outcome`/`block_reason` untouched by update),
OR-08, OR-10 (`project_upsert`), plan §7 (title/description/priority/limit caps).

## Done when

- `pytest tests/test_repository.py -q` green on all three OSes.
- Every validation row in T03's matrix has a case that fails if the rule is removed.
