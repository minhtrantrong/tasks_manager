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

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`, `python -m build`, a clean virtualenv) |
| Command | `python -m build --wheel`, then `python -m pytest tests/test_packaging.py -v` |
| Setup | `python -m pip install -e ".[dev]"` plus `build`; the clean venv is created under `tmp_path` |
| Env | no `TASKS_DB` (nothing may bind or migrate at import); `PIP_NO_INDEX=1` where offline installs are required |
| Prereqs | CPython 3.12; network for the first dependency resolution; `uvx` / `pipx` only in CI (case 7 skips locally) |

## Test data

- Wheel under test: `dist/task_manager-0.1.0-py3-none-any.whl` (version must match
  `task_manager.__version__`).
- Package data expected in the archive: `task_manager/migrations/*.sql`,
  `task_manager/workflows/*.md`, `task_manager/dashboard/templates/**` (`.html`)
  and `task_manager/dashboard/static/**`.
- Clean venv: `tmp_path/venv`, created with `venv --clear`, installed with
  `pip install <wheel>` and, in a second venv, `pip install <wheel>[dashboard]`.
- Entry-point metadata: `task-manager = task_manager.cli:main`.
- Runtime dependencies to assert: `mcp`, `pydantic` only; `fastapi`, `jinja2`,
  `uvicorn` must arrive solely through the `dashboard` extra.

## How to test

1. `python -m build --wheel` and record the artifact name and hash.
2. `python -m pytest tests/test_packaging.py -v` with the recorder running.
3. List the archive contents into `attachments/wheel-contents.txt`
   (`python -m zipfile -l dist\<wheel>` on any OS).
4. Create the clean venv, install the wheel, and run
   `task-manager --help`, `python -m task_manager --help`,
   `python -c "import task_manager"` — screenshot all three.
5. Repeat with the `dashboard` extra in a second venv and start
   `task-manager dashboard --help`-equivalent (import the app factory; do not bind
   a port).
6. In CI only, run the `uvx` / `pipx` smoke (case 7) and link the run.

## Expected results

| Case | Expectation |
|---|---|
| 1 | `importlib.resources` locates migrations, workflows, templates and static assets in the installed package |
| 2 | the wheel contains every declared package-data file, no missing glob and no `__pycache__` |
| 3 | in a clean venv, `task-manager --help`, `python -m task_manager --help` and `import task_manager` all succeed |
| 4 | the entry point maps `task-manager` to `task_manager.cli:main` |
| 5 | installed metadata requires only `mcp` and `pydantic`; `serve` and `--help` work with the dashboard extra absent |
| 6 | installing the `dashboard` extra exposes `task-manager dashboard` without an `ImportError` |
| 7 | the `uvx` / `pipx` smoke runs in CI and skips locally with a recorded reason |
| 8 | the installed package migrates a fresh DB and answers one in-memory MCP call |
| 9 | no network access during install-time import or `--help` |
| 10 | `__version__` equals the wheel version and the filename version |

## Test artifacts

Folder `docs/test-reports/TT18/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 10 case rows, wheel name/hash, venv Python version, embedded screenshots, video link |
| `pytest.log` | full packaging run plus the `uvx`/`pipx` skip reason (or CI link) |
| `screenshots/01-wheel-contents.png` | archive listing with migrations, workflows, templates and static assets |
| `screenshots/02-clean-venv-help.png` | all three clean-venv invocations succeeding |
| `screenshots/03-entry-point.png` | entry-point metadata plus the dependency list from `pip show` / `importlib.metadata` |
| `attachments/wheel-contents.txt` | full archive listing |
| `attachments/pip-list.txt` | installed packages in the clean venv, proving the extra split |
| `video/TT18-packaging.mp4` | 30 s–5 min: build, suite, clean-venv install, the three smoke commands |

## Oracles exercised

OR-11 (no network), N5 (Windows install), plan §14.3 release checklist.

## Done when

- `pytest tests/test_packaging.py -q` green on all three OSes, and the CI packaging
  job is green.
- Case 2 fails if a package-data glob regresses.
- `docs/test-reports/TT18/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT18-packaging.mp4`
  recording.
