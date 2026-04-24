# FoxTray Iter 5a (Quick Wins Bundle) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Five small UX improvements — Restart action, Open logs folder, Copy URL, icon tooltip, Open project root.

**Architecture:** Menu + action layer additions only. Restart uses a background thread so the menu stays responsive. Tooltip updated at the end of each poll tick.

**Tech Stack:** existing only. Windows `clip.exe` for clipboard (stdlib call).

**Spec:** `docs/superpowers/specs/2026-04-24-foxtray-iter5a-design.md`.

---

## Task 1: `path_root` config field

**Files:** `foxtray/config.py`, `tests/test_config.py`.

- [ ] **Step 1: Append failing tests to `tests/test_config.py`**

```python
def test_project_without_path_root_defaults_none(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.projects[0].path_root is None


def test_project_path_root_accepts_absolute(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    path_root: D:\\\\projects\\\\foxrunner\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.projects[0].path_root == Path("D:\\projects\\foxrunner")


def test_project_path_root_rejects_relative(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    path_root: relative/path\n"
    with pytest.raises(config.ConfigError, match="absolute"):
        config.load(write_config(tmp_path, yaml_body))
```

- [ ] **Step 2: Run, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_config.py -v -k path_root
```

- [ ] **Step 3: Extend `Project` dataclass in `foxtray/config.py`**

```python
@dataclass(frozen=True)
class Project:
    name: str
    url: str
    backend: Backend
    frontend: Frontend
    start_timeout: int = 30
    tasks: tuple[Task, ...] = ()
    path_root: Path | None = None
```

- [ ] **Step 4: Extend `_parse_project`**

Inside `_parse_project`, after parsing tasks and before the `return Project(...)`:

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

Add `path_root=path_root,` to the `Project(...)` constructor call.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add foxtray/config.py tests/test_config.py
git commit -m "feat(config): optional Project.path_root for repo parent folder"
```

Full message appends:
```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 2: `paths.logs_dir` helper

**Files:** `foxtray/paths.py`, `tests/test_logs.py` (append to existing).

- [ ] **Step 1: Append failing test to `tests/test_logs.py`**

```python
def test_logs_dir_returns_appdata_logs(tmp_appdata: Path) -> None:
    assert paths.logs_dir() == paths.appdata_root() / "logs"
```

- [ ] **Step 2: Run, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_logs.py -v -k logs_dir
```

Expected: `AttributeError: ... has no attribute 'logs_dir'`.

- [ ] **Step 3: Add `logs_dir` to `foxtray/paths.py`**

Insert after the existing `log_file` helper:

```python
def logs_dir() -> Path:
    """Directory holding per-component log files."""
    return appdata_root() / "logs"
```

- [ ] **Step 4: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

- [ ] **Step 5: Commit**

```bash
git add foxtray/paths.py tests/test_logs.py
git commit -m "feat(paths): logs_dir() helper"
```

---

## Task 3: `actions.on_restart`, `on_open_logs_folder`, `on_copy_url`

**Files:** `foxtray/ui/actions.py`, `tests/test_tray_actions.py`.

- [ ] **Step 1: Append failing tests to `tests/test_tray_actions.py`**

Add tests after existing ones:

```python
def test_on_restart_calls_stop_then_start_in_background_thread() -> None:
    orch = _FakeOrchestrator()
    icon = _FakeIcon()
    user_initiated: set[str] = set()
    actions.on_restart(orch, _project(), icon, user_initiated)
    # Wait for the background thread to finish (up to 1s)
    import time
    deadline = time.monotonic() + 1.0
    while (orch.started == [] or orch.stopped == []) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert orch.stopped == ["Demo"]
    assert orch.started == ["Demo"]
    assert user_initiated == {"Demo"}


def test_on_restart_notifies_on_exception_in_thread() -> None:
    orch = _FakeOrchestrator(raises=RuntimeError("boom"))
    icon = _FakeIcon()
    actions.on_restart(orch, _project(), icon, set())
    import time
    deadline = time.monotonic() + 1.0
    while not icon.notifications and time.monotonic() < deadline:
        time.sleep(0.01)
    assert any("boom" in message for _title, message in icon.notifications)


def test_on_open_logs_folder_calls_open_folder_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from foxtray import paths
    captured: list[Path] = []
    monkeypatch.setattr(actions, "_open_folder_native", captured.append)
    actions.on_open_logs_folder(_FakeIcon())
    assert captured == [paths.logs_dir()]


def test_on_copy_url_copies_and_fires_balloon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[str] = []
    monkeypatch.setattr(actions, "_copy_to_clipboard_windows", recorded.append)
    icon = _FakeIcon()
    actions.on_copy_url("http://localhost:4200", icon)
    assert recorded == ["http://localhost:4200"]
    assert any("URL copied" in message and "4200" in message
               for _title, message in icon.notifications)


def test_on_copy_url_notifies_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(text: str) -> None:
        raise RuntimeError("clip died")
    monkeypatch.setattr(actions, "_copy_to_clipboard_windows", _boom)
    icon = _FakeIcon()
    actions.on_copy_url("http://x", icon)
    assert icon.notifications == [("FoxTray error", "clip died")]
```

