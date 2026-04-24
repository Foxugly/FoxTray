"""Menu action handlers. Each catches its own exceptions and notifies via icon."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from typing import Protocol, Sequence

from foxtray import __version__, config, tasks
from foxtray.project import Orchestrator

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def notify(self, message: str, title: str = "") -> None: ...


class Closable(Protocol):
    def stop(self) -> None: ...


class NotifierClosable(Notifier, Closable, Protocol):
    """Combined Protocol for icons that must both notify and shut down."""


class ReloadableConfig(Protocol):
    def __call__(self) -> None: ...


def _open_url(url: str) -> None:
    webbrowser.open(url)


def _open_folder_native(path: Path) -> None:
    os.startfile(str(path))  # noqa: S606 — Windows-only, user-initiated


def _notify_error(icon: Notifier, exc: Exception) -> None:
    log.warning("tray handler failed", exc_info=True)
    icon.notify(str(exc), title="FoxTray error")


def _show_clickable_toast(title: str, message: str, url: str) -> None:
    def _run() -> None:
        root = tk.Tk()
        root.withdraw()

        toast = tk.Toplevel(root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg="#202124")

        width = 380
        height = 120
        screen_width = toast.winfo_screenwidth()
        screen_height = toast.winfo_screenheight()
        x = screen_width - width - 24
        y = screen_height - height - 64
        toast.geometry(f"{width}x{height}+{x}+{y}")

        frame = tk.Frame(toast, bg="#202124", padx=14, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text=title,
            bg="#202124",
            fg="#ffffff",
            anchor="w",
            font=("Segoe UI Semibold", 11),
        ).pack(fill="x")
        tk.Label(
            frame,
            text=message,
            bg="#202124",
            fg="#d7dadc",
            anchor="w",
            justify="left",
            font=("Segoe UI", 10),
        ).pack(fill="x", pady=(6, 4))

        link = tk.Label(
            frame,
            text=url,
            bg="#202124",
            fg="#7cc7ff",
            anchor="w",
            justify="left",
            cursor="hand2",
            font=("Segoe UI", 10, "underline"),
        )
        link.pack(fill="x")

        def _open_and_close(_event: object | None = None) -> None:
            _open_url(url)
            _close()

        def _close() -> None:
            try:
                toast.destroy()
            finally:
                root.quit()
                root.destroy()

        link.bind("<Button-1>", _open_and_close)
        toast.bind("<Button-1>", _open_and_close)
        toast.after(8000, _close)
        toast.deiconify()
        root.mainloop()

    threading.Thread(target=_run, name="foxtray-toast", daemon=True).start()


def notify_project_up(project: config.Project, icon: Notifier) -> None:
    message = f"{project.name} is up"
    try:
        _show_clickable_toast("FoxTray", message, project.url)
    except Exception:  # noqa: BLE001
        log.warning("clickable project toast failed", exc_info=True)
        icon.notify(f"{message}\n{project.url}", title="FoxTray")


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
    f"FoxTray v{__version__}\n"
    "Windows tray launcher for Django + Angular project pairs.\n\n"
    "Author: Foxugly\n"
    "Website: https://foxugly.com\n"
    "Repository: https://github.com/Foxugly/FoxTray"
)
_about_dialog_open = threading.Event()


def _show_about_dialog(title: str, body: str) -> None:
    """Open a native Windows MessageBox. Extracted so tests can monkeypatch."""
    import ctypes
    # MB_OK = 0x0, MB_ICONINFORMATION = 0x40
    ctypes.windll.user32.MessageBoxW(0, body, title, 0x40)


def on_about(icon: Notifier) -> None:
    if _about_dialog_open.is_set():
        return

    def _run() -> None:
        _about_dialog_open.set()
        try:
            _show_about_dialog(_ABOUT_TITLE, _ABOUT_BODY)
        except Exception as exc:  # noqa: BLE001 — MessageBoxW failure must not crash tray
            _notify_error(icon, exc)
        finally:
            _about_dialog_open.clear()

    threading.Thread(target=_run, name="foxtray-about", daemon=True).start()


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


def on_open_config(config_path: Path | None, icon: Notifier) -> None:
    try:
        if config_path is None:
            raise RuntimeError("No config path available")
        _open_folder_native(config_path)
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_reload_config(reload_config: ReloadableConfig, icon: Notifier) -> None:
    try:
        reload_config()
        icon.notify("Config reloaded", title="FoxTray")
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_toggle_autostart(icon: Notifier) -> None:
    from foxtray import autostart
    if not getattr(sys, "frozen", False):
        icon.notify(
            "Autostart only works for the packaged .exe (dev mode skipped)",
            title="FoxTray",
        )
        return
    try:
        if autostart.is_enabled():
            autostart.disable()
            icon.notify("Autostart disabled", title="FoxTray")
        else:
            autostart.enable(Path(sys.executable))
            icon.notify("Autostart enabled", title="FoxTray")
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)
