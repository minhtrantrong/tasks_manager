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

## Oracles exercised

OR-11 (no network at import), plan §1.2 (no DB requirement for `--help`).

## Done when

- `pytest tests/test_smoke.py -q` green on all three OSes.
- The `python -m` and console-script paths are both covered.
