# Tasks Manager MCP — Test Plan

| | |
|---|---|
| **Status** | Draft for review |
| **Applies to** | `v0.1.0` scope (M0–M6) |
| **Last updated** | 2026-10-29 |
| **Sources of truth** | [intend.md](./intend.md) — behaviour and acceptance tests; [development-plan.md](./development-plan.md) — architecture, gates, NFR enforcement; [docs/tasks/](./tasks/README.md) — per-task test lists |
| **Under test** | `task_manager` package, `task-manager` CLI, MCP server (`stdio`), dashboard (`127.0.0.1`) |

This plan does not replace the task-level test lists; those stay authoritative for
individual cases. This plan owns the **cross-cutting strategy**: test levels, fixtures,
oracles, numeric caps, acceptance-test procedures, CI layout, traceability, and exit
criteria.

---

## 1. Scope

### 1.1 In scope

1. Every tool in intend.md §7 (Projects, Tasks, Relations, Flow, Memory, Sessions).
2. The lifecycle state machine, leases, and cycle rejection (intend §5, §9).
3. `resume` correctness and bounded payload (intend §7.7, N2).
4. The dashboard as a second surface over the same repository (intend §8, N7).
5. Portability and packaging: Windows, macOS, Linux; `pip`, `uvx`, `pipx`,
   `python -m task_manager` (N5).
6. Offline behaviour and vendored assets (N1, N8).
7. The four acceptance tests A–D (intend §16).

### 1.2 Out of scope

Matches intend §8 non-goals and the v1 boundary:

| Not tested | Why |
|---|---|
| Authentication, multi-user, permissions | No auth by design; binds `127.0.0.1` only |
| Load, soak, and throughput benchmarks | Single local writer by design (N1 "sub-second", not a benchmark target) |
| Browser JavaScript execution and drag-and-drop physics | No Node build; routes are asserted over HTTP, drag is one POST |
| Mobile/responsive layout, Gantt, velocity charts | Non-goals |
| Real tokenizer token counts | Budget uses the documented `ceil(len/4)` heuristic (T13) |
| Markdown/EDNL import | Deferred (Q6); export is read-only |
| Data migration from competitor tools | Not a requirement |

---

## 2. Quality objectives

Each objective is a claim the release makes; each maps to at least one automated test.

| ID | Objective | Source | Primary evidence |
|---|---|---|---|
| QO-1 | No state exists that the repository layer could not have produced | N4, N7 | `LINT` + `ACC-D` + `DSH` SQL capture |
| QO-2 | A cold agent resumes from one `resume` call, including what not to retry | intend §16 A | `ACC-A` |
| QO-3 | Two concurrent agents never execute the same task | intend §16 B | `ACC-B` |
| QO-4 | `resume` stays within budget at 50+ tasks and still suffices | intend §16 C, N2 | `ACC-C` |
| QO-5 | Board and MCP never disagree, and refusals are identical | intend §8, §14, N7 | `ACC-D`, `DSH` |
| QO-6 | Illegal states are impossible, not merely discouraged | N4 | `TR`, `REL`, `SCH` |
| QO-7 | Memory is append-only and capped server-side | intend §5, §9, N2 | `JN`, `CTX`, `RES` |
| QO-8 | Same behaviour on three OSes, offline, from an installed wheel | N1, N5, N8 | matrix CI, `PKG` |

---

## 3. Test levels and tooling

| Level | ID | Scope | Mechanism | Database | Speed |
|---|---|---|---|---|---|
| Static analysis | `L0` | Lint, write-path rule, no-network imports, template URLs | `ruff`, `tests/test_write_path_lint.py`, string scans | — | <5 s |
| Pure unit | `L1` | `transitions.py` table, ready/waiting predicates, config resolution, frontmatter parsing, truncation helpers | plain `pytest`, no I/O | none | <5 s |
| Repository integration | `L2` | Every write function, invariants inside the transaction | real SQLite file under `tmp_path`, migrated | file | <60 s |
| Protocol | `L3` | Tool schemas, `{ok, data}` envelope, camelCase aliases, structured errors | `mcp.shared.memory.create_connected_server_and_client_session` | file | <30 s |
| HTTP/UI | `L4` | Routes, columns, badges, refusals, read-only GETs | `fastapi.testclient.TestClient` | file | <30 s |
| Process/concurrency | `L5` | Double claim, double reap, concurrent cycle creation | `multiprocessing` (`spawn`), real file, `BEGIN IMMEDIATE` | shared file | <60 s |
| Packaging/CLI | `L6` | Wheel contents, install, `task-manager --help`, resource lookup | build + clean venv + `subprocess` | none | <120 s |
| Manual/exploratory | `L7` | Claims only a human or a real agent client can judge | charters in §13.2 | real DB | timeboxed |

