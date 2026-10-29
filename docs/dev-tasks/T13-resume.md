# T13 — resume: briefing assembly + token budget (acceptance C)

| | |
|---|---|
| Phase | M4 |
| Depends on | T08, T09, T12 |
| Unblocks | T15 |
| Size | M |
| Status | pending |

## Goal

The flagship: `resume` returns a ≤ ~1200-token briefing that lets a fresh agent
continue without re-derivation (intend §7.7), proven bounded at 50+ tasks
(acceptance test C).

## Files

- `src/task_manager/resume.py` — new (assembly only; all data via repository).
- `src/task_manager/server.py` — register `resume`.
- `tests/test_resume_budget.py` — new (contains acceptance C).

## resume.py

```python
def build_resume(db, project_id) -> dict
```

Assembly steps, in order:

1. `repository.reap_expired_leases(db)` — keep track of reaped ids for `health`.
2. Header: project slug + counts `{open, waiting, blocked, in_progress, done}`.
3. `last_checkpoint`: latest 1 (T12); `summary` truncated to 500 chars + `…`;
   `next_actions` capped at 5.
4. `in_progress`: id, title, workflow, owner, `lease_left_min`
   (`max(0, ceil((lease_expires_at − now) / 60))`), and `last_journal`
   (kind + body truncated to 200 chars) — the most valuable line in the payload.
5. `blocked`: id, title, `reason` (truncated 200).
6. `waiting_on`: scheduler's waiting tasks → `{id, title, needs:[ids]}` (cap 10).
7. `ready`: scheduler's ready tasks, ≤ 10, fields id/title/workflow/priority.
8. `story_context`: stories that have context entries and have children: ≤ 3
   stories, ≤ 3 entries each, entries truncated to 200 chars.
9. `recent`: last 8 journal entries project-wide → `{kind, body≤120 chars, task_id,
   at}`.
10. `health`: `{stale: [ids], compactions_since_checkpoint: n, lease_expired: [ids]}`:
    - `stale` — `in_progress` whose latest journal entry is > 7 days old or missing;
    - `compactions_since_checkpoint` — count of `session_events` with kind
      `compaction` created after the latest checkpoint;
    - `lease_expired` — ids reaped in step 1.

**Budget (N2):** every list is structurally capped as above. Serialise with
`json.dumps(build_resume(...), ensure_ascii=False)` and enforce:

- hard ceiling `len(payload) <= 5200` chars; and
- token estimate `ceil(len(payload) / 4) <= 1300` (the char/4 heuristic stands in
  for a tokenizer; document it in the module docstring).

If the ceiling would be exceeded after caps, drop `recent` entries first, then
`story_context` stories, then `ready` items — always preferring smaller but
sufficient over complete.

## MCP tool

- `resume(project)` — `project` accepts a slug (string) or project id (int); resolve
  to `project_id`; unknown → `NotFound`. Returns `{ok, data: <briefing>}`.

## Tests (`tests/test_resume_budget.py`)

1. **Acceptance C fixture:** seed 50+ tasks across statuses — several
   `in_progress` with leases and journal tails, ~8 `blocked` with reasons, waiting
   chains, ready tasks, a checkpoint, session events (including 2 compactions after
   the checkpoint), one stale task (journal > 7 days old). Assert:
   - `resume` payload ≤ 5200 chars and ≤ 1300 estimated tokens;
   - all sections present and non-empty where expected;
   - `ready` ≤ 10 and contains only truly ready tasks;
   - `in_progress[].last_journal` present with the seeded body;
   - `health.stale` contains the stale task; `compactions_since_checkpoint == 2`.
2. Truncation: a 4000-char checkpoint summary comes back truncated to ≤ 500 + `…`.
3. `lease_left_min` math: lease set to expire in 20 min → `lease_left_min` 20
   (±1 for clock rounding); expired → reaped, task absent from `in_progress`,
   present in `health.lease_expired`.
4. Empty project → valid briefing with zero counts and empty lists (no crash).
5. `resume` by slug and by id return identical payloads.

## Done when

- A fresh agent gets everything needed in one call, within budget, at 50+ tasks
  (intend M4 gate, acceptance C green).
- Tests green on all CI OSes.
