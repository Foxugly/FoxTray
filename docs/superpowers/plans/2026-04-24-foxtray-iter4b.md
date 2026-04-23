# FoxTray Iter 4b (Single-Instance Lock + About Popup) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a second tray instance from launching while one is running, and add an `About` menu entry that shows a native Windows MessageBox with project info (Foxugly, website, repo).

**Architecture:** File-based PID lock at `%APPDATA%\foxtray\tray.lock` with stale-detection via `psutil.pid_exists` (same pattern as orphan state clear). About popup via direct `ctypes.windll.user32.MessageBoxW` call (stdlib, no new deps).

**Tech Stack:** existing only — `psutil`, `ctypes` (stdlib).

**Spec:** `docs/superpowers/specs/2026-04-24-foxtray-iter4b-design.md`.

---

## File structure

New:
- `foxtray/singleton.py`
- `tests/test_singleton.py`
- `docs/manual-tests/iter4b.md`

Modified:
- `foxtray/paths.py` — add `tray_lock_file()`.
- `foxtray/ui/actions.py` — `on_about` + `_show_about_dialog` indirection.
- `foxtray/ui/tray.py` — `Handlers.on_about`, `build_menu_items` appends "About" entry, `TrayApp._handlers` wires it.
- `foxtray/cli.py` — `cmd_tray` acquires lock / releases in `finally` / catches `LockHeldError`.
- `tests/test_tray.py` — new menu test, updated `_noop_handlers*` helpers.
- `tests/test_tray_actions.py` — new `on_about` tests.
- `tests/test_cli.py` — new lock tests.

---

## Task 1: `singleton` module + tests

**Files:**
- Create: `foxtray/singleton.py`
- Modify: `foxtray/paths.py`
- Create: `tests/test_singleton.py`

- [ ] **Step 1: Add `tray_lock_file()` helper to `foxtray/paths.py`**

Find the existing `log_file` / `task_log_file` helpers and add, right after:

```python
def tray_lock_file() -> Path:
    """Path to the single-instance PID lock for the tray."""
    return appdata_root() / "tray.lock"
```

- [ ] **Step 2: Write failing tests in `tests/test_singleton.py`**

```python
"""Single-instance lock unit tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from foxtray import paths, singleton


def test_acquire_writes_current_pid(tmp_appdata: Path) -> None:
    singleton.acquire_lock()
    assert paths.tray_lock_file().exists()
    assert paths.tray_lock_file().read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_succeeds_when_no_existing_lock(tmp_appdata: Path) -> None:
    # No lock file present
    singleton.acquire_lock()  # should not raise
    singleton.release_lock()


def test_acquire_raises_lockheld_when_holder_alive(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.tray_lock_file().parent.mkdir(parents=True, exist_ok=True)
    # Write a PID we'll pretend is alive and different from ours
    other_pid = os.getpid() + 1 if os.getpid() != 99 else 100
    paths.tray_lock_file().write_text(str(other_pid), encoding="utf-8")
    monkeypatch.setattr(singleton.psutil, "pid_exists", lambda pid: pid == other_pid)
    with pytest.raises(singleton.LockHeldError, match="already running"):
        singleton.acquire_lock()


def test_acquire_overwrites_stale_lock(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.tray_lock_file().parent.mkdir(parents=True, exist_ok=True)
    paths.tray_lock_file().write_text("99999", encoding="utf-8")
    monkeypatch.setattr(singleton.psutil, "pid_exists", lambda pid: False)
    singleton.acquire_lock()
    assert paths.tray_lock_file().read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_tolerates_same_pid_rewrite(tmp_appdata: Path) -> None:
    paths.tray_lock_file().parent.mkdir(parents=True, exist_ok=True)
    paths.tray_lock_file().write_text(str(os.getpid()), encoding="utf-8")
    # psutil.pid_exists will see our own process alive — but because PID == os.getpid(),
    # acquire_lock should treat this as a same-process rewrite and succeed.
    singleton.acquire_lock()
    assert paths.tray_lock_file().read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_tolerates_corrupt_lock_file(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.tray_lock_file().parent.mkdir(parents=True, exist_ok=True)
    paths.tray_lock_file().write_text("garbage-not-an-int", encoding="utf-8")
    # Regardless of pid_exists, int parse fails → treated as stale → overwrite
    monkeypatch.setattr(singleton.psutil, "pid_exists", lambda pid: True)
    singleton.acquire_lock()
    assert paths.tray_lock_file().read_text(encoding="utf-8").strip() == str(os.getpid())


def test_release_deletes_lock_when_ours(tmp_appdata: Path) -> None:
    singleton.acquire_lock()
    singleton.release_lock()
    assert not paths.tray_lock_file().exists()


def test_release_noop_when_file_missing(tmp_appdata: Path) -> None:
    # No file, should not raise
    singleton.release_lock()


def test_release_noop_when_other_pid_holds(tmp_appdata: Path) -> None:
    paths.tray_lock_file().parent.mkdir(parents=True, exist_ok=True)
    paths.tray_lock_file().write_text("99999", encoding="utf-8")
    singleton.release_lock()
    # File should still exist (not our lock to release)
    assert paths.tray_lock_file().exists()
    assert paths.tray_lock_file().read_text(encoding="utf-8").strip() == "99999"
```

