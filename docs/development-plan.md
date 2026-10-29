# Tasks Manager MCP — Development Plan

| | |
|---|---|
| **Status** | Draft for review |
| **Last updated** | 2026-10-29 |
| **Source of truth** | [intend.md](./intend.md) — this plan operationalises it, it does not extend it |
| **Environment** | Windows first-class (N5); dev on Python 3.12, code floor Python 3.10 |

---

## 1. Purpose and scope

This plan turns the intent into an executable sequence of work packages. It covers:

1. **Architecture** — package layout and the layering rule that makes N7 ("one write
   path") structurally impossible to violate.
2. **Decisions** — a resolution for every open question in intend.md §15, with a
   decision gate (the milestone by which it must be locked).
3. **Phases** — the intent's M0–M6 milestones expanded into concrete deliverables,
   work items, and "done when" criteria.
4. **Testing** — how the four acceptance tests (A–D) become automated CI tests, not
   manual rituals.
5. **Risks** — the things most likely to bite (Windows SQLite, FTS5, leases, budget).

Scope is v1 exactly as intended. Anything the intent lists as a non-goal (auth,
multi-user, mobile, velocity charts, history editing) stays out.

---

## 2. Locked decisions (already made in intend.md)

These are fixed and not re-opened by this plan:

| Decision | Choice |
|---|---|
| Language / SDK | Python + official MCP SDK (`mcp`, FastMCP-style), `stdio` transport |
| Storage | SQLite single file, WAL, `PRAGMA foreign_keys=ON`, UTC ISO-8601 strings, soft-delete |
| Dashboard | Opt-in HTTP mode in the **same process**, FastAPI + Jinja + HTMX, assets vendored, binds `127.0.0.1`, no auth |
| Write path | Every mutation (MCP tool, dashboard drag, CLI) goes through the repository layer; no code path may `UPDATE tasks.status` directly (N7) |
| Waiting | `waiting` is computed, never a stored status; no `waiting` column on the board |
| Journal | Append-only; no edit, no delete; body ≤ 6 lines; context ≤ 400 chars |
| Cycles | Rejected at `task_link` time, not discovered later |
| Concurrency | `BEGIN IMMEDIATE` around `task_start`/`task_release`; single writer |
| Python floor | 3.10 (MCP SDK requirement); develop against 3.12 |
| DB location | `$TASKS_DB` → else `~/.tasks_manager/tasks.sqlite`; per-repo `.tasks/config.json` override |

---

## 3. Architecture

### 3.1 Package layout

```
tasks_manager/
├── pyproject.toml               # hatchling or setuptools; console scripts task-manager
├── README.md
├── docs/
│   ├── intend.md
│   └── development-plan.md
├── src/task_manager/
│   ├── __init__.py
│   ├── __main__.py              # python -m task_manager
│   ├── cli.py                   # subcommands: serve (stdio) | dashboard (http)
│   ├── config.py                # DB path resolution: env → ~/.tasks_manager → .tasks/config.json
│   ├── db.py                    # connection factory: pragmas, busy_timeout, FTS5 probe
│   ├── migrations/
│   │   └── 0001_initial.sql     # full schema from intend.md §6 + indexes + FTS5 tables
│   ├── errors.py                # typed errors: IllegalTransition, LeaseConflict,
│   │                            #   CycleDetected, MissingOutcome, MissingReason, NotFound
│   ├── models.py                # Pydantic models returned by the repository
│   ├── repository.py            # ★ THE single write path (N7). All invariants live here.
│   ├── transitions.py           # lifecycle state machine (open→in_progress→done→closed…)
│   ├── scheduler.py             # ready/waiting computation, task_next, lease reap, staleness
│   ├── workflows.py             # built-in templates + .tasks/workflows/*.md resolution
│   ├── hooks.py                 # optional git branch/worktree hooks (off by default)
│   ├── export.py                # Markdown/EDNL export (M5)
│   ├── resume.py                # briefing assembly: caps + token budget (N2)
│   ├── prompts.py               # MCP prompts: start-session / compaction / end-session (§9)
│   ├── server.py                # FastMCP server; tools are thin adapters over repository
│   └── dashboard/
│       ├── app.py               # FastAPI app reusing repository.py
│       ├── board.py             # kanban routes; drag = same transition functions as MCP
│       ├── templates/           # Jinja2: board, task detail, graph
│       └── static/              # vendored htmx.min.js + css (no CDN, N8)
└── tests/
    ├── conftest.py              # tmp_path SQLite fixtures, fake MCP client
    ├── test_repository.py
    ├── test_transitions.py
    ├── test_relations.py        # cycles, waiting computation
    ├── test_scheduler.py        # task_next, lease reap
    ├── test_memory.py           # journal, context, recall (FTS5)
    ├── test_resume_budget.py
    ├── test_mcp_tools.py        # every tool via an in-memory client session
    ├── test_hooks_export.py
    ├── test_dashboard.py        # FastAPI TestClient
    └── test_acceptance.py       # A (cold resume), B (no double work),
                                 # C (bounded memory), D (one write path)
```

### 3.2 Layering rule (enforces N7 structurally)

```
MCP tools (server.py) ─┐
Dashboard routes ──────┼──> repository.py  ──>  sqlite3
CLI commands ──────────┘        ▲
                             only file allowed to write rows
```

* **`repository.py` is the only module that issues write statements** to `tasks`,
  `task_relations`, `journal`, `task_context`, `session_events`, `checkpoints`,
  `projects`. A grep rule in CI (`sql."(UPDATE|INSERT|DELETE)"` allowed only in
  `repository.py` and `db.py`) makes violations impossible to merge.
* Every repository function validates its invariant **inside the same transaction**
  that performs the write: transition legality, outcome/reason presence, cycle check,
  lease ownership, size caps. Dashboard and MCP therefore cannot disagree (N4, N7).
* `BEGIN IMMEDIATE` is used for lease-affecting writes (`task_start`, `task_release`,
  transitions); reads use plain deferred transactions with `busy_timeout=5000`.
* `transitions.py` is a pure state-machine table `{status: {action: (next_status,
  requirements)}}`; `repository.py` consults it, so illegal transitions are a data
  error, not scattered `if` statements.

### 3.3 Configuration resolution (M0)

`config.py` resolves once at startup, in order:

1. `$TASKS_DB` env var (explicit path wins, N6-friendly for CI/tests),
2. `.tasks/config.json` in the current working directory (`{"slug": "...",
   "root_path": "..."}` per-repo override),
3. `~/.tasks_manager/tasks.sqlite` default.

The same module resolves `require_closure`, workflow overrides, and hook enablement.

---

## 4. Resolving the open questions (intend.md §15)

| # | Question | Recommendation | Decision gate |
|---|---|---|---|
| 1 | Project identity | `.tasks/config.json` wins if present, else cwd-derived slug. `root_path` recorded so the same repo maps to the same project from any cwd. | M0 |
| 2 | `closed` gate | Keep two-stage model; `require_closure` per project, default **off**. `done` remains the status; `closed` only visible/required when enabled. | M2 |
| 3 | Lease defaults | Global default 60 min, **per-workflow override** via a `lease_minutes` field in the workflow template frontmatter. Implement override in M4, global default in M2. | M2 / M4 |
| 4 | Multi-agent coordination | Per-task leases only for v1. Project-level advisory lock deferred; revisit after acceptance test B runs under real concurrent agents. | M5 review |
| 5 | Journal retention | Never prune in v1. It is the memory; size caps already bound growth. | M3 (confirm, no code) |
| 6 | Markdown/EDNL mirror | Defer mirroring. Ship `export` on demand in M5; revisit mirror only if a real consumer appears. | M5 |
| 7 | Workflow proposal | Agents may add workflows in a **project's** `.tasks/workflows/*.md` (user space) but never modify built-ins. Server validates template shape on read. | M4 |
| 8 | Non-task memory | Out of v1. `recall` covers tasks + journal only; a separate notes tool is v2 territory. | M3 |
| 9 | `done` vs `closed` for dependents | Dependents unblock at `done` by default; when `require_closure` is on, they unblock at `closed`. One computed rule, project-configurable, no per-task flags. | M2 |
| 10 | Board mutation while leased | Explicit **take over lease** action required: one click that atomically `task_release` + transition (re-validating outcome/reason), never a silent write. | M6 |
| 11 | Board columns | Keep `done` and `closed` as separate columns always. Hide `closed` only visually when `require_closure=false` and the column is empty; `cancelled` behind an Archive toggle. | M6 |
| 12 | Live updates | Polling (5 s) first. SSE later only if polling feels slow on real data. | M6 |

Rationale in one line each: the leanings in §15 are adopted because they all push
complexity to configuration/project scope, keep the solo-agent path frictionless, and
never add a second source of truth.

---

## 5. Phases

Each phase is a mergeable slice: it ends with a running server, green tests, and a
tagged capability. No phase depends on code that does not exist yet.

### M0 — Schema + CRUD + stdio skeleton

**Goal.** A shippable skeleton: an agent can `project_upsert`, `task_add`, and
`task_query` from a real MCP client.

**Deliverables**

- `pyproject.toml`: package `task-manager`, deps `mcp`, `pydantic`; dev extras
  `pytest`, `ruff`; console scripts `task-manager` (subcommands `serve`, `dashboard`
  stub); Python `>=3.10`.
- `migrations/0001_initial.sql`: full schema from §6 — all seven tables, all CHECKs,
  all indexes, FTS5 virtual tables over `tasks(title, description)` and
  `journal(body)`, plus triggers keeping FTS5 in sync (external-content or standard
  virtual table with explicit inserts from the repository).
- `db.py`: connection factory with `journal_mode=WAL`, `foreign_keys=ON`,
  `busy_timeout=5000`; `PRAGMA user_version` migration runner; startup probe for FTS5
  (fail `recall` gracefully, never fail the whole server — N5).
- `repository.py` (initial slice): `project_upsert` (idempotent, N3), `project_list`
  (open/waiting counts), `project_archive`, `task_add`, `task_update` (never touches
  status), `task_get` (task + relations + children + context + last N journal entries),
  `task_query` (single filter tool with caps + pagination), `task_delete` (soft-cancel
  default, `hard=True` purges).
- `server.py`: FastMCP server registering the Project and Task tool families with
  Pydantic-typed inputs; errors mapped to structured results, not exceptions.
- GitHub Actions CI: `ruff` + `pytest` on `ubuntu`, `windows`, `macos` (N5 from day
  one). The repo is already on GitHub; CI is the cheapest way to keep Windows honest.
- `tests/`: repository tests against `tmp_path` DBs; one in-memory MCP client session
  test proving `task_add` → `task_query` round-trips over stdio semantics.

**Done when.** The intend's M0 line: an agent can add and list tasks from a client.
Smoke test scripted in CI (spawn `task-manager serve`, run a scripted MCP client).

### M1 — Relations, graph, and the scheduler's read side

**Goal.** The DAG is real: `task_link` rejects cycles, `waiting`/`ready` are computed,
and `task_next` picks work correctly.

**Deliverables**

- `repository.py`: `task_link` / `task_unlink` with in-transaction cycle detection
  (DFS over `blocked_by` edges only) and self-link rejection; `task_graph` returning
  nodes + edges + computed waiting set.
- `scheduler.py`: ready-task predicate exactly as specified — `open`, no blocking
  target that is not terminal, cancelled blockers count as satisfied, and the
  `require_closure` refinement (blockers must be `closed` when enabled). `task_next`:
  workflow queue order if requested, else highest-priority ready task.
- `task_query` filters: by id, workflow, parent, type, status, text (FTS if available,
  else LIKE fallback), `waiting`, `ready`; all lists capped and paginated (N2).
- Tests: cycle diamond rejection, self-link rejection, waiting cascade, cancelled
  blocker unblocks dependents, `require_closure` gating, `task_next` ordering.

**Done when.** Ready/waiting sets are correct across the test matrix; cycles are
rejected at link time with a typed `CycleDetected` error.

### M2 — Lifecycle, leases, and concurrency safety

**Goal.** The state machine is enforceable and safe under two processes.

**Deliverables**

- `transitions.py`: full state table including `reopen` and `unblock` shortcuts;
  requirement checks (outcome for `done`/`closed`, reason for `blocked`) encoded here.
- `repository.py`: `task_start` (atomic claim: `BEGIN IMMEDIATE`, fail with
  `LeaseConflict` if leased and unexpired), `task_release`, `task_complete`,
  `task_close`, `task_block` (reason mirrored into the journal), `task_unblock`,
  `task_reopen` (outcome preserved as history).
- Lease machinery: `owner` + `lease_expires_at`; expiry reaped lazily on read so a
  crashed agent never permanently owns a task; `lease_left_min` surfaced in
  `task_get`/`resume`-adjacent payloads.
- `require_closure` + question-9 rule: dependents unblock at `done` (default) or
  `closed` (when enabled) — implemented as one computed predicate.
- Tests: every legal and illegal transition; lease expiry reclaim; two-process
  double-claim test (spawn two threads/processes racing `task_start`, assert exactly
  one winner) — this is the core of acceptance test **B**.

**Done when.** Scheduler correct; a crashed agent loses its lease; two concurrent
agents never both claim the same task.

### M3 — Memory: journal, context, recall

**Goal.** "Did we try this already?" is a query, not chat archaeology.

**Deliverables**

- `journal_add` (kinds `note`/`decision`/`attempt`/`problem`/`result`, body ≤ 6 lines
  enforced server-side), `journal_list` (reverse-chronological, task or project).
- `context_append` (≤ 400 chars) + automatic inheritance into `task_get` for story
  children.
- `recall`: FTS5 over tasks + journal, returning snippets with task ids; graceful
  `LikeFallback` when FTS5 is unavailable.
- Tests: cap enforcement, cascade delete of journal on `hard=True`, FTS hit quality
  ("retry backoff" finds the task whose journal mentions it), project-level notes.

**Done when.** Recall answers the intend's canonical question from journal data, and
caps are enforced by the server, not by convention.

### M4 — Resumption: the flagship

**Goal.** Acceptance test **A**: a cold agent resumes correctly from one call.

**Deliverables**

- `session_event` (four kinds, tied to project + active task), `checkpoint_save`
  (idempotent re-save updates in place, N3), `checkpoint_latest`, `resume`,
  `workflow_prompt`.
- `resume.py` assembles the §7.7 payload with every cap enforced in code: ≤10 ready,
  ≤8 recent, summaries truncated, `story_context` curated. A CI test asserts the
  serialised payload stays under the 1200-token budget against a seeded DB of 50+
  tasks (acceptance test **C**).
- `workflows.py`: resolution order built-ins → `.tasks/workflows/*.md`; template
  frontmatter carries `lease_minutes`; validation rejects malformed templates.
- `prompts.py`: MCP **prompts** shipping the §9 rituals — start-session (`session_event
  (session_start)` + `resume` + decide), compaction (log `compaction`, warn after two
  without a checkpoint), end-session (complete/block/checkpoint/release).
- Health fields: `stale` (>7 days without journal entry), `lease_expired`,
  `compactions_since_checkpoint`.
- Tests: cold-resume end-to-end through an in-memory client (acceptance **A**), budget
  test (acceptance **C**), idempotency of `checkpoint_save`.

**Done when.** A fresh agent resumes from one call, within budget, including knowing
what not to retry.

### M5 — Hooks, export, packaging

**Goal.** Survives reboot, installs cleanly, and plays well with git.

**Deliverables**

- `hooks.py`: optional `work-on` hooks on `task_start`/`task_complete` — branch
  `<id>-<4-word-slug>`, worktree support; **off by default**, enabled per project
  config; Windows-safe (no POSIX-only shelling; use `subprocess` with explicit args).
- `export.py`: Markdown (and EDNL) export on demand; round-trip test that export never
  writes and import is not implied.
- Packaging: installable via `uvx task-manager` and `pipx`; `python -m task_manager`
  works; README rewritten as user-facing docs (install, MCP client config, dashboard).
- CI: add a `uvx`-install smoke step and a Windows packaging check.

**Done when.** Parallel agents do not collide; the tool installs and survives reboot
in a documented, reproducible way.

### M6 — Dashboard (kanban board)

**Goal.** Acceptance test **D**: a human runs the whole project from the browser and
every board action respects the same invariants as the MCP tools.

**Deliverables**

- `dashboard/app.py`: FastAPI app in-process, `127.0.0.1`, reusing `repository.py`
  exclusively. `task-manager dashboard` starts it; `serve` (stdio) is unchanged.
- Board: columns per real status (`cancelled` behind Archive toggle), cards with
  id/title/priority/workflow/owner/lease countdown/waiting badge/last journal line;
  order priority-then-seq; swimlanes (none / workflow / parent story); computed
  `waiting` as a dimmed badge only.
- Drag-to-transition calling the **same transition functions** as MCP tools; illegal
  drops snap back showing the server's reason (cycle, lease conflict, missing
  outcome/reason).
