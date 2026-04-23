# FoxTray Iter 4a — Per-Project Tasks and Standalone Scripts Design

## Goal

Let the user run short one-off commands from the tray menu — per-project tasks like `python manage.py migrate` or `pytest`, and standalone scripts like `git pull --recurse` — **without touching the active project's lifecycle**. Tasks and scripts run asynchronously: the menu stays responsive, a balloon fires on completion, and logs persist to `%APPDATA%\foxtray\logs\tasks\`.

Iter 4 was originally scoped as "polish + distribution" (single-instance lock, `.exe` packaging, OS integration, Update action). That scope is too large for one spec. This document covers **Iter 4a only**: utility commands (sub-projects A and C from the scoping discussion — per-project tasks and standalone scripts). The rest of Iter 4 (single-instance, packaging, launch-on-boot, global shortcut, "Update" action) stays deferred.

## Non-goals (deferred)

- Single-instance lock — Iter 4b.
- `.exe` packaging with PyInstaller — Iter 4c.
- Launch-on-Windows-boot, global keyboard shortcut — Iter 4d.
- A dedicated "Update" action (git pull + pip install + npm install + manage.py migrate) — Iter 4e. Iter 4a provides the mechanism; the user can compose "Update" as a set of tasks in config.yaml, but no built-in sequencing.
- CLI entry point for tasks (`python main.py task FoxRunner Migrate`) — YAGNI; users can invoke the command directly from a shell.
- Progress bar, live log tail, or dependencies between tasks.
- Task persistence across tray restarts — tasks are in-memory only.

## Architecture overview

Tasks and scripts live **outside** the project lifecycle. No `state.json` mutation, no port-free wait, no health-check, no interaction with `Orchestrator`. Each is a one-shot `Popen` managed by a new `TaskManager`, watched by a dedicated daemon thread, and surfaced through balloons.

```
config.yaml ─┬─ projects[].tasks  ─── new Task dataclass
             └─ scripts           ─── new Script dataclass

TrayApp
  ├─ Orchestrator (unchanged)
  └─ TaskManager (new)
       ├─ running: dict[key, Popen]      thread-safe, guards with Lock
       ├─ run(key, command, cwd)          spawn via ProcessManager
       ├─ is_running(key) / running_keys() used by menu rebuild
       ├─ kill_all()                      called on tray exit
       └─ watcher thread per task        fires on_complete(key, exit_code)

Menu
  ├─ Project submenu  ──► Tasks ▸ [Migrate, Collect static, …]  (if non-empty)
  └─ Root              ──► Scripts ▸ [Git pull all, …]          (if non-empty)
```

### Key invariants

