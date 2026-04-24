# FoxTray Iter 4d — Launch-on-Boot Design (reduced scope)

> **Status:** Reduced from the skeleton's original "launch-on-boot + hotkey" scope to launch-on-boot only. The global-hotkey feature is **deferred** because pystray exposes no public API to open its context menu programmatically, leaving the hotkey with no natural "open menu" semantics. If you later want a hotkey action (e.g., "toggle active project", "show status balloon", "open About"), reopen that spec.

## Goal

Menu entry that toggles whether FoxTray auto-starts when the user signs into Windows.

## Non-goals (for Iter 4d)

- Global keyboard shortcut — deferred.
- Boot-time autostart before login (requires SYSTEM service — not in scope).
- Per-project autostart (Iter 5b already covers `auto_start:` in config for "which project to start when the tray launches").

## Architecture overview

Windows offers two simple per-user autostart mechanisms:

- **`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` registry key** — each named value is an executable to launch on login. Simplest, reversible with one deletion. Stdlib `winreg`.
- **Startup folder** `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup` — drop a `.lnk` shortcut. Requires COM to make shortcuts, more code.

**Decision: registry.** One module (`foxtray/autostart.py`) wrapping `winreg` for `is_enabled()`, `enable(exe_path)`, `disable()`. No new deps.

### Frozen-only

Autostart is only meaningful for the packaged `.exe`. When running from dev Python, the menu entry still appears but the "Start at login" value writes `python.exe main.py tray` — which would trigger a console window flash on login. That's ugly. **Gate the menu entry: only enabled when `sys.frozen` is True.**

### Menu integration

New menu entry `Start at login` placed before `About`. Checkable:
- `checked=lambda _: autostart.is_enabled()` reads the registry each time the menu is painted.
- Click toggles: if enabled → `disable()`; else → `enable(Path(sys.executable))`.

pystray's `MenuItem` supports `checked=callable` (returns bool).

## File structure

New:
- `foxtray/autostart.py` — `is_enabled()`, `enable(exe_path)`, `disable()`.
- `tests/test_autostart.py` — monkeypatched `winreg`.
- `docs/manual-tests/iter4d.md`.

Modified:
- `foxtray/ui/tray.py` — `Handlers.on_toggle_autostart`, menu entry, wiring.
- `foxtray/ui/actions.py` — `on_toggle_autostart`.
- `tests/test_tray_actions.py` — handler tests.
- `tests/test_tray.py` — menu entry presence + update handlers helper.

## Components

### `foxtray/autostart.py`

```python
"""Windows registry Run key for per-user autostart."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "FoxTray"


def is_enabled() -> bool:
    """True if HKCU\\...\\Run\\FoxTray is set."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        log.warning("autostart.is_enabled: OSError reading registry", exc_info=True)
        return False


def enable(exe_path: Path) -> None:
    """Register exe_path + ' tray' in the HKCU Run key under name 'FoxTray'."""
    import winreg
    value = f'"{exe_path}" tray'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, value)


def disable() -> None:
    """Remove HKCU\\...\\Run\\FoxTray. Best-effort — never raises on absent value."""
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        return
    except OSError:
        log.warning("autostart.disable: OSError modifying registry", exc_info=True)
```

### `foxtray/ui/actions.py`

```python
import sys


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
```

### `foxtray/ui/tray.py`

`Handlers` gains:
```python
on_toggle_autostart: Callable[[], None]
```

`build_menu_items` adds a new entry BEFORE `About` (at the very end, between the final separator and "About"):
```python
items.append(MenuItemSpec(
    text="Start at login",
    action=handlers.on_toggle_autostart,
    # NOTE: pystray supports `checked=...` but our MenuItemSpec dataclass
    # does not yet have it. Adding it is Iter 4d's small dataclass tweak.
))
```

**New `MenuItemSpec.checked` field** (optional):
```python
@dataclass(frozen=True)
class MenuItemSpec:
    text: str
    action: Callable[[], None] | None = None
    enabled: bool = True
    submenu: tuple["MenuItemSpec", ...] = field(default_factory=tuple)
    separator: bool = False
    checked: Callable[[], bool] | None = None  # NEW: returns True → menu shows ✓
```

