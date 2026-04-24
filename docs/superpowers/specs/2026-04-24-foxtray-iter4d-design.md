# FoxTray Iter 4d — Launch-on-Boot + Global Keyboard Shortcut Design (Skeleton)

> **Status:** design outline only. No implementation plan yet — the two features are related by "OS integration" but can also be split into 4d-boot and 4d-shortcut if they diverge during brainstorming.

## Goal

Two Windows-integration features:

1. **Launch-on-Windows-boot** — a menu entry (toggle) that registers / unregisters FoxTray for automatic start when the user signs into Windows.
2. **Global keyboard shortcut** — a user-configurable hotkey (e.g., `Ctrl+Shift+F`) that opens the tray menu from anywhere, without requiring the mouse to reach the notification area.

## Non-goals (for Iter 4d)

- Multiple hotkeys (multi-action bindings). Single chord opens the menu — that's it.
- Hotkey for individual tasks / scripts (would require a richer binding config).
- Launch at Windows boot time (before user login) — Iter 4d targets user-login autostart only. Boot-time would require a service / scheduled task with SYSTEM privileges.
- Per-project autostart — the menu entry is global "start tray on login", not "auto-start FoxRunner when tray launches".

## Architecture overview

### Launch-on-boot

Two common mechanisms on Windows:

- **Registry key** `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` — each named value is an executable path that starts on login. Simplest. Per-user. Reversible with a single deletion.
- **Startup folder** `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup` — drop a `.lnk` shortcut. Works but requires COM to create shortcuts; slightly more code.

**Pick the registry approach.** Uses `winreg` stdlib, no deps.

```python
# foxtray/autostart.py
import winreg

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "FoxTray"

def is_enabled() -> bool: ...
def enable(exe_path: Path) -> None:
    # Write HKCU\...\Run\FoxTray = f'"{exe_path}" tray'
    ...
def disable() -> None:
    # Delete HKCU\...\Run\FoxTray (ignore if missing)
    ...
```

The `exe_path` in bundled mode is `sys.executable` (the FoxTray.exe from Iter 4c). In dev mode it's `python.exe` — we probably don't want dev autostart, so the feature is gated on `sys.frozen`.

### Global keyboard shortcut

Registering a global hotkey on Windows from Python has a few options:

- **`keyboard` package (third-party)** — simple API (`keyboard.add_hotkey("ctrl+shift+f", callback)`) but requires admin on some setups, polls input globally, and is a privacy/security footprint we should think about.
- **`pynput` package (third-party)** — similar tradeoffs.
- **`RegisterHotKey` via `ctypes`** — native Windows API, no deps, no admin required, but the window-thread message loop gets messy to reconcile with pystray's event loop.

The cleanest Python-stdlib-only path is **`ctypes` + a dedicated message-loop thread**:
1. Start a daemon thread with its own thread-level `RegisterHotKey` (`MOD_CONTROL | MOD_SHIFT`, vk for F).
2. Pump messages with `GetMessage` / `TranslateMessage` / `DispatchMessage` inside that thread.
3. On `WM_HOTKEY`, call `icon.visible = True` to pop the menu (actually pystray needs `icon.notify` or a custom action — TBD, needs a pystray-specific trick to "open the menu programmatically").

Open question: pystray does not have a public API to open the context menu from code. Possible fallbacks:
- Fire a notification balloon telling the user "Menu hotkey registered, click the icon".
- Call `Shell_NotifyIconW` directly to send a mouse-click event to the icon. Hacky.
- Accept that the hotkey shows a simplified balloon / quick menu via `tkinter` instead of pystray's menu.

**This needs brainstorming.** Possibly simpler: the hotkey triggers an action directly (e.g., cycle next project, or show a balloon with status) instead of opening the menu.

### Hotkey config

In `config.yaml`:
```yaml
hotkey:
  modifiers: ctrl+shift
  key: F
  action: open_menu  # or "cycle_project", "status_balloon", ...
```

Optional — if omitted, no hotkey registered.

Validation: parse modifiers (`ctrl` / `shift` / `alt` / `win`), map `key` to vk code via a lookup table.

### Menu wiring

New menu entry: `Autostart` (checkable toggle):
- If enabled: `Autostart ✓` (or just "Autostart on login" with `checked=True`).
- Click: toggle via `autostart.enable(sys.executable)` / `autostart.disable()`.

pystray supports `MenuItem(checked=lambda item: autostart.is_enabled())`. Use it.

No menu entry for the hotkey itself (it's YAML-configured).

## Open questions (to resolve in brainstorming)

1. **Which hotkey mechanism?** Stdlib `RegisterHotKey` + message loop (preferred) vs `keyboard`/`pynput` package.
2. **What does the hotkey DO?** Opening pystray's context menu programmatically is nontrivial — is a simpler action (status balloon / cycle active project) acceptable?
3. **Autostart only for bundled .exe, or also for dev Python?** Lean: bundled only. Dev users run the tray manually.
4. **Autostart command line:** `"FoxTray.exe" tray` — should we add a `--silent` flag to suppress all stderr on startup, or is stderr-to-void acceptable from the registry invocation?
5. **Interaction with Iter 4b single-instance lock**: if autostart launches the tray, and the user also clicks a shortcut to launch it a second time, the second one exits cleanly — existing behavior, no issue. Verify.
6. **Hotkey config hot-reload?** Probably no — set once at `tray` startup from `config.yaml`, reboot tray to change. Acceptable.

## File structure (anticipated)

New files:
- `foxtray/autostart.py` — winreg Run key management.
- `foxtray/hotkey.py` — RegisterHotKey + message loop thread (or wrapper around a third-party).
- `tests/test_autostart.py` — monkeypatched winreg.
- `tests/test_hotkey.py` — unit tests for config parsing; the message loop is hard to unit-test.
- `docs/manual-tests/iter4d.md`.

Modified files:
- `foxtray/config.py` — optional top-level `hotkey:` block with a `HotkeyConfig` dataclass.
- `foxtray/ui/tray.py` — `Handlers.on_toggle_autostart`; `build_menu_items` adds the `Autostart` checkable entry; `TrayApp.__init__` starts the hotkey thread if configured.
- `foxtray/ui/actions.py` — `on_toggle_autostart`.
- `foxtray/cli.py` — no change expected; `cmd_tray` passes the hotkey config to `TrayApp`.

## Next step

Brainstorming session to answer open questions, especially (1) hotkey mechanism and (2) hotkey action semantics. Then plan.