- **Task lifecycle ≠ project lifecycle.** Starting / stopping a project pair does not touch running tasks. Running a task does not write to `state.json` and does not care whether a project is active.
- **One instance per key.** A key is `"task:{project}:{name}"` or `"script:{name}"`. `TaskManager.run(key, …)` raises `TaskAlreadyRunning` if that exact key is already running. Different tasks run concurrently.
- **Tray exit kills all tasks.** `on_exit` and `on_stop_all_and_exit` call `task_manager.kill_all()` first; balloon `"N tasks killed"` if count > 0. `Stop all` (without exit) leaves tasks alone.
- **Menu reflects running state on demand.** When a task starts or finishes, the watcher fires a callback that calls `icon.update_menu()`; the next menu open shows the "(running…)" suffix or the freshly-cliqueable entry. Between ticks no poll updates the menu for tasks.
- **Logs live in `%APPDATA%\foxtray\logs\tasks\`.** One file per key, rotation via existing `logs.rotate` pattern.

## File structure

New files:
- `foxtray/tasks.py` — `TaskManager` class and `TaskAlreadyRunning` exception.
- `tests/test_tasks.py` — unit tests for `TaskManager`.
- `docs/manual-tests/iter4a.md` — smoke test checklist.

Modified files:
- `foxtray/config.py` — add `Task` and `Script` dataclasses; parse and validate. Extend `Project` with `tasks: tuple[Task, ...]`; extend `Config` with `scripts: tuple[Script, ...]`.
- `foxtray/logs.py` — add `open_task_writer(key: str)` helper writing to `%APPDATA%\foxtray\logs\tasks\{key}_task.log` with rotation.
- `foxtray/ui/tray.py` — `TrayApp` instantiates a `TaskManager`; `Handlers` dataclass gains `on_run_task` and `on_run_script`; `build_menu_items` takes `running_tasks: set[str]` and renders `Tasks ▸` / `Scripts ▸` submenus with "(running…)" suffix and disabled state for running entries; `_on_task_complete` callback fires balloons and calls `icon.update_menu()`.
- `foxtray/ui/actions.py` — add `on_run_task` and `on_run_script` free functions; update `on_exit` and `on_stop_all_and_exit` to call `task_manager.kill_all()` and emit a "N tasks killed" balloon if count > 0.
- `tests/test_config.py` — new parsing tests for tasks and scripts.
- `tests/test_tray.py` — new menu-building tests for tasks/scripts submenus and running suffix.
- `tests/test_tray_actions.py` — new action-handler tests for `on_run_task`, `on_run_script`, exit-kills-tasks.

Unchanged: `foxtray/project.py`, `foxtray/state.py`, `foxtray/process.py`, `foxtray/health.py`, `foxtray/paths.py`, `foxtray/cli.py`, `foxtray/ui/icons.py`.

## Components

### `foxtray/config.py` — `Task`

```python
@dataclass(frozen=True)
class Task:
    name: str
    cwd: str  # "backend" | "frontend"
    command: str

    def resolved_command(self, project: "Project") -> list[str]:
        parts = shlex.split(self.command)
        if not parts:
            raise ConfigError(f"task {self.name!r} command is empty")
        if self.cwd == "backend" and parts[0].lower() == "python":
            return [str(project.backend.python_executable), *parts[1:]]
        return parts

    def resolved_cwd(self, project: "Project") -> Path:
        return project.backend.path if self.cwd == "backend" else project.frontend.path
```

Validation in `_parse_project`:
- `tasks` key optional; if present, must be a list of mappings.
- Each task: `name` (non-empty string), `cwd` (∈ {"backend", "frontend"}), `command` (non-empty string). Extra keys tolerated.
- Duplicate task names within a project → `ConfigError`.
- `shlex.split(command)` must yield at least one token → `ConfigError`.

### `foxtray/config.py` — `Script`

```python
@dataclass(frozen=True)
class Script:
    name: str
    path: Path       # absolute cwd
    command: str
    venv: str | None = None

    def resolved_command(self) -> list[str]:
        parts = shlex.split(self.command)
        if not parts:
            raise ConfigError(f"script {self.name!r} command is empty")
        if self.venv and parts[0].lower() == "python":
            venv_python = self.path / self.venv / "Scripts" / "python.exe"
            return [str(venv_python), *parts[1:]]
        return parts
```

Validation (new helper `_parse_scripts`):
- Top-level `scripts` key optional; if present, must be a list.
- Each script: `name` (non-empty), `path` (absolute, existing is NOT required — user may reference a path that will exist later), `command` (non-empty). `venv` optional; if present, non-empty string.
- Duplicate script names globally → `ConfigError`.

### `foxtray/config.py` — `Project` and `Config`

```python
@dataclass(frozen=True)
class Project:
    name: str
    url: str
    backend: Backend
    frontend: Frontend
    start_timeout: int = 30
    tasks: tuple[Task, ...] = ()


@dataclass(frozen=True)
class Config:
    projects: list[Project] = field(default_factory=list)
    scripts: tuple[Script, ...] = ()
```

Default tuple-valued fields preserve immutability with `frozen=True`.

### `foxtray/tasks.py` (new)

```python
"""One-shot command execution independent of project lifecycle."""
from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import Callable, Protocol

log = logging.getLogger(__name__)


class TaskAlreadyRunning(RuntimeError):
    """Raised when .run() is called for a key that is already running."""


class _ManagerProtocol(Protocol):
    def start(
        self, *, project: str, component: str, command: list[str], cwd: Path
    ) -> subprocess.Popen[bytes]: ...

    def kill_tree(self, pid: int, timeout: float = 5.0) -> None: ...


