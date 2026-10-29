# Tasks Manager MCP — Intent

| | |
|---|---|
| **Status** | Draft for review (rev 3) |
| **Last updated** | 2026-10-29 |
| **Target stack** | Python (official MCP SDK / FastMCP), SQLite, local web dashboard |
| **Repo** | `minhtrantrong/tasks_manager` |

---

## 1. Problem

Coding agents are amnesiac by construction. A context window is a scratchpad that gets
summarised, truncated, or thrown away when the session ends. So every agent ends up
reinventing the same fragile workflow:

* a `todos` table that lives and dies with the session,
* a plan written in chat that nobody reads next time,
* "where was I?" reconstruction at the start of every session,
* duplicated work because *"have we already tried this?"* has no answer.

The result is that agents are good at **single-session** tasks and bad at
**multi-day** ones. Anything that spans more than one context window (a refactor,
a migration, a long bug hunt, a research thread) degrades into repeating work and
silently dropping threads.

**The gap is not planning. It is durable memory of work in progress.**

This gap is *partly* solved already: persistent task queues plus category-specific
execution prompts demonstrably improve agent output across sessions. What that
approach does **not** preserve is the *reasoning* of unfinished work — and that is
where `task-manager` aims.

What an agent needs that a human tracker does not provide: a *small, local, fast,
opinionated* work-state store with an API designed for machine consumption — not
Jira's HTML-shaped, network-bound, token-expensive model.

## 2. Intent (one line)

> A local-first MCP server that gives agents a **durable, dependency-aware task graph
> plus a reasoning journal** — so a fresh agent can resume long-running work in one
> cheap call instead of re-deriving it — with a **kanban dashboard** that lets a human
> see and steer exactly the same state.

## 3. Who this is for

| User | Need |
|---|---|
| **Single long-running agent** (main case) | Pick up work tomorrow exactly where it left off |
| **Agent + human pair** | Human steers the plan from the kanban board (§8); agent executes and records progress |
| **Multiple agents on one project** | No two agents claim the same task; no lost updates |
| **Agent author / evaluator** | Inspect *why* a task is blocked, not just that it is |

## 4. Core insight

Two things are missing from a plain task list, and both are why tasks get abandoned:

1. **Structure** — a real dependency DAG, so "what can I do *now*?" is a query, not
   an inference. Ordering in a list is not a dependency.
2. **Reasoning** — a per-task journal of decisions, dead ends, and next steps.
   Status alone says `in_progress`; the journal says *"I already tried approach A,
   it fails because X, try B next."* That single sentence is worth more than the
   entire status field, and it is what makes resumption cheap.

`task-manager` takes insight (1) as its foundation and solves continuity through
**detailed task specifications** — if the spec is complete, a fresh agent can execute
it. On top of that it adds insight (2): continuity through **work-state memory**, for
tasks whose correct next step is only discoverable by doing the work.

---

## 5. Core concepts

```
Project ──┬── Task ──┬── JournalEntry    (append-only reasoning log)
          │          ├── ContextEntry    (facts passed to child tasks)
          │          ├── Relation ──> Task   (:blocked-by | :related | :discovered-during)
          │          └── SessionEvent   (start | compaction | prompt | switch)
          └── Checkpoint                  (point-in-time handoff summary)
```

| Concept | Definition |
|---|---|
| **Project** | Namespace + config for one body of work. Usually derived from a slug or cwd. |
| **Task** | A unit of work an agent can finish in one session without compaction. |
| **Workflow** | Named execution playbook (`simple`, `bugfix`, `feature`, `spike`…), realised as a prompt template. Data, not code. |
| **Story** | A task with `type='story'` whose children carry the actual work. |
| **Relation** | Typed edge between tasks. `blocked_by` is scheduling-relevant; the rest are provenance. |
| **JournalEntry** | Append-only record on a task: `note`, `decision`, `attempt`, `problem`, `result`. Never edited. |
| **ContextEntry** | A fact deliberately propagated from a parent story to its children. Short, curated, capped. |
| **SessionEvent** | `session_start`, `compaction`, `prompt`, `switch` — recorded against the active task. |
| **Checkpoint** | A short handoff snapshot for a project or task at a moment in time. |
| **Claim (lease)** | Time-bounded ownership of an in-progress task by an agent. Expires so work never stays stuck. |

