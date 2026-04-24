"""Persistence of the currently-active project and its subprocess PIDs.

``ActiveProject`` also carries the ``psutil.Process(pid).create_time()`` of
each child captured at spawn. Windows recycles PIDs aggressively, so a
bare ``psutil.pid_exists(pid)`` check can match an unrelated process that
inherited the number — and the orchestrator would then kill that innocent
process. ``pid_alive`` below compares both the PID *and* the create_time
so the identity of the process is verified before any destructive action.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

import psutil

from foxtray import paths

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActiveProject:
    name: str
    backend_pid: int
    frontend_pid: int | None
    # Default 0.0 / None only exists so tests can construct the dataclass
    # without threading a real psutil create_time through every fixture.
    # Production code (Orchestrator.start) always captures and passes the
    # real ctimes — that's what the PID-reuse guard relies on.
    backend_create_time: float = 0.0
    frontend_create_time: float | None = None


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
        # Also covers pre-create_time state.json from older FoxTray builds:
        # ActiveProject(**{old_fields}) raises TypeError because the required
        # create_time fields are missing. Dropping the entry is correct —
        # we can't trust PIDs without their identity marker.
        log.warning("state.json is unreadable or malformed; treating as empty", exc_info=True)
        return State(active=None)


def save(state: State) -> None:
    paths.ensure_dirs()
    path = paths.state_file()
    payload = {"active": asdict(state.active) if state.active else None}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear() -> None:
    save(State(active=None))


def pid_alive(pid: int, create_time: float) -> bool:
    """True iff ``pid`` is running AND its ``create_time()`` matches ``create_time``.

    The ctime match guards against Windows PID reuse: after our backend dies,
    the same PID can be reassigned to any process, and a plain ``pid_exists``
    check would wrongly conclude "still running" — and a subsequent
    ``kill_tree`` would target a stranger.
    """
    try:
        proc = psutil.Process(pid)
        return proc.create_time() == create_time
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def clear_if_orphaned() -> bool:
    """Clear state.json.active if both recorded children are dead (PID-reuse-safe).

    Returns True if a clear was performed, False otherwise.
    """
    s = load()
    if s.active is None:
        return False
    backend_alive = pid_alive(s.active.backend_pid, s.active.backend_create_time)
    frontend_alive = (
        s.active.frontend_pid is not None
        and s.active.frontend_create_time is not None
        and pid_alive(s.active.frontend_pid, s.active.frontend_create_time)
    )
    if backend_alive or frontend_alive:
        return False
    save(State(active=None))
    return True
