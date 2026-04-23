"""Persistence of the currently-active project and its subprocess PIDs."""
from __future__ import annotations

import json
import logging

import psutil
from dataclasses import asdict, dataclass
from typing import Any

from foxtray import paths

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActiveProject:
    name: str
    backend_pid: int
    frontend_pid: int


@dataclass(frozen=True)
class State:
    active: ActiveProject | None


def load() -> State:
    path = paths.state_file()
    if not path.exists():
        return State(active=None)
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        active_raw = raw.get("active")
        if not active_raw:
            return State(active=None)
        return State(active=ActiveProject(**active_raw))
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        log.warning("state.json is unreadable or malformed; treating as empty", exc_info=True)
        return State(active=None)


def save(state: State) -> None:
    paths.ensure_dirs()
    path = paths.state_file()
    payload = {"active": asdict(state.active) if state.active else None}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear() -> None:
    save(State(active=None))


def clear_if_orphaned() -> bool:
    """Clear state.json.active if both recorded PIDs are dead.

    Returns True if a clear was performed, False otherwise.
    """
    s = load()
    if s.active is None:
        return False
    if psutil.pid_exists(s.active.backend_pid) or psutil.pid_exists(s.active.frontend_pid):
        return False
    save(State(active=None))
    return True
