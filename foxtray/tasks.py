"""One-shot command execution independent of project lifecycle.

A TaskManager owns a dict of running Popens keyed by a string, spawns each
via process.spawn_with_log + logs.rotate_task/open_task_writer, and fires a
completion callback from a watcher thread when each Popen exits.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import Callable

from foxtray import logs, process

log = logging.getLogger(__name__)


class TaskAlreadyRunning(RuntimeError):
    """Raised when .run() is called for a key that is already running."""


class TaskManager:
    def __init__(
        self,
        kill_tree: Callable[[int], None],
        on_complete: Callable[[str, int], None],
    ) -> None:
        self._kill_tree = kill_tree
        self._on_complete = on_complete
        self._running: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def is_running(self, key: str) -> bool:
        with self._lock:
            return key in self._running

    def running_keys(self) -> set[str]:
        with self._lock:
            return set(self._running)

    def run(self, key: str, command: list[str], cwd: Path) -> None:
        with self._lock:
            if key in self._running:
                raise TaskAlreadyRunning(key)
        logs.rotate_task(key)
        log_file = logs.open_task_writer(key)
        popen = process.spawn_with_log(command, cwd, log_file)
        with self._lock:
            self._running[key] = popen
        threading.Thread(
            target=self._watch,
            args=(key, popen),
            name=f"task-{key}",
            daemon=True,
        ).start()

    def _watch(self, key: str, popen: subprocess.Popen[bytes]) -> None:
        exit_code = popen.wait()
        with self._lock:
            self._running.pop(key, None)
        try:
            self._on_complete(key, exit_code)
        except Exception:  # noqa: BLE001 — callback must not crash watcher
            log.warning("task %s on_complete callback failed", key, exc_info=True)

    def kill_all(self) -> int:
        with self._lock:
            victims = list(self._running.items())
            self._running.clear()
        for key, popen in victims:
            try:
                self._kill_tree(popen.pid)
            except Exception:  # noqa: BLE001
                log.warning("kill_all: failed to kill %s", key, exc_info=True)
        return len(victims)
