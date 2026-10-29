# Tasks Manager MCP

A local-first MCP server that gives agents a **durable, dependency-aware task
graph plus a reasoning journal** — so a fresh agent can resume long-running work
in one cheap call instead of re-deriving it — with a **kanban dashboard** that
lets a human see and steer exactly the same state.

Coding agents are good at single-session work and bad at multi-day work: the plan
lives in chat, the context window gets compacted, and the next session starts by
re-deriving what the previous one already knew. `task-manager` fixes the two
things a plain todo list cannot: **structure** (a real dependency DAG, so "what
can I do now?" is a query) and **reasoning** (a per-task journal that records what
was tried and why it failed).

Everything lives in one SQLite file. No network calls, no daemon, no build step.

---

## Install

Requires **Python ≥ 3.10**. FTS5 ships with modern CPython's SQLite, so there is
nothing else to install.

```bash
pipx install .            # isolated CLI install
# or
uvx --from . task-manager # run without installing
```

Optional, for the dashboard only:

```bash
pipx install ".[dashboard]"   # adds fastapi + jinja2 + uvicorn
```

Verify the install:

```bash
task-manager --help
python -m task_manager --help
```

## Quick start

Start the server (stdio transport, the normal MCP mode):

```bash
task-manager serve
```

Then, from any MCP client, drive the graph:

```jsonc
// 1. create or fetch a project
{"tool": "project_upsert", "arguments": {"slug": "demo", "name": "Demo"}}

// 2. add tasks
{"tool": "task_add", "arguments": {"project_id": 1, "title": "Write the parser"}}
{"tool": "task_add", "arguments": {"project_id": 1, "title": "Add tests", "priority": 1}}

// 3. link them: task 2 is blocked by task 1
{"tool": "task_link", "arguments": {"task_id": 2, "related_id": 1, "kind": "blocked_by"}}

// 4. what can I do now?
{"tool": "task_next", "arguments": {"project_id": 1}}
// -> task 1

// 5. claim it (takes a lease), then record reasoning as you go
{"tool": "task_start", "arguments": {"task_id": 1, "actor": "agent-7"}}
{"tool": "journal_add", "arguments": {"task_id": 1, "kind": "attempt", "body": "grammar-first parse works, but fails on nested generics"}}
{"tool": "task_complete", "arguments": {"task_id": 1, "actor": "agent-7", "outcome": "parser handles nested generics; verified with pytest -q tests/test_parser.py"}}
```

The same tools are available over the raw JSON-RPC stdio transport
(`initialize` -> `tools/list` -> `tools/call`) if you are not using an SDK.

## MCP client configuration

VS Code / Claude Desktop style configuration:

```json
{
  "mcpServers": {
    "task-manager": {
      "command": "task-manager",
      "args": ["serve"]
    }
  }
}
```

On Windows, if `task-manager` is not on `PATH`, point `command` at the console
script inside your environment, or use
`{"command": "python", "args": ["-m", "task_manager", "serve"]}`.

## Storage

One SQLite file, WAL mode, `PRAGMA foreign_keys=ON`. Resolution order for the
database path:

1. `$TASKS_DB` environment variable
2. `db_path` in `.tasks/config.json` (per repository)
3. `~/.tasks_manager/tasks.sqlite` (the default, long-lived memory)

`.tasks/config.json` also carries the project identity and optional hooks:

```json
{
  "slug": "my-project",
  "root_path": ".",
  "hooks": { "enabled": false, "worktree": false, "commit_on_complete": false }
}
```

Timestamps are UTC ISO-8601 strings; every row is readable with plain `sqlite3`.

## Workflows

A workflow is a Markdown prompt template, not code. Four ship built in:

| Workflow | Default lease | Purpose |
|---|---|---|
| `simple` | 30 min | A single-session change. The default. |
| `bugfix` | 60 min | Reproduce -> fix -> verify. |
| `feature` | 90 min | Design -> implement -> test -> document. |
| `spike` | 120 min | Time-boxed exploration with a written finding. |

A template is frontmatter plus a prompt body:

```markdown
---
name: feature
description: Ship a feature end-to-end with tests
lease_minutes: 90
---
You are working on task {title} (#{id}) in project {project}.
...
```

