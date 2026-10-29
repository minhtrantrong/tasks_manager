"""T22 / TT22 — mechanical enforcement of N7 (one write path) and the pragma guard.

The scan is AST-based rather than a raw regex over file text: comments and
docstrings may freely mention ``DELETE FROM tasks`` (documentation), while an
executable string literal carrying a write statement is reported with its file
and line. Only ``repository.py`` and ``db.py`` (pragmas + migration runner) may
hold write SQL.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

from task_manager.db import Database

SRC = Path(__file__).resolve().parents[1] / "src" / "task_manager"
ALLOWED_FILES = {"repository.py", "db.py"}
WRITE_PATTERN = re.compile(
    r"(?i)\b(insert\s+into|update\s+[a-z_][a-z0-9_]*|delete\s+from)\b"
)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Ids of ``ast.Constant`` nodes that are module/class/function docstrings."""
    docstrings: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    return docstrings


def find_write_statements(source: str, filename: str = "<memory>") -> list[tuple[str, int, str]]:
    """Return ``(filename, line, statement)`` for every write SQL literal."""
    tree = ast.parse(source, filename=filename)
    docstrings = _docstring_nodes(tree)
    findings: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstrings:
            continue
        for match in WRITE_PATTERN.finditer(node.value):
            offset_line = node.value.count("\n", 0, match.start())
            findings.append(
                (filename, node.lineno + offset_line, match.group(0).strip())
            )
    return findings


def test_only_repository_and_db_contain_write_sql():
    violations: list[tuple[str, int, str]] = []
    scanned = 0
    for path in sorted(SRC.rglob("*.py")):
        scanned += 1
        if path.name in ALLOWED_FILES:
            continue
        violations.extend(
            find_write_statements(path.read_text(encoding="utf-8"), str(path))
        )
    assert scanned > 10, "the scan did not see the package"
    assert violations == [], "\n".join(
        f"{name}:{line}: {statement}" for name, line, statement in violations
    )


def test_scanner_is_not_vacuous():
    repository_source = (SRC / "repository.py").read_text(encoding="utf-8")
    findings = find_write_statements(repository_source, "repository.py")
    assert findings
    assert any(statement.upper().startswith("INSERT INTO") for _, _, statement in findings)
    assert any(statement.upper().startswith("UPDATE") for _, _, statement in findings)

    db_source = (SRC / "db.py").read_text(encoding="utf-8")
    assert "PRAGMA user_version" in db_source
    assert "PRAGMA journal_mode" in db_source


def test_comments_and_docstrings_are_ignored_but_literals_are_reported():
    source = '''
"""Module docstring mentioning DELETE FROM tasks is fine."""

# A comment saying UPDATE tasks SET status='done' is also fine.


def helper():
    """Docs: INSERT INTO tasks is prose."""
    return "SELECT * FROM tasks"


def bad():
    return "UPDATE tasks SET status='done' WHERE id=?"
'''
    findings = find_write_statements(source, "sample.py")
    assert len(findings) == 1
    filename, line, statement = findings[0]
    assert filename == "sample.py"
    assert statement.upper().startswith("UPDATE TASKS")
    assert line == source.splitlines().index(
        "    return \"UPDATE tasks SET status='done' WHERE id=?\""
    ) + 1


def test_negative_fixture_reports_the_right_line(tmp_path):
    module = tmp_path / "rogue.py"
    module.write_text(
        '"""Not allowed here."""\n'
        "\n"
        "def mutate(conn):\n"
        "    conn.execute(\"DELETE FROM tasks WHERE id=?\", (1,))\n",
        encoding="utf-8",
    )
    findings = find_write_statements(module.read_text(encoding="utf-8"), str(module))
    assert findings == [(str(module), 4, "DELETE FROM")]


def test_journal_mode_pragma_runs_once_per_connection(tmp_path, monkeypatch):
    statements: list[str] = []
    real_connect = sqlite3.connect

    def spy(database, *args, **kwargs):
        connection = real_connect(database, *args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", spy)
    path = tmp_path / "pragma.sqlite"
    db = Database(path)
    db.migrate()
    statements.clear()

    connection = db.connect()
    try:
        connection.execute("SELECT 1").fetchone()
    finally:
        connection.close()

    journal_mode = [s for s in statements if "journal_mode" in s.lower()]
    assert len(journal_mode) == 1, statements

    source = (SRC / "db.py").read_text(encoding="utf-8")
    assert source.lower().count("pragma journal_mode") == 1
