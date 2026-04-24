"""Filesystem locations used across FoxTray.

All paths derive from a single root (``%APPDATA%\\foxtray`` in production).
Set ``FOXTRAY_APPDATA`` to override for tests.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def appdata_root() -> Path:
    override = os.environ.get("FOXTRAY_APPDATA")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set; FoxTray is Windows-only")
    return Path(appdata) / "foxtray"


def logs_dir() -> Path:
    return appdata_root() / "logs"


def state_file() -> Path:
    return appdata_root() / "state.json"


def log_file(project: str, component: str) -> Path:
    return logs_dir() / f"{project}_{component}.log"


def bootstrap_log_file() -> Path:
    return bootstrap_log_candidates()[0]


def bootstrap_log_candidates() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get("FOXTRAY_APPDATA")
    if override:
        candidates.append(Path(override) / "logs" / "bootstrap.log")
    else:
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / "bootstrap.log")
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "foxtray" / "logs" / "bootstrap.log")
        elif not getattr(sys, "frozen", False):
            candidates.append(logs_dir() / "bootstrap.log")
        candidates.append(Path(tempfile.gettempdir()) / "foxtray" / "bootstrap.log")

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def task_log_file(key: str) -> Path:
    """Path to the log file for a task/script key. Colons in the key are
    replaced with underscores for Windows filesystem safety."""
    sanitized = key.replace(":", "_")
    return appdata_root() / "logs" / "tasks" / f"{sanitized}.log"


def tray_lock_file() -> Path:
    """Path to the single-instance PID lock for the tray."""
    return appdata_root() / "tray.lock"


def ensure_dirs() -> None:
    logs_dir().mkdir(parents=True, exist_ok=True)
