# Task Breakdown — Tasks Manager MCP

Implement-ready task list derived from [development-plan.md](../development-plan.md)
and [intend.md](../intend.md). One file per task; each file is self-contained.

Verification work packages for these tasks live in
[docs/test-tasks/](../test-tasks/README.md).

## Conventions

- **IDs** — `T01`…`T22` in dependency order (execution order = ID order, except
  where "Depends on" says otherwise).
- **Status** — `pending` → `in_progress` → `done`; `blocked` with a reason if stuck.
  Update the status table in the task file and here when state changes.
- **DoD** — a task is `done` only when its "Done when" section is literally true and
  its tests pass on all CI OSes.
- **One write path (N7)** — no task may add `UPDATE`/`INSERT`/`DELETE` statements to
  any module except `repository.py` and `db.py`. T22 adds a CI lint that enforces this.

## Task list

| ID | Task | Phase | Depends on | Size | Status |
|---|---|---|---|---|---|
| [T01](T01-project-scaffolding.md) | Project scaffolding, CLI skeleton, CI | M0 | — | M | done |
| [T02](T02-database-schema.md) | DB layer: schema, migrations, FTS5 | M0 | T01 | M | done |
| [T03](T03-repository-projects-tasks.md) | Repository: config, projects, task CRUD | M0 | T02 | L | done |
| [T04](T04-mcp-server-core.md) | MCP server: Project + Task tool families | M0 | T03 | M | done |
| [T05](T05-relations-graph.md) | Relations: `task_link`/`task_unlink`/`task_graph` | M1 | T04 | M | done |
| [T06](T06-scheduler-read-side.md) | Scheduler read side: ready/waiting, `task_next` | M1 | T05 | M | pending |
| [T07](T07-lifecycle-transitions.md) | Lifecycle: state machine, leases, transitions | M2 | T04 | L | pending |
| [T08](T08-lease-reaping-concurrency.md) | Lease reaping + concurrency (acceptance B) | M2 | T07 | M | pending |
| [T09](T09-journal.md) | Journal: `journal_add`/`journal_list` | M3 | T04 | S | pending |
| [T10](T10-context.md) | Story context: `context_append` + inheritance | M3 | T04 | S | pending |
| [T11](T11-recall.md) | `recall`: FTS5 + LIKE fallback | M3 | T09 | S | pending |
| [T12](T12-sessions-checkpoints.md) | `session_event`, `checkpoint_save`/`_latest` | M4 | T04 | S | pending |
| [T13](T13-resume.md) | `resume` assembly + budget (acceptance C) | M4 | T08, T09, T12 | M | pending |
| [T14](T14-workflows.md) | Workflow templates + `workflow_prompt` | M4 | T04 | S | pending |
| [T15](T15-mcp-prompts-acceptance-A.md) | MCP prompts + cold-resume (acceptance A) | M4 | T13, T14 | M | pending |
| [T16](T16-git-hooks.md) | Optional git `work-on` hooks | M5 | T07 | S | pending |
| [T17](T17-export.md) | Markdown/EDNL export | M5 | T09 | S | pending |
| [T18](T18-packaging-docs.md) | Packaging (`uvx`/`pipx`) + README | M5 | T15 | S | pending |
| [T19](T19-dashboard-skeleton.md) | Dashboard skeleton: FastAPI app + vendored assets | M6 | T04 | M | pending |
| [T20](T20-dashboard-board.md) | Board UI: columns, cards, swimlanes, waiting | M6 | T19, T06, T08 | L | pending |
| [T21](T21-dashboard-mutations.md) | Board mutations, detail panel, graph, takeover | M6 | T20, T07 | L | pending |
| [T22](T22-acceptance-D-final.md) | Acceptance D + write-path lint + release | M6 | T21 | M | pending |

## Execution order

```
M0: T01 → T02 → T03 → T04
M1: T04 → T05 → T06
M2: T04 → T07 → T08
M3: T04 → T09 → T11       (T10 independent of T09, parallelisable)
M4: T04 → T12 → T13 → T15 ;  T04 → T14 → T15
M5: T07 → T16 ;  T09 → T17 ;  T15 → T18   (all parallelisable)
M6: T04 → T19 → T20 → T21 → T22
```

M5 and M6 may run in parallel once their dependencies are met.

## Final gate

The project is done when acceptance tests A–D (see [T08](T08-lease-reaping-concurrency.md),
[T13](T13-resume.md), [T15](T15-mcp-prompts-acceptance-A.md), [T22](T22-acceptance-D-final.md))
pass in CI on Windows, macOS, and Linux.
