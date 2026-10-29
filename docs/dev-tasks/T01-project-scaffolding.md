# T01 — Project scaffolding, CLI skeleton, CI

| | |
|---|---|
| Phase | M0 |
| Depends on | — |
| Unblocks | T02, T03, T04 |
| Size | M |
| Status | pending |

## Goal

A pip-installable `task-manager` package with an empty module tree, a `task-manager`
console script exposing `serve` and `dashboard` subcommands (stubs), and green CI on
Windows/macOS/Linux.

## Context

Everything else lands in this skeleton. CI runs from day one because N5
(Windows is a first-class target) is cheapest to keep honest continuously.

## Files to create

```
pyproject.toml
.github/workflows/ci.yml
src/task_manager/__init__.py
src/task_manager/__main__.py
src/task_manager/cli.py
src/task_manager/config.py      # stub — implemented in T03
src/task_manager/db.py          # stub — implemented in T02
src/task_manager/errors.py      # stub — implemented in T03
src/task_manager/repository.py  # stub — implemented in T03
tests/test_smoke.py
```

## pyproject.toml requirements

- Build backend: `hatchling`, `requires-python = ">=3.10"`, `src` layout
  (`packages = ["src/task_manager"]`).
- Project name `task-manager`, version `0.1.0`, short description matching the
  intent's one-liner, `readme = "README.md"`.
- Dependencies: `mcp>=1.2`, `pydantic>=2`.
- Optional extras:
  - `dev = ["pytest>=8", "ruff>=0.6", "httpx>=0.27"]`
  - `dashboard = ["fastapi>=0.115", "jinja2>=3.1", "uvicorn>=0.30"]` (used in M6;
    defined now so later tasks never edit this file for deps).
- Scripts: `task-manager = "task_manager.cli:main"`.
- Package data (hatchling): include `workflows/*.md`, `migrations/*.sql`,
  `dashboard/templates/**/*.html`, `dashboard/static/**` — these files don't exist
  yet; the globs are harmless.
- `[tool.ruff]`: `line-length = 100`, `target-version = "py310"`, lint rules
  `E, F, I, UP, B, RUF`.

## Implementation steps

1. Write `pyproject.toml` per the requirements above.
2. `cli.py`: argparse with two subcommands:
   - `serve` — placeholder that raises `NotImplementedError("implemented in T04")`
   - `dashboard` — placeholder that raises `NotImplementedError("implemented in T19")`
   `main()` returns the parser exit code; `__main__.py` calls `main()`.
3. `__init__.py`: `__version__ = "0.1.0"`.
4. Create the four stub modules with a module docstring each and no logic.
5. `.github/workflows/ci.yml`: trigger `push` + `pull_request`; matrix
   `os: [ubuntu-latest, windows-latest, macos-latest]`, `python-version: "3.12"`;
   steps: checkout → setup-python → `pip install -e ".[dev]"` → `ruff check src tests`
   → `pytest -q`.
6. `tests/test_smoke.py`: import package, assert `__version__`, run
   `subprocess.run([sys.executable, "-m", "task_manager", "--help"])` and assert
   exit 0 with both subcommands listed.

## Rules

- No runtime dependency on anything outside stdlib + `mcp` + `pydantic` (N1).
- `task-manager --help` must work with no database and no network.
- Nothing in this task may write to any database (no SQL anywhere yet).

## Done when

- `pip install -e ".[dev]"` succeeds on a clean checkout on Windows.
- `task-manager --help` and `python -m task_manager --help` list `serve` and
  `dashboard`.
- CI is green on all three OSes.
- `ruff check` is clean.
