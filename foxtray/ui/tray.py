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
    if status.backend_alive and status.frontend_alive:
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
