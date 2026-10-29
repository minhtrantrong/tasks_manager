"""Configuration resolution for database location and per-repo overrides."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ValidationError

DEFAULT_DB_PATH = Path.home() / ".tasks_manager" / "tasks.sqlite"


@dataclass
class HookConfig:
    """Optional git work-on hook settings (off by default)."""

    enabled: bool = False
    worktree: bool = False
    commit_on_complete: bool = False


@dataclass
class Config:
    """Resolved runtime configuration."""

    db_path: Path
    root_path: Path | None
    slug: str | None
    hooks: HookConfig = field(default_factory=HookConfig)


def _read_repo_config(cwd: Path) -> dict:
    config_path = cwd / ".tasks" / "config.json"
    if not config_path.is_file():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid .tasks/config.json: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(".tasks/config.json must contain a JSON object")
    return data


def _resolve_path(value: str | os.PathLike[str], base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def load_config(cwd: Path | None = None) -> Config:
    """Resolve the DB path and per-repo defaults.

    Order for the DB path: ``$TASKS_DB`` → optional ``db_path`` in
    ``.tasks/config.json`` → ``~/.tasks_manager/tasks.sqlite``.
    """
    working_dir = Path(cwd) if cwd is not None else Path.cwd()
    working_dir = working_dir.resolve()
    repo_config = _read_repo_config(working_dir)

    env_db = os.environ.get("TASKS_DB")
    if env_db:
        db_path = _resolve_path(env_db, working_dir)
    elif repo_config.get("db_path"):
        db_path = _resolve_path(repo_config["db_path"], working_dir)
    else:
        db_path = DEFAULT_DB_PATH

    if repo_config:
        root_value = repo_config.get("root_path")
        root_path = _resolve_path(root_value, working_dir) if root_value else working_dir
        slug = repo_config.get("slug")
    else:
        root_path = working_dir
        slug = None

    hooks_data = repo_config.get("hooks") or {}
    if not isinstance(hooks_data, dict):
        raise ValidationError(".tasks/config.json hooks must be an object")
    hooks = HookConfig(
        enabled=bool(hooks_data.get("enabled", False)),
        worktree=bool(hooks_data.get("worktree", False)),
        commit_on_complete=bool(hooks_data.get("commit_on_complete", False)),
    )

    return Config(db_path=db_path, root_path=root_path, slug=slug, hooks=hooks)


_CONFIG_CACHE: dict[tuple, Config] = {}


def _cache_key(directory: Path) -> tuple:
    """Cache key that changes when ``.tasks/config.json`` changes on disk."""
    config_path = directory / ".tasks" / "config.json"
    try:
        stat = config_path.stat()
    except OSError:
        return (str(directory), None, None)
    return (str(directory), stat.st_mtime_ns, stat.st_size)


def load_config_cached(cwd: Path | None = None) -> Config:
    """``load_config`` memoised per directory + config-file signature."""
    directory = (Path(cwd) if cwd is not None else Path.cwd()).resolve()
    key = _cache_key(directory)
    cached = _CONFIG_CACHE.get(key)
    if cached is None:
        cached = load_config(directory)
        _CONFIG_CACHE[key] = cached
    return cached


def hooks_for(project: object) -> HookConfig:
    """Resolve a project's hook settings from its ``root_path`` (never raises)."""
    root_path = getattr(project, "root_path", None)
    if not root_path:
        return HookConfig()
    try:
        return load_config_cached(Path(root_path)).hooks
    except ValidationError:
        return HookConfig()
