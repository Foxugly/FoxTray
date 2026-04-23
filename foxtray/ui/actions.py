"""Menu action handlers. Each catches its own exceptions and notifies via icon."""
from __future__ import annotations

import logging
import os
import webbrowser
from pathlib import Path
from typing import Protocol, Sequence

from foxtray import config
from foxtray.project import Orchestrator

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def notify(self, message: str, title: str = "") -> None: ...


class Closable(Protocol):
    def stop(self) -> None: ...


class NotifierClosable(Notifier, Closable, Protocol):
    """Combined Protocol for icons that must both notify and shut down."""


def _open_url(url: str) -> None:
    webbrowser.open(url)


def _open_folder_native(path: Path) -> None:
    os.startfile(str(path))  # noqa: S606 — Windows-only, user-initiated


def _notify_error(icon: Notifier, exc: Exception) -> None:
    log.warning("tray handler failed", exc_info=True)
    icon.notify(str(exc), title="FoxTray error")


def on_start(orchestrator: Orchestrator, project: config.Project, icon: Notifier) -> None:
    orchestrator.pending_starts.add(project.name)
    try:
        orchestrator.start(project)
    except Exception as exc:  # noqa: BLE001 — tray must survive any handler error
        orchestrator.pending_starts.discard(project.name)
        _notify_error(icon, exc)


def on_stop(
    orchestrator: Orchestrator,
    project: config.Project,
    icon: Notifier,
    user_initiated: set[str],
) -> None:
    user_initiated.add(project.name)
    try:
        orchestrator.stop(project.name)
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_open_browser(project: config.Project, icon: Notifier) -> None:
    try:
        _open_url(project.url)
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_open_folder(path: Path, icon: Notifier) -> None:
    try:
        _open_folder_native(path)
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_stop_all(
    orchestrator: Orchestrator,
    icon: Notifier,
    user_initiated: set[str],
    active_names: Sequence[str],
) -> None:
    for name in active_names:
        user_initiated.add(name)
    try:
        orchestrator.stop_all()
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_exit(icon: Closable) -> None:
    # If icon.stop() raises, let it propagate — shutdown should be loud.
    icon.stop()


def on_stop_all_and_exit(
    orchestrator: Orchestrator,
    icon: NotifierClosable,
    user_initiated: set[str],
    active_names: Sequence[str],
) -> None:
    for name in active_names:
        user_initiated.add(name)
    try:
        orchestrator.stop_all()
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)
    # Windows balloon notifications are async; if we just fired one above, it
    # may not render before icon.stop() tears down the message pump. That's
    # acceptable on the exit path — the user is closing the app.
    icon.stop()