Rules that apply to every level:

1. **Seed only through the repository.** Raw SQL in tests is permitted only in
   `test_db.py` (schema/constraint tests) and in negative tests whose purpose is to
   prove the database rejects something.
2. **One database per test.** `tmp_path` file, migrated in a fixture, connections
   closed before teardown (required on Windows or the WAL files stay locked).
3. **No sleeps and no retries.** Time is injected via the clock seam (§5.3). The only
   bounded wait allowed is process join in `ACC-B`.
4. **No test depends on execution order** or on module-level mutable state.
5. **Assertions are on behaviour, never on log text** — except where the intent makes
   a phrase contractual (prompt text, `search_backend="like"`).

---

## 4. Environments and CI

### 4.1 Matrix

| Axis | Values | Status |
|---|---|---|
| OS | `ubuntu-latest`, `windows-latest`, `macos-latest` | Required (N5) |
| Python | `3.12` | Required — pinned in T01 |
| Python | `3.10` | **Proposed** — the declared floor, currently untested (§16 D-4) |
| FTS5 | present (stdlib build) | Required |
| FTS5 | absent | Simulated by monkeypatching `fts_enabled` / migration failure (T02, T06, T11) |
| DB location | `tmp_path` | Required |
| DB location | `$TASKS_DB`, `~/.tasks_manager/`, `.tasks/config.json` | Required for config cases in `REP` (T03) |

### 4.2 Test layout

Authoritative file names come from the task files, not from the illustrative tree in
development-plan §3.1 (see §16 D-3):

```
tests/
  conftest.py                    # fixtures in §5
  test_smoke.py                  # T01
  test_db.py                     # T02
  test_repository.py             # T03 (includes config resolution)
  test_mcp_tools.py              # T04 protocol
  test_relations.py              # T05
  test_scheduler.py              # T06
  test_transitions.py            # T07
  test_lease_reaping.py          # T08
  test_acceptance.py             # ACC-A, ACC-B, ACC-D
  test_journal.py                # T09
  test_context.py                # T10
  test_recall.py                 # T11
  test_sessions_checkpoints.py   # T12
  test_resume_budget.py          # T13 (contains ACC-C)
  test_workflows.py              # T14
  test_prompts.py                # T15
  test_hooks.py                  # T16
  test_export.py                 # T17
  test_packaging.py              # T18
  test_dashboard.py              # T19–T21
  test_write_path_lint.py        # T22
```

### 4.3 Markers

Register these in `[tool.pytest.ini_options]` (small `pyproject.toml` addition, marked
proposed because T01 does not include it):

| Marker | Selects | Typical use |
|---|---|---|
| `unit` | `L1` | fast local loop |
| `integration` | `L2` | repository/scheduler cases |
| `protocol` | `L3` | MCP client cases |
| `dashboard` | `L4` | board/HTTP cases |
| `concurrency` | `L5` | process-level cases (`ACC-B`) |
| `acceptance` | A–D | release gate, never skipped |
| `packaging` | `L6` | wheel/CLI smoke |
| `slow` | >5 s cases | excluded from the inner loop |

### 4.4 CI jobs

| Job | Runs | Gate |
|---|---|---|
| `lint` | `ruff check src tests`, `pytest tests/test_write_path_lint.py` | every push |
| `test` | `pytest -q` on 3 OSes × Python 3.12 | every push |
| `test-floor` | `pytest -q` on Python 3.10 (proposed) | every push |
| `acceptance` | `pytest -q -k "cold_resume or no_double_work or bounded_memory or one_write_path"` | phase gates M2, M4, M6 |
| `packaging` | build wheel, install in clean venv, import resources, `--help` smoke | M5 onward |

Commands used locally and in review:

```powershell
ruff check src tests
pytest -q                                  # everything
pytest -q -m "not slow"                    # inner loop
pytest -q -k "cold_resume or no_double_work or bounded_memory or one_write_path"
```

**Flake policy.** No automatic retries anywhere. A flaky `ACC-B` is a real
concurrency defect (severity S1), not test noise. Add `pytest-timeout` (proposed dev
dependency) so a deadlocked write transaction fails in seconds rather than hanging CI.

