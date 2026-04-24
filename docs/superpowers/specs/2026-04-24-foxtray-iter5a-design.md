# FoxTray Iter 5a — Quick Wins Bundle Design

## Goal

Five small UX improvements that reduce friction in daily use. None require new deps. Implementable together because they touch the same 2-3 files.

1. **Restart action** — per-project menu entry that stops and restarts in one click.
2. **Open logs folder** — root menu entry that opens `%APPDATA%\foxtray\logs\` in Explorer.
3. **Copy URL to clipboard** — per-project submenu entry that copies `project.url` to the Windows clipboard.
4. **Icon tooltip reflects status** — hover text on the tray icon shows current project + state (no menu open needed).
5. **Open project root folder** — per-project submenu entry, shown only when `path_root:` is set in YAML. Points to the parent folder containing backend + frontend.

## Non-goals

- Keyboard shortcut for these actions (Iter 4d).
- Rich click-to-action balloons (pystray limitation).
- Cross-platform clipboard (Windows-only via `clip.exe`).
- Tooltip live-updating faster than the 3s poll tick.

## Architecture overview

- **Restart**: `actions.on_restart(orchestrator, project, icon, user_initiated)` spawns a background thread that calls `orch.stop(name)` then `orch.start(project)`. Thread keeps the menu-callback thread responsive (stop+wait_port_free can take 10s). No extra state — the existing poller picks up the transition from the two sequential state changes.
- **Open logs folder**: `actions.on_open_logs_folder(icon)` calls `os.startfile(paths.logs_dir())`. New helper `paths.logs_dir()` returns `appdata_root() / "logs"`.
- **Copy URL**: `actions.on_copy_url(project.url, icon)` spawns `subprocess.run(["clip"], input=url, text=True, ...)`. Balloon on success: "URL copied".
- **Tooltip**: `TrayApp._poll_tick` computes a human-readable status string at the end of each tick and assigns `self._icon.title = status_str`. String built from `compute_icon_state` result + active project name. Examples: `"FoxTray — idle"`, `"FoxTray — FoxRunner RUNNING"`, `"FoxTray — FoxRunner PARTIAL (frontend crashed)"`.
- **Project root folder**: new optional `path_root: Path | None = None` on `Project`. Menu entry `Open project folder` shown only when `path_root` is set.

## File structure

New files:
- None.

Modified files:
- `foxtray/config.py` — `Project.path_root: Path | None = None` (optional); `_parse_project` reads + validates (absolute path required if present).
- `foxtray/paths.py` — add `logs_dir() -> Path`.
- `foxtray/ui/actions.py` — add `on_restart`, `on_open_logs_folder`, `on_copy_url`; `_copy_to_clipboard_windows` helper (monkeypatchable for tests).
- `foxtray/ui/tray.py` — `Handlers` gains `on_restart: Callable[[Project], None]`, `on_open_logs_folder: Callable[[], None]`, `on_copy_url: Callable[[str], None]`; `_project_submenu` renders `Restart` (running only), `Copy URL`, `Open project folder` (conditional); `build_menu_items` renders `Open logs folder` at root; `TrayApp._poll_tick` updates `self._icon.title` at tick end.
- `tests/test_config.py` — `path_root` parsing tests.
- `tests/test_tray.py` — menu tests for new entries.
- `tests/test_tray_actions.py` — handler tests for the 3 new functions.
- `tests/test_tray_app.py` — poll_tick tooltip update test.
- `foxtray/ui/actions.py` — fix `_noop_handlers*` in test helpers to include new fields.

## Components

### `foxtray/config.py` — `path_root`

```python
@dataclass(frozen=True)
class Project:
    name: str
    url: str
    backend: Backend
    frontend: Frontend
    start_timeout: int = 30
    tasks: tuple[Task, ...] = ()
    path_root: Path | None = None  # NEW
```

In `_parse_project`:
```python
path_root_raw = raw.get("path_root")
path_root: Path | None = None
if path_root_raw is not None:
    path_root = Path(path_root_raw)
    if not path_root.is_absolute():
        raise ConfigError(
            f"project {name!r}: path_root must be absolute, got {path_root_raw!r}"
        )
```

### `foxtray/paths.py`

```python
def logs_dir() -> Path:
    return appdata_root() / "logs"
```

### `foxtray/ui/actions.py`

```python
import subprocess
import threading


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
    """Copy text to Windows clipboard via built-in clip.exe. Extracted for tests."""
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
```

### `foxtray/ui/tray.py`

`Handlers` gains:
```python
on_restart: Callable[[config_mod.Project], None]
on_open_logs_folder: Callable[[], None]
on_copy_url: Callable[[str], None]
```

`_project_submenu` adds 3 entries (after the existing Open-folder ones, before `Tasks ▸` if present):
```python
if icon_state != "stopped":
    entries.append(MenuItemSpec(
        text="Restart",
        action=lambda p=project: handlers.on_restart(p),
    ))
