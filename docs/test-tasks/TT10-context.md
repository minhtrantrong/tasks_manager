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

## Oracles exercised

OR-07 (400-char cap, 20-entry retention, payload bound), N2.

## Done when

- `pytest tests/test_context.py -q` green on all three OSes.
- Inheritance cases fail if the nearest-story walk is replaced by a direct-parent
  lookup.
