# TT18 — Packaging and installation

| | |
|---|---|
| Suite | `PKG` |
| Verifies | [T18](../tasks/T18-packaging-docs.md) |
| Phase | M5 |
| Depends on | TT15 |
| Unblocks | — |
| Level | L6 |
| Size | M |
| Status | pending |

## Goal

Prove the wheel is complete, installable on a machine with only Python, and exposes
the same behaviour as the source tree.

## Files

- `tests/test_packaging.py` — new.
- `.github/workflows/ci.yml` — packaging job (build, clean venv, smoke).

## Cases

1. `importlib.resources` locates `task_manager/migrations/*.sql`,
   `task_manager/workflows/*.md`, and `task_manager/dashboard/templates/**` plus
   `static/**` in the installed package.
2. The built wheel contains all declared package data (inspect the archive; no
   missing globs, no stray `__pycache__`).
3. Clean venv install of the wheel: `task-manager --help`, `python -m task_manager
   --help`, and `python -c "import task_manager"` all succeed.
4. Entry point metadata: `task-manager` maps to `task_manager.cli:main`.
5. Runtime dependency check: installed metadata requires only the declared runtime
   deps (`mcp`, `pydantic`); `fastapi`, `jinja2`, `uvicorn` come from the
   `dashboard` extra and their absence does not break `serve` or `--help`.
6. Installing the `dashboard` extra exposes `task-manager dashboard` without an
   `ImportError` (start with `--help`-equivalent or import the app factory; do not
   bind a port).
7. `uvx`/`pipx` install smoke runs in CI only (marked `packaging`, `slow`); locally
   the test skips with a reason.
8. Installed package migrates a fresh DB and serves one in-memory MCP tool call.
9. No network access during install-time import or `--help` (assert no socket).
10. The installed version matches `__version__` and the wheel filename.

## Oracles exercised

OR-11 (no network), N5 (Windows install), plan §14.3 release checklist.

## Done when

- `pytest tests/test_packaging.py -q` green on all three OSes, and the CI packaging
  job is green.
- Case 2 fails if a package-data glob regresses.
