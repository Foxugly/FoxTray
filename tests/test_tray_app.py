from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from foxtray import config, state
from foxtray.project import ProjectStatus
from foxtray.ui import icons, tray


class _StubProcessManager:
    def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
        pass

    def start(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("ProcessManager.start unused in tests")


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


def _status(
    *,
    has_frontend: bool = True,
    backend_alive: bool = False,
    frontend_alive: bool = False,
    url_ok: bool = False,
) -> ProjectStatus:
    return ProjectStatus(
        name="X",
        has_frontend=has_frontend,
        running=backend_alive and (frontend_alive or not has_frontend),
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
    title: str = "FoxTray"
    menu_updated: int = 0

    def notify(self, message: str, title: str = "") -> None:
        self.notifications.append((title, message))

    def stop(self) -> None:
        self.stopped = True

    def update_menu(self) -> None:
        self.menu_updated += 1


@dataclass
class _FakeOrchestrator:
    next_statuses: dict[str, ProjectStatus] = field(default_factory=dict)
    next_active: state.ActiveProject | None = None
    pending_starts: set[str] = field(default_factory=set)

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
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon  # inject fake
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        tray.actions,
        "notify_project_up",
        lambda project, icon: recorded.append((project.name, project.url)),
    )

    # Simulate CLI having just set state to active A
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # Keep fake PIDs alive so orphan-clear is a no-op inside this tick.
    monkeypatch.setattr("foxtray.state.psutil.pid_exists", lambda pid: True)

    app._poll_tick()

    assert recorded == [("A", "http://localhost:4200")]
    assert icon.notifications == []
    assert icon.icon is icons.load("running")


def test_poll_tick_no_notifications_on_stable_state(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)},
    )
    icon = _FakeIcon(icon=icons.load("running"))
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # Keep fake PIDs alive so orphan-clear is a no-op across both ticks.
    monkeypatch.setattr("foxtray.state.psutil.pid_exists", lambda pid: True)

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
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # Keep fake PIDs alive so orphan-clear is a no-op across both ticks.
    monkeypatch.setattr("foxtray.state.psutil.pid_exists", lambda pid: True)

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
    app = tray.TrayApp(cfg, _Broken(), _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon

    # Must not raise.
    app._poll_tick()

    # Icon unchanged; no notifications fired.
    assert icon.icon is icons.load("stopped")
    assert icon.notifications == []


def test_run_calls_clear_if_orphaned(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    from foxtray import state as state_mod
    called: list[bool] = []
    monkeypatch.setattr(state_mod, "clear_if_orphaned", lambda: called.append(True) or False)

    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]

    # We can't actually run pystray in a test. Monkeypatch pystray.Icon to a stub
    # that immediately returns from .run() so TrayApp.run() finishes.
    import pystray
    class _StubIcon:
        def __init__(self, **kwargs): self._kwargs = kwargs
        def run(self): return None
        def notify(self, message, title=""): pass
        icon = None
    monkeypatch.setattr(pystray, "Icon", _StubIcon)

    app.run()
    # clear_if_orphaned is called at least once from run(); the poller may also
    # fire a tick before the stop event is set, causing a second call — both are fine.
    assert len(called) >= 1


def test_poll_tick_clears_orphan_at_end(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    # Both PIDs dead: status() returns both_alive=False, url_ok=False
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    icon = _FakeIcon(icon=icons.load("running"))  # starts as running
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon
    # Seed prev_active so _poll_tick sees a running → stopped transition
    app._prev_active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    app._prev_statuses = {"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    app._prev_icon_state = "running"

    # state.json says A is still active with dead PIDs
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # pid_exists returns False for both → clear_if_orphaned will fire
    monkeypatch.setattr("foxtray.state.psutil.pid_exists", lambda pid: False)

    app._poll_tick()

    # The "stopped unexpectedly" balloon should have fired
    assert any("stopped unexpectedly" in n[1] for n in icon.notifications)
    # state.json.active is now None
    assert state.load().active is None
    # _prev_active was reset after orphan clear
    assert app._prev_active is None


def test_poll_tick_passes_pending_starts_into_compute_transitions(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)},
    )
    orch.pending_starts.add("A")
    icon = _FakeIcon(icon=icons.load("stopped"))
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon
    recorded: list[str] = []
    monkeypatch.setattr(
        tray.actions,
        "notify_project_up",
        lambda project, icon: recorded.append(project.url),
    )
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # pid_exists True so status() considers procs alive
    monkeypatch.setattr("foxtray.state.psutil.pid_exists", lambda pid: True)
    monkeypatch.setattr("foxtray.project.psutil.pid_exists", lambda pid: True)

    app._poll_tick()

    # Should have fired "A is up" (stopped → running, pending_starts contained A)
    assert recorded == ["http://localhost:4200"]
    assert icon.notifications == []
    # pending_starts consumed
    assert orch.pending_starts == set()


def test_trayapp_creates_task_manager_with_kill_tree_from_process_manager(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})

    class _StubProcessManager:
        def __init__(self) -> None:
            self.kills: list[int] = []

        def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
            self.kills.append(pid)

        # ProcessManager.start is not called by TaskManager construction
        def start(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError("should not be called")

    pm = _StubProcessManager()
    app = tray.TrayApp(cfg, orch, pm)  # type: ignore[arg-type]
    assert app._task_manager is not None


def test_on_task_complete_fires_done_balloon_on_zero_exit(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})

    class _StubProcessManager:
        def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
            pass

        def start(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError

    icon = _FakeIcon(icon=None)
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon  # type: ignore[assignment]

    app._on_task_complete("task:A:Migrate", 0)
    assert any(message == "Migrate done" for _t, message in icon.notifications)


def test_on_task_complete_fires_failed_balloon_on_nonzero(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})

    class _StubProcessManager:
        def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
            pass

        def start(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError

    icon = _FakeIcon(icon=None)
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon  # type: ignore[assignment]

    app._on_task_complete("script:Git pull", 2)
    assert any("Git pull failed" in message for _t, message in icon.notifications)


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


def test_run_schedules_auto_start_when_configured(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(
        projects=[_project("A")],
        auto_start="A",
    )

    started: list[str] = []

    class _OrchStub:
        pending_starts: set[str] = set()
        def start(self, project): started.append(project.name)
        def stop(self, name): ...
        def stop_all(self): ...
        def status(self, project): ...

    import pystray
    class _StubIcon:
        def __init__(self, **kwargs): pass
        def run(self): return None
        def notify(self, message, title=""): pass
        icon = None
        title = "FoxTray"

    monkeypatch.setattr(pystray, "Icon", _StubIcon)

    app = tray.TrayApp(cfg, _OrchStub(), _StubProcessManager())  # type: ignore[arg-type]
    app.run()

    # The auto-start thread is a daemon; give it a moment to run
    import time
    deadline = time.monotonic() + 1.0
    while not started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started == ["A"]


def test_run_skips_auto_start_when_active_project_exists(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(
        projects=[_project("A")],
        auto_start="A",
    )
    # Seed an active project
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))

    started: list[str] = []

    class _OrchStub:
        pending_starts: set[str] = set()
        def start(self, project): started.append(project.name)
        def stop(self, name): ...
        def stop_all(self): ...
        def status(self, project): ...

    import pystray
    class _StubIcon:
        def __init__(self, **kwargs): pass
        def run(self): return None
        def notify(self, message, title=""): pass
        icon = None
        title = "FoxTray"
    monkeypatch.setattr(pystray, "Icon", _StubIcon)
    # Make clear_if_orphaned think the PIDs are alive so state is preserved
    monkeypatch.setattr("foxtray.state.psutil.pid_exists", lambda pid: True)

    app = tray.TrayApp(cfg, _OrchStub(), _StubProcessManager())  # type: ignore[arg-type]
    app.run()

    import time
    time.sleep(0.3)
    assert started == []


def test_reload_config_replaces_cfg_and_updates_menu(
    tmp_appdata: Path, tmp_path: Path
) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
projects:
  - name: B
    url: http://localhost:8000
    backend:
      path: D:\\\\p\\\\B\\\\back
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
""",
        encoding="utf-8",
    )
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    icon = _FakeIcon(icon=icons.load("stopped"))
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), config_path=cfg_path)  # type: ignore[arg-type]
    app._icon = icon

    app._reload_config()

    assert [p.name for p in app._cfg.projects] == ["B"]
    assert [p.name for p in app._orchestrator._cfg.projects] == ["B"]
    assert icon.menu_updated == 1