---

## 5. Fixtures and test data

### 5.1 Shared fixtures (`conftest.py`)

| Fixture | Returns | Notes |
|---|---|---|
| `db_path` | `Path` under `tmp_path` | never a repo-relative path |
| `db` | migrated `Database` | `migrate()` once; teardown closes all connections |
| `project` | upserted project row | created via `project_upsert` |
| `clock` | frozen UTC "now" + `advance(minutes)` | patches the single clock seam |
| `mcp` | async client session bound to the server | in-memory transport (T04) |
| `board` | `TestClient` over the FastAPI app with the same `db` | dashboard levels only |
| `git_repo` | `tmp_path` repo from `git init` | hooks only; skip if `git` absent |
| `sql_capture` | proxy connection recording statements | proves read-only routes and N7 |

### 5.2 Canonical seeds

Seeds are built by helper functions so every suite uses the same shapes.

| Seed | Shape | Used by |
|---|---|---|
| `seed_mid_task` | project `demo`; task 1 `in_progress` owned by `agent-7`, lease +34 min, journal `attempt` with the "try narrowing" line; tasks 2–3 `blocked_by` 1; task 4 priority 1 free; one checkpoint with `next_actions` | `ACC-A`, `PRM` |
| `seed_chain6` | 6 tasks, some `blocked_by` edges, all `open`, real file | `ACC-B`, `LEASE` |
| `seed_large` | 50+ tasks across all statuses, ~8 `blocked` with reasons, waiting chains, 2 compactions after the checkpoint, one stale task (>7 days), one checkpoint | `ACC-C`, `RES`, `DSH` smoke |
| `seed_parity` | two identical copies of a mixed project (open, leased, blocked, done, cancelled, one story + child) | `ACC-D` |
| `seed_board` | p1 open, p2 open waiting on a blocked task, leased `in_progress` (30 min), `done`, `cancelled` | `DSH` |

### 5.3 Determinism

* All timestamps come from one seam: `task_manager.db.utc_now()`. The repository must
  call it as `db.utc_now()` (module attribute), never `from .db import utc_now`, or
  the fixture cannot patch it. **This is a testability constraint on T02/T03.**
* Lease arithmetic is asserted against the frozen clock, never wall-clock deltas.
* `lease_left_min` assertions allow ±1 minute (T13) because of `ceil` rounding.
* `multiprocessing` uses `get_context("spawn")` and module-level worker functions so
  the same code runs on Windows.

---

## 6. Oracles: the invariant catalogue

These are checked repeatedly, not once. `OR-*` IDs are referenced from §11.

| ID | Invariant | Source | How asserted |
|---|---|---|---|
| OR-01 | Write SQL exists only in `repository.py` and `db.py` | N7 | `LINT` regex over `src/task_manager/**/*.py`; `sql_capture` on HTTP GETs |
| OR-02 | No tool, route, or repository function accepts `status` as an input | N7, T07 | schema introspection over the MCP tool list; grep-level test in `test_transitions.py` |
| OR-03 | `done`/`closed` ⇒ non-empty `outcome`; `blocked` ⇒ non-empty `block_reason`; block reason mirrored to journal as `problem` | intend §5, §9 | `TR` cases, plus an invariant sweep over `seed_large` |
| OR-04 | `waiting` is computed; it is never a column, a status, or a writable field | intend §5, §8 | schema has no `waiting` column; `DSH` asserts no `waiting` column heading; `SCH` recomputes the set |
| OR-05 | The `blocked_by` graph is acyclic and self-link free | intend §5 | `REL` cases incl. concurrent 2-cycle race |
| OR-06 | The journal is append-only | intend §5, §13 | no update/delete symbol exists (`JN`); `PUT`/`DELETE` journal routes return 404/405 (`DSH`) |
| OR-07 | Caps in §7 are enforced server-side | N2 | boundary cases per cap (exact limit passes, limit+1 fails) |
| OR-08 | Timestamps are UTC ISO-8601 text ending in `Z` | intend §6 | regex assertion over every timestamp column after a full walk |
| OR-09 | A lease claim is atomic, idempotent for the same actor, and exclusive across actors | N3, N4 | `TR`, `LEASE`, `ACC-B` |
| OR-10 | `project_upsert`, `checkpoint_save`, `task_start`, `workflow_prompt` are retry-safe | N3 | repeated-call cases in `REP`, `SES`, `TR`, `WF` |
| OR-11 | No network: no HTTP client imports, no external URLs in assets, server binds `127.0.0.1` | N1, N8 | ruff ban rule, template scan, app config assertion |
| OR-12 | Board and MCP produce identical payloads and identical DB state for the same operations | intend §8, §14 | `ACC-D` step 5; `DSH` error-payload comparisons |