- Task detail panel (full `task_get` output), graph view (DAG + waiting set),
  append-only journal UI, explicit *take over lease* action (question 10).
- HTMX + CSS vendored into the package; CI greps templates for external URLs to prove
  N8; first-paint test on a seeded local DB.
- Tests: `fastapi` TestClient driving every transition path — legal and illegal —
  asserting identical error reasons to the MCP tools (acceptance **D**).

**Done when.** The intend's M6 line: a human runs the project from the browser, and
the DB shows no state an MCP client could not have produced.

---

## 6. Acceptance tests → automated CI

| Acceptance test | Automated where | Blocking? |
|---|---|---|
| **A — Cold resume** | `tests/test_acceptance.py::test_cold_resume` — seed mid-task state, new client session, call `resume`, assert correct continuation *including* the not-to-retry knowledge | M4 gate |
| **B — No double work** | `test_acceptance.py::test_no_double_claim` — two processes race `task_start` on the same queue; assert exactly-once execution | M2 gate |
| **C — Bounded memory** | `test_resume_budget.py` — 50-task seed; assert payload ≤ budget and still sufficient (ready/in-progress/blocked all present) | M4 gate |
| **D — One write path** | `test_dashboard.py` — drive a project entirely through board HTTP calls; illegal drags refused with MCP-identical reasons; DB state identical to MCP-driven state | M6 gate |

