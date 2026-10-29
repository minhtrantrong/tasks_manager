"""Command-line interface for task-manager."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .db import Database

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="task-manager",
        description="Durable, dependency-aware task graph plus reasoning journal for agents.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    subparsers.add_parser(
        "serve",
        help="Run the MCP server over stdio.",
        description="Run the MCP server over stdio.",
    )

    dashboard = subparsers.add_parser(
        "dashboard",
        help="Run the local kanban dashboard.",
        description="Run the local kanban dashboard.",
    )
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument("--allow-external", action="store_true")
    return parser


def _serve() -> int:
    from .server import create_server

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    config = load_config()
    database = Database(config.db_path)
    database.migrate()
    server = create_server(config.db_path)
    server.run(transport="stdio")
    return 0


def _dashboard(host: str, port: int, allow_external: bool) -> int:
    if host not in LOOPBACK_HOSTS and not allow_external:
        print(
            f"refusing to bind {host!r}: the dashboard is a local tool. "
            "Pass --allow-external if you really mean to expose it.",
            file=sys.stderr,
        )
        return 2
    try:
        import uvicorn

        from .dashboard.app import DEFAULT_HOST, DEFAULT_PORT, create_app
    except ImportError as exc:
        print(
            "the dashboard extra is not installed "
            f"({exc}); install it with: pip install 'task-manager[dashboard]'",
            file=sys.stderr,
        )
        return 2

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    config = load_config()
    database = Database(config.db_path)
    database.migrate()
    resolved_host = host or DEFAULT_HOST
    resolved_port = port or DEFAULT_PORT
    print(f"task-manager dashboard on http://{resolved_host}:{resolved_port}/board")
    uvicorn.run(create_app(config.db_path), host=resolved_host, port=resolved_port)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return _serve()
    if args.command == "dashboard":
        return _dashboard(args.host, args.port, args.allow_external)

    parser.print_help()
    return 0
