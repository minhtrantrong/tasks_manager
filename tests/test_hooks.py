"""T16 / TT16 — optional git work-on hooks that can never break a transition."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from task_manager import hooks, repository
from task_manager.db import Database
from task_manager.errors import TaskManagerError

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed"
)


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "tasks.sqlite")
    database.migrate()
    return database


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    assert _git(path, "init").returncode == 0
    _git(path, "config", "user.email", "tests@example.com")
    _git(path, "config", "user.name", "Task Manager Tests")
    _git(path, "config", "commit.gpgsign", "false")
    (path / ".gitignore").write_text(".tasks/\n", encoding="utf-8")
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    _git(path, "add", "README.md", ".gitignore")
    _git(path, "commit", "-m", "initial")
    return path


def _write_config(repo: Path, hooks_block: dict) -> None:
    config_dir = repo / ".tasks"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(
        json.dumps({"slug": "demo", "root_path": ".", "hooks": hooks_block}),
        encoding="utf-8",
    )


def _project(db, repo: Path):
    return repository.project_upsert(db, "demo", "Demo", root_path=str(repo))


def _branches(repo: Path) -> set[str]:
    result = _git(repo, "branch", "--list", "--format=%(refname:short)")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def test_branch_name_is_deterministic_and_sanitised():
    assert (
        hooks.branch_name(12, "Fix plugin loader crash on startup")
        == "12-fix-plugin-loader-crash"
    )
    assert hooks.branch_name(7, "  Weird: title!! with; punctuation && $()") == (
        "7-weird-title-with-punctuation"
    )
    assert hooks.branch_name(3, "Ünïcode title") == hooks.branch_name(3, "Ünïcode title")
    long_title = " ".join(["word"] * 40)
    assert hooks.branch_name(5, long_title) == "5-word-word-word-word"
    assert hooks.branch_name(9, "!!!") == "9-task"


def test_hooks_off_by_default_create_no_branch(db, tmp_path):
    repo = _make_repo(tmp_path / "repo")
    project = _project(db, repo)
    task = repository.task_add(db, project.id, "No hook here")
    before = _branches(repo)

    repository.task_start(db, task.id, actor="agent-1")
    assert _branches(repo) == before


def test_hooks_enabled_create_a_branch(db, tmp_path):
    repo = _make_repo(tmp_path / "repo")
    _write_config(repo, {"enabled": True})
    project = _project(db, repo)
    task = repository.task_add(db, project.id, "Fix plugin loader crash on startup")

    started = repository.task_start(db, task.id, actor="agent-1")
    assert started.status == "in_progress"
    assert f"{task.id}-fix-plugin-loader-crash" in _branches(repo)


def test_worktree_hook_creates_the_worktree(db, tmp_path):
    repo = _make_repo(tmp_path / "repo")
    _write_config(repo, {"enabled": True, "worktree": True})
    project = _project(db, repo)
    task = repository.task_add(db, project.id, "Isolated work")

    repository.task_start(db, task.id, actor="agent-1")
    worktree = repo / ".tasks" / "worktrees" / str(task.id)
    assert worktree.is_dir()
    assert f"{task.id}-isolated-work" in _branches(repo)


def test_commit_on_complete_commits_a_dirty_tree(db, tmp_path):
    repo = _make_repo(tmp_path / "repo")
    _write_config(repo, {"enabled": True, "commit_on_complete": True})
    project = _project(db, repo)
    task = repository.task_add(db, project.id, "Commit me")
    repository.task_start(db, task.id, actor="agent-1")
    (repo / "work.txt").write_text("done\n", encoding="utf-8")

    repository.task_complete(db, task.id, actor="agent-1", outcome="wrote work.txt")

    log = _git(repo, "log", "-1", "--format=%s")
    assert f"task-manager: complete task #{task.id}" in log.stdout
    assert repository.task_get(db, task.id).status == "done"


def test_commit_on_complete_is_a_noop_on_a_clean_tree(db, tmp_path):
    repo = _make_repo(tmp_path / "repo")
    _write_config(repo, {"enabled": True, "commit_on_complete": True})
    project = _project(db, repo)
    task = repository.task_add(db, project.id, "Nothing to commit")
    repository.task_start(db, task.id, actor="agent-1")
    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()

    repository.task_complete(db, task.id, actor="agent-1", outcome="no change")
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert repository.task_get(db, task.id).status == "done"


def test_non_git_root_path_degrades_with_a_journal_warning(db, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    _write_config(plain, {"enabled": True, "commit_on_complete": True})
    project = _project(db, plain)
    task = repository.task_add(db, project.id, "Still works")

    started = repository.task_start(db, task.id, actor="agent-1")
    assert started.status == "in_progress"
    assert started.owner == "agent-1"

    notes = [
        entry.body
        for entry in repository.journal_list(db, task_id=task.id)
        if entry.kind == "note"
    ]
    assert any("hook warning" in body for body in notes)

    repository.task_complete(db, task.id, actor="agent-1", outcome="fine")
    assert repository.task_get(db, task.id).status == "done"


def test_missing_git_binary_degrades(db, tmp_path, monkeypatch):
    repo = _make_repo(tmp_path / "repo")
    _write_config(repo, {"enabled": True})
    project = _project(db, repo)
    task = repository.task_add(db, project.id, "No git anywhere")

    original_which = shutil.which
    monkeypatch.setattr(
        hooks.shutil,
        "which",
        lambda name: None if name == "git" else original_which(name),
    )
    started = repository.task_start(db, task.id, actor="agent-1")
    assert started.status == "in_progress"
    notes = [
        entry.body
        for entry in repository.journal_list(db, task_id=task.id)
        if entry.kind == "note"
    ]
    assert any("git is not available" in body for body in notes)


def test_failing_command_never_rolls_back_the_transition(db, tmp_path, monkeypatch):
    repo = _make_repo(tmp_path / "repo")
    _write_config(repo, {"enabled": True})
    project = _project(db, repo)
    task = repository.task_add(db, project.id, "Hook explodes")

    def boom(*args, **kwargs):
        raise OSError("git exploded")

    monkeypatch.setattr(hooks, "_git", boom)
    started = repository.task_start(db, task.id, actor="agent-1", lease_minutes=30)
    assert started.status == "in_progress"
    assert started.owner == "agent-1"
    assert started.lease_expires_at is not None


def test_titles_cannot_inject_shell_arguments(db, tmp_path, monkeypatch):
    repo = _make_repo(tmp_path / "repo")
    _write_config(repo, {"enabled": True})
    project = _project(db, repo)
    task = repository.task_add(db, project.id, "Evil; rm -rf / && echo $(whoami)")

    captured: list[tuple[str, ...]] = []
    real_run = subprocess.run

    def spy(args, *rest, **kwargs):
        captured.append(tuple(args) if isinstance(args, list) else (str(args),))
        assert kwargs.get("shell") in (None, False)
        return real_run(args, *rest, **kwargs)

    monkeypatch.setattr(hooks.subprocess, "run", spy)
    repository.task_start(db, task.id, actor="agent-1")

    flattened = [" ".join(entry) for entry in captured]
    assert any("checkout" in entry and "-b" in entry for entry in flattened)
    branch_arg = next(
        part for entry in captured for part in entry if part.endswith("evil-rm-rf-echo")
    )
    assert branch_arg == f"{task.id}-evil-rm-rf-echo"
    assert not any("shell=True" in entry for entry in flattened)


def test_missing_root_path_degrades(db, tmp_path):
    missing = tmp_path / "gone"
    project = repository.project_upsert(db, "demo", "Demo", root_path=str(missing))
    _write_config(missing, {"enabled": True})
    task = repository.task_add(db, project.id, "Root vanished")

    started = repository.task_start(db, task.id, actor="agent-1")
    assert started.status == "in_progress"
    assert any(
        "hook warning" in entry.body
        for entry in repository.journal_list(db, task_id=task.id)
    )


def test_hook_errors_are_never_propagated(db, tmp_path):
    repo = _make_repo(tmp_path / "repo")
    _write_config(repo, {"enabled": True})
    project = _project(db, repo)
    task = repository.task_add(db, project.id, "Journal failure")

    def failing_journal(*args, **kwargs):
        raise TaskManagerError("journal unavailable")

    original = repository.journal_add
    repository.journal_add = failing_journal
    try:
        started = repository.task_start(db, task.id, actor="agent-1")
        assert started.status == "in_progress"
    finally:
        repository.journal_add = original
