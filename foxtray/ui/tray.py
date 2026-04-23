"""Tray UI orchestration: dataclasses, pure helpers, TrayApp integration."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pystray

from foxtray import config as config_mod
from foxtray import state as state_mod
from foxtray.project import Orchestrator, ProjectStatus
from foxtray.ui import actions, icons
from foxtray.ui.icons import IconState

log = logging.getLogger(__name__)

_POLL_INTERVAL_S = 3.0


@dataclass(frozen=True)
class Notification:
    title: str
    message: str


@dataclass(frozen=True)
class MenuItemSpec:
    text: str
    action: Callable[[], None] | None = None
    enabled: bool = True
    submenu: tuple[MenuItemSpec, ...] = field(default_factory=tuple)
    separator: bool = False


@dataclass
class Handlers:
    """Menu-action callbacks. Intentionally mutable: TrayApp rebuilds a fresh
    instance per menu paint, so callers should not cache instances."""

    on_start: Callable[[config_mod.Project], None]
    on_stop: Callable[[config_mod.Project], None]
    on_open_browser: Callable[[config_mod.Project], None]
    on_open_folder: Callable[[Path], None]
    on_stop_all: Callable[[], None]
    on_exit: Callable[[], None]
    on_stop_all_and_exit: Callable[[], None]


def _status_to_icon_state(status: ProjectStatus) -> IconState:
    if status.backend_alive and status.frontend_alive and status.url_ok:
        return "running"
    if status.backend_alive or status.frontend_alive:
        return "partial"
    return "stopped"


def compute_icon_state(
    active: state_mod.ActiveProject | None,
    statuses: dict[str, ProjectStatus],
) -> IconState:
    if active is None:
        return "stopped"
    status = statuses.get(active.name)
    if status is None:
        return "stopped"
    return _status_to_icon_state(status)


def _project_icon_state(
    name: str,
    active: state_mod.ActiveProject | None,
    status: ProjectStatus | None,
) -> IconState:
    if active is None or active.name != name or status is None:
        return "stopped"
    return _status_to_icon_state(status)


def _dead_component(prev: ProjectStatus, curr: ProjectStatus) -> str:
    if prev.backend_alive and not curr.backend_alive:
        return "backend"
    if prev.frontend_alive and not curr.frontend_alive:
        return "frontend"
    # Called only when caller has already determined a running→partial transition,
    # which mathematically requires exactly one component to have died. Reaching
    # here means the caller violated its invariant.
    raise AssertionError(
        "_dead_component called without a single-component death; "
        f"prev(backend={prev.backend_alive}, frontend={prev.frontend_alive}) "
        f"curr(backend={curr.backend_alive}, frontend={curr.frontend_alive})"
    )


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
        # Single guard around the ENTIRE tick body: reading state, calling the
        # orchestrator, AND the pystray mutations (notify / icon.icon) can all
        # raise. Any uncaught exception here would kill the daemon thread
        # silently, freezing the icon.
        try:
            curr_active = state_mod.load().active
            curr_statuses = {
                p.name: self._orchestrator.status(p) for p in self._cfg.projects
            }

            # Atomic swap: any handler calling .add(name) on the old set before
            # we reassign goes into `suppressed`; any add after the reassign
            # goes into the fresh set and survives to the next tick.
            suppressed = self._user_initiated_stop
            self._user_initiated_stop = set()

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
        except Exception:  # noqa: BLE001 — poll loop must never die
            log.warning("poll tick failed", exc_info=True)

    def _build_menu(self) -> tuple[pystray.MenuItem, ...]:
        # pystray only calls _build_menu after icon.run() has set self._icon,
        # so no None-guard needed here. Transient errors during build fall
        # through to a disabled "FoxTray error" placeholder item; the next
        # menu open re-runs this method and recovers automatically.
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

        def _active_names() -> list[str]:
            a = state_mod.load().active
            return [a.name] if a is not None else []

        # Lambdas read self._user_initiated_stop at click time, not menu-open
        # time. _poll_tick may atomically swap the set between menu-open and
        # click; capturing the old reference would silently drop the user's
        # stop-intent flag.
        return Handlers(
            on_start=lambda p: actions.on_start(orch, p, icon),
            on_stop=lambda p: actions.on_stop(orch, p, icon, self._user_initiated_stop),
            on_open_browser=lambda p: actions.on_open_browser(p, icon),
            on_open_folder=lambda path: actions.on_open_folder(path, icon),
            on_stop_all=lambda: actions.on_stop_all(
                orch, icon, self._user_initiated_stop, _active_names()
            ),
            on_exit=lambda: actions.on_exit(icon),
            on_stop_all_and_exit=lambda: actions.on_stop_all_and_exit(
                orch, icon, self._user_initiated_stop, _active_names()
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
