"""SQLite connection factory, migration runner, and FTS5 capability probe."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path

logger = logging.getLogger(__name__)


def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 ``...Z`` string.

    Microseconds are kept so that events recorded in the same second still
    order correctly (``resume`` counts compactions after the latest
    checkpoint by comparing timestamps).
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into executable statements.

    Triggers contain semicolons in their body, so a naive ``split(";")`` would
    break them. A trigger statement ends at the line that is exactly ``END;``.
    """
    statements: list[str] = []
    buffer: list[str] = []
    in_trigger = False

    for line in sql.splitlines():
        stripped = line.strip()
        if not buffer and (not stripped or stripped.startswith("--")):
            continue
        buffer.append(line)
        joined = "\n".join(buffer).lstrip()
        if joined.upper().startswith("CREATE TRIGGER"):
            in_trigger = True
        if in_trigger:
            if stripped.upper() == "END;":
                statements.append("\n".join(buffer))
                buffer = []
                in_trigger = False
        elif stripped.endswith(";"):
            statements.append("\n".join(buffer))
            buffer = []

    if buffer and "\n".join(buffer).strip():
        statements.append("\n".join(buffer))
    return statements


class Database:
    """A SQLite database bound to a single file path."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @staticmethod
    def utc_now() -> str:
        """Return the current UTC timestamp (matches the module-level helper)."""
        return utc_now()

    def connect(self) -> sqlite3.Connection:
        """Open a connection with the required pragmas and row factory."""
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.isolation_level = None
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _migration_files(self) -> list[tuple[int, str]]:
        directory = files("task_manager").joinpath("migrations")
        migrations: list[tuple[int, str]] = []
        for entry in directory.iterdir():
            name = entry.name
            if not name.endswith(".sql"):
                continue
            prefix = name.split("_", 1)[0]
            if not prefix.isdigit():
                continue
            migrations.append((int(prefix), name))
        migrations.sort(key=lambda item: item[0])
        return migrations

    def migrate(self) -> None:
        """Apply pending migrations, bumping ``PRAGMA user_version`` per file."""
        conn = self.connect()
        try:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])
            for version, name in self._migration_files():
                if version <= current:
                    continue
                sql = (
                    files("task_manager")
                    .joinpath("migrations")
                    .joinpath(name)
                    .read_text(encoding="utf-8")
                )
                self._apply_migration(conn, version, sql)
                current = version
        finally:
            conn.close()

    def _execute(self, conn: sqlite3.Connection, statement: str) -> sqlite3.Cursor:
        """Execute one migration statement (a seam used by failure-path tests)."""
        return conn.execute(statement)

    def _apply_migration(self, conn: sqlite3.Connection, version: int, sql: str) -> None:
        conn.execute("BEGIN")
        fts_available = True
        try:
            for statement in _split_statements(sql):
                lowered = statement.lower()
                try:
                    self._execute(conn, statement)
                except sqlite3.OperationalError as exc:
                    if "fts5" in lowered:
                        fts_available = False
                        logger.warning(
                            "FTS5 unavailable; skipping FTS statements in migration %s: %s",
                            version,
                            exc,
                        )
                        continue
                    if not fts_available and ("task_fts" in lowered or "journal_fts" in lowered):
                        continue
                    raise
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def fts_enabled(self, conn: sqlite3.Connection | None = None) -> bool:
        """Return True iff the ``task_fts`` virtual table exists."""
        own_connection = conn is None
        active = conn if conn is not None else self.connect()
        try:
            row = active.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_fts'"
            ).fetchone()
            return row is not None
        finally:
            if own_connection:
                active.close()