- [ ] **Step 3: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_singleton.py -v
```

Expected: 9 failures (module does not exist).

- [ ] **Step 4: Create `foxtray/singleton.py`**

```python
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
```

- [ ] **Step 5: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_singleton.py -v
```

Expected: all 9 green.

- [ ] **Step 6: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add foxtray/singleton.py foxtray/paths.py tests/test_singleton.py
git commit -m "feat(singleton): tray.lock with stale-PID reclaim"
```

Full message:
```
feat(singleton): tray.lock with stale-PID reclaim

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 2: `About` action + menu entry

**Files:**
- Modify: `foxtray/ui/actions.py`
- Modify: `foxtray/ui/tray.py`
- Modify: `tests/test_tray_actions.py`
- Modify: `tests/test_tray.py`

- [ ] **Step 1: Append failing tests to `tests/test_tray_actions.py`**

```python
def test_on_about_calls_show_dialog_with_title_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        actions, "_show_about_dialog",
        lambda title, body: recorded.append((title, body)),
    )
    actions.on_about(_FakeIcon())
    assert len(recorded) == 1
    title, body = recorded[0]
    assert "About" in title
    assert "Foxugly" in body
    assert "foxugly.com" in body
    assert "Foxugly/FoxTray" in body


def test_on_about_notifies_on_dialog_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(title: str, body: str) -> None:
        raise RuntimeError("boom")
    monkeypatch.setattr(actions, "_show_about_dialog", _boom)
    icon = _FakeIcon()
    actions.on_about(icon)
    assert icon.notifications == [("FoxTray error", "boom")]
```

Add `import pytest` at the top of `tests/test_tray_actions.py` if not already present (it should be).

- [ ] **Step 2: Append failing test to `tests/test_tray.py`**

```python
def test_menu_has_about_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    # "About" must appear after "Stop all and exit"
    non_sep = [i for i in items if not i.separator]
    texts = [i.text for i in non_sep]
    assert "About" in texts
    assert texts.index("About") > texts.index("Stop all and exit")
```

Also **update `_noop_handlers()` and `_noop_handlers_with_tasks()`** in `tests/test_tray.py` to include `on_about=lambda: None` as a new field.

- [ ] **Step 3: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py tests/test_tray_actions.py -v
```

Expected: 3+ failures (new tests + existing Handlers instantiations missing new field).

- [ ] **Step 4: Add `on_about` to `foxtray/ui/actions.py`**

Append at the end of the file:

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

- [ ] **Step 5: Extend `Handlers` and `build_menu_items` in `foxtray/ui/tray.py`**

Add a field to the `Handlers` dataclass:

```python
@dataclass
class Handlers:
    # ... existing fields unchanged ...
    on_run_task: Callable[[config_mod.Project, config_mod.Task], None]
    on_run_script: Callable[[config_mod.Script], None]
    on_about: Callable[[], None]
```

Append the `About` entry to `build_menu_items`, at the very end (after `Stop all and exit`):

```python
def build_menu_items(
    cfg: config_mod.Config,
    active: state_mod.ActiveProject | None,
    statuses: dict[str, ProjectStatus],
    handlers: Handlers,
    running_tasks: set[str],
) -> list[MenuItemSpec]:
    # ... existing body up to and including Exit / Stop all and exit ...
    items.append(MenuItemSpec(text="", separator=True))
    items.append(MenuItemSpec(text="About", action=handlers.on_about))
    return items
```

Update `TrayApp._handlers()` to wire `on_about`:

```python
on_about=lambda: actions.on_about(icon),
```

- [ ] **Step 6: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py tests/test_tray_actions.py tests/test_tray_app.py -v
```

Expected: all green.

- [ ] **Step 7: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add foxtray/ui/actions.py foxtray/ui/tray.py tests/test_tray_actions.py tests/test_tray.py
git commit -m "feat(ui): About menu entry with native Windows MessageBox"
```

Full message:
```
feat(ui): About menu entry with native Windows MessageBox

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 3: `cmd_tray` acquires/releases lock

