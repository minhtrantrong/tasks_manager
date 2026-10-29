# TT10 — Story context and inheritance

| | |
|---|---|
| Suite | `CTX` |
| Verifies | [T10](../tasks/T10-context.md) |
| Phase | M3 |
| Depends on | TT04 |
| Unblocks | — |
| Level | L2 |
| Size | S |
| Status | pending |

## Goal

Prove curated facts flow from a story to its descendants, stay short, and never leak
sideways.

## Files

- `tests/test_context.py` — new.

## Cases

1. `context_append` on a `story` succeeds; on a plain `task` raises
   `ValidationError` naming the task type.
2. A child's `task_get` includes the parent story's entries oldest-first.
3. Grandchild inheritance: story → child → grandchild shows the story's entries, not
   the child's.
4. Nearest-story rule: a child whose parent is a plain task and whose grandparent is
   a story inherits from the grandparent.
5. Boundary: 400 characters accepted, 401 rejected; whitespace-only rejected.
6. Retention: the 21st append evicts the oldest; 20 remain and the newest is present.
7. `story_context` on a story returns its own entries; a task with no story ancestor
   returns `[]`; a sibling story's context never appears.
8. Payload bound: a story with many maximum-size entries returns ≤~2000 characters
   (plan §7), and the truncation is deterministic across two calls.
9. `task_get` with `context_limit` smaller than the stored count returns the newest
   entries in oldest-first display order.
10. Hard-deleting the story removes its context rows; deleting a child does not
    affect the story's context.

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`); no server, no browser |
| Command | `python -m pytest tests/test_context.py -v` |
| Setup | `python -m pip install -e ".[dev]"` |
| Env | `TASKS_DB=<repo>\.tmp-tt10\tasks.sqlite`; frozen clock for retention order |
| Prereqs | CPython 3.12; no network |

## Test data

- Story `S` (`type='story'`), child `C` (parent `S`), grandchild `G` (parent `C`),
  and a sibling story `S2` for the leak check.
- Plain-task parent chain for case 4: story `S` → plain `task` → grandchild.
- Bodies: `"f" * 400` (accepted), `"f" * 401` (rejected), `"   "` (rejected).
- Retention fixture: 21 sequential appends to one story under a frozen clock.
- Payload fixture: a story with many maximum-size entries, called twice to compare
  the truncated output byte-for-byte.
- `context_limit=2` when 5 entries are stored (case 9).

## How to test

1. `python -m pytest tests/test_context.py -v` with the recorder running.
2. Run the inheritance group — `-k "inherit or nearest"` — and screenshot the story
   → child → grandchild result.
3. Run the cap group — `-k "boundary or retention"` — showing 400/401 and the 21st
   append evicting the oldest.
4. Run `-k "payload or limit or delete"` for the payload bound, the
   `context_limit` window and the cascade behaviour.
5. Save one `story_context` payload into `attachments/context-payload.json` with its
   character count recorded in the report (case 8).

## Expected results

| Case | Expectation |
|---|---|
| 1 | `context_append` succeeds on a `story` and raises `ValidationError` naming the type on a plain `task` |
| 2 | a child's `task_get` includes the story's entries oldest-first |
| 3 | a grandchild sees the story's entries and never the child's |
| 4 | with a plain-task parent, the nearest-story walk finds the grandparent story |
| 5 | 400 characters accepted, 401 rejected, whitespace-only rejected |
| 6 | the 21st append evicts the oldest; 20 remain and the newest is present |
| 7 | `story_context` returns the story's own entries, `[]` for a task with no story ancestor, and never a sibling story's entries |
| 8 | a many-entry story returns ≤~2000 characters and two calls are byte-identical |
| 9 | `context_limit` smaller than the stored count returns the newest entries, displayed oldest-first |
| 10 | hard-deleting the story removes its context rows; deleting a child leaves the story's context intact |

## Test artifacts

Folder `docs/test-reports/TT10/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 10 case rows, payload character count, embedded screenshots, video link |
| `pytest.log` | full run plus the inheritance and cap selections |
| `screenshots/01-inheritance.png` | story → child → grandchild entries and the nearest-story case |
| `screenshots/02-retention-21.png` | the 21st append evicting the oldest with 20 remaining |
| `screenshots/03-payload-bound.png` | payload length under the bound and identical on the second call |
| `attachments/context-payload.json` | the measured `story_context` payload |
| `video/TT10-context.mp4` | 30 s–5 min: suite, inheritance group, cap group, payload bound |

## Oracles exercised

OR-07 (400-char cap, 20-entry retention, payload bound), N2.

## Done when

- `pytest tests/test_context.py -q` green on all three OSes.
- Inheritance cases fail if the nearest-story walk is replaced by a direct-parent
  lookup.
- `docs/test-reports/TT10/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT10-context.mp4`
  recording.
