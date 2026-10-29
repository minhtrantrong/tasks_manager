# T14 — Workflow templates + workflow_prompt

| | |
|---|---|
| Phase | M4 |
| Depends on | T04 |
| Unblocks | T15 |
| Size | S |
| Status | done |

## Goal

Workflows are data, not code: markdown prompt templates with a fixed resolution
order (built-ins → project overrides) and a `workflow_prompt` tool (intend §7.6,
§11; open question 7).

## Files

- `src/task_manager/workflows.py` — new.
- `src/task_manager/workflows/*.md` — 4 built-in templates (package data).
- `src/task_manager/server.py` — register 1 tool.
- `tests/test_workflows.py` — new.

## Template format

Frontmatter + prompt body:

```markdown
---
name: feature
description: Ship a feature end-to-end with tests
lease_minutes: 90
---
You are working on task {title} (#{id}) in project {project}.

1. Re-read the task description and design notes.
2. …
```

Frontmatter is a minimal parser (stdlib only, no yaml dependency): lines between
the first `---` and the next `---`, `key: value` pairs. Unknown keys ignored;
`name` and `description` required. Malformed frontmatter → `ValidationError` on
load (server refuses to serve a broken template).

Built-ins (ship as package data, included by the T01 hatchling globs):

| name | lease_minutes | purpose |
|---|---|---|
| `simple` | 30 | Single-session change, default workflow |
| `bugfix` | 60 | Reproduce → fix → verify |
| `feature` | 90 | Design → implement → test → document |
| `spike` | 120 | Time-boxed exploration, write up findings |

Each template's body must reference `{title}`, `{id}`, `{project}` placeholders and
must not exceed ~1200 chars.

## workflows.py contract

```python
def load_workflow(db, project_id, name) -> dict
    # returns {"name", "description", "lease_minutes", "prompt", "source"}
    # source ∈ {'builtin','project'}
    # Resolution order: project dir → built-ins.
    # Project dir: <project.root_path>/.tasks/workflows/<name>.md  (fallback to
    #   cwd/.tasks/workflows/<name>.md when root_path is None)
    # Built-in: task_manager/workflows/<name>.md
    # Unknown name → NotFound("unknown workflow '<name>'")

def list_workflows(db, project_id) -> list[dict]   # merged view, project overrides win
def render_prompt(template: str, *, title, task_id, project) -> str
```

`lease_minutes` from the template is what `task_start` should default to per
workflow — wire it: when `task_start` is called without an explicit
`lease_minutes`, look up the task's workflow and use its `lease_minutes` (fallback
60 on any load error, never crash the transition). This resolves open question 3.

Project-level workflow files may be **created by agents** (open question 7) via the
filesystem only — no tool is added for it in v1; document it in README (T18).

## MCP tool

- `workflow_prompt(project_id, name)` → `{ok, data: {name, description,
  lease_minutes, prompt, source}}`. Idempotent and side-effect-free (N3).

## Tests (`tests/test_workflows.py`)

1. All four built-ins load; `render_prompt` fills placeholders.
2. Project override: write `.tasks/workflows/simple.md` in a tmp project dir →
   `load_workflow` returns it with `source='project'` and the project's
   `lease_minutes`.
3. Unknown workflow → `NotFound`.
4. Malformed frontmatter (missing `name`, no closing `---`) → `ValidationError`.
5. `task_start` without `lease_minutes` uses the workflow's value (e.g. start a
   `feature` task → lease ≈ 90 min).
6. Override precedence across two project dirs (root_path vs cwd fallback).

## Done when

- The server is the single source of workflow truth and lease defaults come from
  templates (open questions 3 & 7 resolved as planned).
- Tests green on all CI OSes.
