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

## Test environment

| | |
|---|---|
| Surface | Terminal CLI (`pytest`) with an in-memory MCP client session; no URL, no socket |
| Command | `python -m pytest tests/test_mcp_tools.py -v` |
| Setup | `python -m pip install -e ".[dev]"` (`mcp` is a runtime dependency) |
| Env | `TASKS_DB=<repo>\.tmp-tt04\tasks.sqlite` for the optional stdio smoke only |
| Prereqs | CPython 3.12; `mcp.shared.memory.create_connected_server_and_client_session` importable |
| Optional | Real stdio check: `task-manager serve` with `TASKS_DB` set, driven by an MCP client over stdin |

## Test data

- Happy path: `project_upsert {"slug": "demo", "name": "Demo"}` then
  `task_add {"project_id": 1, "title": "Fix loader crash", "priority": 1}`.
- Aliases to assert: `leaseExpiresAt`, `blockReason`, `projectId`, `parentId`.
- Rejections: blank title `""`, `priority: "high"` (string), missing required
  argument, unknown argument `{"colour": "red"}`, bogus id `9999`.
- Unreadable start-up path for case 9: a directory created with no read/execute
  permission for the current user (Windows ACL or `chmod 000` on POSIX), used as
  `TASKS_DB`.
- Full tool inventory for case 5: the names in intend §7.1–§7.6, grouped per family.

## How to test

1. `python -m pytest tests/test_mcp_tools.py -v` with the recorder running.
2. Dump the registered tool list (name, description, input schema) into
   `attachments/tool-inventory.json` — case 5 and OR-02 evidence.
3. Run the envelope group alone: `-k "envelope or alias or error"`, and screenshot
   one `{"ok": false, ...}` payload and one `{"ok": true, ...}` payload.
4. Run `-k "schema or atomicity"` and confirm the failed `task_add` did not change
   the task count.
5. Optional stdio smoke: start `task-manager serve`, issue `initialize` +
   `tools/list` from an MCP client, and record the exchange in
   `attachments/stdio-session.txt`.

## Expected results

| Case | Expectation |
|---|---|
| 1 | the client round-trip returns the added task with the documented fields |
| 2 | every tool returns `{"ok": true, "data": …}` on success and never a bare value |
| 3 | JSON output uses camelCase (`leaseExpiresAt`, `blockReason`, `projectId`) and contains no snake_case key |
| 4 | bogus id → `{"ok": false, "error": "NotFound", "message": …}`; blank title → `ValidationError`; each typed error's `error` equals its class name |
| 5 | the inventory matches intend §7.1–§7.6 without duplicates; every tool has a non-empty description and a JSON schema |
| 6 | no input schema contains `status` or `waiting`; `task_complete` is the only tool with `outcome`, `task_block` the only one with `reason` |
| 7 | a string `priority`, a missing argument and an unknown argument each return a structured error, never a crash, and write no row |
| 8 | a failed `task_add` (invalid parent) leaves the task count unchanged |
| 9 | an unreadable `TASKS_DB` returns a structured tool error instead of killing the process |

## Test artifacts

Folder `docs/test-reports/TT04/` — layout and capture commands in
[test-reports/README.md](../test-reports/README.md).

| Path | Must show |
|---|---|
| `test-report.md` | verdict, 9 case rows, embedded screenshots, video link |
| `pytest.log` | full run plus the envelope and schema/atomicity selections |
| `screenshots/01-success-envelope.png` | a `{"ok": true, "data": …}` payload with camelCase keys |
| `screenshots/02-error-contract.png` | `NotFound` and `ValidationError` payloads side by side |
| `screenshots/03-tool-inventory.png` | the tool list with descriptions and schemas, `status` absent |
| `attachments/tool-inventory.json` | name/description/inputSchema for every registered tool |
| `attachments/stdio-session.txt` | optional `initialize` + `tools/list` exchange over real stdio |
| `video/TT04-mcp-protocol.mp4` | 30 s–5 min: suite, envelope/error group, inventory dump |

## Oracles exercised

OR-02, OR-10 (tool-level retry), N1 (in-memory transport only).

## Done when

- `pytest tests/test_mcp_tools.py -q` green on all three OSes.
- Every later tool registration task adds its cases here before its own suite.
- `docs/test-reports/TT04/` holds `test-report.md`, `pytest.log`,
  every screenshot embedded in the report, and the `video/TT04-mcp-protocol.mp4`
  recording.
