# FoxTray Iter 4d (Launch-on-Boot) Implementation Plan

**Goal:** `Start at login` menu entry (checkable) that writes/removes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\FoxTray` pointing at `sys.executable` + " tray".

**Scope note:** Hotkey feature deferred per spec.

**Spec:** `docs/superpowers/specs/2026-04-24-foxtray-iter4d-design.md`.

---

## Task 1: `autostart` module

**Files:** `foxtray/autostart.py`, `tests/test_autostart.py`.

- [ ] **Step 1: Create `tests/test_autostart.py` with failing tests**

```python
"""foxtray.autostart unit tests — winreg monkeypatched."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from foxtray import autostart


def test_is_enabled_true_when_value_present(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__ = MagicMock(return_value=mock_key)
    mock_key.__exit__ = MagicMock(return_value=False)
    mock_winreg.OpenKey.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = ('"C:\\x.exe" tray', 1)
    monkeypatch.setattr(autostart, "winreg", mock_winreg)
    assert autostart.is_enabled() is True


def test_is_enabled_false_when_value_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__ = MagicMock(return_value=mock_key)
    mock_key.__exit__ = MagicMock(return_value=False)
    mock_winreg.OpenKey.return_value = mock_key
    mock_winreg.QueryValueEx.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", mock_winreg)
    assert autostart.is_enabled() is False


def test_is_enabled_false_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", mock_winreg)
    assert autostart.is_enabled() is False


def test_enable_writes_value(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__ = MagicMock(return_value=mock_key)
    mock_key.__exit__ = MagicMock(return_value=False)
    mock_winreg.CreateKey.return_value = mock_key
    mock_winreg.REG_SZ = 1  # fake constant
    monkeypatch.setattr(autostart, "winreg", mock_winreg)

    autostart.enable(Path("C:\\foxtray\\FoxTray.exe"))

    mock_winreg.SetValueEx.assert_called_once()
    args = mock_winreg.SetValueEx.call_args[0]
    # (key, value_name, reserved, type, value)
    assert args[1] == "FoxTray"
    assert args[3] == 1  # REG_SZ
    assert args[4] == '"C:\\foxtray\\FoxTray.exe" tray'


def test_disable_deletes_value(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__ = MagicMock(return_value=mock_key)
    mock_key.__exit__ = MagicMock(return_value=False)
    mock_winreg.OpenKey.return_value = mock_key
    mock_winreg.KEY_SET_VALUE = 2
    monkeypatch.setattr(autostart, "winreg", mock_winreg)

    autostart.disable()

    mock_winreg.DeleteValue.assert_called_once_with(mock_key, "FoxTray")


def test_disable_noop_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", mock_winreg)
    # Should not raise
    autostart.disable()
```

- [ ] **Step 2: Run, confirm failures (module doesn't exist).**

- [ ] **Step 3: Create `foxtray/autostart.py`**

```python
"""Windows registry Run key for per-user autostart."""
from __future__ import annotations

import logging
import winreg
from pathlib import Path

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "FoxTray"


def is_enabled() -> bool:
    """True if HKCU\\...\\Run\\FoxTray is set."""
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
    value = f'"{exe_path}" tray'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, value)


def disable() -> None:
    """Remove HKCU\\...\\Run\\FoxTray. Best-effort."""
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

- [ ] **Step 4: Run tests, confirm all 6 pass.**

- [ ] **Step 5: Run full suite, all green.**

- [ ] **Step 6: Commit**

```
feat(autostart): HKCU Run key wrapper for per-user login autostart

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 2: `on_toggle_autostart` action + menu entry with checked state

**Files:** `foxtray/ui/actions.py`, `foxtray/ui/tray.py`, `tests/test_tray_actions.py`, `tests/test_tray.py`.

- [ ] **Step 1: Append failing tests to `tests/test_tray_actions.py`**

```python
def test_on_toggle_autostart_enables_when_currently_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from foxtray import autostart
    enabled_calls: list[Path] = []
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", r"C:\fake\FoxTray.exe", raising=False)
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart, "enable", enabled_calls.append)
    monkeypatch.setattr(autostart, "disable", lambda: None)

    icon = _FakeIcon()
    actions.on_toggle_autostart(icon)
    assert enabled_calls == [Path(r"C:\fake\FoxTray.exe")]
    assert any("enabled" in message for _title, message in icon.notifications)


def test_on_toggle_autostart_disables_when_currently_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from foxtray import autostart
    disable_calls: list[bool] = []
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr(autostart, "is_enabled", lambda: True)
    monkeypatch.setattr(autostart, "enable", lambda p: None)
    monkeypatch.setattr(autostart, "disable", lambda: disable_calls.append(True))

    icon = _FakeIcon()
    actions.on_toggle_autostart(icon)
    assert disable_calls == [True]
    assert any("disabled" in message for _title, message in icon.notifications)


def test_on_toggle_autostart_noop_when_not_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from foxtray import autostart
    called: list[bool] = []
    monkeypatch.delattr("sys.frozen", raising=False)
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart, "enable", lambda p: called.append(True))
    monkeypatch.setattr(autostart, "disable", lambda: called.append(True))

    icon = _FakeIcon()
    actions.on_toggle_autostart(icon)
    assert called == []
    assert any("packaged" in message for _title, message in icon.notifications)
```

- [ ] **Step 2: Append failing test to `tests/test_tray.py`**

```python
def test_menu_has_start_at_login_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    non_sep = [i for i in items if not i.separator]
    texts = [i.text for i in non_sep]
    assert "Start at login" in texts
    # Placed BEFORE About
    assert texts.index("Start at login") < texts.index("About")
```

Also update `_noop_handlers()` and `_noop_handlers_with_tasks()` — add:
```python
on_toggle_autostart=lambda: None,
```

- [ ] **Step 3: Run, confirm failures**

- [ ] **Step 4: Add `on_toggle_autostart` to `foxtray/ui/actions.py`**

Append at end of file:
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

(`import sys` is likely already at module scope. Don't duplicate.)

- [ ] **Step 5: Add `checked` field to `MenuItemSpec` in `foxtray/ui/tray.py`**

Current dataclass:
```python
@dataclass(frozen=True)
class MenuItemSpec:
    text: str
    action: Callable[[], None] | None = None
    enabled: bool = True
    submenu: tuple["MenuItemSpec", ...] = field(default_factory=tuple)
    separator: bool = False
```

Add:
```python
    checked: Callable[[], bool] | None = None
```

- [ ] **Step 6: Update `_spec_to_pystray` to honor `checked`**

Current relevant branch (simplified):
```python
def _spec_to_pystray(spec: MenuItemSpec) -> pystray.MenuItem:
    if spec.separator:
        return pystray.Menu.SEPARATOR
    if spec.submenu:
        return pystray.MenuItem(
            spec.text,
            pystray.Menu(*(_spec_to_pystray(s) for s in spec.submenu)),
            enabled=spec.enabled,
        )
    action = spec.action if spec.action is not None else (lambda: None)
    return pystray.MenuItem(
        spec.text,
        lambda _icon, _item: action(),
        enabled=spec.enabled,
    )
```

Replace the final return to:
```python
    action = spec.action if spec.action is not None else (lambda: None)
    if spec.checked is not None:
        return pystray.MenuItem(
            spec.text,
            lambda _icon, _item: action(),
            enabled=spec.enabled,
            checked=lambda _item, c=spec.checked: c(),
        )
    return pystray.MenuItem(
        spec.text,
        lambda _icon, _item: action(),
        enabled=spec.enabled,
    )
```

- [ ] **Step 7: Extend `Handlers` dataclass in `foxtray/ui/tray.py`**

Add:
```python
on_toggle_autostart: Callable[[], None]
```

- [ ] **Step 8: Add `Start at login` entry in `build_menu_items`**

Currently `build_menu_items` appends (in order):
- projects
- (optional) Scripts ▸
- separator + Open logs folder
- separator + Stop all
- separator + Exit + Stop all and exit
- separator + About

Insert BEFORE the final separator+About, or just BEFORE About:
```python
from foxtray import autostart as autostart_mod

# ... in build_menu_items, right before the 'About' append ...
items.append(MenuItemSpec(
    text="Start at login",
    action=handlers.on_toggle_autostart,
    checked=lambda: autostart_mod.is_enabled(),
))
```

Make sure `import sys` is in tray.py (it probably is).

- [ ] **Step 9: Wire `TrayApp._handlers`**

Add:
```python
on_toggle_autostart=lambda: actions.on_toggle_autostart(icon),
```

- [ ] **Step 10: Run full suite — all green**

- [ ] **Step 11: Commit**

```
feat(ui/tray): Start at login menu entry (checkable, bundled-exe only)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 3: Manual smoke doc

File: `docs/manual-tests/iter4d.md` — content in the spec.

Commit:
```
docs(iter4d): manual smoke checklist for launch-on-boot
```

---

## Self-review

- Task 1 is standalone (new module + tests); no signature changes.
- Task 2 adds one `Handlers` field. The `_noop_handlers*` update is in the same task.
- `MenuItemSpec.checked` is an additive field with default None — existing tests pass unchanged.
- `_spec_to_pystray` change preserves the old behavior for entries without `checked`.
- Hotkey is explicitly out of scope — deferred for separate brainstorming if needed.
