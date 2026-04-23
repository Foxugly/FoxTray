# FoxTray Iter 2 — Tray Icon Design

## Goal

Add a Windows tray icon that sits alongside the Iter 1 CLI and makes day-to-day start/stop of Django + Angular project pairs a two-click operation. The tray reflects live state, surfaces crashes through balloon notifications, and exposes the same five operations as the CLI via a dynamic menu.

## Non-goals (deferred to later iterations)

- In-app log viewer (Iter 3)
- Health-check wait loop after start / wait-for-port-free before start (Iter 3)
- `git pull` / `pip install` / `npm install` / `python manage.py migrate` "Update" action (Iter 4)
- `.exe` packaging with PyInstaller (Iter 4)
- Single-instance protection (Iter 4)
- Global keyboard shortcut to open the menu (Iter 4)
- Launch-on-Windows-boot (Iter 4)

## Architecture

### Entry point

A new argparse subcommand `tray` wired in `foxtray/cli.py`. `python main.py tray` instantiates `TrayApp(config, Orchestrator(ProcessManager())).run()` and blocks until the tray is exited. All five existing CLI subcommands stay unchanged.

### Threading model

Three threads cooperate. No mutable shared state requires a lock.

1. **Main thread / pystray event loop** — handles menu clicks. Handlers call `Orchestrator.start/stop/stop_all`, which are non-blocking (Popen returns immediately; `kill_tree` is bounded by its 5-second timeout).
2. **Poller thread** (daemon, 3-second tick) — reads `Orchestrator.status(project)` for every project, compares to the previous snapshot, fires Windows balloon notifications on meaningful transitions, and updates the tray icon color if the global state changed. Stores the previous snapshot in a thread-local variable — no locking needed.
3. **Pystray menu-callback thread** (managed by pystray internally) — invoked whenever the user opens the menu. Rebuilds the menu from `Orchestrator.status(project)` on demand, so the menu is always fresh without polling.

The `pystray.Icon` object is thread-safe for `.icon = new_image` and `.notify(message, title)`, which is all the poller does.

## File structure

New files:
- `foxtray/ui/__init__.py` — empty package marker
- `foxtray/ui/tray.py` — `TrayApp` class plus pure helpers (`compute_icon_state`, `compute_transitions`, `build_menu_items`)
- `foxtray/ui/icons.py` — `IconState` alias and `load(state)` function with a module-level 3-image cache
- `foxtray/ui/actions.py` — menu action handlers as free functions, decoupled from pystray
- `assets/icon_running.png` / `icon_partial.png` / `icon_stopped.png` — 32×32 colored discs on transparent background
- `scripts/gen_icons.py` — one-off Pillow script that regenerates the three PNG placeholders; committed so the design can be iterated without hand-editing image files
- `tests/test_tray.py` — unit tests for the three pure helpers
- `tests/test_icons.py` — smoke tests that verify each PNG loads as a valid `PIL.Image`
- `tests/test_tray_actions.py` — unit tests for action handlers with a fake orchestrator
- `docs/manual-tests/iter2.md` — manual smoke-test checklist

Modified files:
- `foxtray/cli.py` — add `cmd_tray` and wire it into `build_parser`
- `requirements.txt` — add `pystray` and `Pillow`

Unchanged from Iter 1:
- `foxtray/{config,state,logs,health,process,project}.py`
- `main.py`

## Components

### `foxtray/ui/tray.py`

Public class `TrayApp(config: Config, orchestrator: Orchestrator)`:

- `.run()` — builds the `pystray.Icon`, starts the poller thread, calls `icon.run()` (blocks until `icon.stop()`).
- `._poll_tick()` — single tick of the polling loop. Reads status for all projects, feeds the three pure helpers, calls `icon.notify(...)` per transition, and updates `icon.icon` if the state changed.
- `._build_menu()` — invoked by pystray on menu open; returns a `pystray.Menu` built from the output of `build_menu_items`.
- `._user_initiated_stop: set[str]` — project names that should suppress the next `running → stopped` notification (populated by `on_stop` and `on_stop_all_and_exit`, consumed by the poller when the transition is observed).

Pure helpers (no pystray dependency, fully unit-tested):