`_spec_to_pystray` honors `checked`:
```python
if spec.checked is not None:
    return pystray.MenuItem(
        spec.text,
        lambda _icon, _item: action(),
        enabled=spec.enabled,
        checked=lambda _item: spec.checked(),
    )
```

(Keep the existing non-checked branch as-is for all other entries.)

The `Start at login` entry gets `checked=lambda: autostart.is_enabled()`:
```python
from foxtray import autostart

items.append(MenuItemSpec(
    text="Start at login",
    action=handlers.on_toggle_autostart,
    checked=lambda: autostart.is_enabled(),
))
```

`TrayApp._handlers` wires:
```python
on_toggle_autostart=lambda: actions.on_toggle_autostart(icon),
```

## Testing

- `test_autostart.py`:
  - `test_is_enabled_false_when_value_missing` — monkeypatch `winreg.OpenKey` raises `FileNotFoundError` OR returns a key whose `QueryValueEx` raises.
  - `test_is_enabled_true_when_value_present` — monkeypatch returns a mock key with valid `QueryValueEx`.
  - `test_enable_writes_value` — monkeypatch `winreg.CreateKey` and `winreg.SetValueEx` to record args; call `enable(Path("C:\\x\\FoxTray.exe"))`; assert `SetValueEx(..., _VALUE_NAME, 0, REG_SZ, '"C:\\x\\FoxTray.exe" tray')`.
  - `test_disable_deletes_value` — similar.
  - `test_disable_noop_when_missing` — monkeypatch `OpenKey` raises `FileNotFoundError`; `disable()` returns silently.

Mocking `winreg` is nontrivial (Windows-only module, module-level constants). Use `unittest.mock.MagicMock` + `monkeypatch.setattr("foxtray.autostart.winreg", mock)`.

Actually, since `winreg` is imported inside the functions (`import winreg`), we need a different strategy. Let me adjust: **import `winreg` at module top** to make monkeypatching trivial, and guard it with a Windows check:

```python
# top of foxtray/autostart.py
import winreg  # stdlib on Windows
```

And the tests monkeypatch `foxtray.autostart.winreg` with a mock.

- `test_tray.py`: `test_menu_has_start_at_login_entry` — verify an entry named "Start at login" exists between separator and About.
- `test_tray.py`: update `_noop_handlers()` / `_noop_handlers_with_tasks()` to include `on_toggle_autostart=lambda: None`.
- `test_tray_actions.py`:
  - `test_on_toggle_autostart_enables_when_currently_disabled` — monkeypatch `autostart.is_enabled` → False, `autostart.enable` records.
  - `test_on_toggle_autostart_disables_when_currently_enabled`.
  - `test_on_toggle_autostart_notifies_when_not_frozen` — monkeypatch `sys.frozen` absent → balloon "Autostart only works for the packaged .exe".

## Manual smoke

```markdown
# FoxTray Iter 4d — Manual Test Log

Prerequisite: Iter 4c passed (you have a built FoxTray.exe).

## Start at login (bundled .exe only)

- [ ] Launch `dist\FoxTray.exe`. Right-click → Start at login. Balloon "Autostart enabled".
- [ ] `reg query HKCU\Software\Microsoft\Windows\CurrentVersion\Run` — has a `FoxTray` value pointing to the .exe path.
- [ ] Right-click → Start at login. Balloon "Autostart disabled". Registry value removed.
- [ ] Sign out + sign in. If autostart was enabled before sign-out, tray is visible after login.

## Dev mode behavior

- [ ] `./.venv/Scripts/python.exe main.py tray` (not the .exe). Right-click → Start at login. Balloon "Autostart only works for the packaged .exe (dev mode skipped)". Registry NOT modified.

## Known limitations
- Per-user only (HKCU). A different Windows user needs their own toggle.
- If FoxTray.exe moves, registry entry points to the old location. User must re-enable from the new location.

## Observed issues
_None yet._
```

## Self-review

- Decisions made: registry-based (vs startup folder), frozen-only (dev mode balloons a skip message), `checked=` via new `MenuItemSpec.checked` field.
- Placeholder scan: clean.
- Deferred cleanly: hotkey feature moved out of this iteration with documented reason.
