# TT14 — Workflow templates and lease defaults

| | |
|---|---|
| Suite | `WF` |
| Verifies | [T14](../tasks/T14-workflows.md) |
| Phase | M4 |
| Depends on | TT04 |
| Unblocks | TT15 |
| Level | L1 (parsing) + L2 (resolution) |
| Size | S |
| Status | pending |

## Goal

Prove workflows are data: four built-ins, project overrides with predictable
precedence, and lease defaults that come from the template rather than from code.

## Files

- `tests/test_workflows.py` — new.

## Cases

1. All four built-ins (`simple`, `bugfix`, `feature`, `spike`) load; each has a
   name, a body, and valid frontmatter; `render_prompt` fills every placeholder.
2. Project override: `.tasks/workflows/simple.md` under the project's `root_path`
   wins over the built-in; `source == "project"` and its `lease_minutes` is used.
3. Unknown workflow name → `NotFound`; an empty name → `ValidationError`.
4. Malformed frontmatter: missing `name`, missing closing `---`, non-integer or
   negative `lease_minutes` → `ValidationError` naming the file.
5. Lease default from the template: starting a `feature` task without an explicit
   `lease_minutes` produces a lease of ≈90 minutes; `simple` produces 60.
6. Explicit `lease_minutes` on `task_start` overrides the template.
7. Precedence across two project dirs: the override is resolved from the project's
   recorded `root_path`, not from the process cwd.
8. No runtime authoring: `workflow_prompt` never writes a file and there is no tool
   that creates a template (Q7).
9. `workflow_prompt` is retry-safe (N3): two calls return identical text.
10. A workflow referenced by a task but missing on disk surfaces a typed error on
    `workflow_prompt`, not a crash, and the task remains readable.

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_workflows.py -v` |
| Setup | `python -m pip install -e ".[dev]"`; project directories created under `tmp_path` |
| Env | `TASKS_DB=<repo>\.tmp-tt14\tasks.sqlite`; never rely on the process cwd for resolution |
| Prereqs | CPython 3.12; the four built-in templates shipped in the package |

## Test data

- Built-ins: `simple`, `bugfix`, `feature`, `spike` — each with `name`, body and
  valid frontmatter; placeholders filled by `render_prompt`.
- Project override at `<root_path>/.tasks/workflows/simple.md`:
  `---\nname: simple\nlease_minutes: 90\n---\n<custom body>`.
- Malformed variants: missing `name`, missing closing `---`, `lease_minutes: abc`,
  `lease_minutes: -5`.
- Two project dirs (`proj-a`, `proj-b`) each with its own override, to prove
  resolution follows the project's recorded `root_path`.
- Lease fixtures: `feature` ≈90 min, `simple` 60 min, explicit `lease_minutes=30`.
- Unknown name `"nope"`; empty name `""`; a task referencing `legacy` with no file.

## How to test

1. `python -m pytest tests/test_workflows.py -v` with the recorder running.
2. Run the built-ins group — `-k "builtin or render"` — and save each rendered
   prompt into `attachments/workflow-prompts.txt`.
3. Run the override group — `-k "override or precedence"` — with the process cwd
   set to a *different* directory, proving `root_path` decides.
4. Run the lease group — `-k "lease"` — showing 90 / 60 / explicit 30 minutes.
5. Run the error group — `-k "malformed or unknown or missing"`.

## Expected results

| Case | Expectation |
|---|---|
| 1 | all four built-ins load with name, body and valid frontmatter, and `render_prompt` fills every placeholder |
| 2 | a project override wins over the built-in with `source == "project"` and its `lease_minutes` in effect |
| 3 | an unknown workflow name raises `NotFound`; an empty name raises `ValidationError` |
| 4 | four malformed files each raise `ValidationError` naming the file |
| 5 | a `feature` task without an explicit lease gets ≈90 min; `simple` gets 60 |
| 6 | an explicit `lease_minutes` on `task_start` overrides the template |
| 7 | with two project dirs, the override resolves from the project's recorded `root_path`, not the cwd |
| 8 | `workflow_prompt` writes no file and no tool creates a template |
| 9 | two `workflow_prompt` calls return identical text (retry-safe) |
| 10 | a missing template surfaces a typed error on `workflow_prompt` and the task stays readable |

## Test artifacts

Folder `docs/test-reports/TT14/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 10 case rows, embedded screenshots, video link |
| `pytest.log` | full run plus the override, lease and error selections |
| `screenshots/01-builtins.png` | the four built-ins loading and rendering |
| `screenshots/02-project-override.png` | `source == "project"` with cwd elsewhere |
| `screenshots/03-lease-defaults.png` | 90 / 60 / explicit 30 minutes on the lease |
| `attachments/workflow-prompts.txt` | rendered prompt text for each built-in |
| `video/TT14-workflows.mp4` | 30 s–5 min: suite, built-ins, override, lease defaults, error group |

## Oracles exercised

OR-10 (`workflow_prompt`), Q3/Q7 resolutions (plan §11.2), N5 (path handling).

## Done when

- `pytest tests/test_workflows.py -q` green on all three OSes.
- No test depends on the process cwd for workflow resolution.
- `docs/test-reports/TT14/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT14-workflows.mp4`
  recording.