```python
def compute_icon_state(
    active: ActiveProject | None,
    statuses: dict[str, ProjectStatus],
) -> IconState: ...

def compute_transitions(
    prev: dict[str, ProjectStatus],
    curr: dict[str, ProjectStatus],
    suppressed: set[str],
) -> list[Notification]: ...

def build_menu_items(
    config: Config,
    statuses: dict[str, ProjectStatus],
    handlers: Handlers,
) -> list[MenuItemSpec]: ...
```

Return types are plain dataclasses (`Notification`, `MenuItemSpec`, `Handlers`) so tests can assert on them without pystray imports.

### `foxtray/ui/icons.py`

```python
IconState = Literal["running", "partial", "stopped"]

_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
_cache: dict[IconState, Image.Image] = {}

def load(state: IconState) -> Image.Image:
    if state not in _cache:
        _cache[state] = Image.open(_ASSETS / f"icon_{state}.png")
    return _cache[state]
```

### `foxtray/ui/actions.py`

Free functions, one per menu action. Each takes an `Orchestrator`, the `Project`/`Config` it needs, and the `pystray.Icon` to notify. Example signatures:

```python
def on_start(orchestrator: Orchestrator, project: Project, icon: Icon) -> None: ...
def on_stop(orchestrator: Orchestrator, project: Project, icon: Icon,
            user_initiated: set[str]) -> None: ...
def on_open_browser(project: Project) -> None: ...
def on_open_folder(folder: Path) -> None: ...
def on_stop_all(orchestrator: Orchestrator, icon: Icon,
                user_initiated: set[str]) -> None: ...
def on_exit(icon: Icon) -> None: ...
def on_stop_all_and_exit(orchestrator: Orchestrator, icon: Icon,
                         user_initiated: set[str]) -> None: ...
```

Exceptions raised by any handler are caught inside the handler, logged, and surfaced via `icon.notify(str(exc), "FoxTray error")`. The tray never dies from a menu click.

### `foxtray/cli.py` additions

```python
from foxtray.ui import tray as tray_module

def cmd_tray(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    orchestrator = project.Orchestrator(manager=process.ProcessManager())
    tray_module.TrayApp(cfg, orchestrator).run()
    return 0
```

Wired into `build_parser` as a subparser with no positional arguments:

```python
sub.add_parser("tray", help="Run FoxTray as a Windows tray icon").set_defaults(func=cmd_tray)
```

## Menu specification

Root menu (top to bottom):

```
FoxRunner   (<LABEL>)  ▶
QuizOnline  (<LABEL>)  ▶
PushIT      (<LABEL>)  ▶
─────────────────────
Stop all            [enabled iff a project is active]
─────────────────────
Exit
Stop all and exit
```

`<LABEL>` is `RUNNING` when both components are alive, `PARTIAL` when one is alive, `stopped` otherwise. Projects appear in the order they are declared in `config.yaml`.

Submenu per project:

```
Start | Stop              [Start if stopped, Stop otherwise]
─────────────────────
Open in browser           [enabled iff running/partial]
Open backend folder
Open frontend folder
```

`Open in browser` calls `webbrowser.open(project.url)`.
`Open backend/frontend folder` calls `os.startfile(str(path))`, which opens Windows Explorer at the given directory.

## Icon state rule

The tray has one global icon. Its color is computed from `state.json` and `psutil.pid_exists`:

| Condition | State | Color |
|---|---|---|
| `state.active is None` | `stopped` | grey |
| `state.active` set; both backend_pid and frontend_pid exist | `running` | green |
| `state.active` set; exactly one of the two PIDs exists | `partial` | orange |
| `state.active` set; neither exists | `stopped` | grey (orphaned state auto-cleared not handled — known limitation) |

When the icon color computed from `_poll_tick` differs from the current `icon.icon`, the icon is replaced via `icon.icon = icons.load(new_state)`.

## Notification transitions

Fired from the poller on the 3-second tick. Computed by diffing the previous and current `IconState` for the *active* project only (the others are `stopped` by definition).

| From | To | Notification |
|---|---|---|
| stopped | running | `FoxRunner is up` |
| stopped | partial | `FoxRunner started but one component failed` |
| running | partial | `⚠ FoxRunner: <component> crashed` |
| partial | running | `FoxRunner recovered` |
| running | stopped | silent if project in `_user_initiated_stop`, else `⚠ FoxRunner stopped unexpectedly` |
| partial | stopped | silent if project in `_user_initiated_stop`, else `⚠ FoxRunner fully stopped` |

