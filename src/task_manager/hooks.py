"""Optional git "work-on" hooks: a branch (and optionally a worktree) per task.

Hooks are off by default and never a premise. They run *after* the transition's
transaction has committed, so a hook can never fail or roll back a transition:
every failure becomes a logged warning plus a journal ``note``.

No shell is involved — commands are argument lists run with ``shell=False`` —
so task titles can never be reinterpreted by a shell, on any OS.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .config import hooks_for

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .db import Database
    from .models import Project, Task

logger = logging.getLogger(__name__)

MAX_SLUG_WORDS = 4
GIT_TIMEOUT = 30
MAX_WARNING = 900


def branch_name(task_id: int, title: str) -> str:
    """``<id>-<first four title words>``, deterministic and shell-safe."""
    words = re.findall(r"[a-z0-9]+", title.lower())[:MAX_SLUG_WORDS]
    slug = "-".join(words) or "task"
    return f"{task_id}-{slug}"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git") or "git"
    return subprocess.run(
        [executable, "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
        check=False,
    )


def _warn(db: Database, task: Task, message: str) -> None:
    """Log and journal a hook warning; never raise."""
    from . import repository

    detail = " ".join(str(message).split())[:MAX_WARNING]
    logger.warning("work-on hook for task %s: %s", task.id, detail)
    try:
        repository.journal_add(
            db, task_id=task.id, kind="note", body=f"hook warning: {detail}"
        )
    except Exception:  # pragma: no cover - journaling a warning must not fail
        logger.warning("work-on hook warning could not be journalled")


def _project_root(project: Project) -> Path | None:
    if not project.root_path:
        return None
    return Path(project.root_path).expanduser()


def _is_git_repo(root: Path) -> bool:
    result = _git(root, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def _worktree_path(root: Path, task_id: int) -> Path:
    return root / ".tasks" / "worktrees" / str(task_id)


def on_task_start(db: Database, project: Project, task: Task) -> None:
    """Create or switch to the task branch; degrade to a warning on any failure."""
    hooks = hooks_for(project)
    if not hooks.enabled:
        return
    try:
        root = _project_root(project)
        if root is None or not root.is_dir():
            _warn(db, task, f"root_path {project.root_path!r} is not a directory")
            return
        if shutil.which("git") is None:
            _warn(db, task, "git is not available on PATH")
            return
        if not _is_git_repo(root):
            _warn(db, task, f"{root} is not a git repository")
            return

        branch = branch_name(task.id, task.title)
        if hooks.worktree:
            target = _worktree_path(root, task.id)
            if target.is_dir():
                return
            result = _git(root, "worktree", "add", "-b", branch, str(target))
            if result.returncode != 0:
                _warn(db, task, result.stderr or "git worktree add failed")
            return

        result = _git(root, "checkout", "-b", branch)
        if result.returncode != 0:
            if "already exists" in (result.stderr or "").lower():
                switch = _git(root, "checkout", branch)
                if switch.returncode == 0:
                    return
                _warn(db, task, switch.stderr or "git checkout failed")
                return
            _warn(db, task, result.stderr or "git checkout -b failed")
    except Exception as exc:  # pragma: no cover - defensive: hooks never raise
        _warn(db, task, f"hook failed: {exc}")


def on_task_complete(db: Database, project: Project, task: Task) -> None:
    """Commit the working tree for the task when ``commit_on_complete`` is on."""
    hooks = hooks_for(project)
    if not (hooks.enabled and hooks.commit_on_complete):
        return
    try:
        root = _project_root(project)
        if root is None or not root.is_dir():
            _warn(db, task, f"root_path {project.root_path!r} is not a directory")
            return
        if shutil.which("git") is None:
            _warn(db, task, "git is not available on PATH")
            return
        repo = _worktree_path(root, task.id) if hooks.worktree else root
        if not _is_git_repo(repo):
            _warn(db, task, f"{repo} is not a git repository")
            return

        status = _git(repo, "status", "--porcelain")
        if status.returncode != 0:
            _warn(db, task, status.stderr or "git status failed")
            return
        if not status.stdout.strip():
            return

        added = _git(repo, "add", "-A")
        if added.returncode != 0:
            _warn(db, task, added.stderr or "git add failed")
            return
        message = f"task-manager: complete task #{task.id} — {task.title}"
        committed = _git(repo, "commit", "-m", message)
        if committed.returncode != 0:
            _warn(db, task, committed.stderr or "git commit failed")
    except Exception as exc:  # pragma: no cover - defensive: hooks never raise
        _warn(db, task, f"hook failed: {exc}")
