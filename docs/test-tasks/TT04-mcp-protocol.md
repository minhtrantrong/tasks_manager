# TT04 — MCP protocol: schemas, envelopes, errors

| | |
|---|---|
| Suite | `MCP` |
| Verifies | [T04](../tasks/T04-mcp-server-core.md) |
| Phase | M0 |
| Depends on | TT03 |
| Unblocks | TT05, TT07, TT09, TT10, TT12, TT14, TT19 |
| Level | L3 |
| Size | M |
| Status | pending |

## Goal

Prove the tool surface an agent actually sees: complete for the intent's families,
typed, camelCased, and incapable of leaking an exception as a transport error.

## Files

- `tests/test_mcp_tools.py` — new (in-memory session per T04).

## Cases

1. Round-trip over a real client session: `project_upsert` → `task_add` →
   `task_query` returns the added task with the expected fields.
2. Every registered tool returns `{"ok": true, "data": ...}` on success; no tool
   returns a bare value or raises.
3. Aliases: model output uses camelCase (`leaseExpiresAt`, `blockReason`,
   `projectId`); snake_case keys are absent from JSON output.
4. Error contract: bogus id → `{"ok": false, "error": "NotFound", "message": ...}`;
   blank title → `"ValidationError"`; the `error` value equals the exception class
   name for every typed error in `errors.py`.
5. Inventory: the tool list covers exactly the tool names in intend §7.1–§7.6
   (subset check per family, no duplicates); every tool has a non-empty
   description and a JSON schema.
6. OR-02: no tool input schema contains a `status` property, and none accepts
   `waiting` as an input. `task_complete` is the only tool with `outcome`;
   `task_block` the only one with `reason`.
7. Schema rejection: `priority` as a string, a missing required argument, and an
   unknown argument each produce a structured error rather than a crash, and no
   row is written.
8. Failure atomicity: a failed `task_add` (invalid parent) leaves the task count
   unchanged.
9. Server startup with an unreadable `$TASKS_DB` path returns a structured error
   from tools rather than crashing the process.

## Oracles exercised

OR-02, OR-10 (tool-level retry), N1 (in-memory transport only).

## Done when

- `pytest tests/test_mcp_tools.py -q` green on all three OSes.
- Every later tool registration task adds its cases here before its own suite.