### Task lifecycle

```
         task_start                 task_complete
  open ─────────────> in_progress ───────────────> done ──task_close──> closed
   ^                      │                          │
   │      task_release    │  task_block(reason)      └── task_reopen ──> in_progress
   └──────────────────────┤
                   blocked ──task_unblock──> open
```

* **`blocked` means an external factor** (missing decision, credential, dependency
  outside the graph) and **requires a reason**, which is also journalled.
* **`waiting_on` is not a status** — it is a computed flag: a task is *waiting* when
  any `blocked_by` relation points at a task that is not `done`/`closed`/`cancelled`.
  A task can be `open` and waiting at the same time. Conflating these two is the
  mistake to design out.
* **`done` requires an outcome** (1–3 sentences: what changed, how it was verified).
* **`done` vs `closed`** — `done` unblocks dependents; `closed` means accepted (merged,
  reviewed). `closed` is optional per project (`require_closure`, default `false`) so a
  solo agent is not burdened, while a human-review workflow gets the extra gate.
* Terminal: `closed`, `cancelled`. Deletion is soft (`cancelled`) by default.

## 6. Data model (SQLite)

One file, WAL mode, `PRAGMA foreign_keys=ON`. All timestamps are UTC ISO-8601 text.

```sql
projects(
  id            INTEGER PRIMARY KEY,
  slug          TEXT NOT NULL UNIQUE,
  name          TEXT NOT NULL,
  description   TEXT,
  root_path     TEXT,
  require_closure INTEGER NOT NULL DEFAULT 0,   -- two-stage done/closed?
  created_at    TEXT NOT NULL,
  archived_at   TEXT
)

tasks(
  id            INTEGER PRIMARY KEY,
  project_id    INTEGER NOT NULL REFERENCES projects(id),
  parent_id     INTEGER REFERENCES tasks(id),   -- story children
  seq           REAL NOT NULL,                  -- explicit queue order (sparse floats)
  title         TEXT NOT NULL,
  description   TEXT,                           -- the spec / acceptance criteria
  design        TEXT,                           -- approach notes, kept out of the spec
  type          TEXT NOT NULL DEFAULT 'task'
                CHECK (type IN ('task','bug','feature','story','chore')),
  workflow      TEXT NOT NULL DEFAULT 'simple', -- selects a prompt template
  status        TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','in_progress','blocked','done','closed','cancelled')),
  priority      INTEGER NOT NULL DEFAULT 3,     -- 1 highest .. 5 lowest
  meta          TEXT NOT NULL DEFAULT '{}',     -- JSON escape hatch, no migrations
  owner         TEXT,                           -- lease holder
  lease_expires_at TEXT,
  block_reason  TEXT,                           -- required iff status='blocked'
  outcome       TEXT,                           -- required iff status='done' or 'closed'
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  started_at    TEXT,
  finished_at   TEXT
)

task_relations(
  task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  related_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL
                CHECK (kind IN ('blocked_by','related','discovered_during')),
  PRIMARY KEY (task_id, related_id, kind),
  CHECK (task_id <> related_id)
)

journal(
  id            INTEGER PRIMARY KEY,
  task_id       INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
  project_id    INTEGER NOT NULL REFERENCES projects(id),  -- project-level notes allowed
  kind          TEXT NOT NULL
                CHECK (kind IN ('note','decision','attempt','problem','result')),
  body          TEXT NOT NULL,                  -- target <= 6 lines
  actor         TEXT,
  session_ref   TEXT,
  created_at    TEXT NOT NULL
)

task_context(                                   -- replaces a 50 KB shared-context blob
  id            INTEGER PRIMARY KEY,
  task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,  -- usually a story
  body          TEXT NOT NULL,                  -- target <= 400 chars
  actor         TEXT,
  created_at    TEXT NOT NULL
)

session_events(
  id            INTEGER PRIMARY KEY,
  project_id    INTEGER NOT NULL REFERENCES projects(id),
  task_id       INTEGER REFERENCES tasks(id),
  kind          TEXT NOT NULL
                CHECK (kind IN ('session_start','compaction','prompt','task_switch')),
  detail        TEXT,
  created_at    TEXT NOT NULL
)

checkpoints(
  id            INTEGER PRIMARY KEY,
  project_id    INTEGER NOT NULL REFERENCES projects(id),
  task_id       INTEGER REFERENCES tasks(id),   -- NULL = whole-project checkpoint
  summary       TEXT NOT NULL,                  -- <= ~60 lines, markdown
  next_actions  TEXT,                           -- JSON array of strings
  created_at    TEXT NOT NULL
)
```

