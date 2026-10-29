"""Pure lifecycle state machine (no I/O).

``TRANSITIONS[status][action] = Transition(next_status, requirements)``.
Requirement names are ``outcome``, ``reason``, and ``lease``.
"""

from __future__ import annotations

from typing import NamedTuple

from .errors import IllegalTransition


class Transition(NamedTuple):
    next_status: str
    requirements: frozenset[str]


TRANSITIONS: dict[str, dict[str, Transition]] = {
    "open": {
        "start": Transition("in_progress", frozenset({"lease"})),
        "block": Transition("blocked", frozenset({"reason"})),
        "cancel": Transition("cancelled", frozenset()),
    },
    "in_progress": {
        "release": Transition("open", frozenset()),
        "block": Transition("blocked", frozenset({"reason"})),
        "complete": Transition("done", frozenset({"outcome"})),
        "cancel": Transition("cancelled", frozenset()),
    },
    "blocked": {
        "unblock": Transition("open", frozenset()),
        "cancel": Transition("cancelled", frozenset()),
    },
    "done": {
        "close": Transition("closed", frozenset()),
        "reopen": Transition("in_progress", frozenset({"lease"})),
        "cancel": Transition("cancelled", frozenset()),
    },
    "closed": {
        "reopen": Transition("in_progress", frozenset({"lease"})),
        "cancel": Transition("cancelled", frozenset()),
    },
    "cancelled": {},
}


def assert_transition(current: str, action: str) -> Transition:
    """Return the transition or raise ``IllegalTransition`` naming both sides."""
    try:
        return TRANSITIONS[current][action]
    except KeyError:
        raise IllegalTransition(f"{current} -> {action}") from None