All four run in CI on every commit once their phase lands. The project is not done
until all four pass — per the intent, this is the final gate, not a checklist item.

Procedures, fixtures, numeric caps, and traceability are specified in
[test-plan.md](./test-plan.md).

---

## 7. Cross-cutting enforcement (N1–N8)

| NFR | Enforcement mechanism |
|---|---|
| N1 no network | No runtime HTTP client imports (ruff ban rule `TID251` on `requests`/`urllib`); dashboard binds localhost |
| N2 token discipline | Budget assertions in CI; caps implemented in `resume.py`, not in tool docs |
| N3 idempotency | Dedicated tests for `project_upsert`, `checkpoint_save`, `task_start` retry, `workflow_prompt` |
| N4 integrity | All invariants in `repository.py` inside the writing transaction; `transitions.py` table |
| N5 portability | CI matrix ubuntu/windows/macos from M0; stdlib `sqlite3` only; Windows path handling in tests |
| N6 inspectability | No opaque blobs in tables except documented `meta` JSON; plain-SQL migration files |
| N7 one write path | Layering rule + CI grep: write statements only in `repository.py` |
| N8 offline dashboard | Vendored assets; CI check that templates contain no `http://`/`https://` references |

---

## 8. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| FTS5 missing on some Python builds | Low (ships with CPython 3.10+ on Windows/macOS/Linux) | Startup probe; `recall` degrades to LIKE with a clear note, server still runs (N5) |
| SQLite WAL problems on network-synced home dirs (Windows OneDrive) | Medium | Default DB under `~/.tasks_manager/` but document `$TASKS_DB` override; detect and warn on `SQLITE_IOERR` |
| Lease clock skew between processes | Low (same machine) | UTC ISO-8601 everywhere; expiry compared against `datetime.now(timezone.utc)` |
| Token budget creeping as features land | Medium | Budget test in CI from M4 onward; any `resume` payload change must keep the test green |
| HTMX/CSS vendoring drift or accidental CDN reference | Medium | Pin vendored version in repo; CI template scan (N8) |
| `BEGIN IMMEDIATE` contention with a busy dashboard | Low (single human + agents) | `busy_timeout=5000`; short write transactions; reads never hold write locks |
| Scope creep into v2 (auth, mirrors, notes) | Medium | Section 4 gates: deferred items are explicitly listed as post-v1 |

