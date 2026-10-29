# T04 — MCP server: Project + Task tool families

| | |
|---|---|
| Phase | M0 |
| Depends on | T03 |
| Unblocks | T05–T15, T19 |
| Size | M |
| Status | done |

## Goal

A stdio FastMCP server exposing the Project and Task tool families from intend.md
§7.1–7.2 as thin adapters over the repository, plus a scripted-client smoke test.

## Files

- `src/task_manager/server.py` — new.
- `src/task_manager/cli.py` — implement `serve` (replace the T01 stub).
- `tests/test_mcp_tools.py` — new.

## server.py

```python
mcp = FastMCP("task-manager")   # module-level singleton

def create_server(db_path: Path) -> FastMCP  # wires a Database bound to db_path
```

Tools to register (Pydantic-typed parameters, snake_case names exactly as below):

| Tool | Calls |
|---|---|
| `project_upsert(slug, name, root_path=None, description=None, require_closure=False)` | `repository.project_upsert` |
| `project_list()` | `repository.project_list` |
| `project_archive(project_id)` | `repository.project_archive` |
| `task_add(project_id, title, description=None, design=None, type='task', workflow='simple', priority=3, parent_id=None, blocked_by=None, prepend=False, meta=None)` | `repository.task_add` |
| `task_update(task_id, title=None, description=None, design=None, priority=None, workflow=None, parent_id=None, meta=None)` | `repository.task_update` |
| `task_get(task_id, journal_limit=5, context_limit=10)` | `repository.task_get` |
| `task_query(project_id=None, task_id=None, workflow=None, parent_id=None, type=None, status=None, text=None, waiting=None, ready=None, limit=20, offset=0)` | `repository.task_query` |
| `task_delete(task_id, hard=False)` | `repository.task_delete` |

**Error contract (used by every later task):**

- Tools catch `TaskManagerError` subclasses and return a structured result —
  `{"ok": False, "error": "<ErrorClassName>", "message": "<str(error)>"}` — and
  **do not** raise. MCP tool errors must be reserved for transport-level failures.
- Success returns `{"ok": True, "data": <model_dump(by_alias=True)>}`.
- `task_query` success returns `{"ok": True, "data": {items, total, offset, limit}}`.

Each tool opens one connection per call (`Database.connect()`), runs the repository
function, and closes it. Transactions are owned by the repository functions.

## cli.py

`serve` subcommand: resolve `Config.db_path` (T03), `migrate()`, then
`mcp.run(transport="stdio")` via `create_server`. Print nothing to stdout except
what the MCP transport requires (all logs to stderr).

## Tests (`tests/test_mcp_tools.py`)

Use the SDK's in-memory session so tests exercise real tool schemas without
spawning processes:

```python
from mcp.shared.memory import create_connected_server_and_client_session

async with create_connected_server_and_client_session(server) as (server_session, client_session):
    result = await client_session.call_tool("project_upsert", {...})
```

Cover:

1. `project_upsert` → `task_add` → `task_query` round-trip over the client session.
2. Every tool returns the `{ok, data}` shape; models serialize with camelCase
   aliases (`lease_expires_at` appears as `leaseExpiresAt` only where present).
3. `task_update` with a bogus `task_id` returns `{"ok": False, "error":
   "NotFound"}` — no exception escapes.
4. Structured-error contract: an invalid title returns
   `{"ok": False, "error": "ValidationError", "message": ...}`.
5. A `pytest.mark.anyio` event-loop test calling two tools sequentially on the same
   session.

Also add one subprocess smoke test (spawns `python -m task_manager serve`, sends the
JSON-RPC `initialize` handshake, expects a response) so the stdio path is proven.

## Rules

- Server tools contain **zero SQL and zero business logic** — call the repository.
- Never `print()` inside tools; logging via `logging` module to stderr.
- Tool docstrings must state side effects and the structured-error contract.

## Done when

- `task-manager serve` works over stdio; a scripted client can add and list tasks
  (intend M0 gate).
- All tests above green on all CI OSes.