Indexes: `tasks(project_id, status, priority, seq)`, `tasks(parent_id)`,
`tasks(owner, lease_expires_at)`, `journal(task_id, id DESC)`,
`task_relations(related_id, kind)`, `session_events(project_id, id DESC)`.

Plus FTS5 over `tasks(title, description)` and `journal(body)` for `recall`.

**A ready task** is `status='open'`, has no blocking `blocked_by` target that is not
`done`/`closed`/`cancelled`, and — if `require_closure` — all such targets are `done`.
Cancelled blockers count as satisfied so a dropped thread never deadlocks the graph.
Cycles are **rejected at insert time** by `task_link`, not discovered later.

## 7. Tool surface (MCP)

`task-manager` keeps the tool count small and pushes workflow into prompts — that
ratio is right. The count below is larger only because this server owns reasoning
state and the scheduler; it stays grouped in six families an agent can learn in one
pass.

### 7.1 Projects

| Tool | Purpose |
|---|---|
| `project_upsert` | Create or fetch by slug (idempotent). Maps `root_path` → slug. |
| `project_list` | Projects with open/waiting counts. |
| `project_archive` | Hide a finished project without deleting it. |

### 7.2 Tasks

| Tool | Purpose |
|---|---|
| `task_add` | Add a task: title, description, design, type, workflow, priority, parent, `blocked_by`, `prepend`. |
| `task_update` | Patch fields (title, description, design, priority, workflow, parent). Never changes status. |
| `task_get` | One task + relations, children, context, and the last N journal entries. |
| `task_query` | **One** filter tool instead of a query language: by id, workflow, parent, type, status, text, `waiting`, `ready`; capped + paginated. |
| `task_reopen` | Return a `done`/`closed` task to `in_progress`, keeping the outcome as history. |
| `task_delete` | Soft-cancel by default; `hard=True` purges. |

### 7.3 Relations

| Tool | Purpose |
|---|---|
| `task_link` | Add `blocked_by` / `related` / `discovered_during`; rejects self-links and cycles. |
| `task_unlink` | Remove a relation. |
| `task_graph` | Project DAG as nodes + edges, plus the computed waiting set. |

### 7.4 Flow (scheduler + lifecycle)

| Tool | Purpose |
|---|---|
| `task_next` | Next executable task: optionally by workflow queue, else highest priority ready task. |
| `task_start` | Atomically `in_progress` + `owner` + lease (default 60 min), then run `work-on` hooks (branch / worktree / state file). Fails if leased by another agent. |
| `task_release` | Back to `open`; abandon the lease, keep the journal. |
| `task_complete` | `done` + required `outcome`; clears lease; unblocks dependents. |
| `task_close` | `done` → `closed` (accept/merge gate), optional per project. |
| `task_block` | `blocked` + required `reason` (mirrored into the journal). |
| `task_unblock` | `blocked` → `open` (or straight to `in_progress`). |

### 7.5 Memory

| Tool | Purpose |
|---|---|
| `journal_add` | Append `note`/`decision`/`attempt`/`problem`/`result`. Body capped (see §9). |
| `journal_list` | Reverse-chronological entries for a task or project. |
| `context_append` | Append a short fact to a story's context; children read it automatically. |
| `recall` | FTS over tasks + journal; returns snippets with task ids. Answers "did we try this already?". |

