# Test Task Breakdown — Tasks Manager MCP

Implement-ready test work packages derived from [test-plan.md](../test-plan.md).
Each `TTxx` verifies the implementation task `Txx` in [docs/tasks/](../tasks/README.md).

## Conventions

- **IDs** — `TT00`…`TT23` in execution order. `TT00` is the shared harness; the
  remaining IDs mirror the implementation task they verify (`TT07` verifies `T07`).
- **Status** — `pending` → `in_progress` → `done`; `blocked` with a reason if stuck.
  Update the row below and the task file together.
- **Suite prefixes** — from [test-plan.md](../test-plan.md) §15 (`SMK`, `DB`, `REP`,
  `MCP`, `REL`, `SCH`, `TR`, `LEASE`, `JN`, `CTX`, `RCL`, `SES`, `RES`, `WF`, `PRM`,
  `HK`, `EXP`, `PKG`, `DSH`, `LINT`, `ACC`). Cite a case as `TT07/3`.
- **Done** — a test task is `done` only when every case in its file passes on Windows,
  macOS, and Linux, the oracles it lists still hold, **and** its evidence folder
  `docs/test-reports/<Test-ID>/` is complete (report, log, screenshots, video).
- **No production code** — a test task may not change `src/`. If a test needs a seam
  (clock, SQL capture, bind address), the change is requested from the owning `Txx`.
- **Disagreements** — when code and plan contradict each other, the test task records
  the discrepancy against the open item in [test-plan.md](../test-plan.md) §16 and
  blocks rather than encoding a guess.

## Execution and evidence

Every test task states, in this order, the fields a tester needs to run it without
asking questions:

| Section | Must answer |
|---|---|
| `Test environment` | Terminal CLI command(s) and/or the dashboard base URL (`http://127.0.0.1:8765`), the install extra, env vars, and platform prerequisites |
| `Test data` | The fixtures and seeds used, plus every literal the cases depend on (boundary strings, ids, timestamps, JSON payloads). "None" only when the case is genuinely data-free |
| `How to test` | Numbered, copy-pasteable steps from a clean checkout to the verdict |
| `Expected results` | One row per case (or case group) with the observable pass criterion and the failure it is designed to catch |
| `Test artifacts` | The `<Test-ID>` folder contents: `test-report.md`, `pytest.log`, `screenshots/`, `video/`, and what each file must show |

Evidence standard — folder layout, naming, capture commands per OS, the
`test-report.md` template, and the per-run checklist — lives in
[test-reports/README.md](../test-reports/README.md). Two rules are non-negotiable:

1. **Screenshots are embedded.** Every file in `screenshots/` appears in
   `test-report.md` with a caption naming the case it proves.
2. **One video per test task.** `video/<Test-ID>-<slug>.mp4` records the same steps
   as *How to test* and ends on the pass/fail verdict.

## Task list