- [ ] **Step 2: Run, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_actions.py -v -k "restart or open_logs or copy_url"
```

- [ ] **Step 3: Implement in `foxtray/ui/actions.py`**

Add imports if not already present:
```python
import subprocess
import threading
```

Append handlers at end of the file (after `on_about`):

```python
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
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_actions.py -v
```

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

- [ ] **Step 6: Commit**

```bash
git add foxtray/ui/actions.py tests/test_tray_actions.py
git commit -m "feat(ui/actions): on_restart, on_open_logs_folder, on_copy_url"
```

---

## Task 4: Menu entries + tooltip + Handlers wiring

**Files:** `foxtray/ui/tray.py`, `tests/test_tray.py`, `tests/test_tray_app.py`.

- [ ] **Step 1: Append failing tests to `tests/test_tray.py`**

```python
def test_menu_running_project_has_restart_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    items = tray.build_menu_items(
        cfg, active, statuses, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Restart" in submenu_texts


def test_menu_stopped_project_has_no_restart_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Restart" not in submenu_texts


def test_menu_project_always_has_copy_url_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Copy URL" in submenu_texts


def test_menu_project_without_path_root_has_no_open_project_entry() -> None:
    cfg = config.Config(projects=[_project("A")])  # _project default has path_root=None
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Open project folder" not in submenu_texts


def test_menu_project_with_path_root_has_open_project_entry() -> None:
    base = _project("A")
    project_with_root = config.Project(
        name=base.name, url=base.url, backend=base.backend, frontend=base.frontend,
        start_timeout=base.start_timeout, tasks=base.tasks,
        path_root=Path("D:\\\\repos\\\\A"),
    )
    cfg = config.Config(projects=[project_with_root])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Open project folder" in submenu_texts


def test_menu_root_has_open_logs_folder_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    root_texts = [i.text for i in items if not i.separator and not i.submenu]
    assert "Open logs folder" in root_texts
```

Also **update `_noop_handlers()` and `_noop_handlers_with_tasks()`** in `tests/test_tray.py` to include the 3 new fields:

```python
on_restart=lambda p: None,
on_open_logs_folder=lambda: None,
on_copy_url=lambda u: None,
```

- [ ] **Step 2: Append failing test to `tests/test_tray_app.py`**

```python
def test_poll_tick_updates_icon_title_with_status(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)},
    )
    icon = _FakeIcon(icon=icons.load("stopped"))
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    monkeypatch.setattr("foxtray.state.psutil.pid_exists", lambda pid: True)
    monkeypatch.setattr("foxtray.project.psutil.pid_exists", lambda pid: True)

    app._poll_tick()

    assert hasattr(icon, "title")
    assert "RUNNING" in icon.title
    assert "A" in icon.title
```

`_FakeIcon` needs a `title` attribute. Find the existing `_FakeIcon` definition in `tests/test_tray_app.py` and add `title: str = "FoxTray"` if not already present.

- [ ] **Step 3: Run, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py tests/test_tray_app.py -v
```

- [ ] **Step 4: Extend `Handlers` in `foxtray/ui/tray.py`**

```python
@dataclass
class Handlers:
    on_start: Callable[[config_mod.Project], None]
    on_stop: Callable[[config_mod.Project], None]
    on_open_browser: Callable[[config_mod.Project], None]
    on_open_folder: Callable[[Path], None]
    on_stop_all: Callable[[], None]
    on_exit: Callable[[], None]
    on_stop_all_and_exit: Callable[[], None]
    on_run_task: Callable[[config_mod.Project, config_mod.Task], None]
    on_run_script: Callable[[config_mod.Script], None]
    on_about: Callable[[], None]
    on_restart: Callable[[config_mod.Project], None]
    on_open_logs_folder: Callable[[], None]
    on_copy_url: Callable[[str], None]
```

- [ ] **Step 5: Update `_project_submenu`**

Replace its body:

```python
def _project_submenu(
    project: config_mod.Project,
    icon_state: IconState,
    handlers: Handlers,
    running_tasks: set[str],
) -> tuple[MenuItemSpec, ...]:
    is_stopped = icon_state == "stopped"
    if is_stopped:
        start_or_stop = MenuItemSpec(
            text="Start", action=lambda p=project: handlers.on_start(p)
        )
    else:
        start_or_stop = MenuItemSpec(
            text="Stop", action=lambda p=project: handlers.on_stop(p)
        )
    entries: list[MenuItemSpec] = [
        start_or_stop,
        MenuItemSpec(text="", separator=True),
        MenuItemSpec(
            text="Open in browser",
            action=lambda p=project: handlers.on_open_browser(p),
            enabled=not is_stopped,
        ),
        MenuItemSpec(
            text="Open backend folder",
            action=lambda path=project.backend.path: handlers.on_open_folder(path),
        ),
        MenuItemSpec(
            text="Open frontend folder",
            action=lambda path=project.frontend.path: handlers.on_open_folder(path),
        ),
    ]
    if not is_stopped:
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
    if project.tasks:
        task_specs = tuple(
            _task_spec(project, task, handlers, running_tasks)
            for task in project.tasks
        )
        entries.append(MenuItemSpec(text="Tasks", submenu=task_specs))
    return tuple(entries)
```

