# TT01 — Package import and CLI smoke

| | |
|---|---|
| Suite | `SMK` |
| Verifies | [T01](../tasks/T01-project-scaffolding.md) |
| Phase | M0 |
| Depends on | TT00 |
| Unblocks | TT02 |
| Level | L6 |
| Size | S |
| Status | pending |

## Goal

Prove the package is installed, importable, and exposes the two subcommands without
a database, a config file, or a network.

## Files

- `tests/test_smoke.py` — new.

## Cases

1. `import task_manager` succeeds; `task_manager.__version__ == "0.1.0"`.
2. `subprocess.run([sys.executable, "-m", "task_manager", "--help"])` exits 0 and
   lists both `serve` and `dashboard`.
3. The console script `task-manager --help` exits 0 (skipped with a clear reason
   when the script is not on `PATH`, e.g. running from a source tree).
4. `--help` works with no database: run with `TASKS_DB` pointing at a
   non-existent path and `HOME` redirected to `tmp_path`, then assert no file or
   directory was created anywhere.
5. `serve` and `dashboard` exist as parser choices: an unknown subcommand exits
   non-zero with a usage message.
6. Importing `task_manager` performs no network access and no database access
   (assert no socket created and no default DB file appears).

## Test environment

| | |
|---|---|
| Surface | Terminal CLI; no server, no browser |
| Command | `python -m pytest tests/test_smoke.py -v`, then the manual `--help` checks below |
| Setup | `python -m pip install -e ".[dev]"`; the console-script case needs a non-editable install or `pipx` / `uvx` |
| Env | `TASKS_DB=<repo>\.tmp-tt01\missing\tasks.sqlite` (must not exist) and `HOME` / `USERPROFILE=<repo>\.tmp-tt01\home` |
| Prereqs | CPython 3.12; no database, no `.tasks/config.json`, no network |

## Test data

- None by design: the empty `HOME` and the non-existent `TASKS_DB` path **are** the
  test data, because case 4 asserts nothing is created.
- Literals the cases assert on: version `0.1.0`, subcommand names `serve` and
  `dashboard`, an unknown subcommand `bogus`, and a non-zero exit code with a
  `usage:` line.
- Console-script probe: `task-manager` resolved from `PATH`; record the explicit
  skip reason when it is absent (source-tree runs).

## How to test

1. `python -m pip install -e ".[dev]"`.
2. Set `TASKS_DB` and `HOME` as above, then `python -m pytest tests/test_smoke.py -v`
   — cases 1, 2, 5, 6 must pass.
3. In the same shell run `python -m task_manager --help`; capture the help text,
   then prove no side effects:
   `Test-Path $env:TASKS_DB` → `False`, and `Get-ChildItem $HOME` → empty.
4. Run `task-manager --help` (console script). If it is not on `PATH`, record the
   skip reason instead of a pass.
5. Run `task-manager bogus` and record the exit code plus the usage text.
6. For case 6, run `python -c "import task_manager; print(task_manager.__version__)"`
   in a fresh interpreter and confirm no socket and no default DB file appear.

## Expected results

| Case | Expectation |
|---|---|
| 1 | `import task_manager` succeeds and `__version__ == "0.1.0"` |
| 2 | `python -m task_manager --help` exits 0 and lists both `serve` and `dashboard` |
| 3 | `task-manager --help` exits 0; otherwise a skip that names why the script is unavailable |
| 4 | after `--help`, neither the `TASKS_DB` path nor any file under the redirected `HOME` exists |
| 5 | `serve` and `dashboard` are parser choices; an unknown subcommand exits non-zero with `usage:` and `invalid choice` |
| 6 | importing the package opens no socket and creates no default database file |

## Test artifacts

Folder `docs/test-reports/TT01/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 6 case rows, embedded screenshots, video link |
| `pytest.log` | `pytest tests/test_smoke.py -v` output with the summary line |
| `screenshots/01-help-module.png` | `python -m task_manager --help` listing `serve` and `dashboard` |
| `screenshots/02-help-console.png` | the console-script help, or the recorded skip reason |
| `screenshots/03-unknown-subcommand.png` | `task-manager bogus` usage text and non-zero exit code |
| `attachments/no-side-effects.txt` | `Test-Path` / `ls $HOME` output proving case 4 |
| `video/TT01-smoke-cli.mp4` | 30 s–5 min: pytest run, both help paths, the unknown subcommand, the version print |

## Oracles exercised

OR-11 (no network at import), plan §1.2 (no DB requirement for `--help`).

## Done when

- `pytest tests/test_smoke.py -q` green on all three OSes.
- The `python -m` and console-script paths are both covered.
- `docs/test-reports/TT01/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT01-smoke-cli.mp4`
  recording.
