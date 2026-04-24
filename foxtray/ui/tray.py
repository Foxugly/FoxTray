"""Tray UI orchestration: dataclasses, pure helpers, TrayApp integration."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pystray

from foxtray import config as config_mod
from foxtray import paths
from foxtray import state as state_mod
from foxtray import tasks
from foxtray.process import ProcessManager
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
    on_run_task: Callable[[config_mod.Project, config_mod.Task], None]
    on_run_script: Callable[[config_mod.Script], None]
    on_about: Callable[[], None]
    on_restart: Callable[[config_mod.Project], None]
    on_open_logs_folder: Callable[[], None]
    on_copy_url: Callable[[str], None]
    on_open_log: Callable[[Path], None]


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
    pending_starts: set[str],
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
            pending_starts.discard(name)
        elif prev_state == "stopped" and curr_state == "partial":
            if name not in pending_starts:
                notifications.append(
                    Notification("FoxTray", f"{name} started but one component failed")
                )
            # else: silent — we're still booting
        elif prev_state == "running" and curr_state == "partial":
            dead = _dead_component(prev_statuses[name], curr_statuses[name])
            notifications.append(
                Notification("FoxTray", f"⚠ {name}: {dead} crashed")
            )
        elif prev_state == "partial" and curr_state == "running":
            if name in pending_starts:
                notifications.append(Notification("FoxTray", f"{name} is up"))
                pending_starts.discard(name)
            else:
                notifications.append(Notification("FoxTray", f"{name} recovered"))
        elif prev_state == "running" and curr_state == "stopped":
            if name not in suppressed:
                notifications.append(
                    Notification("FoxTray", f"⚠ {name} stopped unexpectedly")
                )
        elif prev_state == "partial" and curr_state == "stopped":
            if name in pending_starts:
                notifications.append(
                    Notification("FoxTray", f"⚠ {name} failed to start")
                )
                pending_starts.discard(name)
            elif name not in suppressed:
                notifications.append(
                    Notification("FoxTray", f"⚠ {name} fully stopped")
                )

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
        MenuItemSpec(
            text="Open backend log",
            action=lambda p=paths.log_file(project.name, "backend"): handlers.on_open_log(p),
        ),
        MenuItemSpec(
            text="Open frontend log",
            action=lambda p=paths.log_file(project.name, "frontend"): handlers.on_open_log(p),
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


def _task_spec(
    project: config_mod.Project,
    task: config_mod.Task,
    handlers: Handlers,
    running_tasks: set[str],
) -> MenuItemSpec:
    key = f"task:{project.name}:{task.name}"
    if key in running_tasks:
        return MenuItemSpec(
            text=f"{task.name} (running…)", enabled=False,
        )
    return MenuItemSpec(
        text=task.name,
        action=lambda p=project, t=task: handlers.on_run_task(p, t),
    )


def build_menu_items(
    cfg: config_mod.Config,
    active: state_mod.ActiveProject | None,
    statuses: dict[str, ProjectStatus],
    handlers: Handlers,
    running_tasks: set[str],
) -> list[MenuItemSpec]:
    items: list[MenuItemSpec] = []
    for project in cfg.projects:
        proj_state = _project_icon_state(project.name, active, statuses.get(project.name))
        label = _project_label(proj_state)
        items.append(
            MenuItemSpec(
                text=f"{project.name} ({label})",
                submenu=_project_submenu(project, proj_state, handlers, running_tasks),
            )
        )
    if cfg.scripts:
        items.append(MenuItemSpec(text="", separator=True))
        script_specs = tuple(
            _script_spec(script, handlers, running_tasks) for script in cfg.scripts
        )
        items.append(MenuItemSpec(text="Scripts", submenu=script_specs))
    items.append(MenuItemSpec(text="", separator=True))
    items.append(MenuItemSpec(
        text="Open logs folder",
        action=handlers.on_open_logs_folder,
    ))
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
    items.append(MenuItemSpec(text="", separator=True))
    items.append(MenuItemSpec(text="About", action=handlers.on_about))
    return items


def _script_spec(
    script: config_mod.Script,
    handlers: Handlers,
    running_tasks: set[str],
) -> MenuItemSpec:
    key = f"script:{script.name}"
    if key in running_tasks:
        return MenuItemSpec(
            text=f"{script.name} (running…)", enabled=False,
        )
    return MenuItemSpec(
        text=script.name,
        action=lambda s=script: handlers.on_run_script(s),
    )


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


class TrayApp:
    """Integrates pystray + 3s poller on top of the pure helpers above."""

    def __init__(
        self,
        cfg: config_mod.Config,
        orchestrator: Orchestrator,
        process_manager: ProcessManager,
    ) -> None:
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
        self._task_manager = tasks.TaskManager(
            kill_tree=process_manager.kill_tree,
            on_complete=self._on_task_complete,
        )

    def run(self) -> None:
        state_mod.clear_if_orphaned()
        self._icon = pystray.Icon(
            name="FoxTray",
            icon=icons.load("stopped"),
            title="FoxTray",
            menu=pystray.Menu(self._build_menu),
        )
        poller = threading.Thread(target=self._poll_loop, name="foxtray-poller", daemon=True)
        poller.start()
        self._schedule_auto_start()
        try:
            self._icon.run()
        finally:
            self._stop_event.set()
            poller.join(timeout=_POLL_INTERVAL_S + 1.0)

    def _schedule_auto_start(self) -> None:
        if self._cfg.auto_start is None:
            return
        if state_mod.load().active is not None:
            return
        project = next(
            (p for p in self._cfg.projects if p.name == self._cfg.auto_start), None
        )
        if project is None:
            log.warning("auto_start references unknown project %r", self._cfg.auto_start)
            return
        threading.Thread(
            target=self._auto_start_project, args=(project,),
            name=f"auto-start-{project.name}", daemon=True,
        ).start()

    def _auto_start_project(self, project: config_mod.Project) -> None:
        self._orchestrator.pending_starts.add(project.name)
        try:
            self._orchestrator.start(project)
        except Exception:  # noqa: BLE001
            self._orchestrator.pending_starts.discard(project.name)
            log.warning("auto_start failed for %s", project.name, exc_info=True)

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
                suppressed=suppressed,
                pending_starts=self._orchestrator.pending_starts,
            ):
                self._icon.notify(note.message, title=note.title)

            new_icon_state = compute_icon_state(curr_active, curr_statuses)
            if new_icon_state != self._prev_icon_state:
                self._icon.icon = icons.load(new_icon_state)
                self._prev_icon_state = new_icon_state

            self._prev_active = curr_active
            self._prev_statuses = curr_statuses

            # Orphan reconciliation — runs AFTER transition computation so that the
            # "stopped unexpectedly" balloon still fires for the dying tick.
            if state_mod.clear_if_orphaned():
                log.info(
                    "poll tick cleared orphaned state for %s",
                    curr_active.name if curr_active else "?",
                )
                self._prev_active = None

            try:
                self._icon.title = _tooltip_text(curr_active, curr_statuses)
            except Exception:  # noqa: BLE001
                log.warning("tooltip update failed", exc_info=True)
        except Exception:  # noqa: BLE001 — poll loop must never die
            log.warning("poll tick failed", exc_info=True)

    def _on_task_complete(self, key: str, exit_code: int) -> None:
        if self._icon is None:
            return
        display_name = key.rsplit(":", 1)[-1]
        try:
            if exit_code == 0:
                self._icon.notify(f"{display_name} done", title="FoxTray")
            else:
                log_path = paths.task_log_file(key)
                self._icon.notify(
                    f"⚠ {display_name} failed — see {log_path}",
                    title="FoxTray",
                )
        except Exception:
            log.warning("notify after task %s completion failed", key, exc_info=True)
        try:
            self._icon.update_menu()
        except Exception:
            log.warning("update_menu after task %s failed", key, exc_info=True)

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
        specs = build_menu_items(
            self._cfg, active, statuses, handlers,
            running_tasks=self._task_manager.running_keys(),
        )
        return tuple(_spec_to_pystray(s) for s in specs)

    def _handlers(self) -> Handlers:
        icon = self._icon
        assert icon is not None
        orch = self._orchestrator
        tm = self._task_manager

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
            on_exit=lambda: actions.on_exit(icon, tm),
            on_stop_all_and_exit=lambda: actions.on_stop_all_and_exit(
                orch, icon, self._user_initiated_stop, _active_names(), tm,
            ),
            on_run_task=lambda p, t: actions.on_run_task(tm, p, t, icon),
            on_run_script=lambda s: actions.on_run_script(tm, s, icon),
            on_about=lambda: actions.on_about(icon),
            on_restart=lambda p: actions.on_restart(orch, p, icon, self._user_initiated_stop),
            on_open_logs_folder=lambda: actions.on_open_logs_folder(icon),
            on_copy_url=lambda url: actions.on_copy_url(url, icon),
            on_open_log=lambda path: actions.on_open_log(path, icon),
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
