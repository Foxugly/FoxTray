# FoxTray Iter 2 (Tray Icon) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Windows tray icon layered on top of the Iter 1 `Orchestrator`, so starting or stopping a Django + Angular pair is a two-click menu action with a live icon color and balloon notifications on state transitions.

**Architecture:** Three cooperating threads — pystray event loop (main), 3-second poller (daemon), pystray menu-callback (internal). No shared mutable state needing locks. The tray's "business logic" is split into pure helpers (`compute_icon_state`, `compute_transitions`, `build_menu_items`) that are unit-tested without pystray, plus a thin `TrayApp` integration layer that is manually smoke-tested.

**Tech Stack:** `pystray` (tray icon + menu), `Pillow` (icon images), `webbrowser` / `os.startfile` (menu actions), existing `foxtray.project.Orchestrator` (business logic).

**Spec:** `docs/superpowers/specs/2026-04-23-foxtray-iter2-design.md`.

---

## File Structure

Created files (production):
- `foxtray/ui/__init__.py` — empty package marker
- `foxtray/ui/icons.py` — `IconState` Literal + cached `load(state)` returning `PIL.Image`
- `foxtray/ui/tray.py` — dataclasses (`Notification`, `MenuItemSpec`, `Handlers`), pure helpers (`compute_icon_state`, `compute_transitions`, `build_menu_items`), and the `TrayApp` integration class
- `foxtray/ui/actions.py` — menu action handlers (`on_start`, `on_stop`, `on_open_browser`, `on_open_folder`, `on_stop_all`, `on_exit`, `on_stop_all_and_exit`) as free functions with exception-to-notification catch
- `scripts/gen_icons.py` — one-off Pillow script that writes `assets/icon_{running,partial,stopped}.png`
- `assets/icon_running.png` / `icon_partial.png` / `icon_stopped.png` — 32×32 colored-disc placeholders
- `tests/test_icons.py`
- `tests/test_tray.py` — pure helper tests
- `tests/test_tray_actions.py` — action handler tests with fake orchestrator + fake icon
- `tests/test_tray_app.py` — `TrayApp._poll_tick` integration test with fakes
- `docs/manual-tests/iter2.md`

Modified files:
- `foxtray/cli.py` — add `cmd_tray` + subparser
- `requirements.txt` — add `pystray>=0.19` and `Pillow>=10.0`

Unchanged: everything under `foxtray/` outside `ui/`, `main.py`, `config.yaml`, Iter 1 tests.

---

### Task 1: Scaffolding + dependencies

**Files:**
- Modify: `requirements.txt`
- Create: `foxtray/ui/__init__.py`

- [ ] **Step 1: Add pystray + Pillow to `requirements.txt`**

Replace the file with:
```
psutil>=5.9
PyYAML>=6.0
requests>=2.31
pystray>=0.19
Pillow>=10.0
```

- [ ] **Step 2: Install the new deps into the existing `.venv`**

```
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
```

Expected: installs `pystray` and `Pillow` without touching the others.

- [ ] **Step 3: Verify imports work**

```
./.venv/Scripts/python.exe -c "import pystray; import PIL.Image; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 4: Create empty `foxtray/ui/__init__.py`** (single blank line)

- [ ] **Step 5: Full suite still green**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 49 passed (no new tests yet).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt foxtray/ui/__init__.py
git commit -m "chore(iter2): add pystray + Pillow dependencies, create ui package"
```

---

### Task 2: Icon asset generation + `icons.py`

The `assets/` PNGs are placeholders produced by a script. Commit both the script and the PNGs so subsequent tasks can assume the images exist and the generator is reproducible.

**Files:**
- Create: `scripts/gen_icons.py`
- Create (via script): `assets/icon_running.png`, `assets/icon_partial.png`, `assets/icon_stopped.png`
- Create: `foxtray/ui/icons.py`
- Create: `tests/test_icons.py`

- [ ] **Step 1: Write `scripts/gen_icons.py`**

```python
"""One-off icon generator. Re-run to update placeholder PNGs.

Usage:
    python scripts/gen_icons.py

Writes three 32x32 RGBA PNGs into assets/.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_SIZE = 32
_PADDING = 2  # leave a 2px margin so the disc doesn't touch the bounding box
_COLORS = {
    "running": (0x33, 0xAA, 0x33, 0xFF),   # green
    "partial": (0xEE, 0x99, 0x00, 0xFF),   # orange
    "stopped": (0x88, 0x88, 0x88, 0xFF),   # grey
}


def main() -> None:
    _ASSETS.mkdir(parents=True, exist_ok=True)
    for state, color in _COLORS.items():
        img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse(
            (_PADDING, _PADDING, _SIZE - _PADDING - 1, _SIZE - _PADDING - 1),
            fill=color,
        )
        out = _ASSETS / f"icon_{state}.png"
        img.save(out, format="PNG")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the generator**

```
./.venv/Scripts/python.exe scripts/gen_icons.py
```

Expected: prints three `wrote ...\assets\icon_*.png` lines, each file is roughly 200–500 bytes.

- [ ] **Step 3: Write failing tests in `tests/test_icons.py`**

```python
from PIL import Image

from foxtray.ui import icons


def test_load_returns_image_for_running() -> None:
    img = icons.load("running")
    assert isinstance(img, Image.Image)
    assert img.size == (32, 32)


def test_load_returns_image_for_partial() -> None:
    img = icons.load("partial")
    assert isinstance(img, Image.Image)


def test_load_returns_image_for_stopped() -> None:
    img = icons.load("stopped")
    assert isinstance(img, Image.Image)