entries.append(MenuItemSpec(
    text="Copy URL",
    action=lambda u=project.url: handlers.on_copy_url(u),
))
if project.path_root is not None:
    entries.append(MenuItemSpec(
        text="Open project folder",
        action=lambda path=project.path_root: handlers.on_open_folder(path),
    ))
```

`build_menu_items` adds `Open logs folder` at root (after `Scripts ▸` if present, before the `Stop all` separator):
```python
items.append(MenuItemSpec(text="", separator=True))
items.append(MenuItemSpec(
    text="Open logs folder",
    action=handlers.on_open_logs_folder,
))
```

Tooltip update in `_poll_tick`:
```python
# At the end of the successful tick body, after state.clear_if_orphaned block:
if self._icon is not None:
    try:
        self._icon.title = _tooltip_text(curr_active, curr_statuses)
    except Exception:
        log.warning("tooltip update failed", exc_info=True)
```

Helper:
```python
def _tooltip_text(
    active: state_mod.ActiveProject | None,
    statuses: dict[str, ProjectStatus],
) -> str:
    if active is None:
        return "FoxTray — idle"
    status = statuses.get(active.name)
    if status is None:
        return f"FoxTray — {active.name} (unknown)"
    if status.backend_alive and status.frontend_alive and status.url_ok:
        return f"FoxTray — {active.name} RUNNING"
    if status.backend_alive and status.frontend_alive:
        return f"FoxTray — {active.name} (starting…)"
    if status.backend_alive:
        return f"FoxTray — {active.name} PARTIAL (frontend down)"
    if status.frontend_alive:
        return f"FoxTray — {active.name} PARTIAL (backend down)"
    return f"FoxTray — {active.name} stopped"
```

`TrayApp._handlers()` wires the three new callbacks.

### Menu layout after this change

```
FoxRunner (RUNNING)
  ├─ Stop
  ├───
  ├─ Open in browser
  ├─ Open backend folder
  ├─ Open frontend folder
  ├─ Restart                   ← new (visible when running/partial)
  ├─ Copy URL                  ← new
  ├─ Open project folder       ← new (only if path_root set)
  └─ Tasks ▸                   (from Iter 4a)
───
Scripts ▸                      (from Iter 4a, if any)
───
Open logs folder               ← new
───
Stop all
───
Exit
Stop all and exit
───
About                          (from Iter 4b)
```

## Error handling

| Failure | Behavior |
|---|---|
| `on_restart` stop fails | `_notify_error` balloon, no start attempt |
| `on_restart` start fails | `_notify_error` balloon, state left as stop cleared it |
| `clip.exe` not on PATH | `subprocess.CalledProcessError` → `_notify_error` |
| Clipboard subprocess exits non-zero | `CalledProcessError` → `_notify_error` |
| `os.startfile` fails on logs dir | `_notify_error` |
| Tooltip assignment raises (pystray quirk) | Logged warning; tick continues |
| `path_root` invalid in YAML | `ConfigError` at load (existing pattern) |

## Testing

**Unit:**
- `test_config.py` — `path_root` defaults None; accepts absolute; rejects relative.
- `test_tray.py` — `Restart` visible on running, hidden on stopped; `Copy URL` always visible; `Open project folder` conditional on `path_root`; `Open logs folder` at root.
- `test_tray_actions.py`:
  - `on_restart` calls `orchestrator.stop` then `.start` (via thread — test waits for completion); adds to `user_initiated`.
  - `on_open_logs_folder` calls `_open_folder_native(paths.logs_dir())` (monkeypatched).
  - `on_copy_url` calls `_copy_to_clipboard_windows(url)` (monkeypatched) + fires "URL copied" balloon.
  - `on_copy_url` on subprocess failure → `_notify_error`.
- `test_tray_app.py` — `_poll_tick` assigns the expected tooltip string after a normal tick.

**Manual (`docs/manual-tests/iter5a.md`)**:
- Click Restart on a running project → icon briefly grey then orange then green; menu returns immediately (not blocked 10s).
- Click Copy URL → balloon "URL copied: http://localhost:4200". Paste in browser confirms.
- Click Open logs folder → Explorer opens at the logs dir.
- Add `path_root: D:\PycharmProjects\FoxRunner` to FoxRunner → "Open project folder" appears, clicking opens Explorer there. Remove the YAML line → entry disappears on next tray launch.
- Hover tray icon → tooltip reflects state (idle / RUNNING / PARTIAL). Changes within 3s of a state change.

## Self-review

- Placeholder scan: clean.
- Internal consistency: `Handlers` order stays stable (new fields at the end); `_noop_handlers*` in tests must be updated accordingly.
- Restart thread uses `user_initiated.add` BEFORE `stop` so the tray's `compute_transitions` suppresses the "stopped unexpectedly" balloon during the brief stopped→starting window.
- Tooltip updates at the end of each tick so it reflects the same status the icon and menu reflect for that tick. Consistent with the existing pattern.
