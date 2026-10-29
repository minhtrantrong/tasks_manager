"""Typed errors raised by the repository layer."""

from __future__ import annotations


class TaskManagerError(Exception):
    """Base class for all expected task-manager failures."""


class NotFound(TaskManagerError):
    """The requested project, task, or workflow does not exist."""


class ValidationError(TaskManagerError):
    """Input failed a repository-level validation rule."""


class IllegalTransition(TaskManagerError):
    """The requested lifecycle action is not legal from the current status."""


class LeaseConflict(TaskManagerError):
    """Another actor holds an unexpired lease on the task."""


class CycleDetected(TaskManagerError):
    """The requested relation would create a dependency cycle."""


class MissingOutcome(TaskManagerError):
    """Completing a task requires a non-empty outcome."""


class MissingReason(TaskManagerError):
    """Blocking a task requires a non-empty reason."""


class FtsUnavailable(TaskManagerError):
    """Full-text search was required but FTS5 is not available."""
