# T22 — Acceptance D, write-path lint, release

| | |
|---|---|
| Phase | M6 |
| Depends on | T21 |
| Unblocks | — |
| Size | M |
| Status | pending |

## Goal

Close the loop: prove the one-write-path claim end-to-end (acceptance D), make N7
and N8 mechanically enforced in CI, and cut v0.1.0.

## Files

- `tests/test_acceptance.py` — add `test_one_write_path`.
- `tests/test_write_path_lint.py` — new.
- `.github/workflows/ci.yml` — confirm final matrix runs everything.
- `README.md` — release notes section (if any gaps from T18).

## Acceptance test D — `test_acceptance.py::test_one_write_path`

1. Seed a project (repository calls allowed for seeding only): 4 tasks, one
   dependency edge, one story with a child.
2. **Drive everything through the board** (`TestClient`): add 2 tasks via
   `POST /tasks`, link them (`POST /transitions` has no link action — expose link
   in the detail panel as `POST /tasks/{id}/links` calling `task_link`; add this
   route here if T21 omitted it), start/complete/block/unblock/close per T21.
3. Assert the final DB state is exactly what the HTTP calls produced — and
   **no state an MCP client could not have produced**: every task's
   status/owner/outcome/reason trace back to a valid transition (replay the audit
   by asserting each row satisfies the transitions table).
4. Illegal drags during the run were refused with the same `error` + `message` a
   direct MCP tool call produces for the same action (call the MCP in-memory
   client for the identical illegal action and compare payloads).
5. Re-run the identical sequence via the MCP in-memory client on an identical
   seed; assert the two final DB snapshots are equal (row-for-row on tasks,
   relations, journal kinds/actors where deterministic).

## Write-path lint — `tests/test_write_path_lint.py`

Mechanical N7 enforcement, run in CI forever:

- Scan every `src/task_manager/**/*.py` for SQL write statements with a regex like
  `(?i)\b(insert\s+into|update\s+|delete\s+from)\s+` on file text.
- Allowed files: `repository.py`, `db.py` (pragmas + migrations runner), and
  nothing else. Any other file containing a write statement → test fails with the
  offending file/line.
- Also assert `PRAGMA journal_mode` is never executed on a per-request connection
  more than once (sanity guard against connection-factory regressions).

## Final sweep (do not skip)

1. Run the full suite on Windows locally: `ruff check src tests && pytest -q`.
2. Re-verify the four acceptance gates by name: `pytest -q -k "cold_resume or
   no_double_work or bounded_memory or one_write_path"` — all must pass.
3. Confirm N8 test (no external URLs) still green; confirm the T13 budget test
   still green (N2).
4. `python -m build` + install the wheel + `task-manager --help` smoke (T18 job
   covers it in CI; repeat locally on Windows).
5. Update `docs/tasks/README.md` statuses to `done` for all tasks and record the
   release tag in this file's footer.

## Release

- Bump `__version__` to `0.1.0`, tag `v0.1.0` on main after CI is green on all
  three OSes.
- The project's definition of done (intend §16): all four acceptance tests pass —
  this task's green CI run is that proof.

## Done when

- Acceptance D passes; N7/N8 are enforced by failing tests, not conventions;
  `v0.1.0` is tagged with a green full CI matrix.