- [ ] **Step 6: Add `Open logs folder` and tooltip helper to `foxtray/ui/tray.py`**

Inside `build_menu_items`, right before the `items.append(MenuItemSpec(text="", separator=True))` that precedes "Stop all", add:

```python
items.append(MenuItemSpec(text="", separator=True))
items.append(MenuItemSpec(
    text="Open logs folder",
    action=handlers.on_open_logs_folder,
))
```

Add tooltip helper at module scope (before `TrayApp`):

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

Update `TrayApp._poll_tick` — at the end of the try block (after the orphan-clear block):

```python
try:
    self._icon.title = _tooltip_text(curr_active, curr_statuses)
except Exception:  # noqa: BLE001
    log.warning("tooltip update failed", exc_info=True)
```

- [ ] **Step 7: Wire new handlers in `TrayApp._handlers`**

Inside the `Handlers(...)` return, add:

```python
on_restart=lambda p: actions.on_restart(orch, p, icon, self._user_initiated_stop),
on_open_logs_folder=lambda: actions.on_open_logs_folder(icon),
on_copy_url=lambda url: actions.on_copy_url(url, icon),
```

- [ ] **Step 8: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: ALL green.

- [ ] **Step 9: Commit**

```bash
git add foxtray/ui/tray.py tests/test_tray.py tests/test_tray_app.py
git commit -m "feat(ui/tray): Restart + Copy URL + Open logs folder + tooltip status"
```

---

## Task 5: Manual smoke test doc

**Files:** `docs/manual-tests/iter5a.md`.

- [ ] **Step 1: Create the doc**

```markdown
# FoxTray Iter 5a — Manual Test Log

Prerequisite: Iter 4b passed.

## Environment

- Date: <fill>
- HEAD: <commit sha>
- pytest: all green

## Restart

- [ ] Start FoxRunner, wait green.
- [ ] Right-click → FoxRunner ▸ Restart. Menu closes immediately (no 10s freeze).
- [ ] Within ~10s icon cycles: green → grey → orange → green. Expected balloon sequence depends on transitions (probably "FoxRunner is up" once healthy again).
- [ ] `state.json.active` points to FoxRunner throughout (no gap).

## Copy URL

- [ ] Right-click → FoxRunner ▸ Copy URL. Balloon "URL copied: http://localhost:4200".
- [ ] Paste in a browser address bar. URL matches.

## Open logs folder

- [ ] Right-click → Open logs folder (bottom of root menu, before Stop all).
- [ ] Explorer opens at `%APPDATA%\foxtray\logs\`. Shows `FoxRunner_backend.log`, etc.

## Open project folder (requires `path_root`)

- [ ] Add `path_root: D:\PycharmProjects\FoxRunner` to the FoxRunner YAML entry. Restart tray.
- [ ] Right-click → FoxRunner ▸ Open project folder. Explorer opens at the root.
- [ ] Remove the line, restart tray. The entry is gone from the submenu.

## Icon tooltip

- [ ] With no project active, hover icon → tooltip "FoxTray — idle".
- [ ] Start FoxRunner → tooltip "FoxTray — FoxRunner RUNNING" (after health check passes).
- [ ] Kill the frontend node.exe via Task Manager → tooltip "FoxTray — FoxRunner PARTIAL (frontend down)" within 3s.
- [ ] Click Stop. Tooltip returns to "FoxTray — FoxRunner stopped" briefly, then "FoxTray — idle" on next tick once state clears.

## Known limitations

- Tooltip updates at the 3s poll cadence, not instantly.
- `clip.exe` requires Windows (no graceful fallback elsewhere).

## Observed issues
_None yet._
```

- [ ] **Step 2: Commit**

```bash
git add docs/manual-tests/iter5a.md
git commit -m "docs(iter5a): manual smoke checklist"
```

---

## Self-review summary

- 5 spec features each have ≥1 task.
- No transient test failures expected between tasks. Task 4 adds 3 required `Handlers` fields; the same task updates `_noop_handlers*`.
- Type consistency: `on_restart: Callable[[Project], None]`, `on_open_logs_folder: Callable[[], None]`, `on_copy_url: Callable[[str], None]` across spec + plan.
- `_tooltip_text` is a pure helper testable via `test_tray_app.py`.
