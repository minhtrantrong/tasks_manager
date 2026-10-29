# T17 — Export: Markdown + EDNL mirror

| | |
|---|---|
| Phase | M5 |
| Depends on | T09 |
| Unblocks | — |
| Size | S |
| Status | done |

## Goal

Human-readable reviewability on demand without giving up queryability (intend §11
"Human diffing", open question 6: export now, mirror never).

## Files

- `src/task_manager/export.py` — new.
- `src/task_manager/server.py` — register 1 tool.
- `tests/test_export.py` — new.

## export.py contract

```python
def export_project(db, project_id, *, fmt="markdown", path=None) -> str | Path
    # fmt ∈ {'markdown','ednl'}; path=None → returns the text; path given → writes
    # UTF-8 and returns the Path. Read-only with respect to the database.
```

**Markdown layout** (deterministic ordering everywhere: `priority, seq, id`):

```markdown
# Project: <slug> (<name>)

> exported <utc timestamp> · open 4 · in_progress 1 · blocked 1 · done 2

## In progress
### #12 — Fix plugin loader crash  [feature, p2, owner=agent-7]
**Outcome:** —
- journal (attempt, 2026-…): mypy --strict fails …
- blocked by: #9 (if any)

## Open
…

## Blocked
…  **Reason:** <block_reason>

## Done / Closed / Cancelled
…

## Checkpoints
- 2026-… — <first line of summary>
```

Include for every task: title, type, workflow, priority, owner, status, seq,
outcome/reason, relations (`blocked by #id`, `related #id`, `discovered during
#id`), and its journal entries (oldest-first). Story tasks additionally list
`context` entries.

**EDNL layout:** one fact per line (machine-parseable):

```
project <id> slug <slug>
task <id> title <title> status <status> priority <n> workflow <w> seq <s>
relation <task_id> blocked_by <related_id>
journal <id> task <task_id> kind <kind> body <body-escaped-newlines-as-\n>
context <id> task <task_id> body <body>
checkpoint <id> project <project_id> summary <first-line>
```

## MCP tool

- `export(project_id, fmt='markdown', path=None)` → `{ok, data: {path, preview}}`
  (`preview` = first 1000 chars when path given; full text when path=None).
  Document in the tool docstring that export never writes to the DB.

## Tests (`tests/test_export.py`)

1. Seeded project → Markdown contains every task title, every journal body, block
   reasons, and relation lines.
2. EDNL output round-trip: parse the lines and assert every task/journal/relation
   row from the DB is represented exactly once.
3. Ordering is stable across two runs (byte-identical output).
4. `path=` writes UTF-8; DB row counts unchanged after export (export is read-only).
5. Story context appears under story tasks only.

## Done when

- A human can review a project's full history from plain text; the DB is provably
  untouched by export.
- Tests green on all CI OSes.
