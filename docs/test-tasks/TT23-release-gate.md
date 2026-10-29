# TT23 — Release gate and manual charters

| | |
|---|---|
| Suite | `ACC`, `MC` |
| Verifies | [test-plan §13.2, §14.3](../test-plan.md) |
| Phase | M6 |
| Depends on | TT22 |
| Unblocks | release `v0.1.0` |
| Level | L7 |
| Size | S |
| Status | pending |

## Goal

Turn the plan's claims into recorded evidence, close the open decisions, and only
then tag the release.

## Files

- `docs/test-tasks/TT23-release-gate.md` — this file; fill the evidence table below.
- `docs/development-plan.md`, `docs/intend.md`, `docs/tasks/*.md` — only if a §16
  decision changes their wording.

## Cases

1. Full suite green on Windows, macOS, and Linux:
   `ruff check src tests && pytest -q`.
2. All four acceptance gates in one invocation on each OS:
   `pytest -q -k "cold_resume or no_double_work or bounded_memory or one_write_path"`.
3. Packaging evidence: wheel built, installed in a clean venv, `task-manager --help`
   and `python -m task_manager --help` both exit 0.
4. Decisions closed: every item in [test-plan §16](../test-plan.md) has a recorded
   resolution (D-1…D-10), and the docs that contradicted each other now agree.
   A resolution that is deferred must be written down as a post-v1 item.
5. Charter `MC-1` (cold resume with a real client) executed; evidence recorded.
6. Charter `MC-2` (whole project from the board only) executed; evidence recorded.
7. Charter `MC-3` (clean Windows install and MCP client configuration) executed;
   evidence recorded.
8. Charter `MC-4` (two compactions force a checkpoint or split) executed; evidence
   recorded.
9. Charter `MC-5` (inspectability with plain SQL) executed; evidence recorded.
10. Charter `MC-6` (OneDrive/network-path DB) executed; result and workaround
    recorded, including whether the `SQLITE_IOERR` warning fired.
11. Defect gate: no open S1/S2; every open S3 listed as a known issue with a
    severity label.
12. Version and tag: `__version__` equals the wheel version, the tag is `v0.1.0`,
    and it points at the commit whose CI run is linked below.
13. Traceability spot-check: pick three `QO-*` objectives and confirm the named
    evidence exists and is green in the linked run.

## Test environment

| | |
|---|---|
| Surface | Terminal CLI on three OSes, HTTP dashboard for the charters, wheel install |
| Base URL | `http://127.0.0.1:8765/board` (charters `MC-2`, `MC-3`) |
| Commands | `ruff check src tests`; `pytest -q`; `pytest -q -k "cold_resume or no_double_work or bounded_memory or one_write_path"`; `python -m build --wheel` |
| Setup | `python -m pip install -e ".[dev,dashboard]"`; clean venv under `tmp_path` for `MC-3` |
| Env | a real `TASKS_DB` under the tester's home for charters; `tmp_path` for the automated runs |
| Prereqs | Windows, macOS and Linux runners; a real MCP client (VS Code or Claude Desktop); `git`; `sqlite3` for `MC-5` |

## Test data

- No new fixtures: this task consumes the suites and seeds of TT00–TT22 exactly as
  they are.
- Charter inputs: a real project created only through the board (`MC-2`), a wheel
  installed on a clean Windows machine (`MC-3`), two compactions before a
  checkpoint (`MC-4`), `seed_large` for the inspectability queries (`MC-5`), and a
  OneDrive-synced directory as `TASKS_DB` (`MC-6`).
- Decision evidence: one row per item in [test-plan §16](../test-plan.md)
  (D-1 … D-10), each with a resolution and the file that now agrees.
- Traceability sample: three `QO-*` objectives and the evidence that proves each.

## How to test

1. Record the commit under test (`git rev-parse --short HEAD`) and start the screen
   recording.
2. Run `ruff check src tests` and `pytest -q` on Windows; capture the summary.
3. Run the same on macOS and Linux CI; capture the matrix page.
4. Run the four-gate selection in one invocation on each OS:
   `python -m pytest -q -k "cold_resume or no_double_work or bounded_memory or one_write_path"`.
5. Build the wheel, install it in a clean venv, and run both `--help` paths
   (packaging evidence).
6. Execute charters `MC-1` … `MC-6` in order, recording each in its own
   `attachments/mc-N.md` with a pass/fail line, timing and the screenshot names.
7. Fill the `## Evidence` table and the decision list; then tag `v0.1.0` from the
   commit whose CI run is linked.

## Expected results

| Case | Expectation |
|---|---|
| 1 | `ruff` clean and `pytest -q` green on all three OSes |
| 2 | the four acceptance gates pass in one invocation on each OS |
| 3 | wheel builds, installs in a clean venv, and both `--help` paths exit 0 |
| 4 | D-1 … D-10 each have a recorded resolution and the contradicting docs now agree |
| 5 | `MC-1` passes: a real client resumes after a kill and does not repeat the logged dead end |
| 6 | `MC-2` passes: a whole project is driven from the board with no SQLite CLI |
| 7 | `MC-3` passes: clean Windows install plus MCP client configuration reaches a working board |
| 8 | `MC-4` passes: the second compaction forces a checkpoint or a split |
| 9 | `MC-5` passes: "what is stuck and why", "what did we try" and "who owns this" are answerable in SQL |
| 10 | `MC-6` records whether the OneDrive path worked or failed with the documented `SQLITE_IOERR` and the `TASKS_DB` workaround |
| 11 | no open S1/S2; every open S3 is listed as a known issue |
| 12 | `__version__` equals the wheel version and tag `v0.1.0` points at the linked CI commit |
| 13 | three `QO-*` objectives trace to green evidence in the linked run |

## Test artifacts

Folder `docs/test-reports/TT23/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 13 case rows, the filled Evidence table, embedded screenshots, video link |
| `pytest.log` | local `pytest -q` run; alongside it `attachments/pytest-linux.log` and `attachments/pytest-macos.log` |
| `screenshots/01-full-suite-3-os.png` | the CI matrix with all three OS jobs green |
| `screenshots/02-acceptance-gates.png` | the four-gate selection passing in one invocation per OS |
| `screenshots/03-packaging-smoke.png` | the wheel build plus both `--help` paths in the clean venv |
| `screenshots/04-mc2-board-walk.png` | the board at the end of the board-only project (`MC-2`) |
| `screenshots/05-mc5-sql.png` | the three inspectability queries and their answers (`MC-5`) |
| `attachments/mc-1.md` … `attachments/mc-6.md` | one charter record each: question, timing, result, evidence |
| `attachments/decisions.md` | D-1 … D-10 with resolutions and the doc that changed |
| `attachments/release-notes.txt` | version, tag, commit, CI run link, known issues |
| `video/TT23-release-gate.mp4` | 30 s–5 min: local suite, acceptance gates, packaging smoke, the `MC-2` board walk |

## Evidence

| Item | Result | Evidence (run link / note) |
|---|---|---|
| Full suite, 3 OSes | | |
| Four acceptance gates | | |
| Packaging smoke | | |
| D-1 … D-10 closed | | |
| MC-1 | | |
| MC-2 | | |
| MC-3 | | |
| MC-4 | | |
| MC-5 | | |
| MC-6 | | |
| Open defects | | |

## Done when

- Every row above is filled with a result and a link or note.
- No S1/S2 defect is open; S3 items are documented.
- `v0.1.0` is tagged only after all of the above, never before.
- `docs/test-reports/TT23/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT23-release-gate.mp4`
  recording.