### 7.6 Sessions & resumption

| Tool | Purpose |
|---|---|
| `session_event` | Record `session_start` / `compaction` / `prompt` / `task_switch` against a project (and active task). |
| `checkpoint_save` | Store a handoff summary + `next_actions` for a project or task. |
| `checkpoint_latest` | Fetch recent checkpoints. |
| `resume` | **The flagship tool.** Returns a compact briefing (payload in §7.7). |
| `workflow_prompt` | Return the prompt template for a workflow, so the server stays the single source of workflow truth. |

### 7.7 `resume` payload

```jsonc
{
  "project": { "slug": "tasks-manager", "open": 7, "waiting": 2, "blocked": 1 },
  "last_checkpoint": { "at": "2026-10-28T09:12:00Z", "summary": "...", "next_actions": ["..."] },
  "in_progress": [ { "id": 12, "title": "...", "workflow": "feature", "owner": "agent-7",
                     "lease_left_min": 34,
                     "last_journal": { "kind": "attempt", "body": "tried X, failed because Y" } } ],
  "blocked":     [ { "id": 9, "title": "...", "reason": "waiting on upstream API key" } ],
  "waiting_on":  [ { "id": 11, "title": "...", "needs": [9] } ],   // dependency-blocked
  "ready":       [ { "id": 15, "title": "...", "workflow": "simple", "priority": 1 } ], // <=10
  "story_context": [ { "story_id": 4, "entries": ["Task 12: retry uses backoff 2^n"] } ],
  "recent":      [ { "kind": "decision", "body": "...", "task_id": 12, "at": "..." } ], // <=8
  "health":      { "stale": [3], "compactions_since_checkpoint": 2, "lease_expired": [] }
}
```

Budget: **≤ ~1200 tokens**. Everything capped and summarised; detail is one
`task_get` away. The contract is *"enough to resume, not to be complete."*

## 8. Dashboard (kanban board)

The MCP surface is shaped for agents; the agent + human pair in §3 still needs a surface
shaped for eyes. So the server ships one optional, self-contained web dashboard — a
**kanban board over the same SQLite file** — so the human and the agent always look at
identical state. It is a view and a control surface, never a second source of truth.

```
┌ open ─────────────┬ in_progress ──────┬ blocked ──────────┬ done ─┬ closed ┐
│ #15 p1 simple     │ #12 p2 ▸agent-7   │ #9  needs API key │ #3    │ #1     │
│ #11 p3 ⧗ waits#9  │ lease 34m left    │                   │ #7    │        │
└───────────────────┴───────────────────┴───────────────────┴───────┴────────┘
            ⧗ = waiting (computed, not a column)
```

| Element | Requirement |
|---|---|
| **Columns** | One per real status: `open`, `in_progress`, `blocked`, `done`, `closed`; `cancelled` behind an "Archive" toggle. |
| **No `waiting` column** | Waiting is the computed flag from §5, rendered as a badge on a dimmed card — never a column, never something a human can drag a task into. |
| **Cards** | id, title, priority, workflow, owner, lease countdown, waiting/`blocked_by` badge, and the **last journal line** — the same fields `resume` returns. Order within a column: `priority`, then `seq`. |
| **Swimlanes** | Toggle: none, by `workflow`, or by parent story. |
| **Drag to transition** | A drop calls the *same* transition function as the MCP tool, not a raw status write: `open→in_progress` = `task_start` (takes a lease), `→done` = `task_complete` (prompts for `outcome`), `→blocked` = `task_block` (prompts for `reason`), `done→closed` = `task_close`, `in_progress→open` = `task_release`. An illegal drop snaps back and shows the server's reason (cycle, lease conflict, missing outcome). |
| **Task detail panel** | Everything `task_get` returns: description/design, relations with the computed ready/waiting state, children, story context, and the journal timeline. |
| **Journal in the UI** | Append-only and newest-first; adding an entry is allowed, editing or deleting one is not — the §5 rule is enforced by the UI, not just by convention. |
| **Graph view** | `task_graph`'s DAG plus the waiting set: a second read-only view over the same data. |
| **Lease safety** | A card owned by an agent is visibly leased; a human write on a leased task requires an explicit *take over lease* action, so a click cannot silently yank work away from a running agent. |

