"""FastAPI app factory for the opt-in dashboard.

The app is a thin surface over :mod:`task_manager.repository`: it holds a
``Database`` path, opens connections through the same factory as the MCP server,
and never issues SQL itself (N7). Routes live in
:mod:`task_manager.dashboard.board` (read side) and
:mod:`task_manager.dashboard.mutations` (write side).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..db import Database
from .board import BOARD_COLUMNS
from .board import router as board_router

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

__all__ = [
    "BOARD_COLUMNS",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "LOOPBACK_HOSTS",
    "PACKAGE_DIR",
    "create_app",
    "get_db",
]


def get_db(request: Request) -> Database:
    """A per-request ``Database`` bound to the app's file (no pooled state)."""
    return Database(request.app.state.db_path)


def create_app(db_path: Path) -> FastAPI:
    """Build the dashboard app bound to ``db_path``."""
    app = FastAPI(title="task-manager dashboard")
    app.state.db_path = Path(db_path)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse(url="/board")

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(board_router)

    from .mutations import router as mutations_router

    app.include_router(mutations_router)
    return app