---

## 7. Numeric caps (single source of truth)

Every value below is asserted at its boundary: `limit` passes, `limit + 1` fails.

| Item | Cap | Enforced in | Test suite |
|---|---|---|---|
| Task title | non-empty, ≤200 chars | `repository.py` | `REP` |
| `description` / `design` | ≤4000 chars | `repository.py` | `REP` |
| Priority | integer 1–5 | schema + repository | `REP`, `DB` |
| `outcome` | non-empty, ≤500 chars | `repository.py` | `TR` |
| `block_reason` | non-empty, ≤500 chars | `repository.py` | `TR` |
| Journal body | ≤6 lines; long-body guard rejects 1600 chars (T09) | `repository.py` | `JN` |
| Context entry | ≤400 chars | `repository.py` | `CTX` |
| Context retention per story | 20 entries; returned payload ≤~2000 chars | `repository.py` | `CTX` |
| Checkpoint summary | ≤60 lines | `repository.py` | `SES` |
| `next_actions` item | ≤300 chars | `repository.py` | `SES` |
| `checkpoint_latest(n)` | ≤20 | `repository.py` | `SES` |
| `task_query(limit)` | ≤50 (default 20) | `repository.py` | `REP` |
| `resume` payload | ≤5200 chars and ≤1300 est. tokens (`ceil(len/4)`) | `resume.py` | `RES`, `ACC-C` |
| `resume.ready` | ≤10 | `resume.py` | `RES` |
| `resume.waiting_on` | ≤10 | `resume.py` | `RES` |
| `resume.recent` | ≤8 | `resume.py` | `RES` |
| `resume.story_context` | ≤3 stories × ≤3 entries | `resume.py` | `RES` |
| `resume` truncations | checkpoint 500, `last_journal` 200, `recent` 120, `reason` 200, `next_actions` 5 items | `resume.py` | `RES` |
| Lease | 60 min default; per-workflow override (`feature` ≈90) | `transitions.py` / workflows | `TR`, `WF` |
| Staleness | no journal entry for >7 days on `in_progress` | `resume.py` | `RES` |
| Compaction warning | ≥2 compactions since the latest checkpoint | `resume.py`, prompts | `RES`, `PRM` |
| SQLite `busy_timeout` | 5000 ms | `db.py` | `DB` |

Degradation rule: when the character ceiling would still be exceeded after structural
caps, `resume` drops `recent`, then `story_context`, then `ready` — never a section
needed to resume (`in_progress`, `blocked`, `waiting_on`, `last_checkpoint`). A test
must assert both the ceiling and that the essential sections survive.

---

## 8. Acceptance tests (release contract)

All four run on every OS in CI. None may be skipped, retried, or marked flaky.

### 8.1 ACC-A — Cold resume

| | |
|---|---|
| Intent | intend §16 A |
| Test | `tests/test_acceptance.py::test_cold_resume` |
| Level | `L3` (in-memory MCP client) |
| Seed | `seed_mid_task` |
| Gate | M4 |

Procedure: new client session → `session_event(session_start)` → `resume("demo")`.

Assertions:

1. Task 1 appears in `in_progress` with `last_journal.body` equal to the seeded
   attempt line, verbatim.
2. `waiting_on` contains tasks 2 and 3 with `needs: [1]`.
3. `ready` contains task 4 and not tasks 2/3.
4. `last_checkpoint` is present with `next_actions`.
5. `task_next` returns task 4; after completing it, tasks 2 and 3 are still waiting.
6. **Anti-false-pass:** the "try narrowing to a concrete class" instruction must be
   recoverable from `in_progress[].last_journal` specifically — a payload that
   surfaces it only under `recent` fails the test. The instruction must not appear
   in any other task's data. Removing `last_journal` from `resume` must make this
   test fail.

### 8.2 ACC-B — No double work

| | |
|---|---|
| Intent | intend §16 B |
| Test | `tests/test_acceptance.py::test_no_double_work` |
| Level | `L5` (two real processes, `spawn`) |
| Seed | `seed_chain6` on a real file |
| Gate | M2 |

Procedure: two worker processes loop `task_next` → `task_start` → `task_complete`,
treating `LeaseConflict` as "try the next task".