**Where it runs.** `task-manager dashboard` starts an opt-in HTTP mode in the same
process (the stdio MCP server is unchanged) that reuses the same repository layer:
FastAPI + server-rendered Jinja + HTMX, with JS/CSS vendored into the package. No Node
build, no CDN, no network calls at runtime (N1 holds), binds `127.0.0.1` by default,
and refreshes via polling/SSE over the local socket.

**One write path.** No dashboard route issues `UPDATE` directly. Every mutation goes
through the same functions the MCP tools call, inside the same `BEGIN IMMEDIATE`
transaction, so cycles, illegal transitions, missing outcomes/reasons, and lease
conflicts are rejected identically (N4). If a rule lives only in the UI, it is a bug.

**Non-goals (v1).** Gantt/velocity charts, multi-user accounts and auth, rich text,
history editing, and a mobile layout. The board is for the person who already has the
repo checked out; agents keep using `resume`, not the board.

## 9. Session protocols (the long-term mechanics)

Tools alone do not produce long-term follow-up; the **rituals** do. Ship them as MCP
*prompts* so agents get them for free.

### Start of session — `resume`

1. `session_event(session_start)`; `resume(project)`.
2. If `in_progress` and the lease is ours or expired → continue; read its journal tail
   and its story context.
3. Else take the highest-priority `ready` task and `task_start` it.
4. Never open a new task while a claimed one is unfinished unless it is blocked.

### During work — journal as you go

Write a `decision` when choosing an approach, an `attempt` **after** a failed try
(include the error and *why* it failed), and a `problem` when blocked. Budget per
entry: **≤ 6 lines**. Facts a sibling task will need go to `context_append`
(**≤ 400 chars**), not the journal.

### On compaction — the signal that matters

`session_event(compaction)` on every context compaction. Two compactions without an
intervening checkpoint means the task is too big: the start-session prompt must then
recommend splitting it or checkpointing before continuing. `task-manager` records
these events precisely because they are the only reliable signal that a task outgrew
a single context window.

### End of session — checkpoint

1. `task_complete` anything finished (with `outcome`).
2. `task_block` anything stuck (with a specific `reason`).
3. `checkpoint_save` a ≤60-line summary + `next_actions`.
4. `task_release` any lease not being kept.

### Hygiene the server enforces

* **Lease expiry** — expired leases are reaped to `open` on read, so a crashed agent
  never permanently owns a task.
* **Staleness** — `in_progress` with no journal entry for > 7 days → `health.stale`.
* **Done requires outcome**, **blocked requires reason** — kills "silently stuck" and
  "done, but did it work?".
* **Cycle rejection** at `task_link`.
* **Size caps** on journal and context entries, so memory cannot silently blow the
  context budget that it exists to protect.

## 10. Walkthrough (typical multi-day flow)

**Day 1** — agent plans: `task_add` ×6 with `type`/`workflow`, then `task_link` to
build the chain. `task_start` task 1 (branch created by the `work-on` hook), works,
hits a wall, writes `attempt: "mypy --strict fails on plugin loader; the Protocol is
unbound — try narrowing to a concrete class"`, `checkpoint_save`, `task_release`.

**Day 3, new session, empty context** — `session_event(session_start)` then `resume`
returns: last checkpoint summary, task 1 `in_progress` with its last journal line,
`waiting_on` the two tasks gated behind it, and 2 `ready` tasks. The agent reads one
line and knows what to try next. No re-derivation, no duplicated effort.

**Day 5** — task 2 blocks on an external decision → `task_block(reason=...)`. Its
dependents move from `waiting_on` into plain `blocked` visibility; no agent
re-attempts them. Story task 4 accumulates `context_append` facts that its children
inherit, so child tasks do not re-derive what the story already learned.