class TaskManager:
    """Runs one-off commands (per-project tasks, standalone scripts) outside
    the project lifecycle.

    Thread model:
      - Caller threads (pystray menu-callback) invoke .run() / .is_running() / .kill_all().
      - One watcher thread per running task calls popen.wait() then the
        on_complete callback.
      - A threading.Lock guards the running dict against the inherent
        menu-thread vs watcher-thread race.
    """

    def __init__(
        self,
        manager: _ManagerProtocol,
        on_complete: Callable[[str, int], None],
    ) -> None:
        self._manager = manager
        self._on_complete = on_complete
        self._running: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def is_running(self, key: str) -> bool:
        with self._lock:
            return key in self._running

    def running_keys(self) -> set[str]:
        with self._lock:
            return set(self._running)

    def run(self, key: str, command: list[str], cwd: Path) -> None:
        with self._lock:
            if key in self._running:
                raise TaskAlreadyRunning(key)
        popen = self._manager.start(
            project=key, component="task", command=command, cwd=cwd,
        )
        with self._lock:
            self._running[key] = popen
        threading.Thread(
            target=self._watch, args=(key, popen),
            name=f"task-{key}", daemon=True,
        ).start()

    def _watch(self, key: str, popen: subprocess.Popen[bytes]) -> None:
        exit_code = popen.wait()
        with self._lock:
            self._running.pop(key, None)
        try:
            self._on_complete(key, exit_code)
        except Exception:
            log.warning("task %s on_complete callback failed", key, exc_info=True)

    def kill_all(self) -> int:
        with self._lock:
            victims = list(self._running.items())
            self._running.clear()
        for key, popen in victims:
            try:
                self._manager.kill_tree(popen.pid)
            except Exception:
                log.warning("kill_all: failed to kill %s", key, exc_info=True)
        return len(victims)
```

### `foxtray/logs.py` — `open_task_writer`

Task logs live in `%APPDATA%\foxtray\logs\tasks\` to keep the root `logs/` dir populated by project logs only. Add two helpers to `logs.py`:

- `rotate_task(key: str) -> None` — mirrors `rotate` but targets the tasks subdir and sanitises `key` by replacing `:` with `_` (Windows filesystem safety). Creates the subdir on demand.
- `open_task_writer(key: str) -> BinaryIO` — mirrors `open_writer`, same sanitisation.

Sanitised filename example: key `"task:FoxRunner:Migrate"` → file `%APPDATA%\foxtray\logs\tasks\task_FoxRunner_Migrate.log`.

### `foxtray/process.py` — shared `spawn_with_log`

Extract the common Popen plumbing so both `ProcessManager.start` and `TaskManager.run` can reuse it:

```python
def spawn_with_log(command: list[str], cwd: Path, log_file) -> subprocess.Popen[bytes]:
    """Spawn a process with stdout+stderr redirected to log_file. Closes log_file
    and re-raises on Popen failure. Command is resolved via _resolve_command."""
    resolved = _resolve_command(command)
    try:
        return subprocess.Popen(
            resolved, cwd=str(cwd),
            stdout=log_file, stderr=subprocess.STDOUT,
            creationflags=_CREATION_FLAGS,
        )
    except Exception:
        log_file.close()
        raise
```

`ProcessManager.start` becomes:
```python
def start(self, *, project, component, command, cwd):
    logs.rotate(project, component)
    return spawn_with_log(command, cwd, logs.open_writer(project, component))
```

`TaskManager.run` calls:
```python
logs.rotate_task(key)
popen = process.spawn_with_log(command, cwd, logs.open_task_writer(key))
```

Existing tests of `ProcessManager` still hold because external behaviour is unchanged. Adds one new free function in `process.py`.

### `foxtray/ui/tray.py` — TrayApp changes

`TaskManager` needs only a `kill_tree` callback (for `kill_all`); the rest of the Popen work is done via the shared `process.spawn_with_log` helper. Passing just the callback keeps the dependency explicit and avoids reaching into Orchestrator's private `_manager`:

```python
class TaskManager:
    def __init__(
        self,
        kill_tree: Callable[[int], None],
        on_complete: Callable[[str, int], None],
    ) -> None:
        ...
