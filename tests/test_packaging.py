"""T18 / TT18 — package data, entry points, and wheel completeness.

The resource assertions here are what make the CI wheel-content check
meaningful: they fail the moment a package-data glob regresses.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import task_manager
from task_manager.cli import build_parser

REQUIRED_WORKFLOWS = {"simple", "bugfix", "feature", "spike"}


def test_workflow_templates_ship_with_the_package():
    directory = importlib.resources.files("task_manager").joinpath("workflows")
    names = {entry.name for entry in directory.iterdir() if entry.name.endswith(".md")}
    assert REQUIRED_WORKFLOWS <= {name[: -len(".md")] for name in names}
    for name in REQUIRED_WORKFLOWS:
        text = directory.joinpath(f"{name}.md").read_text(encoding="utf-8")
        assert text.startswith("---")
        assert "{title}" in text and "{id}" in text and "{project}" in text


def test_migrations_ship_with_the_package():
    directory = importlib.resources.files("task_manager").joinpath("migrations")
    names = [entry.name for entry in directory.iterdir() if entry.name.endswith(".sql")]
    assert names
    assert any(name.startswith("0001") for name in names)


def test_dashboard_assets_ship_with_the_package():
    dashboard = importlib.resources.files("task_manager").joinpath("dashboard")
    assert dashboard.joinpath("templates", "base.html").is_file()
    assert dashboard.joinpath("templates", "board.html").is_file()
    assert dashboard.joinpath("static", "app.css").is_file()
    assert dashboard.joinpath("static", "htmx.min.js").is_file()


def test_console_scripts_and_subcommands():
    entry_points = importlib.metadata.entry_points()
    scripts = {
        entry.name: entry.value
        for entry in entry_points.select(group="console_scripts")
        if entry.name == "task-manager"
    }
    assert scripts.get("task-manager") == "task_manager.cli:main"

    parser = build_parser()
    help_text = parser.format_help()
    assert "serve" in help_text
    assert "dashboard" in help_text


def test_module_entry_point_and_version():
    assert task_manager.__version__ == importlib.metadata.version("task-manager")

    result = subprocess.run(
        [sys.executable, "-m", "task_manager", "--help"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0
    assert "serve" in result.stdout
    assert "dashboard" in result.stdout


def test_runtime_requirements_are_minimal():
    requirements = importlib.metadata.requires("task-manager") or []
    runtime = [item for item in requirements if "extra ==" not in item]
    names = {item.split()[0].split(">")[0].split("<")[0].split("=")[0] for item in runtime}
    assert {"mcp", "pydantic"} <= names
    assert "fastapi" not in names
    assert "uvicorn" not in names


@pytest.mark.skipif(
    os.environ.get("TASKS_BUILD_WHEEL") != "1",
    reason="set TASKS_BUILD_WHEEL=1 to build and inspect the wheel (slow, packaging job)",
)
def test_wheel_contains_all_package_data(tmp_path):
    build = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheels = list(Path(tmp_path).glob("*.whl"))
    assert len(wheels) == 1

    required_suffixes = (
        "task_manager/workflows/simple.md",
        "task_manager/workflows/bugfix.md",
        "task_manager/migrations/0001_initial.sql",
        "task_manager/dashboard/templates/base.html",
        "task_manager/dashboard/templates/board.html",
        "task_manager/dashboard/static/app.css",
        "task_manager/dashboard/static/htmx.min.js",
    )
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
    for suffix in required_suffixes:
        assert any(name.endswith(suffix) for name in names), suffix
    assert not any("__pycache__" in name for name in names)