**Day 6, human review** — the human opens the dashboard, sees task 12 leased by
`agent-7` (so it is not theirs to touch), reads task 2's journal tail before deciding
whether to unblock it, and drags task 1 from `done` to `closed` — accepted because task 1
already has an `outcome`. Same state the agent sees, no sync, no export step.

## 11. Runtime & storage decisions

| Decision | Choice | Why |
|---|---|---|
| Language / SDK | **Python + official MCP SDK (`mcp`, FastMCP-style)** | Small, data-shaped server; strong SQLite support; runs under `stdio`. |
| Transport | **stdio** default; opt-in HTTP for the dashboard (§8) | Local-first; spawned as a subprocess; the board needs a socket, agents do not. |
| Storage | **SQLite** (single file, WAL) | Durable, transactional, FK integrity, FTS5. |
| Location | `$TASKS_DB` or `~/.tasks_manager/tasks.sqlite`; per-repo override in `.tasks/config.json` | One long-lived memory, not a per-repo throwaway. |
| Workflows | Markdown prompt templates with a fixed resolution order: built-ins → `.tasks/workflows/*.md` override | Keeps workflow knowledge out of code. |
| Git integration | **Optional hook** on `task_start`/`task_complete` (branch name `<id>-<4-word-slug>`, worktree), off by default | Good ergonomics without making git a premise. |
| Concurrency | `BEGIN IMMEDIATE` around `task_start`/`task_release`; single writer | Prevents double-claim without a daemon. |
| Time | UTC ISO-8601 strings | Sortable, unambiguous, JSON-safe. |
| Deletion | Soft-cancel default | Long-term memory should not silently lose history. |
| Human diffing | Optional `export` to Markdown/EDNL mirror | Human-readable reviewability without giving up queryability. |
| Dashboard | **Opt-in HTTP mode in the same process** (`task-manager dashboard`): FastAPI + server-rendered Jinja + HTMX, assets vendored | Human surface without a second service, a Node toolchain, or a sync step; reuses the same repository layer as the MCP tools. |
| Dashboard binding | `127.0.0.1` by default, no auth | It is a power tool for the person with the repo checked out, not a shared service. |

Rejected: JSON/EDNL as primary store (no queries, no atomicity, order-fragile),
Postgres/Mongo (service dependency breaks local-first), GitHub Issues as backend
(network, token cost, human-shaped).

## 12. Non-functional requirements

* **N1 — No network calls.** Offline, sub-second per tool call.
* **N2 — Token discipline.** `resume` ≤1200 tokens; lists capped and paginated; no
  prose formatting in results; hard caps on journal and context entries.
* **N3 — Idempotency.** `project_upsert`, `checkpoint_save`, `task_start`, and
  `workflow_prompt` are safe to retry.
* **N4 — Integrity.** Cycles, self-relations, and illegal transitions rejected by the
  server, not by convention.
