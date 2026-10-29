"""Command-line interface for task-manager."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_config
from .db import Database


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


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return _serve()
    if args.command == "dashboard":
        raise NotImplementedError("implemented in T19")

    parser.print_help()
    return 0
