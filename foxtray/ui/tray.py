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
