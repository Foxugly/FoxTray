"""Filesystem locations used across FoxTray.

All paths derive from a single root (``%APPDATA%\\foxtray`` in production).
Set ``FOXTRAY_APPDATA`` to override for tests.
"""
from __future__ import annotations

import os
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


def ensure_dirs() -> None:
    logs_dir().mkdir(parents=True, exist_ok=True)
