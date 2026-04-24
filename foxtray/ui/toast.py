"""Thread-safe clickable toast notifications.

Tkinter is strictly single-threaded. The previous implementation spawned a
fresh ``tk.Tk()`` per balloon in a new daemon thread, so two "project up"
events arriving within a poll tick produced two live Tk roots fighting
over the same global Tcl interpreter — at best a RuntimeError, at worst
a segfault or phantom window that outlived the process.

``ToastManager`` centralises all Tk work on one dedicated thread that
owns a single hidden root. Any thread submits toast requests via
``show()``; the Tk thread drains them serially via ``root.after``.
"""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass

log = logging.getLogger(__name__)

_TOAST_WIDTH = 380
_TOAST_HEIGHT = 120
_TOAST_MARGIN_X = 24
_TOAST_MARGIN_Y = 64
_TOAST_AUTOCLOSE_MS = 8000
_DRAIN_INTERVAL_MS = 80


@dataclass(frozen=True)
class ToastRequest:
    title: str
    message: str
    url: str


class ToastManager:
    """Owns a single Tk root on a dedicated thread and displays toasts serially."""

    def __init__(self) -> None:
        self._queue: queue.Queue[ToastRequest | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._root: tk.Tk | None = None

    def start(self, timeout: float = 3.0) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="foxtray-toast-ui", daemon=True
        )
        self._thread.start()
        # Wait for the Tk root so callers can assume show() lands on a live loop.
        self._ready.wait(timeout=timeout)

    def stop(self, timeout: float = 2.0) -> None:
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def show(self, title: str, message: str, url: str) -> None:
        """Submit a toast request from any thread. Non-blocking."""
        self._queue.put(ToastRequest(title=title, message=message, url=url))

    # -- owner thread only --------------------------------------------------

    def _run(self) -> None:
        try:
            self._root = tk.Tk()
            self._root.withdraw()
        except Exception:  # noqa: BLE001
            log.warning("ToastManager: Tk root creation failed", exc_info=True)
            self._ready.set()
            return
        self._ready.set()
        self._root.after(_DRAIN_INTERVAL_MS, self._drain)
        try:
            self._root.mainloop()
        except Exception:  # noqa: BLE001
            log.warning("ToastManager mainloop crashed", exc_info=True)
        finally:
            try:
                if self._root is not None:
                    self._root.destroy()
            except Exception:  # noqa: BLE001
                log.warning("ToastManager root destroy failed", exc_info=True)

    def _drain(self) -> None:
        assert self._root is not None
        try:
            while True:
                req = self._queue.get_nowait()
                if req is None:
                    self._root.quit()
                    return
                try:
                    self._show_one(req)
                except Exception:  # noqa: BLE001
                    log.warning("ToastManager: show_one failed", exc_info=True)
        except queue.Empty:
            pass
        self._root.after(_DRAIN_INTERVAL_MS, self._drain)

    def _show_one(self, req: ToastRequest) -> None:
        assert self._root is not None
        toast = tk.Toplevel(self._root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg="#202124")

        screen_w = toast.winfo_screenwidth()
        screen_h = toast.winfo_screenheight()
        x = screen_w - _TOAST_WIDTH - _TOAST_MARGIN_X
        y = screen_h - _TOAST_HEIGHT - _TOAST_MARGIN_Y
        toast.geometry(f"{_TOAST_WIDTH}x{_TOAST_HEIGHT}+{x}+{y}")

        frame = tk.Frame(toast, bg="#202124", padx=14, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame, text=req.title,
            bg="#202124", fg="#ffffff",
            anchor="w", font=("Segoe UI Semibold", 11),
        ).pack(fill="x")
        tk.Label(
            frame, text=req.message,
            bg="#202124", fg="#d7dadc",
            anchor="w", justify="left", font=("Segoe UI", 10),
        ).pack(fill="x", pady=(6, 4))
        link = tk.Label(
            frame, text=req.url,
            bg="#202124", fg="#7cc7ff",
            anchor="w", justify="left",
            cursor="hand2", font=("Segoe UI", 10, "underline"),
        )
        link.pack(fill="x")

        def _open_and_close(_event: object | None = None) -> None:
            webbrowser.open(req.url)
            try:
                toast.destroy()
            except Exception:  # noqa: BLE001
                log.warning("toast destroy after click failed", exc_info=True)

        link.bind("<Button-1>", _open_and_close)
        toast.bind("<Button-1>", _open_and_close)
        toast.after(_TOAST_AUTOCLOSE_MS, toast.destroy)
        toast.deiconify()
