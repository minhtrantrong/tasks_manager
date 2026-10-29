"""Opt-in local kanban dashboard over the same SQLite file.

The dashboard is a view and a control surface, never a second source of truth:
every route calls :mod:`task_manager.repository`, and no route contains SQL.
"""

from __future__ import annotations
