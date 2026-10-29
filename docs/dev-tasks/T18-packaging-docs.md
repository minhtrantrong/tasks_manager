# T18 — Packaging (uvx / pipx) + README rewrite

| | |
|---|---|
| Phase | M5 |
| Depends on | T15 |
| Unblocks | — |
| Size | S |
| Status | done |

## Goal

`uvx task-manager` and `pipx install .` work out of the box; README becomes the
user-facing manual (intend M5: survives reboot, documented).

## Files

- `pyproject.toml` — finalise metadata.
- `README.md` — full rewrite.
- `.github/workflows/ci.yml` — add a packaging job.

## pyproject.toml finalisation

- Complete `[project]`: description (intend's one-liner), authors, license
  (MIT), `readme = "README.md"`, `requires-python = ">=3.10"`, keywords
  (`mcp`, `tasks`, `kanban`, `sqlite`), classifiers.
- Confirm hatchling package-data globs from T01 actually ship: build a wheel and
  assert `workflows/*.md`, `migrations/*.sql`, and `dashboard/templates|static`
  are inside it (write a test or a CI step that lists wheel contents).
- Console script `task-manager` already wired (T01); verify `serve` and
  `dashboard` subcommands surface in `--help`.

## README rewrite (user manual, not intent prose)

Sections, in order:

1. One-paragraph pitch + the intent's one-liner.
2. **Install** — `pipx install .` and `uvx task-manager`; prerequisites (Python
   ≥ 3.10; FTS5 ships with stdlib).
3. **Quick start** — create a project, add tasks, link them, start one (copy-paste
   MCP tool calls or a tiny JSON-RPC example).
4. **MCP client config** — a working snippet for VS Code / Claude Desktop:
   `{"mcpServers": {"task-manager": {"command": "task-manager", "args": ["serve"]}}}`
   (adjust command name per platform).
5. **Storage** — `$TASKS_DB` → `.tasks/config.json` → `~/.tasks_manager/tasks.sqlite`
   resolution order.
6. **Workflows** — built-ins table (T14), overriding via `.tasks/workflows/*.md`,
   and that agents may author project-level templates.
7. **Git hooks** — off by default; enable via `.tasks/config.json` hooks block (T16).
8. **Dashboard** — `task-manager dashboard`, binds `127.0.0.1:8765`, no auth, for
   the person with the repo checked out.
9. **Agent rituals** — the three MCP prompts (T15) and when to use them.
10. **Rules agents must follow** — condensed §13 anti-pattern list.
11. **Development** — `pip install -e ".[dev]"`, test/lint commands, task index at
    `docs/tasks/README.md`.

## CI packaging job

New job `package` (ubuntu, runs after tests): `pip install build`, `python -m
build`, install the wheel into a clean venv, run `task-manager --help` and
`python -m task_manager --help` (exit 0, subcommands listed). Reuse the T01 smoke
assertions against the **wheel**, not the source checkout.

## Tests

- `tests/test_packaging.py`: locates package resources via `importlib.resources`
  (workflows, migrations, dashboard assets) — these assertions are what make the
  wheel-content CI check meaningful.

## Done when

- The wheel installs cleanly and runs on a machine with only Python installed;
  README lets a new user (agent or human) go from zero to a working board.
- CI green on all OSes including the packaging job.
