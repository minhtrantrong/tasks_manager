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

## Oracles exercised

OR-10 (`workflow_prompt`), Q3/Q7 resolutions (plan §11.2), N5 (path handling).

## Done when

- `pytest tests/test_workflows.py -q` green on all three OSes.
- No test depends on the process cwd for workflow resolution.