`<component>` is `backend` or `frontend`, determined by which of the two PIDs died between ticks. The `_user_initiated_stop` set is populated in the `on_stop` / `on_stop_all_and_exit` handlers and consumed (cleared) inside the poller after a single firing. If the user clicks Stop but the poller never sees a `running→stopped` transition (race), the flag is cleared on the next tick regardless.

## Data flow per tick

```
_poll_tick:
  current = { name: orchestrator.status(project) for project in config.projects }
  new_state = compute_icon_state(state.load().active, current)
  transitions = compute_transitions(self._prev, current, self._user_initiated_stop)
  self._user_initiated_stop.clear()
  for notification in transitions:
    icon.notify(notification.message, title="FoxTray")
  if new_state != self._prev_icon_state:
    icon.icon = icons.load(new_state)
    self._prev_icon_state = new_state
  self._prev = current
```

## Error handling

- Any exception inside `_poll_tick` is caught, logged at `WARNING`, and the tick is skipped. The poller never dies.
- Any exception inside a menu handler is caught by the handler itself, logged at `WARNING`, and surfaced as a notification `FoxTray error: <exc>`.
- If the assets directory is missing or a PNG fails to load, `icons.load` raises at startup — this is treated as a fatal configuration error and the tray refuses to start with a clear stderr message. Guarded by a test.

## Testing strategy

### Unit tests (in `tests/`)

- `test_icons.py` — for each of the three `IconState` values, assert `icons.load(state)` returns a `PIL.Image` with non-zero size. Guarantees the assets remain in the repo.
- `test_tray.py` :
  - `compute_icon_state`: five scenarios (no active project, active+both-alive, active+backend-only, active+frontend-only, active+neither).
  - `compute_transitions`: table-driven over the six transition rows above, plus the two "silent if user_initiated" rows.
  - `build_menu_items`: verifies Start appears when stopped, Stop appears when running, Open-in-browser is disabled when stopped, Stop-all is disabled when no project is active.
- `test_tray_actions.py` — action handlers tested with a `FakeOrchestrator`. `on_start` should call orchestrator.start. `on_open_browser` should call `webbrowser.open` (monkey-patched) with `project.url`. `on_open_folder` should call `os.startfile` (monkey-patched) with the correct path. `on_stop` should populate `user_initiated`. Handlers must not raise on any orchestrator failure (exception is caught inside, `icon.notify` is called instead).

### Not unit-tested (acknowledged gaps)

- Visual appearance of the tray icon in Windows Explorer.
- Actual appearance of balloon notifications on the Windows notification center.
- Exact timing of the 3-second poller loop.
- Full `icon.run()` event loop (requires a real Windows session).

### Manual smoke test (`docs/manual-tests/iter2.md`)

Matches the list in Section 4 of the brainstorming:

1. `python main.py tray` — grey icon appears in the system tray.
2. Right-click → FoxRunner → Start. Within ~20 seconds the icon turns green and a balloon "FoxRunner is up" shows.
3. Kill the `node.exe` manually from Task Manager. Within 3 seconds the icon turns orange and a balloon "⚠ FoxRunner: frontend crashed" shows.
4. Right-click → FoxRunner → Stop. Icon turns grey. No balloon (user-initiated).
5. Right-click → Exit. Icon disappears. `python main.py list` still shows FoxRunner stopped (it was already stopped in step 4).
6. Right-click → Start FoxRunner → Right-click → Stop all and exit. Everything dies.
7. Right-click → FoxRunner → Open in browser — default browser opens `http://localhost:4200`.
8. Right-click → FoxRunner → Open backend folder — Explorer opens at `D:\PycharmProjects\FoxRunner_server`.

## Known limitations (Iter 2 scope)

Documented up front in the iter2.md smoke test:

- **No single-instance lock.** Launching `python main.py tray` twice creates two trays. Iter 4.
- **No health-check wait.** Notification `FoxRunner is up` fires as soon as both PIDs are alive, not when Django and Angular are actually serving 200s. A fast click to `Open in browser` may get a connection refused for a few seconds. Iter 3 adds the wait.
- **No auto-clear of orphaned state.** If both PIDs are gone but `state.json` still has an active project (the tray was killed mid-run), the first tick after startup computes `stopped`, the menu shows everything as stopped, but `state.json` still says active. Next `start` or `stop-all` will clear it. Iter 3.
- **Tray process must stay alive for notifications.** Closing the tray means no more crash notifications. Iter 4 packaging may include a Windows service option.