Resolution order is **project override -> built-in**:
`.tasks/workflows/<name>.md` inside the project's `root_path` wins over the
packaged template. Agents may author project-level templates on the filesystem
(there is deliberately no tool that writes them, so templates stay reviewable
like any other file). `task_start` uses the workflow's `lease_minutes` when the
caller does not pass one explicitly; `workflow_prompt` returns the resolved
template so the server stays the single source of workflow truth.

## Git hooks (optional)

Off by default — git is never a premise. Enable them in `.tasks/config.json`:

```json
{ "hooks": { "enabled": true, "worktree": true, "commit_on_complete": true } }
```

* `enabled` — `task_start` creates/switches to the branch `<id>-<first four title words>`.
* `worktree` — use `git worktree add` at `.tasks/worktrees/<id>` instead of
  switching the main checkout.
* `commit_on_complete` — `task_complete` stages and commits a dirty tree with
  `task-manager: complete task #<id> — <title>`.

Hooks run after the transition commits and never fail it: a non-git directory, a
missing `git`, or a failing command only adds a `hook warning` journal note and a
logged warning. No shell is involved, so task titles cannot inject commands.

## Dashboard

```bash
task-manager dashboard            # http://127.0.0.1:8765/board
```

The board shows exactly the MCP state: the five real status columns
(`open`, `in_progress`, `blocked`, `done`, `closed`), cards with id, title,
priority, workflow, owner, lease countdown and the last journal line, computed
`⧗ waits #n` badges (never a `waiting` column), swimlanes by workflow or parent
story, a task detail panel with the journal timeline, and a read-only graph view.
Drag-to-transition calls the same repository functions as the MCP tools, so an
illegal drop is refused with the server's own reason. Taking a card away from an
agent requires the explicit *take over lease* action.

It binds `127.0.0.1` by default, has no auth, and loads only vendored assets — no
CDN, no telemetry, no external requests. Use `--host` with `--allow-external`
only if you really mean to expose it.

## Agent rituals

Three MCP **prompts** ship with the server. Their presence is what turns tools
into a protocol:

* **`start-session`** — record `session_event(session_start)`, call `resume`, and
  either continue the claimed task (read its journal tail first, do not restart
  it) or claim the next ready task. Never open a new task while a claimed one is
  unfinished, unless it is blocked.
* **`compaction`** — record `session_event(compaction)` immediately. On the
  second compaction since the last checkpoint, stop and either save a checkpoint
  or split the task, then journal the state before continuing.
* **`end-session`** — complete what is finished (with an outcome), block what is
  stuck (with a reason), save a checkpoint with concrete `next_actions`, and
  release any lease you are not keeping.

## Rules agents must follow

* Add one task per unit of work a single session can finish; split instead of
  growing a mega-task.
* `waiting_on` is computed from `blocked_by` — never fake it with `blocked`.
  `blocked` means an *external* factor and requires a reason.
* `done` requires an outcome: what changed and how it was verified.
* Journal as you go: a `decision` when choosing an approach, an `attempt` after a
  failed try (with the error and why), a `problem` when stuck. Keep entries to a
  few lines.
* Facts a sibling task needs go to `context_append`, which is a budget
  (≤ 400 chars, 20 entries per story), not a transcript.
* The journal is append-only: never edit or delete an entry; the schema has no
  path for it.
* Store no secrets in journal or context bodies.
* Never fix state by editing SQLite rows; every write goes through the tools (or
  the board, which calls the same functions).

## Development

```bash
pip install -e ".[dev,dashboard]"
ruff check src tests
pytest -q
```

The four acceptance gates:

```bash
pytest -q -k "cold_resume or no_double_work or bounded_memory or one_write_path"
```

Task breakdown lives in [docs/dev-tasks/](docs/dev-tasks/README.md); the intent
that drives it is [docs/intend.md](docs/intend.md).

## Release notes — v0.1.0

The first complete cut: task graph with typed relations and cycle rejection,
leases with reaping, an append-only journal, story context, FTS-backed `recall`
(with LIKE fallback), checkpoints and the bounded `resume` briefing, workflow
templates, the MCP prompt rituals, optional git hooks, Markdown/EDNL export, and
the offline kanban dashboard.

