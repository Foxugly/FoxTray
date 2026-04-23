"""Single-instance lock for the tray application.

File at %APPDATA%/foxtray/tray.lock holds the PID of the current holder.
Stale locks (holder dead) are automatically reclaimed.
"""
from __future__ import annotations

import logging
import os

import psutil

from foxtray import paths

log = logging.getLogger(__name__)


class LockHeldError(RuntimeError):
    """Raised when another live FoxTray tray instance already holds the lock."""


def acquire_lock() -> None:
    """Create tray.lock with the current PID. If the file exists and the PID
    inside is still alive and is NOT our PID, raise LockHeldError. Stale or
    corrupt locks are silently reclaimed."""
    lock_path = paths.tray_lock_file()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            holder_pid = int(lock_path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            holder_pid = 0
        if holder_pid and holder_pid != os.getpid() and psutil.pid_exists(holder_pid):
            raise LockHeldError(
                f"FoxTray tray is already running (pid {holder_pid})"
            )
    lock_path.write_text(str(os.getpid()), encoding="utf-8")


def release_lock() -> None:
    """Delete tray.lock if it exists and belongs to this process. Best-effort —
    never raises."""
    lock_path = paths.tray_lock_file()
    try:
        if not lock_path.exists():
            return
        holder_pid = int(lock_path.read_text(encoding="utf-8").strip())
        if holder_pid == os.getpid():
            lock_path.unlink()
    except (ValueError, OSError):
        log.warning("release_lock: could not inspect/remove %s", lock_path, exc_info=True)