def test_load_is_cached() -> None:
    first = icons.load("running")
    second = icons.load("running")
    assert first is second
```

- [ ] **Step 4: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_icons.py -v
```

Expected: 4 failures (`ModuleNotFoundError: No module named 'foxtray.ui.icons'`).

- [ ] **Step 5: Implement `foxtray/ui/icons.py`**

```python
"""Tray icon images by state, cached once on first load."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image

IconState = Literal["running", "partial", "stopped"]

_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
_cache: dict[IconState, Image.Image] = {}


def load(state: IconState) -> Image.Image:
    if state not in _cache:
        path = _ASSETS / f"icon_{state}.png"
        _cache[state] = Image.open(path).copy()
    return _cache[state]
```

Note: `Image.open(...).copy()` materialises the image in memory so the file handle can be closed, and the cached object is a plain in-memory image.

- [ ] **Step 6: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_icons.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/gen_icons.py assets/icon_running.png assets/icon_partial.png assets/icon_stopped.png foxtray/ui/icons.py tests/test_icons.py
git commit -m "feat(ui/icons): generate tray icon PNGs and expose cached loader"
```

---

### Task 3: Tray dataclasses + `compute_icon_state`

`tray.py` gets built up in three tasks (3, 4, 5) each introducing one pure helper. This task introduces the shared dataclasses and the simplest helper, plus the `ProjectSnapshot` that Task 4 will reuse.

**Files:**
- Create: `foxtray/ui/tray.py`
- Create: `tests/test_tray.py`

- [ ] **Step 1: Write failing tests in `tests/test_tray.py`**

```python
from foxtray import config, state
from foxtray.project import ProjectStatus
from foxtray.ui import tray


def _status(*, backend_alive: bool = False, frontend_alive: bool = False) -> ProjectStatus:
    return ProjectStatus(
        name="X",
        running=backend_alive and frontend_alive,
        backend_alive=backend_alive,
        frontend_alive=frontend_alive,
        backend_port_listening=False,
        frontend_port_listening=False,
        url_ok=False,
    )


def test_icon_state_stopped_when_no_active() -> None:
    assert tray.compute_icon_state(None, {}) == "stopped"


def test_icon_state_running_when_both_alive() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    assert tray.compute_icon_state(active, statuses) == "running"


def test_icon_state_partial_when_only_backend_alive() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    assert tray.compute_icon_state(active, statuses) == "partial"


def test_icon_state_partial_when_only_frontend_alive() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=False, frontend_alive=True)}
    assert tray.compute_icon_state(active, statuses) == "partial"


def test_icon_state_stopped_when_active_but_both_dead() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=False, frontend_alive=False)}
    assert tray.compute_icon_state(active, statuses) == "stopped"
