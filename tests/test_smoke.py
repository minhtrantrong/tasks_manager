"""Smoke tests for the package skeleton and CLI."""

from __future__ import annotations

import subprocess
import sys

import task_manager


def test_version() -> None:
    assert task_manager.__version__ == "0.1.0"


def test_module_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "task_manager", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "serve" in result.stdout
    assert "dashboard" in result.stdout