Assertions:

1. Both workers exit normally; every task reaches `done`.
2. Exactly one actor id appears in each task's `outcome`.
3. `task_relations` are unchanged by execution.
4. No task's `outcome` was written twice and no completion journal entry appears twice.
5. **Anti-false-pass:** the test must fail if `task_start` drops `BEGIN IMMEDIATE`
   (verified once by mutation during review, not in CI).

Runtime target: <60 s on Windows, where process spawn dominates.

### 8.3 ACC-C — Bounded memory

| | |
|---|---|
| Intent | intend §16 C |
| Test | `tests/test_resume_budget.py::test_bounded_memory` (name fixed here — §16 D-2) |
| Level | `L2` + serialization |
| Seed | `seed_large` (50+ tasks) |
| Gate | M4 |

Assertions:

1. `len(json.dumps(payload, ensure_ascii=False)) <= 5200` and
   `ceil(len/4) <= 1300`.
2. Needed sections are present and non-empty; `ready ≤ 10` and only truly ready;
   `health.stale` contains the stale task; `compactions_since_checkpoint == 2`.
3. Truncation boundaries hold (§7).
4. Empty project returns a valid briefing with zero counts and empty lists.
5. `resume` by slug and by id return identical payloads.

### 8.4 ACC-D — One write path

| | |
|---|---|
| Intent | intend §16 D |
| Test | `tests/test_acceptance.py::test_one_write_path` |
| Level | `L4` + `L3` |
| Seed | `seed_parity` (two copies) |
| Gate | M6 |

Assertions:

1. A full project is driven through HTTP only: create tasks, link, start, block,
   unblock, start, complete, close.
2. Each illegal drag is refused with the same `error` and `message` a direct MCP call
   produces for the identical action (compare payloads, not status text).
3. `done` without outcome and `blocked` without reason are refused on both surfaces.
4. Replaying the same sequence through the MCP client on the identical seed yields an
   equal final snapshot (tasks, relations, journal kinds/actors).
5. Every final row satisfies the transitions table — no state an MCP client could not
   have produced.
6. `POST`/`DELETE` on journal entries return 404/405; the routes do not exist.

---

## 9. Per-task test inventory

Authoritative case lists live in each task file; this table is the map and the gate.
The implement-ready work packages that produce these suites are in
[docs/test-tasks/](./test-tasks/README.md) (`TT00`–`TT23`).

| Task | Suite | Test file(s) | Focus | Gate |
|---|---|---|---|---|
| T01 | `SMK` | `test_smoke.py` | package imports, `__version__`, `--help` lists `serve` and `dashboard` | M0 |
| T02 | `DB` | `test_db.py` | migration idempotency, pragmas, FK/cascade, CHECK constraints, FTS sync and skip path | M0 |
| T03 | `REP` | `test_repository.py` | config resolution order, validation matrix, `seq`, pagination cap, soft/hard delete, `task_get` shape | M0 |
| T04 | `MCP` | `test_mcp_tools.py` | `{ok, data}` envelope, camelCase aliases, structured errors, no escaping exceptions | M0 |
| T05 | `REL` | `test_relations.py` | self/cross-project/2-cycle/transitive cycle rejection, diamond legal, provenance kinds ignored, concurrent cycle race | M1 |
| T06 | `SCH` | `test_scheduler.py` | ready/waiting matrix, `require_closure`, cancelled blocker, `blocked` orthogonal to waiting, `task_next` ordering, filter parity | M1 |
| T07 | `TR` | `test_transitions.py` | every legal/illegal edge, missing outcome/reason, journal mirror, idempotent start, lease conflict, `force` release, reopen history, happy path | M2 |
| T08 | `LEASE` | `test_lease_reaping.py` | reap on read, unexpired untouched, concurrent reap winner, reaped task restartable, `require_closure` end-to-end | M2 |
| T09 | `JN` | `test_journal.py` | 6-line/1600-char boundary, project-level notes, cursor pagination, no edit/delete symbol, cascade | M3 |
| T10 | `CTX` | `test_context.py` | story-only append, nearest-story inheritance, 400-char boundary, 20-entry eviction, bounded payload | M3 |
| T11 | `RCL` | `test_recall.py` | journal/title/description hits, project scoping, quote handling, blank query, LIKE fallback, `FtsUnavailable` | M3 |
| T12 | `SES` | `test_sessions_checkpoints.py` | four event kinds, cross-project rejection, checkpoint idempotency, scoping, 60-line/300-char limits, `n` cap | M4 |
| T13 | `RES` | `test_resume_budget.py` | budget, truncation, `lease_left_min` math, empty project, slug/id parity | M4 |
| T14 | `WF` | `test_workflows.py` | built-ins, project override precedence, unknown → `NotFound`, malformed frontmatter, workflow lease default | M4 |
| T15 | `PRM` | `test_prompts.py` | three prompts registered, text encodes the §9 rituals, compaction warning | M4 |
| T16 | `HK` | `test_hooks.py` | branch naming/sanitising, opt-in only, worktree, commit-on-complete, non-git and missing-git graceful | M5 |
| T17 | `EXP` | `test_export.py` | Markdown completeness, EDNL round-trip, byte-stable ordering, read-only DB, story placement | M5 |
| T18 | `PKG` | `test_packaging.py` | `importlib.resources` finds workflows, migrations, dashboard assets; wheel install smoke | M5 |
| T19 | `DSH` | `test_dashboard.py` | routes, five columns, static assets, no external URLs, GET is read-only | M6 |
| T20 | `DSH` | `test_dashboard.py` | column placement, priority ordering, waiting badge not column, lease countdown, swimlanes, last journal line | M6 |
| T21 | `DSH` | `test_dashboard.py` | legal walk parity, illegal payload parity, takeover, create via `POST`, journal routes absent, graph, no raw SQL | M6 |
| T22 | `LINT`, `ACC-D` | `test_write_path_lint.py`, `test_acceptance.py` | write-statement scan, pragma guard, acceptance D, release sweep | M6 |