```

To wire this, `TrayApp.__init__` takes a `process_manager: ProcessManager` alongside `cfg` and `orchestrator`. CLI's `cmd_tray` builds both and passes both in:

```python
def cmd_tray(args):
    cfg = config.load(args.config)
    manager = process.ProcessManager()
    orchestrator = project.Orchestrator(manager=manager, cfg=cfg)
    tray_module.TrayApp(cfg, orchestrator, manager).run()
    return 0

# TrayApp.__init__:
self._task_manager = tasks.TaskManager(
    kill_tree=process_manager.kill_tree,
    on_complete=self._on_task_complete,
)
```

`TrayApp._on_task_complete(key, exit_code)`:
```python
def _on_task_complete(self, key: str, exit_code: int) -> None:
    if self._icon is None:
        return
    display_name = key.rsplit(":", 1)[-1]
    if exit_code == 0:
        self._icon.notify(f"{display_name} done", title="FoxTray")
    else:
        log_path = paths.app_data_dir() / "logs" / "tasks" / f"{_sanitize(key)}_task.log"
        self._icon.notify(
            f"⚠ {display_name} failed — see {log_path}",
            title="FoxTray",
        )
    try:
        self._icon.update_menu()
    except Exception:  # pystray menu rebuild can race on exit
        log.warning("update_menu after task %s failed", key, exc_info=True)
```

Menu wiring: `build_menu_items` signature gains `running_tasks: set[str]` and `scripts: tuple[Script, ...]`. `_project_submenu` appends `Tasks ▸` submenu if `project.tasks` non-empty. Root menu appends `Scripts ▸` submenu before `Stop all` if `cfg.scripts` non-empty. Running entries get `text=f"{name} (running…)"` and `enabled=False`.

`Handlers` dataclass gains:
```python
on_run_task: Callable[[config.Project, config.Task], None]
on_run_script: Callable[[config.Script], None]
```

### `foxtray/ui/actions.py` — new handlers

```python
def on_run_task(
    task_manager: _TaskRunnerProtocol,
    project: config.Project,
    task: config.Task,
    icon: _Notifier,
) -> None:
    key = f"task:{project.name}:{task.name}"
    try:
        task_manager.run(key, task.resolved_command(project), task.resolved_cwd(project))
    except tasks.TaskAlreadyRunning:
        icon.notify(f"{task.name} is already running", title="FoxTray")
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_run_script(
    task_manager: _TaskRunnerProtocol,
    script: config.Script,
    icon: _Notifier,
) -> None:
    key = f"script:{script.name}"
    try:
        task_manager.run(key, script.resolved_command(), script.path)
    except tasks.TaskAlreadyRunning:
        icon.notify(f"{script.name} is already running", title="FoxTray")
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)
```

Update existing `on_exit` and `on_stop_all_and_exit` to accept a `task_manager: _TaskRunnerProtocol` and invoke `kill_all()` before `icon.stop()`:

```python
def on_exit(icon: _Closable, task_manager: _TaskRunnerProtocol) -> None:
    killed = task_manager.kill_all()
    if killed > 0:
        # Best-effort: icon may already be stopping. Wrap in try to avoid raising on exit.
        try:
            icon.notify(f"{killed} task(s) killed", title="FoxTray")
        except Exception:  # noqa: BLE001
            pass
    icon.stop()
