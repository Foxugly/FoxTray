"""Menu action handlers. Each catches its own exceptions and notifies via icon."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import webbrowser
from pathlib import Path
from typing import Protocol, Sequence

from foxtray import config, tasks
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


class _TaskRunnerProtocol(Protocol):
    def run(self, key: str, command: list[str], cwd: Path) -> None: ...
    def is_running(self, key: str) -> bool: ...
    def kill_all(self) -> int: ...


def on_exit(icon: Closable, task_manager: _TaskRunnerProtocol) -> None:
    killed = task_manager.kill_all()
    if killed > 0:
        try:
            icon.notify(f"{killed} task(s) killed", title="FoxTray")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    icon.stop()


def on_stop_all_and_exit(
    orchestrator: Orchestrator,
    icon: NotifierClosable,
    user_initiated: set[str],
    active_names: Sequence[str],
    task_manager: _TaskRunnerProtocol,
) -> None:
    for name in active_names:
        user_initiated.add(name)
    try:
        orchestrator.stop_all()
    except Exception as exc:  # noqa: BLE001
        if hasattr(icon, "notify"):
            _notify_error(icon, exc)  # type: ignore[arg-type]
    killed = task_manager.kill_all()
    if killed > 0:
        try:
            icon.notify(f"{killed} task(s) killed", title="FoxTray")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    icon.stop()


def on_run_task(
    task_manager: _TaskRunnerProtocol,
    project: config.Project,
    task: config.Task,
    icon: Notifier,
) -> None:
    key = f"task:{project.name}:{task.name}"
    try:
        task_manager.run(
            key, task.resolved_command(project), task.resolved_cwd(project)
        )
    except tasks.TaskAlreadyRunning:
        icon.notify(f"{task.name} is already running", title="FoxTray")
    except Exception as exc:  # noqa: BLE001 — tray must survive any handler error
        _notify_error(icon, exc)


def on_run_script(
    task_manager: _TaskRunnerProtocol,
    script: config.Script,
    icon: Notifier,
) -> None:
    key = f"script:{script.name}"
    try:
        task_manager.run(key, script.resolved_command(), script.path)
    except tasks.TaskAlreadyRunning:
        icon.notify(f"{script.name} is already running", title="FoxTray")
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


_ABOUT_TITLE = "About FoxTray"
_ABOUT_BODY = (
    "FoxTray\n"
    "Windows tray launcher for Django + Angular project pairs.\n\n"
    "Author: Foxugly\n"
    "Website: https://foxugly.com\n"
    "Repository: https://github.com/Foxugly/FoxTray"
)


def _show_about_dialog(title: str, body: str) -> None:
    """Open a native Windows MessageBox. Extracted so tests can monkeypatch."""
    import ctypes
    # MB_OK = 0x0, MB_ICONINFORMATION = 0x40
    ctypes.windll.user32.MessageBoxW(0, body, title, 0x40)


def on_about(icon: Notifier) -> None:
    try:
        _show_about_dialog(_ABOUT_TITLE, _ABOUT_BODY)
    except Exception as exc:  # noqa: BLE001 — MessageBoxW failure must not crash tray
        _notify_error(icon, exc)


def on_restart(
    orchestrator: Orchestrator,
    project: config.Project,
    icon: Notifier,
    user_initiated: set[str],
) -> None:
    """Stop then start in a background thread. The menu-callback thread
    returns immediately so pystray stays responsive during the kill/wait."""
    def _run() -> None:
        user_initiated.add(project.name)
        try:
            orchestrator.stop(project.name)
            orchestrator.start(project)
        except Exception as exc:  # noqa: BLE001
            _notify_error(icon, exc)
    threading.Thread(target=_run, name=f"restart-{project.name}", daemon=True).start()


def on_open_logs_folder(icon: Notifier) -> None:
    from foxtray import paths
    try:
        _open_folder_native(paths.logs_dir())
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def _copy_to_clipboard_windows(text: str) -> None:
    """Copy text to Windows clipboard via built-in clip.exe."""
    subprocess.run(
        ["clip"], input=text, text=True, check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def on_copy_url(url: str, icon: Notifier) -> None:
    try:
        _copy_to_clipboard_windows(url)
        icon.notify(f"URL copied: {url}", title="FoxTray")
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_open_log(log_path: Path, icon: Notifier) -> None:
    try:
        if not log_path.exists():
            icon.notify(f"No log yet: {log_path.name}", title="FoxTray")
            return
        _open_folder_native(log_path)
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)