---

## 10. NFR verification (N1–N8)

| NFR | Automated check | Pass criterion |
|---|---|---|
| N1 no network | ruff ban on `requests`/`urllib` (TID251) plus an import scan of `src` for any HTTP client; dashboard bind assertion | no client imports in `src`; `127.0.0.1` default |
| N2 token discipline | `ACC-C` + §7 boundary tests | ceiling holds; caps fail closed |
| N3 idempotency | repeated-call cases for the four named operations | second call returns equal state, no extra row |
| N4 integrity | `TR`, `REL`, `SCH` | every illegal action raises a typed error |
| N5 portability | 3-OS matrix, `pathlib` only, spawn-based concurrency, Windows path cases | green on all three |
| N6 inspectability | `EXP` + SQL-only manual charter `MC-6` | full history readable from tables and export |
| N7 one write path | `LINT` + `sql_capture` + `ACC-D` | zero write SQL outside the two allowed modules |
| N8 offline dashboard | template/asset URL scan; asset serving test | zero external URLs, all assets 200 |

---

## 11. Traceability

### 11.1 Intent success metrics (§14) → tests

| Metric | Tests | Coverage note |
|---|---|---|
| New agent resumes with `resume` + one `task_get` | `ACC-A`, `RES` | direct |
| Zero duplicated tasks across sessions | `REP` (idempotent upsert), `RCL` (find before creating) | **partial** — duplication is a behaviour, not a state; see `MC-1` |
| Every `blocked` has a reason, every `done` an outcome | `TR`, OR-03 sweep | direct |
| `resume` bounded as the project grows | `ACC-C` at 50+ tasks | scale ceiling untested beyond 50 (§13.1) |
| Recall answers "did we try this?" | `RCL`, `JN` | direct |
| Two agents never run the same task | `ACC-B`, `LEASE` | direct |
| Human answers flight/stuck from the board alone | `DSH` (T20), `MC-2` | mixed |
| Board and MCP never disagree | `ACC-D`, OR-12 | direct |

### 11.2 Open questions (intend §15) with a testable resolution

| Q | Resolution in plan | Test |
|---|---|---|
| Q1 project identity | `.tasks/config.json` wins, else cwd slug; `root_path` recorded | `REP` config cases + **new** case: same repo from two cwds maps to one project |
| Q2 `closed` gate | default off; `require_closure` per project | `SCH` cases 3–5 |
| Q3 lease defaults | 60 min global; per-workflow override | `TR`, `WF` case 5 |
| Q4 multi-agent | per-task leases only (project lock deferred) | `ACC-B`; residual risk §13.1 |
| Q5 journal retention | never prune | `JN` (no delete symbol), cascade case |
| Q6 mirror | export on demand, read-only | `EXP` case 4 |
| Q7 workflow creation | unknown workflow → `NotFound`; no runtime authoring | `WF` case 3 |
| Q8 non-task memory | project-level journal entries | `JN` case 2 |
| Q9 done vs closed | dependents unblock per `require_closure` | `SCH` cases 3–5 |
| Q10 board mutation while leased | explicit takeover; other writes refused | `DSH` (T21) case 3 |
| Q11 board columns | five status columns, `cancelled` behind toggle | `DSH` (T19/T20) cases 1, 4 |
| Q12 live updates | polling; no external connection | `DSH` (T19) case 4; manual `MC-2` |