* **N5 — Portability.** Linux/macOS/**Windows**; stdlib SQLite only (FTS5 ships with
  modern CPython). Windows is a first-class target, not an afterthought.
* **N6 — Inspectability.** Full history readable with plain SQL.
* **N7 — One write path.** Every mutation — MCP tool, dashboard drag, CLI — goes
  through the same repository functions that own the invariants. No code path may
  `UPDATE tasks.status` directly.
* **N8 — Offline dashboard.** The board loads with no external requests: assets are
  vendored, no CDN, no telemetry; first paint < 1s on a local DB.

## 13. Anti-patterns / guardrails

* ❌ Using tasks as a substitute for doing the work (planning theatre).
* ❌ Re-planning into new duplicate tasks instead of updating the existing one.
* ❌ Large journal dumps — keep entries to a few lines.
* ❌ Marking `done` without an `outcome`, or blocking without a reason.
* ❌ Treating `waiting_on` as a status and manually setting `blocked` for a dependency.
* ❌ Letting one "mega task" absorb a week of work; split it instead.
* ❌ Storing secrets in journal or context bodies.
* ❌ Inflating shared context — it is a budget, not a transcript.
* ❌ Fixing the board by editing rows in SQLite — every write goes through the API (§8).
* ❌ Editing or deleting journal entries so the board looks tidy; the log is append-only.
* ❌ Adding a board column for `waiting` — it is computed, not a state a human sets.

## 14. Success metrics

* A brand-new agent can resume a multi-day task using **only** `resume` + one
  `task_get`.
* Zero duplicated tasks across sessions for the same intent.
* Every `blocked` task carries a meaningful reason; every `done` task an outcome.
* `resume` stays within budget as the project grows to hundreds of tasks.
* Recall answers "did we already try this?" from the journal, not from chat history.
* Two agents started concurrently on the same queue never execute the same task.
* A human can answer "what is in flight, what is stuck, and why?" from the board
  alone — no SQL, no asking the agent, no reading transcripts.
* Board and MCP client never disagree: the same task shows the same status, owner, and
  last journal line in both.

## 15. Open questions

1. **Project identity** — cwd-derived slug vs explicit config? (Leaning:
   `.tasks/config.json` wins if present, else cwd slug.)
2. **`closed` gate** — is two-stage completion worth the extra step for solo agents?
   (Leaning: default off, enable for human-review projects.)
3. **Lease defaults** — 60 min globally, or per-workflow (spikes run longer)?
4. **Multi-agent coordination** — are per-task leases enough, or is a project-level
   advisory lock needed for plan mutation?
5. **Journal retention** — ever prune? (Leaning: never; it is the memory.)
6. **Markdown/EDNL mirror** — worth the sync complexity, or trust `export` on demand?
7. **Workflow proposal** — should the agent be allowed to *create* a workflow template
   when none fits, or must a human always author it?
8. **Non-task memory** — should `recall` also cover free-form project facts (env
   quirks, decisions), or is that a separate "notes" tool?
9. **`done` vs `closed` and dependents** — should dependents unblock at `done`, or
   only at `closed`, given that `done` may only mean "PR raised"?
10. **Board mutation while leased** — is an explicit *take over lease* action enough, or
    should the board refuse writes to any agent-owned task?
11. **Board column set** — keep `done` and `closed` as separate columns (wordy for solo
    projects), or collapse them behind the `require_closure` setting?
12. **Live updates** — SSE or plain polling? (Leaning: polling first; a local board does
    not need a persistent connection.)

## 16. Milestones

| Phase | Scope | Done when |
|---|---|---|
| **M0** | Schema + project/task CRUD, stdio server, smoke test | Agent can add and list tasks from a client |
| **M1** | Relations, cycle rejection, computed `waiting_on`, `task_query`/`task_next` | Ready/waiting sets are correct; cycles rejected |
| **M2** | `task_start`/lease/reap, `complete`/`close`/`block`, `reopen` | Scheduler correct; a crashed agent loses its lease |
| **M3** | Journal, `context_append`, `recall` (FTS5) | "Did we try this?" answerable |
| **M4** | `checkpoint_save`, `resume`, `session_event`, workflow prompts | Fresh agent resumes from one call |
| **M5** | `work-on` hooks (branch/worktree), optional mirror export, packaging (`uvx`/`pipx`) | Survives reboot; parallel agents do not collide |
| **M6** | **Dashboard**: kanban board over the same DB, drag-to-transition, task detail with journal timeline, graph view | A human can run the whole project from the browser; every board action respects the same invariants as the MCP tools |

---

### The acceptance tests

> **A. Cold resume.** Kill the agent mid-task, open a **new** session with **empty**
> context, call `resume` once — the agent continues correctly, *including knowing what
> not to retry*.

> **B. No double work.** Start two agents against the same project concurrently; each
> task is executed exactly once, and the second agent either waits or picks a different
> ready task.

> **C. Bounded memory.** After 50 tasks, `resume` is still under budget and still
> sufficient.

> **D. One write path.** Drive a project entirely from the board: illegal drags are
> refused with the same reason the MCP tool gives, `done` still demands an outcome,
> `blocked` still demands a reason, and the DB shows no state an MCP client could not
> have produced.

Until all four pass, the project is not done.