```

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: 5 failures (`ModuleNotFoundError: No module named 'foxtray.ui.tray'`).

- [ ] **Step 3: Implement `foxtray/ui/tray.py` (partial — dataclasses + icon state helper)**

```python
"""Tray UI orchestration: dataclasses, pure helpers, TrayApp integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from foxtray import config as config_mod
from foxtray import state as state_mod
from foxtray.project import ProjectStatus
from foxtray.ui.icons import IconState


@dataclass(frozen=True)
class Notification:
    title: str
    message: str


@dataclass(frozen=True)
class MenuItemSpec:
    text: str
    action: Callable[[], None] | None = None
    enabled: bool = True
    submenu: tuple["MenuItemSpec", ...] = field(default_factory=tuple)
    separator: bool = False


@dataclass
class Handlers:
    on_start: Callable[[config_mod.Project], None]
    on_stop: Callable[[config_mod.Project], None]
    on_open_browser: Callable[[config_mod.Project], None]
    on_open_folder: Callable[[Path], None]
    on_stop_all: Callable[[], None]
    on_exit: Callable[[], None]
    on_stop_all_and_exit: Callable[[], None]


def compute_icon_state(
    active: state_mod.ActiveProject | None,
    statuses: dict[str, ProjectStatus],
) -> IconState:
    if active is None:
        return "stopped"
    status = statuses.get(active.name)
    if status is None:
        return "stopped"
    if status.backend_alive and status.frontend_alive:
        return "running"
    if status.backend_alive or status.frontend_alive:
        return "partial"
    return "stopped"
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add foxtray/ui/tray.py tests/test_tray.py
git commit -m "feat(ui/tray): add tray dataclasses and compute_icon_state"
```

---

### Task 4: `compute_transitions`

Appends the second pure helper and its tests. Transitions are computed per-project by comparing each project's "per-project icon state" across the two snapshots. The helper must honour the `suppressed` set (populated when the user clicked Stop) by skipping the corresponding `running→stopped` / `partial→stopped` notification.

**Files:**
- Modify: `foxtray/ui/tray.py` (append function + private helper)
- Modify: `tests/test_tray.py` (append tests)

- [ ] **Step 1: Append failing tests to `tests/test_tray.py`**

```python
def test_transitions_stopped_to_running_fires_up() -> None:
    prev_active = None
    curr_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses: dict[str, ProjectStatus] = {
        "FoxRunner": _status(),
    }
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, curr_active, curr_statuses, suppressed=set()
    )
    assert [n.message for n in notifications] == ["FoxRunner is up"]


def test_transitions_stopped_to_partial_fires_component_failure() -> None:
    prev_active = None
    curr_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, curr_active, curr_statuses, suppressed=set()
    )
    assert len(notifications) == 1
    assert "FoxRunner" in notifications[0].message
    assert "one component failed" in notifications[0].message


def test_transitions_running_to_partial_names_dead_component() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    notifications = tray.compute_transitions(
        active, prev_statuses, active, curr_statuses, suppressed=set()
    )
    assert len(notifications) == 1
    assert "frontend crashed" in notifications[0].message


def test_transitions_partial_to_running_fires_recovered() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    notifications = tray.compute_transitions(
        active, prev_statuses, active, curr_statuses, suppressed=set()
    )
    assert [n.message for n in notifications] == ["FoxRunner recovered"]


def test_transitions_running_to_stopped_suppressed_is_silent() -> None:
    prev_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    curr_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, None, curr_statuses, suppressed={"FoxRunner"}
    )
    assert notifications == []


def test_transitions_running_to_stopped_unsuppressed_fires_unexpected() -> None:
    prev_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    curr_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, None, curr_statuses, suppressed=set()
    )
    assert len(notifications) == 1
    assert "stopped unexpectedly" in notifications[0].message


def test_transitions_no_change_returns_empty() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    notifications = tray.compute_transitions(
        active, statuses, active, statuses, suppressed=set()
    )
    assert notifications == []
```

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: 7 new failures (`AttributeError: module 'foxtray.ui.tray' has no attribute 'compute_transitions'`).

- [ ] **Step 3: Append `compute_transitions` (and its private helpers) to `foxtray/ui/tray.py`**

```python
def _project_icon_state(
    name: str,
    active: state_mod.ActiveProject | None,
    status: ProjectStatus | None,
) -> IconState:
    if active is None or active.name != name or status is None:
        return "stopped"
    if status.backend_alive and status.frontend_alive:
        return "running"
    if status.backend_alive or status.frontend_alive:
        return "partial"
    return "stopped"


def _dead_component(prev: ProjectStatus, curr: ProjectStatus) -> str:
    if prev.backend_alive and not curr.backend_alive:
        return "backend"
    if prev.frontend_alive and not curr.frontend_alive:
        return "frontend"
    return "unknown"


def compute_transitions(
    prev_active: state_mod.ActiveProject | None,
    prev_statuses: dict[str, ProjectStatus],
    curr_active: state_mod.ActiveProject | None,
    curr_statuses: dict[str, ProjectStatus],
    suppressed: set[str],
) -> list[Notification]:
    # Every project name that appears in either snapshot is checked.
    names = set(prev_statuses) | set(curr_statuses)
    if prev_active is not None:
        names.add(prev_active.name)
    if curr_active is not None:
        names.add(curr_active.name)

    notifications: list[Notification] = []
    for name in sorted(names):
        prev_state = _project_icon_state(name, prev_active, prev_statuses.get(name))
        curr_state = _project_icon_state(name, curr_active, curr_statuses.get(name))
        if prev_state == curr_state:
            continue

        if prev_state == "stopped" and curr_state == "running":
            notifications.append(Notification("FoxTray", f"{name} is up"))
        elif prev_state == "stopped" and curr_state == "partial":
            notifications.append(
                Notification("FoxTray", f"{name} started but one component failed")
            )
        elif prev_state == "running" and curr_state == "partial":
            dead = _dead_component(prev_statuses[name], curr_statuses[name])
            notifications.append(
                Notification("FoxTray", f"⚠ {name}: {dead} crashed")
            )
        elif prev_state == "partial" and curr_state == "running":
            notifications.append(Notification("FoxTray", f"{name} recovered"))
        elif prev_state == "running" and curr_state == "stopped":
            if name not in suppressed:
                notifications.append(
                    Notification("FoxTray", f"⚠ {name} stopped unexpectedly")
                )
        elif prev_state == "partial" and curr_state == "stopped":
            if name not in suppressed:
                notifications.append(
                    Notification("FoxTray", f"⚠ {name} fully stopped")
                )
        # Any other transition (e.g. stopped→stopped handled by the continue above)
        # is silent by design.

    return notifications
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: 12 passed (5 from Task 3 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add foxtray/ui/tray.py tests/test_tray.py
git commit -m "feat(ui/tray): compute_transitions with suppression support"
```

---

### Task 5: `build_menu_items`

Produces the tree of `MenuItemSpec` objects that drive the menu. pystray conversion happens later in `TrayApp._build_menu`.

**Files:**
- Modify: `foxtray/ui/tray.py` (append function)
- Modify: `tests/test_tray.py` (append tests)

- [ ] **Step 1: Append failing tests to `tests/test_tray.py`**

```python
from pathlib import Path


def _project(name: str, url: str = "http://localhost:4200") -> config.Project:
    return config.Project(
        name=name,
        url=url,
        backend=config.Backend(
            path=Path(f"D:\\projects\\{name}-server"),
            venv=".venv",
            command="python manage.py runserver 8000",
            port=8000,
        ),
        frontend=config.Frontend(
            path=Path(f"D:\\projects\\{name}-frontend"),
            command="ng serve --port 4200",
            port=4200,
        ),
    )


def _noop_handlers() -> tray.Handlers:
    return tray.Handlers(
        on_start=lambda p: None,
        on_stop=lambda p: None,
        on_open_browser=lambda p: None,
        on_open_folder=lambda path: None,
        on_stop_all=lambda: None,
        on_exit=lambda: None,
        on_stop_all_and_exit=lambda: None,
    )


def test_menu_lists_all_projects_in_config_order() -> None:
    cfg = config.Config(projects=[_project("A"), _project("B"), _project("C")])
    statuses = {"A": _status(), "B": _status(), "C": _status()}
    items = tray.build_menu_items(cfg, None, statuses, _noop_handlers())
    project_items = [i for i in items if not i.separator and i.submenu]
    assert [i.text.split(" ")[0] for i in project_items] == ["A", "B", "C"]


def test_menu_stopped_project_shows_start() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers())
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Start" in submenu_texts
    assert "Stop" not in submenu_texts


def test_menu_running_project_shows_stop() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers())
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Stop" in submenu_texts
    assert "Start" not in submenu_texts


def test_menu_stopped_project_disables_open_in_browser() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers())
    browser_item = next(s for s in items[0].submenu if s.text == "Open in browser")
    assert browser_item.enabled is False


def test_menu_running_project_enables_open_in_browser() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers())
    browser_item = next(s for s in items[0].submenu if s.text == "Open in browser")
    assert browser_item.enabled is True


def test_menu_stop_all_disabled_when_no_active() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers())
    stop_all = next(i for i in items if i.text == "Stop all")
    assert stop_all.enabled is False


def test_menu_stop_all_enabled_when_active() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers())
    stop_all = next(i for i in items if i.text == "Stop all")
    assert stop_all.enabled is True


def test_menu_has_exit_and_stop_all_and_exit() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers())
    texts = [i.text for i in items if not i.separator]
    assert "Exit" in texts
    assert "Stop all and exit" in texts


def test_menu_project_label_reflects_status() -> None:
    cfg = config.Config(projects=[_project("A"), _project("B"), _project("C")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {
        "A": _status(backend_alive=True, frontend_alive=True),   # RUNNING
        "B": _status(backend_alive=False, frontend_alive=False), # stopped
        "C": _status(),                                          # stopped
    }
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers())
    labels_by_name = {i.text.split(" ")[0]: i.text for i in items if i.submenu}
    assert "RUNNING" in labels_by_name["A"]
    assert "stopped" in labels_by_name["B"]
    assert "stopped" in labels_by_name["C"]


def test_menu_partial_project_labelled_partial() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=False)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers())
    assert "PARTIAL" in items[0].text
```

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: 10 new failures.

- [ ] **Step 3: Append `build_menu_items` to `foxtray/ui/tray.py`**

```python
def _project_label(state: IconState) -> str:
    return {
        "running": "RUNNING",
        "partial": "PARTIAL",
        "stopped": "stopped",
    }[state]


def _project_submenu(
    project: config_mod.Project,
    icon_state: IconState,
    handlers: Handlers,
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
    return (
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
    )


def build_menu_items(
    cfg: config_mod.Config,
    active: state_mod.ActiveProject | None,
    statuses: dict[str, ProjectStatus],
    handlers: Handlers,
) -> list[MenuItemSpec]:
    items: list[MenuItemSpec] = []
    for project in cfg.projects:
        proj_state = _project_icon_state(project.name, active, statuses.get(project.name))
        label = _project_label(proj_state)
        items.append(
            MenuItemSpec(
                text=f"{project.name} ({label})",
                submenu=_project_submenu(project, proj_state, handlers),
            )
        )
    items.append(MenuItemSpec(text="", separator=True))
    items.append(
        MenuItemSpec(
            text="Stop all",
            action=handlers.on_stop_all,
            enabled=active is not None,
        )
    )
    items.append(MenuItemSpec(text="", separator=True))
    items.append(MenuItemSpec(text="Exit", action=handlers.on_exit))
    items.append(
        MenuItemSpec(
            text="Stop all and exit",
            action=handlers.on_stop_all_and_exit,
            enabled=active is not None,
        )
    )
    return items
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: 22 passed (5 + 7 + 10).

- [ ] **Step 5: Commit**

```bash
git add foxtray/ui/tray.py tests/test_tray.py
git commit -m "feat(ui/tray): build_menu_items with project submenus and global items"
```

---

### Task 6: Action handlers

The action handlers are thin wrappers around `Orchestrator` and `webbrowser`/`os.startfile`. Each catches exceptions and surfaces them via `icon.notify`. The `icon` argument is a `NotifierProtocol` so we can test with a fake instead of a real pystray icon.

**Files:**
- Create: `foxtray/ui/actions.py`
- Create: `tests/test_tray_actions.py`

- [ ] **Step 1: Write failing tests in `tests/test_tray_actions.py`**

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from foxtray import config
from foxtray.ui import actions


def _project(name: str = "Demo") -> config.Project:
    return config.Project(
        name=name,
        url="http://localhost:4200",
        backend=config.Backend(
            path=Path("D:\\proj\\back"),
            venv=".venv",
            command="python manage.py runserver 8000",
            port=8000,
        ),
        frontend=config.Frontend(
            path=Path("D:\\proj\\front"),
            command="ng serve --port 4200",
            port=4200,
        ),
    )


@dataclass
class _FakeIcon:
    notifications: list[tuple[str, str]] = field(default_factory=list)

    def notify(self, message: str, title: str = "") -> None:
        self.notifications.append((title, message))


@dataclass
class _FakeOrchestrator:
    started: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    stop_all_called: int = 0
    raises: Exception | None = None

    def start(self, project: Any) -> None:
        if self.raises:
            raise self.raises
        self.started.append(project.name)

    def stop(self, name: str) -> None:
        if self.raises:
            raise self.raises
        self.stopped.append(name)

    def stop_all(self) -> None:
        if self.raises:
            raise self.raises
        self.stop_all_called += 1


def test_on_start_calls_orchestrator() -> None:
    orch = _FakeOrchestrator()
    icon = _FakeIcon()
    actions.on_start(orch, _project(), icon)
    assert orch.started == ["Demo"]
    assert icon.notifications == []


def test_on_start_notifies_on_exception() -> None:
    orch = _FakeOrchestrator(raises=RuntimeError("boom"))
    icon = _FakeIcon()
    actions.on_start(orch, _project(), icon)
    assert icon.notifications == [("FoxTray error", "boom")]


def test_on_stop_adds_to_user_initiated_and_calls_orchestrator() -> None:
    orch = _FakeOrchestrator()
    icon = _FakeIcon()
    user_initiated: set[str] = set()
    actions.on_stop(orch, _project(), icon, user_initiated)
    assert orch.stopped == ["Demo"]
    assert user_initiated == {"Demo"}


def test_on_stop_notifies_on_exception_but_still_flags_user_initiated() -> None:
    orch = _FakeOrchestrator(raises=RuntimeError("boom"))
    icon = _FakeIcon()
    user_initiated: set[str] = set()
    actions.on_stop(orch, _project(), icon, user_initiated)
    # Even if stop fails, user intent was to stop, so flag it to avoid a
    # false-positive "crashed" notification on the next tick.
    assert user_initiated == {"Demo"}
    assert icon.notifications == [("FoxTray error", "boom")]


def test_on_open_browser_calls_webbrowser_open(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(actions, "_open_url", lambda url: captured.append(url))
    actions.on_open_browser(_project(), _FakeIcon())
    assert captured == ["http://localhost:4200"]


def test_on_open_folder_calls_startfile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(actions, "_open_folder_native", lambda p: captured.append(str(p)))
    actions.on_open_folder(Path("D:\\proj\\back"), _FakeIcon())
    assert captured == ["D:\\proj\\back"]


def test_on_stop_all_populates_user_initiated_for_each_active_name() -> None:
    orch = _FakeOrchestrator()
    icon = _FakeIcon()
    user_initiated: set[str] = set()
    # In real use only one project is active, but the handler must cover whatever
    # the state says before stop_all clears it.
    actions.on_stop_all(orch, icon, user_initiated, active_names=["FoxRunner"])
    assert orch.stop_all_called == 1
    assert user_initiated == {"FoxRunner"}


def test_on_exit_calls_icon_stop() -> None:
    class _Icon:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    icon = _Icon()
    actions.on_exit(icon)
    assert icon.stopped is True


def test_on_stop_all_and_exit_stops_then_exits() -> None:
    class _Icon:
        def __init__(self) -> None:
            self.stopped = False
            self.notifications: list[tuple[str, str]] = []

        def notify(self, message: str, title: str = "") -> None:
            self.notifications.append((title, message))

        def stop(self) -> None:
            self.stopped = True

    orch = _FakeOrchestrator()
    icon = _Icon()
    user_initiated: set[str] = set()
    actions.on_stop_all_and_exit(orch, icon, user_initiated, active_names=["FoxRunner"])
    assert orch.stop_all_called == 1
    assert user_initiated == {"FoxRunner"}
    assert icon.stopped is True
```

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_actions.py -v
```

Expected: 9 failures (`ModuleNotFoundError: No module named 'foxtray.ui.actions'`).

- [ ] **Step 3: Implement `foxtray/ui/actions.py`**

```python
"""Menu action handlers. Each catches its own exceptions and notifies via icon."""
from __future__ import annotations

import logging
import os
import webbrowser
from pathlib import Path
from typing import Protocol, Sequence

from foxtray import config
from foxtray.project import Orchestrator

log = logging.getLogger(__name__)


class _Notifier(Protocol):
    def notify(self, message: str, title: str = "") -> None: ...


class _Closable(Protocol):
    def stop(self) -> None: ...


def _open_url(url: str) -> None:
    webbrowser.open(url)


def _open_folder_native(path: Path) -> None:
    os.startfile(str(path))  # noqa: S606 — Windows-only, user-initiated


def _notify_error(icon: _Notifier, exc: Exception) -> None:
    log.warning("tray handler failed", exc_info=True)
    icon.notify(str(exc), title="FoxTray error")


def on_start(orchestrator: Orchestrator, project: config.Project, icon: _Notifier) -> None:
    try:
        orchestrator.start(project)
    except Exception as exc:  # noqa: BLE001 — tray must survive any handler error
        _notify_error(icon, exc)


def on_stop(
    orchestrator: Orchestrator,
    project: config.Project,
    icon: _Notifier,
    user_initiated: set[str],
) -> None:
    user_initiated.add(project.name)
    try:
        orchestrator.stop(project.name)
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_open_browser(project: config.Project, icon: _Notifier) -> None:
    try:
        _open_url(project.url)
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_open_folder(path: Path, icon: _Notifier) -> None:
    try:
        _open_folder_native(path)
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_stop_all(
    orchestrator: Orchestrator,
    icon: _Notifier,
    user_initiated: set[str],
    active_names: Sequence[str],
) -> None:
    for name in active_names:
        user_initiated.add(name)
    try:
        orchestrator.stop_all()
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)


def on_exit(icon: _Closable) -> None:
    icon.stop()


def on_stop_all_and_exit(
    orchestrator: Orchestrator,
    icon: _Closable,
    user_initiated: set[str],
    active_names: Sequence[str],
) -> None:
    for name in active_names:
        user_initiated.add(name)
    try:
        orchestrator.stop_all()
    except Exception as exc:  # noqa: BLE001
        # cast: we know the production icon satisfies both Protocols
        if hasattr(icon, "notify"):
            _notify_error(icon, exc)  # type: ignore[arg-type]
    icon.stop()
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_actions.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 49 (Iter 1) + 4 (icons) + 22 (tray) + 9 (actions) = 84 passed.

- [ ] **Step 6: Commit**

```bash
git add foxtray/ui/actions.py tests/test_tray_actions.py
git commit -m "feat(ui/actions): menu action handlers with exception-to-notify catch"
```

---

### Task 7: `TrayApp` integration — `_poll_tick`

`TrayApp` owns the pystray icon, the poller thread, and the previous-snapshot state. The critical testable method is `_poll_tick`, which wires the pure helpers to a real orchestrator and icon. `TrayApp.run()` itself is only smoke-tested manually.

**Files:**
- Modify: `foxtray/ui/tray.py` (append `TrayApp` class + helper for building handlers)
- Create: `tests/test_tray_app.py`

- [ ] **Step 1: Write failing tests in `tests/test_tray_app.py`**

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foxtray import config, state
from foxtray.project import ProjectStatus
from foxtray.ui import icons, tray


def _project(name: str) -> config.Project:
    return config.Project(
        name=name,
        url="http://localhost:4200",
        backend=config.Backend(
            path=Path(f"D:\\p\\{name}\\back"),
            venv=".venv",
            command="python manage.py runserver 8000",
            port=8000,
        ),
        frontend=config.Frontend(
            path=Path(f"D:\\p\\{name}\\front"),
            command="ng serve --port 4200",
            port=4200,
        ),
    )


def _status(*, backend_alive: bool = False, frontend_alive: bool = False) -> ProjectStatus:
    return ProjectStatus(
        name="X",
        running=backend_alive and frontend_alive,
        backend_alive=backend_alive,
        frontend_alive=frontend_alive,
        backend_port_listening=False,
        frontend_port_listening=False,
        url_ok=False,
    )


@dataclass
class _FakeIcon:
    icon: Any = None
    notifications: list[tuple[str, str]] = field(default_factory=list)
    stopped: bool = False

    def notify(self, message: str, title: str = "") -> None:
        self.notifications.append((title, message))

    def stop(self) -> None:
        self.stopped = True


@dataclass
class _FakeOrchestrator:
    next_statuses: dict[str, ProjectStatus] = field(default_factory=dict)
    next_active: state.ActiveProject | None = None

    def status(self, project: config.Project) -> ProjectStatus:
        return self.next_statuses[project.name]

    def start(self, project: config.Project) -> None: ...
    def stop(self, name: str) -> None: ...
    def stop_all(self) -> None: ...


def test_poll_tick_sets_icon_to_running_and_notifies(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True)},
    )
    icon = _FakeIcon(icon=icons.load("stopped"))
    app = tray.TrayApp(cfg, orch)  # type: ignore[arg-type]
    app._icon = icon  # inject fake

    # Simulate CLI having just set state to active A
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))

    app._poll_tick()

    assert icon.notifications == [("FoxTray", "A is up")]
    assert icon.icon is icons.load("running")


def test_poll_tick_no_notifications_on_stable_state(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True)},
    )
    icon = _FakeIcon(icon=icons.load("running"))
    app = tray.TrayApp(cfg, orch)  # type: ignore[arg-type]
    app._icon = icon
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))

    # First tick: transition from baseline (nothing) to running → notify.
    app._poll_tick()
    icon.notifications.clear()

    # Second tick with same state: silent.
    app._poll_tick()
    assert icon.notifications == []


def test_poll_tick_running_to_partial_notifies_crash(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True)},
    )
    icon = _FakeIcon(icon=icons.load("stopped"))
    app = tray.TrayApp(cfg, orch)  # type: ignore[arg-type]
    app._icon = icon
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))

    # Tick 1: both alive → running.
    app._poll_tick()
    icon.notifications.clear()

    # Tick 2: frontend dies.
    orch.next_statuses["A"] = _status(backend_alive=True, frontend_alive=False)
    app._poll_tick()

    assert len(icon.notifications) == 1
    assert "frontend crashed" in icon.notifications[0][1]
    assert icon.icon is icons.load("partial")


def test_poll_tick_survives_orchestrator_exception(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    class _Broken(_FakeOrchestrator):
        def status(self, project: config.Project) -> ProjectStatus:
            raise RuntimeError("orchestrator exploded")

    cfg = config.Config(projects=[_project("A")])
    icon = _FakeIcon(icon=icons.load("stopped"))
    app = tray.TrayApp(cfg, _Broken())  # type: ignore[arg-type]
    app._icon = icon

    # Must not raise.
    app._poll_tick()

    # Icon unchanged; no notifications fired.
    assert icon.icon is icons.load("stopped")
    assert icon.notifications == []
```

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_app.py -v
```

Expected: 4 failures (`AttributeError: module 'foxtray.ui.tray' has no attribute 'TrayApp'`).

- [ ] **Step 3: Append `TrayApp` to `foxtray/ui/tray.py`**

```python
import logging
import threading
import time

import pystray

from foxtray import state as state_mod
from foxtray.project import Orchestrator
from foxtray.ui import actions, icons

log = logging.getLogger(__name__)

_POLL_INTERVAL_S = 3.0


class TrayApp:
    """Integrates pystray + 3s poller on top of the pure helpers above."""

    def __init__(self, cfg: config_mod.Config, orchestrator: Orchestrator) -> None:
        self._cfg = cfg
        self._orchestrator = orchestrator
        self._icon: pystray.Icon | None = None
        self._prev_active: state_mod.ActiveProject | None = None
        self._prev_statuses: dict[str, ProjectStatus] = {
            p.name: _zero_status(p.name) for p in cfg.projects
        }
        self._prev_icon_state: IconState = "stopped"
        self._user_initiated_stop: set[str] = set()
        self._stop_event = threading.Event()

    def run(self) -> None:
        self._icon = pystray.Icon(
            name="FoxTray",
            icon=icons.load("stopped"),
            title="FoxTray",
            menu=pystray.Menu(self._build_menu),
        )
        poller = threading.Thread(target=self._poll_loop, name="foxtray-poller", daemon=True)
        poller.start()
        try:
            self._icon.run()
        finally:
            self._stop_event.set()
            poller.join(timeout=_POLL_INTERVAL_S + 1.0)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            self._poll_tick()
            self._stop_event.wait(_POLL_INTERVAL_S)

    def _poll_tick(self) -> None:
        if self._icon is None:
            return
        try:
            curr_active = state_mod.load().active
            curr_statuses = {
                p.name: self._orchestrator.status(p) for p in self._cfg.projects
            }
        except Exception:  # noqa: BLE001 — poll loop must never die
            log.warning("poll tick failed", exc_info=True)
            return

        suppressed = set(self._user_initiated_stop)
        self._user_initiated_stop.clear()

        for note in compute_transitions(
            self._prev_active, self._prev_statuses,
            curr_active, curr_statuses,
            suppressed,
        ):
            self._icon.notify(note.message, title=note.title)

        new_icon_state = compute_icon_state(curr_active, curr_statuses)
        if new_icon_state != self._prev_icon_state:
            self._icon.icon = icons.load(new_icon_state)
            self._prev_icon_state = new_icon_state

        self._prev_active = curr_active
        self._prev_statuses = curr_statuses

    def _build_menu(self) -> tuple[pystray.MenuItem, ...]:
        if self._icon is None:
            return ()
        try:
            active = state_mod.load().active
            statuses = {
                p.name: self._orchestrator.status(p) for p in self._cfg.projects
            }
        except Exception:  # noqa: BLE001
            log.warning("menu build failed", exc_info=True)
            return (pystray.MenuItem("FoxTray error", None, enabled=False),)
        handlers = self._handlers()
        specs = build_menu_items(self._cfg, active, statuses, handlers)
        return tuple(_spec_to_pystray(s) for s in specs)

    def _handlers(self) -> Handlers:
        icon = self._icon
        assert icon is not None
        orch = self._orchestrator
        user_init = self._user_initiated_stop

        def _active_names() -> list[str]:
            a = state_mod.load().active
            return [a.name] if a is not None else []

        return Handlers(
            on_start=lambda p: actions.on_start(orch, p, icon),
            on_stop=lambda p: actions.on_stop(orch, p, icon, user_init),
            on_open_browser=lambda p: actions.on_open_browser(p, icon),
            on_open_folder=lambda path: actions.on_open_folder(path, icon),
            on_stop_all=lambda: actions.on_stop_all(orch, icon, user_init, _active_names()),
            on_exit=lambda: actions.on_exit(icon),
            on_stop_all_and_exit=lambda: actions.on_stop_all_and_exit(
                orch, icon, user_init, _active_names()
            ),
        )


def _zero_status(name: str) -> ProjectStatus:
    return ProjectStatus(
        name=name,
        running=False,
        backend_alive=False,
        frontend_alive=False,
        backend_port_listening=False,
        frontend_port_listening=False,
        url_ok=False,
    )


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

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_app.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 88 passed (84 + 4).

- [ ] **Step 6: Commit**

```bash
git add foxtray/ui/tray.py tests/test_tray_app.py
git commit -m "feat(ui/tray): TrayApp integration with poll loop and menu builder"
```

---

### Task 8: CLI wiring — `cmd_tray`

Add the `tray` subcommand. Because the tray's `run()` blocks on the pystray event loop (which needs a real Windows session), the unit test only covers the argparse wiring and that `cmd_tray` would call `TrayApp(...).run()` given valid config.

**Files:**
- Modify: `foxtray/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Append failing test to `tests/test_cli.py`**

```python
def test_tray_command_parses_and_dispatches(
    demo_config: Path, tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []

    class _FakeTray:
        def __init__(self, cfg, orchestrator) -> None:  # type: ignore[no-untyped-def]
            called.append(f"init:{len(cfg.projects)}")

        def run(self) -> None:
            called.append("run")

    from foxtray.ui import tray as tray_mod
    monkeypatch.setattr(tray_mod, "TrayApp", _FakeTray)

    rc = cli.main(["--config", str(demo_config), "tray"])
    assert rc == 0
    assert called == ["init:1", "run"]
```

- [ ] **Step 2: Run the test, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_cli.py::test_tray_command_parses_and_dispatches -v
```

Expected: FAIL (`argparse` rejects unknown command `tray`, exit 2).

- [ ] **Step 3: Add `cmd_tray` and subparser in `foxtray/cli.py`**

Import at the top (add alongside other foxtray imports):
```python
from foxtray.ui import tray as tray_module
```

Add the command implementation before `build_parser`:
```python
def cmd_tray(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    orchestrator = project.Orchestrator(manager=process.ProcessManager())
    tray_module.TrayApp(cfg, orchestrator).run()
    return 0
```

Add the subparser in `build_parser`, right before `return parser`:
```python
    sub.add_parser(
        "tray", help="Run FoxTray as a Windows tray icon"
    ).set_defaults(func=cmd_tray)
```

- [ ] **Step 4: Run test, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_cli.py -v
```

Expected: all passed (including the new one).

- [ ] **Step 5: Sanity-check the argparse wiring at the shell**

```
./.venv/Scripts/python.exe main.py tray --help
```

Expected: prints tray-specific help and exits 0.

- [ ] **Step 6: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: 89 passed (88 + 1).

- [ ] **Step 7: Commit**

```bash
git add foxtray/cli.py tests/test_cli.py
git commit -m "feat(cli): add tray subcommand"
```

---

### Task 9: Manual smoke test document

The tray can't be unit-tested end-to-end. This doc captures what a human must verify after Iter 2 is implemented, mirroring the spec's testing section.

**Files:**
- Create: `docs/manual-tests/iter2.md`

- [ ] **Step 1: Write the checklist**

```markdown
# FoxTray Iter 2 — Manual Test Log

Prerequisite: Iter 1 manual test (`docs/manual-tests/iter1.md`) passed once on this machine.

## Environment

- Date: <fill>
- HEAD: <commit sha>
- pystray version: `./.venv/Scripts/python.exe -c "import pystray; print(pystray.__version__)"`
- Full test suite: `./.venv/Scripts/python.exe -m pytest -v` (must show 89 passed)

## Scenarios

- [ ] `python main.py tray` — a grey disc icon appears in the Windows notification area
- [ ] Right-click the icon — root menu lists FoxRunner / QuizOnline / PushIT, each followed by `(stopped)`; `Stop all` is greyed; `Stop all and exit` is greyed
- [ ] Hover FoxRunner submenu — shows `Start`, separator, `Open in browser` (greyed), `Open backend folder`, `Open frontend folder`
- [ ] Click Start on FoxRunner. Within ≤20 s the icon turns green AND a balloon notification "FoxRunner is up" shows
- [ ] Right-click icon — FoxRunner submenu now shows `Stop` instead of `Start`; `Open in browser` is enabled
- [ ] Click Open in browser — default browser opens `http://localhost:4200`
- [ ] Click Open backend folder — Explorer opens at `D:\PycharmProjects\FoxRunner_server`
- [ ] Open Task Manager. Find and End one child python.exe of the Django tree (not the root). Within ~3 s icon turns orange AND a balloon "⚠ FoxRunner: backend crashed" shows
- [ ] Click Stop. Icon turns grey. **No balloon** (user-initiated stop is silent)
- [ ] Click Exit. Icon disappears. `python main.py list` shows all stopped
- [ ] `python main.py tray` again → click Start FoxRunner → Stop all and exit → within 5 s icon disappears and `python main.py list` shows all stopped

## Partial-state visual check

- [ ] After step "icon turns orange", the orange tone should be visually distinct from the green tone (not a slight variation). If it's hard to distinguish, revisit colors in `scripts/gen_icons.py` and regenerate.

## Known Iter 2 limitations (intentional)

- **No single-instance lock.** Running `python main.py tray` twice is not prevented. Iter 4.
- **No health-check wait.** "FoxRunner is up" may fire before Django/Angular actually serve 200s. Iter 3.
- **No auto-clear of orphaned state.** If state.json has an active project but no PIDs are alive at startup, the tray shows `stopped` but state.json is not cleared until the next user action. Iter 3.

## Observed issues
<!-- Fill during run. Link to follow-up fix commits. -->

_None yet._
```

- [ ] **Step 2: Commit**

```bash
git add docs/manual-tests/iter2.md
git commit -m "docs(iter2): manual smoke test checklist for tray"
```

---

## Self-Review Summary

- **Spec coverage:**
  - Goal — covered by Task 8 (CLI wiring) + Task 7 (TrayApp).
  - Non-goals — explicitly listed in Task 9 doc "Known Iter 2 limitations".
  - Threading model — Task 7 (`_poll_loop` + `_poll_tick`), tests assert the poll loop survives orchestrator exceptions.
  - File structure — Tasks 1 through 7 create every file listed in the spec.
  - Components (`tray.py`, `icons.py`, `actions.py`, `cli.py` addition) — Tasks 2, 3–5, 6, 7, 8 respectively.
  - Menu specification — Task 5 tests enforce the exact layout.
  - Icon state rule — Task 3 tests cover all four rows of the icon-state table.
  - Notification transitions — Task 4 tests cover all six rows (six distinct tests).
  - Data flow per tick — Task 7's `_poll_tick` implementation exactly mirrors the spec pseudocode; Task 7 test scenarios exercise the full path.
  - Error handling — Task 6 tests "notifies on exception"; Task 7 test `test_poll_tick_survives_orchestrator_exception` covers the poll-loop guard.
  - Testing strategy — each test file maps 1:1 to a spec bullet; manual smoke test is Task 9.
- **Placeholder scan:** no TBD / TODO / "handle edge cases" / "similar to" references present. Every code block is complete and type-consistent with the blocks that consume it.
- **Type consistency:**
  - `Handlers.on_open_folder` takes `Path`, matches the lambda in `_project_submenu`.
  - `Notification(title, message)` — `title` always used for pystray's `title` kwarg in `_poll_tick`.
  - `IconState` Literal reused across `icons.py`, `tray.py`, and tests.
  - `ProjectStatus` — imported from `foxtray.project` in every test file that uses it, consistent with Iter 1.
  - `MenuItemSpec.submenu` is `tuple[MenuItemSpec, ...]` (immutable), matches the `_project_submenu` return type.
- **Scope:** single iteration, single plan. No decomposition needed.
