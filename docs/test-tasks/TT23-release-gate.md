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
