# FoxTray Iter 4b — Single-Instance Lock + About Popup Design

## Goal

Two small, independent polish features:

1. **Single-instance lock** — `python main.py tray` refuses to start if another tray instance is already running on the same machine/user. Prevents two pollers fighting over `state.json` and two icons in the notification area.
2. **About popup** — new `About` entry in the root tray menu. Clicking it opens a native Windows MessageBox with project info: FoxTray version/tagline, author (Foxugly), website URL, GitHub repository URL.

## Non-goals

- Updating / self-update — Iter 4e.
- Cross-user single-instance (a second user starting their own tray is fine).
- Semver / release versioning infrastructure — version string is hardcoded for now.
- Clickable URLs inside the MessageBox (native MB doesn't support them; user copy-pastes or memorises).

## Architecture overview

**Single-instance lock:** file-based, sits at `%APPDATA%\foxtray\tray.lock`. Contains the PID of the holder. Acquired at the top of `cmd_tray`, released in a `finally` clause. Stale detection via `psutil.pid_exists` (same pattern as `state.clear_if_orphaned`).

**About popup:** new `actions.on_about(icon)` handler that calls `ctypes.windll.user32.MessageBoxW` directly. Blocks the menu-callback thread (fine — pystray's main-thread event loop keeps the icon responsive) until the user clicks OK. Menu entry added at the bottom of the root menu, after `Stop all and exit`, with a separator.

No new dependencies (`ctypes` and `psutil` already used).

## File structure

New files:
- `foxtray/singleton.py` — `acquire_lock()`, `release_lock()`, `LockHeldError`.
- `tests/test_singleton.py`.

Modified files:
- `foxtray/ui/tray.py` — `Handlers.on_about: Callable[[], None]`; `build_menu_items` appends `About` entry.
- `foxtray/ui/actions.py` — `on_about(icon)` handler.
- `foxtray/cli.py` — `cmd_tray` acquires/releases lock around `TrayApp.run()`.
- `foxtray/paths.py` — `tray_lock_file()` helper.
- `tests/test_tray.py` — new tests for `About` menu entry.
- `tests/test_tray_actions.py` — new test for `on_about` (with monkeypatched MessageBox).
- `tests/test_cli.py` — new tests for lock behavior in `cmd_tray`.
- `tests/test_tray_app.py` — update `_noop_handlers_with_tasks` / callers with new `on_about` field.

Unchanged: `foxtray/state.py`, `foxtray/project.py`, `foxtray/process.py`, `foxtray/health.py`, `foxtray/tasks.py`, `foxtray/logs.py`, `foxtray/config.py`.

## Components

### `foxtray/singleton.py` (new)

```python
"""Single-instance lock for the tray application.

File at %APPDATA%\\foxtray\\tray.lock holds the PID of the current holder.
Stale locks (holder dead) are automatically reclaimed.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import psutil

from foxtray import paths

log = logging.getLogger(__name__)


class LockHeldError(RuntimeError):
    """Raised when another live FoxTray tray instance already holds the lock."""


def acquire_lock() -> None:
    """Create tray.lock with the current PID. If the file exists and the PID
    inside is still alive, raise LockHeldError. Stale locks are silently
    reclaimed."""
    lock_path = paths.tray_lock_file()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            holder_pid = int(lock_path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            holder_pid = 0
        if holder_pid and psutil.pid_exists(holder_pid) and holder_pid != os.getpid():
            raise LockHeldError(
                f"FoxTray tray is already running (pid {holder_pid})"
            )
        # stale or same-process: overwrite below
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
```

### `foxtray/paths.py` — `tray_lock_file`

```python
def tray_lock_file() -> Path:
    return appdata_root() / "tray.lock"
```

### `foxtray/ui/actions.py` — `on_about`

```python
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
```

The `_show_about_dialog` indirection lets tests monkeypatch a fake and verify it was called with the right arguments, without popping a real dialog during CI.

### `foxtray/ui/tray.py` — menu wiring

`Handlers` dataclass gains one field:
```python
on_about: Callable[[], None]
```

`build_menu_items` adds the `About` entry after `Stop all and exit`:
```python
items.append(MenuItemSpec(text="", separator=True))
items.append(MenuItemSpec(text="About", action=handlers.on_about))
```

`TrayApp._handlers` wires it:
```python
on_about=lambda: actions.on_about(icon),
```

### `foxtray/cli.py` — lock around `cmd_tray`

```python
def cmd_tray(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    try:
        singleton.acquire_lock()
    except singleton.LockHeldError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    try:
        manager = process.ProcessManager()
        orchestrator = project.Orchestrator(manager=manager, cfg=cfg)
        tray_module.TrayApp(cfg, orchestrator, manager).run()
    finally:
        singleton.release_lock()
    return 0
```

Add `from foxtray import singleton` at the top of `cli.py`.

## Data flow

**Happy start:** `cmd_tray` → `singleton.acquire_lock()` writes PID to `tray.lock` → TrayApp runs → on exit (clean or Ctrl+C) the `finally` block calls `release_lock()` which removes the file.

**Second instance while first runs:** `cmd_tray` → `acquire_lock()` reads PID, `psutil.pid_exists` = True → `LockHeldError("FoxTray tray is already running (pid N)")` → stderr + exit 1. No TrayApp construction, no pystray icon, no menu.

**After a crashed first instance:** `tray.lock` has a stale PID. Second `cmd_tray` → `acquire_lock` sees PID, `psutil.pid_exists` = False → overwrite with own PID → proceed normally.

**About click:** pystray menu thread → `handlers.on_about()` → `actions.on_about(icon)` → `_show_about_dialog(title, body)` → `ctypes.windll.user32.MessageBoxW` blocks until OK clicked → return → menu thread idle again. Tray icon remains fully responsive throughout because the pystray event loop is on the main thread.

## Error handling

| Failure | Behavior |
|---|---|
| `tray.lock` file corrupt (non-int content) | Treated as stale; overwritten |
| `tray.lock` unreadable (permissions) | `OSError` caught, treated as stale; overwritten |
| `release_lock` fails (file already gone) | Logged as warning, no raise |
| MessageBoxW fails (should not happen, but e.g. session 0 service) | Caught, `_notify_error(icon, exc)` balloon |
| `cmd_tray` interrupted mid-run (KeyboardInterrupt, uncaught exc) | `finally` still releases lock |

## Testing

### `tests/test_singleton.py` (new)

- `test_acquire_writes_current_pid` — with a fresh `tmp_appdata`, `acquire_lock()` creates `tray.lock` containing `str(os.getpid())`.
- `test_acquire_succeeds_when_no_existing_lock` — no-op case.
- `test_acquire_raises_lockheld_when_holder_alive` — pre-write a PID that's alive (use parent PID or monkeypatch `psutil.pid_exists` to True) + make `os.getpid()` return something different → `LockHeldError`.
- `test_acquire_overwrites_stale_lock` — pre-write bogus PID `99999`, monkeypatch `psutil.pid_exists` → False → `acquire_lock()` succeeds and file contains current PID.
- `test_acquire_tolerates_same_pid_rewrite` — pre-write current PID → `acquire_lock()` succeeds (no raise).
- `test_acquire_tolerates_corrupt_lock_file` — pre-write "garbage" → `acquire_lock()` overwrites.
- `test_release_deletes_lock_when_ours` — after `acquire`, `release_lock()` removes the file.
- `test_release_noop_when_file_missing` — no raise.
- `test_release_noop_when_other_pid_holds` — pre-write a different PID → `release_lock()` does NOT delete.

### `tests/test_tray_actions.py` additions

- `test_on_about_calls_show_dialog_with_title_and_body` — monkeypatch `actions._show_about_dialog` to record args; `actions.on_about(_FakeIcon())` → recorded title starts "About" and body contains "Foxugly" / "foxugly.com" / "Foxugly/FoxTray".
- `test_on_about_notifies_on_dialog_exception` — monkeypatch `_show_about_dialog` to raise → `_FakeIcon` gets `("FoxTray error", "boom")`.

### `tests/test_tray.py` additions

- `test_menu_has_about_entry` — `build_menu_items(..., running_tasks=set())` → the root `items` contain an entry with `text="About"` placed after `Stop all and exit`.
- Update the existing `_noop_handlers()` / `_noop_handlers_with_tasks()` helpers to include `on_about=lambda: None`.

### `tests/test_tray_app.py` additions

- Update the existing `TrayApp._handlers()` plumbing test (if any) to ensure `on_about` is wired.
- Update `_FakeOrchestrator` usage if needed (unlikely — `on_about` doesn't involve orchestrator).

### `tests/test_cli.py` additions

- `test_cmd_tray_acquires_and_releases_lock` — monkeypatch `singleton.acquire_lock` and `singleton.release_lock` to record; monkeypatch `TrayApp` to a stub that returns immediately. After `cli.main(["tray"])`, both recorded. rc=0.
- `test_cmd_tray_exits_1_when_lock_held` — monkeypatch `singleton.acquire_lock` to raise `LockHeldError("already running (pid 123)")`; `cli.main(["tray"])` → rc=1, stderr contains "already running".
- `test_cmd_tray_releases_lock_even_when_trayapp_raises` — monkeypatch `TrayApp` to raise mid-`run()`; verify `release_lock` still called (finally block).

### Manual (`docs/manual-tests/iter4b.md`)

- Launch `python main.py tray`. Works. Second shell: `python main.py tray` → "FoxTray tray is already running (pid N)" stderr + exit 1. Icon still only one in the tray.
- Click About menu entry. Windows MessageBox appears with FoxTray / Foxugly / website / repo. Click OK, menu responsive again.
- Kill the first tray via Task Manager (end process). `%APPDATA%\foxtray\tray.lock` still on disk (orphan). New `python main.py tray` → starts cleanly; lock overwritten with new PID.
- Exit cleanly. `tray.lock` deleted.

## Self-review

- **Placeholder scan:** no TBD / "similar to" / "add handling".
- **Internal consistency:** `on_about: Callable[[], None]` matches the zero-arg signature used by `on_exit`, `on_stop_all`, etc. `LockHeldError(RuntimeError)` follows the `PortInUse(RuntimeError)` pattern.
- **Scope:** single iteration, single plan. About feature is additive menu-only (no state, no threading).
- **Ambiguity check:**
  - "Current PID == lock holder PID" case: the spec says `acquire_lock()` overwrites silently (same-process rewrite, e.g. after a restart where release failed). Tests cover this.
  - Lock released even on uncaught exception: `finally` in `cmd_tray` guarantees it.
  - MessageBox blocking: documented as non-issue because pystray event loop is on main thread, menu thread is separate.
