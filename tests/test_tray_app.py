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


def _status(*, backend_alive: bool = False, frontend_alive: bool = False, url_ok: bool = False) -> ProjectStatus:
    return ProjectStatus(
        name="X",
        running=backend_alive and frontend_alive,
        backend_alive=backend_alive,
        frontend_alive=frontend_alive,
        backend_port_listening=False,
        frontend_port_listening=False,
        url_ok=url_ok,
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
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)},
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
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)},
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
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)},
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