**Files:**
- Modify: `foxtray/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Append failing tests to `tests/test_cli.py`**

```python
def test_cmd_tray_acquires_and_releases_lock(
    demo_config: Path, tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    from foxtray import singleton
    monkeypatch.setattr(singleton, "acquire_lock", lambda: calls.append("acquire"))
    monkeypatch.setattr(singleton, "release_lock", lambda: calls.append("release"))

    class _FakeTray:
        def __init__(self, cfg, orch, pm) -> None: ...
        def run(self) -> None: calls.append("run")

    from foxtray.ui import tray as tray_mod
    monkeypatch.setattr(tray_mod, "TrayApp", _FakeTray)

    rc = cli.main(["--config", str(demo_config), "tray"])
    assert rc == 0
    assert calls == ["acquire", "run", "release"]


def test_cmd_tray_exits_1_when_lock_held(
    demo_config: Path, tmp_appdata: Path,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    from foxtray import singleton
    def _raise() -> None:
        raise singleton.LockHeldError("FoxTray tray is already running (pid 123)")
    monkeypatch.setattr(singleton, "acquire_lock", _raise)

    rc = cli.main(["--config", str(demo_config), "tray"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "already running" in err
    assert "123" in err


def test_cmd_tray_releases_lock_even_when_trayapp_raises(
    demo_config: Path, tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    released: list[bool] = []
    from foxtray import singleton
    monkeypatch.setattr(singleton, "acquire_lock", lambda: None)
    monkeypatch.setattr(singleton, "release_lock", lambda: released.append(True))

    class _BoomTray:
        def __init__(self, cfg, orch, pm) -> None: ...
        def run(self) -> None:
            raise RuntimeError("mid-run crash")

    from foxtray.ui import tray as tray_mod
    monkeypatch.setattr(tray_mod, "TrayApp", _BoomTray)

    with pytest.raises(RuntimeError, match="mid-run crash"):
        cli.main(["--config", str(demo_config), "tray"])
    assert released == [True]
```

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k "tray_acquires or tray_exits_1 or tray_releases"
```

Expected: 3 failures (`cmd_tray` doesn't yet import/use `singleton`).

- [ ] **Step 3: Update `cmd_tray` and imports in `foxtray/cli.py`**

Add to imports:
```python
from foxtray import singleton
```

Replace `cmd_tray`:
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

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_cli.py -v
```

Expected: all green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add foxtray/cli.py tests/test_cli.py
git commit -m "feat(cli): cmd_tray acquires single-instance lock, releases in finally"
```

Full message:
```
feat(cli): cmd_tray acquires single-instance lock, releases in finally

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 4: Manual smoke test document

**Files:**
- Create: `docs/manual-tests/iter4b.md`

- [ ] **Step 1: Create `docs/manual-tests/iter4b.md`**

```markdown
# FoxTray Iter 4b — Manual Test Log

Prerequisite: Iter 4a manual test (`docs/manual-tests/iter4a.md`) passed.

## Environment

- Date: <fill>
- HEAD: <commit sha>
- Full test suite: `./.venv/Scripts/python.exe -m pytest -v` (must show all green)

## Single-instance lock

- [ ] Clean state: delete `%APPDATA%\foxtray\tray.lock` if present.
- [ ] Launch `python main.py tray` in shell #1. Tray icon appears.
- [ ] In shell #2: `python main.py tray` — within a second prints `FoxTray tray is already running (pid N)` to stderr, exits with code 1. No second tray icon appears.
- [ ] Check `%APPDATA%\foxtray\tray.lock` — contains the PID of shell #1's Python.
- [ ] Right-click icon → Exit in shell #1. Tray disappears. `tray.lock` is deleted.
- [ ] Launch `python main.py tray` in shell #1 again. Successful.
- [ ] Kill Python in shell #1 via Task Manager (End Task, not menu Exit). Tray disappears but `tray.lock` remains (stale).
- [ ] Launch `python main.py tray` in shell #2: succeeds. `tray.lock` is overwritten with new PID.
- [ ] Exit cleanly. Lock file deleted.

## About popup

- [ ] With tray running, right-click icon → click `About` (at the bottom of the menu).
- [ ] Native Windows MessageBox appears with title `About FoxTray` and body containing:
  - Line 1: `FoxTray`
  - Line 2: `Windows tray launcher for Django + Angular project pairs.`
  - `Author: Foxugly`
  - `Website: https://foxugly.com`
  - `Repository: https://github.com/Foxugly/FoxTray`
- [ ] Click OK. Dialog disappears. Tray icon and menu still responsive.
- [ ] While dialog is open, verify clicking the icon in the notification area still works (can open menu in parallel). pystray continues running.

## Known Iter 4b limitations (intentional)

- Lock is per-user, not per-machine. A second user logged in via RDP or fast user switching can still launch their own tray.
- Lock file is cleaned up only on clean exit. Kill-9 / power-cycle leaves a stale lock that is auto-reclaimed on the next launch.
- About MessageBox URLs are not clickable (native Windows MessageBox limitation).

## Observed issues
<!-- Fill during run. -->

_None yet._
```

- [ ] **Step 2: Commit**

```bash
git add docs/manual-tests/iter4b.md
git commit -m "docs(iter4b): manual smoke checklist for single-instance + About"
```

Full message:
```
docs(iter4b): manual smoke checklist for single-instance + About

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Self-review summary

- **Spec coverage:** Task 1 covers singleton module + paths helper; Task 2 covers About action + menu wiring; Task 3 covers CLI integration with acquire/release/finally; Task 4 is the manual checklist.
- **Placeholder scan:** no TBD / "similar to" / "add handling".
- **Type consistency:** `LockHeldError(RuntimeError)`, `on_about: Callable[[], None]`, `_show_about_dialog(title: str, body: str)` — consistent across tasks.
- **Scope:** single iteration. No transient failures expected between tasks (Task 2's `Handlers` field addition is the only signature change, closed in the same task via `_noop_handlers` updates).