---

## 12. Defect severity and triage

| Severity | Definition | Examples | Effect |
|---|---|---|---|
| S1 | Data integrity or a release claim is false | write outside `repository.py`, double claim, illegal transition persisted, journal mutated, `resume` loses the journal tail | blocks release; `ACC-*` failure is always S1 |
| S2 | Invariant or contract violation without data loss | missing outcome accepted, cap not enforced, wrong typed error, board/MCP payload mismatch | blocks the phase gate |
| S3 | Behaviour correct, experience or format wrong | badge missing, swimlane grouping wrong, export ordering unstable | fix before release or record as known issue |
| S4 | Cosmetic/documentation | wording, README example | next change |

Rules: no test may be quarantined to get CI green; a skipped acceptance test is a
failed acceptance test; any new cap or invariant requires a new row in §6/§7 and a
traceability entry in the same PR.

---

## 13. Coverage gaps, risks, and manual testing

### 13.1 Known gaps (accepted or to be closed)

| Gap | Impact | Plan |
|---|---|---|
| Python 3.10 floor untested (T01 pins 3.12) | A floor claim with no evidence | add `test-floor` job or drop the floor claim (§16 D-4) |
| FTS5-absent path is only monkeypatched | A build without FTS5 could still fail at import/migration | acceptable: migration path is exercised by forcing `OperationalError`; a container without FTS5 is a stretch goal |
| WAL on network-synced home dirs (OneDrive) | Documented risk in development-plan §8 | manual charter `MC-6` with a OneDrive path; `$TASKS_DB` override is the mitigation |
| Budget uses `ceil(len/4)`, not a tokenizer | Budget is an estimate | document in `resume.py`; regression is caught by the char ceiling |
| 500+ task scale | `ACC-C` stops at 50+ | proposed non-blocking extension: same assertions at 500 tasks |
| No browser JS execution | Drag-and-drop handler unverified end-to-end | covered by HTTP-level tests plus `MC-2` |
| No load/soak/performance tests | "Sub-second" and "first paint <1s" are unmeasured | manual `MC-2`; add a loose perf smoke only if regressions appear |
| Project-level advisory lock not implemented | Concurrent plan mutation could interleave (Q4) | documented deferral; revisit after `ACC-B` under real agents |
| Security surface beyond localhost binding | No auth by design | assert bind address in `DSH`; document "do not expose" in README (T18) |

### 13.2 Manual charters (`L7`)

Each charter is timeboxed, has one question, and records pass/fail with evidence.

| ID | Charter | Timebox | Exit criterion |
|---|---|---|---|
| MC-1 | Cold resume with a real client (VS Code/Claude Desktop): kill mid-task, reopen, call `resume`, continue without re-deriving | 20 min | agent continues correctly and does not repeat the logged dead end |
| MC-2 | Run a full project from the board only (create, link, start, block, unblock, complete, close, journal) | 30 min | project finishes; no SQLite CLI used; illegal drops explain themselves |
| MC-3 | Install from wheel on a clean Windows machine; configure an MCP client; open the board | 30 min | zero-to-working without a repo checkout; survives reboot |
| MC-4 | Compaction ritual: trigger two compactions before a checkpoint | 15 min | prompt stops and demands a checkpoint or a split |
| MC-5 | Inspectability audit: answer "what is stuck and why", "what did we try", "who owns this" using only `sqlite3` queries | 20 min | all three answerable from tables; no opaque blobs |
| MC-6 | OneDrive/network-path DB: run a session on a synced folder | 15 min | either works or fails with the documented `SQLITE_IOERR` warning and the `$TASKS_DB` workaround |

---

## 14. Entry and exit criteria

### 14.1 Entry (per phase)

1. The phase's task files exist and their signatures are agreed.
2. Fixtures in §5 compile against the code under test.
3. CI matrix is green on the previous phase.

### 14.2 Exit (per phase)