| ID | Phase | Test package | Suite | Verifies | Depends on | Level | Size | Status |
|---|---|---|---|---|---|---|---|---|
| [TT00](TT00-test-infrastructure.md) | M0 | Harness: fixtures, seeds, markers | — | plan §4.3, §5 | T01, T02 | L1–L4 | M | pending |
| [TT01](TT01-smoke-cli.md) | M0 | Package import and CLI smoke | SMK | T01 | TT00 | L6 | S | pending |
| [TT02](TT02-db-layer.md) | M0 | Schema, migrations, FTS5 | DB | T02 | TT00 | L2 | M | pending |
| [TT03](TT03-repository-core.md) | M0 | Config, projects, task CRUD | REP | T03 | TT02 | L1–L2 | L | pending |
| [TT04](TT04-mcp-protocol.md) | M0 | Tool schemas and envelopes | MCP | T04 | TT03 | L3 | M | pending |
| [TT05](TT05-relations.md) | M1 | Cycles, links, graph | REL | T05 | TT04 | L2–L5 | M | pending |
| [TT06](TT06-scheduler.md) | M1 | Ready/waiting, `task_next` | SCH | T06 | TT05 | L1–L2 | M | pending |
| [TT07](TT07-lifecycle-transitions.md) | M2 | State machine and requirements | TR | T07 | TT04 | L1–L2 | L | pending |
| [TT08](TT08-lease-reaping-double-work.md) | M2 | Reaping and acceptance B | LEASE, ACC-B | T08 | TT07 | L2–L5 | M | pending |
| [TT09](TT09-journal.md) | M3 | Append-only journal and caps | JN | T09 | TT04 | L2 | S | pending |
| [TT10](TT10-context.md) | M3 | Story context and inheritance | CTX | T10 | TT04 | L2 | S | pending |
| [TT11](TT11-recall.md) | M3 | FTS5 search and LIKE fallback | RCL | T11 | TT09 | L2 | S | pending |
| [TT12](TT12-sessions-checkpoints.md) | M4 | Session events, checkpoints | SES | T12 | TT04 | L2 | S | pending |
| [TT13](TT13-resume-budget.md) | M4 | `resume` assembly, acceptance C | RES, ACC-C | T13 | TT08, TT09, TT12 | L2 | M | pending |
| [TT14](TT14-workflows.md) | M4 | Templates and lease defaults | WF | T14 | TT04 | L1–L2 | S | pending |
| [TT15](TT15-prompts-cold-resume.md) | M4 | MCP prompts, acceptance A | PRM, ACC-A | T15 | TT13, TT14 | L3 | M | pending |
| [TT16](TT16-git-hooks.md) | M5 | Opt-in hooks and graceful failure | HK | T16 | TT07 | L2 | M | pending |
| [TT17](TT17-export.md) | M5 | Markdown/EDNL export | EXP | T17 | TT09 | L2 | S | pending |
| [TT18](TT18-packaging.md) | M5 | Wheel contents and install | PKG | T18 | TT15 | L6 | M | pending |
| [TT19](TT19-dashboard-skeleton.md) | M6 | App, assets, offline rule | DSH | T19 | TT04 | L4 | M | pending |
| [TT20](TT20-dashboard-board.md) | M6 | Board rendering | DSH | T20 | TT19, TT06, TT08 | L4 | L | pending |
| [TT21](TT21-dashboard-mutations.md) | M6 | Drag parity, takeover, journal UI | DSH | T21 | TT20, TT07 | L4 | L | pending |
| [TT22](TT22-acceptance-d-write-path.md) | M6 | Acceptance D and N7 lint | LINT, ACC-D | T22 | TT21 | L0, L4 | M | pending |
| [TT23](TT23-release-gate.md) | M6 | Release verification and charters | ACC, MC | T22 | TT22 | L7 | S | pending |

## Execution order

```
M0: TT00 → TT01 → TT02 → TT03 → TT04
M1: TT04 → TT05 → TT06
M2: TT04 → TT07 → TT08
M3: TT04 → TT09 → TT11     (TT10 independent of TT09)
M4: TT04 → TT12 → TT13 → TT15 ;  TT04 → TT14 → TT15
M5: TT07 → TT16 ;  TT09 → TT17 ;  TT15 → TT18
M6: TT04 → TT19 → TT20 → TT21 → TT22 → TT23
```

`TT10` runs in parallel with `TT09`. M5 and M6 may run in parallel once their
dependencies are met.

## Gates

| Gate | Required green | Blocks |
|---|---|---|
| M0 | TT00–TT04 | start of M1 |
| M1 | TT05, TT06 | start of M2 |
| M2 | TT07, TT08 (incl. ACC-B) | start of M3 |
| M3 | TT09, TT10, TT11 | start of M4 |
| M4 | TT12, TT13, TT14, TT15 (incl. ACC-A, ACC-C) | start of M5/M6 |
| M5 | TT16, TT17, TT18 | release |
| M6 | TT19–TT22 (incl. ACC-D) | release |

## Final gate

The four acceptance tests must pass in one invocation on all three OSes:
`pytest -q -k "cold_resume or no_double_work or bounded_memory or one_write_path"`,
plus the manual charters in [TT23](TT23-release-gate.md).