```

Note on ordering: `kill_all` sends SIGTERM to each Popen and returns immediately; it doesn't wait. Processes may still be dying when `icon.stop()` returns. Acceptable — the tray exit is bounded by existing `poller.join(timeout=…)`.

## Data flow

### Clicking a task

1. User clicks `FoxRunner ▸ Tasks ▸ Migrate`.
2. pystray menu-callback thread fires `handlers.on_run_task(project, task)`, which calls `actions.on_run_task(task_manager, project, task, icon)`.
3. `on_run_task` computes `key = "task:FoxRunner:Migrate"`, resolves command/cwd, calls `task_manager.run(key, command, cwd)`.
4. `TaskManager.run` checks `key` not already in `_running`, rotates log file, spawns Popen via `process.spawn_with_log`, stores in `_running`, starts watcher thread.
5. Watcher calls `popen.wait()` (blocks until process exits).
6. Watcher removes key from `_running`, calls `on_complete(key, exit_code)`.
7. `TrayApp._on_task_complete`: fire balloon (`"Migrate done"` or `"⚠ Migrate failed — see …"`), call `icon.update_menu()`.
8. User opens the menu again: the entry is back to `Migrate` (cliqueable).

### Clicking a task that's already running

1. Menu shows `Migrate (running…)` as disabled — user can't click it normally.
2. If they somehow trigger the handler (race: menu rebuild hasn't happened yet), `TaskManager.run` raises `TaskAlreadyRunning`.
3. `on_run_task` catches it, fires balloon `"Migrate is already running"`. No new Popen.

### Exiting the tray with 2 tasks running

1. User clicks `Exit` (or `Stop all and exit`).
2. `actions.on_exit(icon, task_manager)` calls `task_manager.kill_all()`:
   - Acquires lock, snapshots the running dict, clears it.
   - Releases lock, iterates over snapshot and calls `kill_tree(pid)` for each.
   - Returns 2.
3. Balloon `"2 task(s) killed"` fires (best-effort).
4. `icon.stop()` exits the pystray event loop; tray vanishes.
5. Watcher threads wake up after Popen.wait returns (non-zero due to kill), hit `self._running.pop(key, None)` (no-op — already cleared), call `_on_complete` — but `self._icon` is None now, so the callback early-returns. No crash.

### Config load with tasks + scripts

1. `config.load(path)` reads YAML, parses `projects` (now with `tasks`) and new top-level `scripts`.
2. Validation errors (duplicate names, invalid cwd, non-absolute script path, empty command) surface as `ConfigError` and the CLI exits 2 before anything starts.

## Testing

### Unit (pytest)

**`tests/test_config.py` additions:**
- `test_task_cwd_backend_swaps_python` — `Task(cwd="backend", command="python manage.py migrate").resolved_command(project)` returns `[backend.python_executable, "manage.py", "migrate"]`.
- `test_task_cwd_backend_does_not_swap_non_python` — `Task(cwd="backend", command="pytest tests/")` returns `["pytest", "tests/"]`.
- `test_task_cwd_frontend_never_swaps` — `Task(cwd="frontend", command="python build.py")` returns `["python", "build.py"]` (no swap; pystray trusts whatever's on PATH).
- `test_task_cwd_frontend_uses_frontend_path`.
- `test_task_rejects_invalid_cwd` — `cwd: "random"` → `ConfigError`.
- `test_task_rejects_empty_command` → `ConfigError`.
- `test_task_rejects_duplicate_names_within_project` → `ConfigError`.
- `test_project_without_tasks_has_empty_tuple`.
- `test_script_rejects_relative_path` → `ConfigError`.
- `test_script_with_venv_swaps_python` — `Script(path=abs, command="python x.py", venv=".venv").resolved_command()` returns `[abs/.venv/Scripts/python.exe, "x.py"]`.
- `test_script_without_venv_no_swap`.
- `test_script_rejects_duplicate_names_globally` → `ConfigError`.
- `test_config_without_scripts_has_empty_tuple`.

**`tests/test_tasks.py` (new):**
- `test_run_spawns_and_registers` — with a `_FakeManager` (kill_tree stub) and a real Popen of `sys.exit(0)`, `run(key, [sys.executable, "-c", "import sys; sys.exit(0)"], tmp_path)` registers the key, watcher eventually fires `on_complete(key, 0)`.
- `test_is_running_reflects_state`.
- `test_run_second_time_raises_TaskAlreadyRunning`.
- `test_watcher_removes_key_on_completion`.
- `test_on_complete_called_with_nonzero_exit` — Popen of `sys.exit(1)` → callback gets `(key, 1)`.
- `test_kill_all_kills_all_tracked_popens_and_returns_count`.
- `test_on_complete_exception_does_not_crash_watcher`.

**`tests/test_tray.py` additions:**
- `test_menu_project_with_tasks_adds_tasks_submenu` — project with 2 tasks → submenu has a `Tasks ▸` entry with 2 sub-sub-items.
- `test_menu_project_without_tasks_has_no_tasks_submenu`.
- `test_menu_config_with_scripts_adds_scripts_submenu` at root, before `Stop all`.
- `test_menu_config_without_scripts_has_no_scripts_submenu`.
- `test_menu_running_task_shows_disabled_suffix` — with `running_tasks={"task:A:Migrate"}`, the `Migrate` entry has `enabled=False` and `text="Migrate (running…)"`.
- `test_menu_running_script_shows_disabled_suffix`.

**`tests/test_tray_actions.py` additions:**
- `test_on_run_task_calls_task_manager_run_with_key_command_cwd`.
- `test_on_run_task_already_running_notifies` (fake task_manager that raises).
- `test_on_run_task_unexpected_exception_notifies_error`.
- `test_on_run_script_calls_task_manager_with_key_and_script_path`.
- `test_on_exit_calls_kill_all_and_notifies_if_nonzero`.
- `test_on_exit_silent_if_zero_tasks_killed`.
- `test_on_stop_all_and_exit_calls_kill_all`.

### Manual (`docs/manual-tests/iter4a.md`)

- Add `tasks:` to FoxRunner with 2 entries (Migrate, Collect static). `python main.py tray` → FoxRunner ▸ Tasks ▸ shows the 2 entries.
- Click Migrate while FoxRunner is stopped → balloon "Migrate done" within a few seconds, log file in `%APPDATA%\foxtray\logs\tasks\`.
- Click Migrate while FoxRunner is RUNNING → task runs against the same DB; balloon on completion; icon color unchanged (still green).
- Click Migrate then immediately click Migrate again (or while it's still running) → balloon "Migrate is already running".
- Add a task with a non-existent command (`python nonexistent.py`) → click → balloon "⚠ Migrate failed — see {path}", log contains traceback.
- Add `scripts:` top-level. Menu shows Scripts ▸ before Stop all. Click a script → balloon on completion.
- 2 tasks running → click Exit → balloon "2 task(s) killed", tray disappears, verify no orphan processes in Task Manager.
- `Stop all` while a task is running → project stopped, task UNTOUCHED (continues running; balloon fires on completion).

## Error handling summary

| Failure | Behavior |
|---|---|
| `Task.cwd` invalid / duplicate names / missing command | `ConfigError` at load — CLI exit 2 before tray launches |
| Script path not absolute | `ConfigError` at load |
| User clicks a running task | `TaskAlreadyRunning` → balloon "X is already running" (non-fatal) |
| Command not found on PATH | `process.ExecutableNotFound` from `spawn_with_log` → balloon via `_notify_error` |
| Task exits non-zero | Watcher fires balloon "⚠ X failed — see {log path}", entry becomes cliqueable again |
| `on_complete` callback raises | Caught in `_watch`, logged as warning; running dict still cleared |
| Tray exits with tasks running | `kill_all()` sends terminate to each; processes clean up via `kill_tree` (same as project components) |
| `icon.update_menu()` races with `icon.stop()` on exit | Wrapped in try/except; ignored |

## Self-review

- **Placeholder scan:** no "TBD" / "similar to" references.
- **Internal consistency:** `TaskManager` takes only `kill_tree` callback — confirmed in Architecture + Components sections. `TrayApp` passes it explicitly, no private-attribute access. The `spawn_with_log` shared helper is a minor refactor in `foxtray/process.py`.
- **Scope:** single iteration, single plan. Decomposition from original Iter 4 was done upfront.
- **Ambiguity check:**
  - "Task display name" in balloons = last segment after `:` in the key (e.g., "Migrate" from "task:FoxRunner:Migrate"). Documented.
  - Log file path sanitization: colons replaced by underscores (Windows filesystem safety). Documented in `logs.open_task_writer`.
  - Menu update after task completion: `icon.update_menu()` in the watcher callback; documented.
  - Running task behavior when the tray restarts mid-execution: tasks die with the tray process (daemon threads + kill_all on exit); no persistence. Listed as limitation.