---

## 9. Sequencing and rough sizing

| Phase | Depends on | Rough size | Exit artefact |
|---|---|---|---|
| M0 | — | M | Installable package, schema, CRUD via MCP |
| M1 | M0 | M | DAG + ready/waiting computation |
| M2 | M1 | M | Leases + lifecycle, double-claim proof |
| M3 | M2 | S | Journal/context/recall |
| M4 | M3 | L | `resume` + prompts, acceptance A & C |
| M5 | M4 | S | Hooks, export, packaging, docs |
| M6 | M4 (M5 parallelisable) | L | Dashboard, acceptance D |

Suggested order of commits: one phase = one series of small PRs, each with its own
tests; CI is green on `main` at all times. M5 and M6 are the only phases that can
proceed in parallel, since the dashboard depends on the repository API but not on the
git hooks.

---

## 10. Definition of done (project)

All of:

1. M0–M6 exit artefacts exist and their "done when" lines are true.
2. Acceptance tests A–D pass automatically in CI on Windows, macOS, and Linux.
3. `resume` stays within budget at 50+ tasks (N2), and every write path is audited
   to go through `repository.py` (N7).
4. A human can complete a full project from the board alone, and the board and an MCP
   client never disagree (intend §14).
5. README documents install, MCP client configuration, and dashboard usage for a
   Windows-first developer.

---

## 11. Immediate next step (today)

Start M0 with this order:

1. `pyproject.toml` + package skeleton + CI workflow (the first PR).
2. `migrations/0001_initial.sql` implementing §6 verbatim, with a migration runner.
3. Repository slice: `project_upsert`, `task_add`, `task_update`, `task_get`,
   `task_query`, `task_delete`.
4. `server.py` exposing the Project and Task tool families; smoke-test via a scripted
   MCP client in CI.

These four steps are expanded into implement-ready tasks **T01–T04** (and all later
phases into **T05–T22**) in [docs/tasks/](./tasks/README.md) — one self-contained
markdown file per task, with exact signatures, validation matrices, and per-task
test lists.