| Phase | Exit criteria |
|---|---|
| M0 | `SMK`, `DB`, `REP`, `MCP` green; `ruff` clean; CLI `--help` smoke green |
| M1 | `REL`, `SCH` green; cycles rejected at link time with `CycleDetected` |
| M2 | `TR`, `LEASE` green; `ACC-B` green on all OSes |
| M3 | `JN`, `CTX`, `RCL` green; caps enforced at boundaries |
| M4 | `SES`, `RES`, `WF`, `PRM` green; `ACC-A` and `ACC-C` green |
| M5 | `HK`, `EXP`, `PKG` green; wheel installs on a clean machine |
| M6 | `DSH`, `LINT` green; `ACC-D` green; all four `ACC-*` pass in one run |

### 14.3 Release (v0.1.0)

1. `pytest -q` green on three OSes (plus the 3.10 job if adopted).
2. `pytest -q -k "cold_resume or no_double_work or bounded_memory or one_write_path"`
   green in one invocation.
3. `ruff check src tests` clean; write-path lint green.
4. Wheel built, installed in a clean venv, `--help` smoke green.
5. `MC-2` and `MC-3` executed and recorded.
6. No open S1/S2 defects; every S3 either fixed or listed as a known issue.

---

## 15. Test ID scheme and adding tests

Suite prefixes (`SMK`, `DB`, `REP`, `MCP`, `REL`, `SCH`, `TR`, `LEASE`, `JN`, `CTX`,
`RCL`, `SES`, `RES`, `WF`, `PRM`, `HK`, `EXP`, `PKG`, `DSH`, `LINT`, `ACC`) name the
owning task. Cross-cutting IDs are `OR-*` (invariants), `QO-*` (objectives), `MC-*`
(charters), `ACC-*` (acceptance).

A change is test-complete only when all that apply are true:

1. New or changed repository function → happy path, each typed error, each cap
   boundary, and idempotency where claimed.
2. New MCP tool → appears in `test_mcp_tools.py` with schema, envelope, alias, and
   structured-error cases; OR-02 holds (no `status` input).
3. New dashboard route or mutation → parity case against the MCP call, SQL-capture
   read-only assertion, and the corresponding `DSH` rendering assertion.
4. New field surfaced by `resume` → budget still passes and the field is truncated.
5. New timestamp or status write → OR-08 and `transitions.assert_transition` hold.
6. New cap → row added to §7 with a boundary test.
7. New file containing SQL → `test_write_path_lint.py` allows it explicitly, or the
   change is rejected.

---

## 16. Findings and decisions needed

These are documentation inconsistencies found while writing this plan. Each needs a
one-line decision so tests do not encode ambiguity.

| # | Observation | Proposed resolution |
|---|---|---|
| D-1 | development-plan §6 names acceptance B `test_no_double_claim`; T08 and the T22 sweep use `test_no_double_work` | standardise on `test_no_double_work` |
| D-2 | Acceptance C has no mandated test name, but the T22 sweep uses `-k bounded_memory` | name it `test_bounded_memory` |
| D-3 | development-plan §3.1 lists `test_memory.py` and `test_hooks_export.py`; task files use `test_journal.py`, `test_context.py`, `test_recall.py`, `test_hooks.py`, `test_export.py` | task-file names are authoritative (§4.2) |
| D-4 | Python floor is declared 3.10, CI pins 3.12 only | add a 3.10 job, or restate the floor as 3.12 |
| D-5 | intend §6 says ready tasks require blockers to be "done" when `require_closure`; T06 requires `closed` | lock T06 behaviour and correct the intent wording |
| D-6 | Journal cap reads "target ≤6 lines" in intend §9, while T09 rejects 7 lines and 1600+ chars | treat both as hard limits (§7) |
| D-7 | Budget is "~1200 tokens" in intend §7.7 and "≤1300 estimated / ≤5200 chars" in T13 | lock the T13 numbers and the `len/4` heuristic |
| D-8 | T03 defines `task_delete` (soft/hard) and T07 defines `task_cancel` as its successor | one public path: `task_cancel`; keep `task_delete` as a deprecated alias or remove it, and test only the survivor |
| D-9 | `pyproject.toml` currently has no pytest configuration | add markers, `testpaths`, and `pytest-timeout` (§4.3) |
| D-10 | development-plan §6 places acceptance D in `test_dashboard.py`; T22 defines it as `test_acceptance.py::test_one_write_path` | keep the acceptance test in `test_acceptance.py`, reuse `test_dashboard.py` helpers |
