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


class _StubToastManager:
    """No-op replacement so tests never spin up a real Tk root."""
    def __init__(self) -> None:
        self.shown: list[tuple[str, str, str]] = []

    def start(self, timeout: float = 3.0) -> None:
        pass

    def stop(self, timeout: float = 2.0) -> None:
        pass

    def show(self, title: str, message: str, url: str) -> None:
        self.shown.append((title, message, url))


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
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = icon  # inject fake
    recorded: list[tuple[str, str]] = []
    monkeypatch.setattr(
        tray.actions,
        "notify_project_up",
        lambda project, icon, show_toast=None: recorded.append((project.name, project.url)),
    )

    # Simulate CLI having just set state to active A
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # Keep fake PIDs alive so orphan-clear is a no-op inside this tick.
    monkeypatch.setattr("foxtray.state.pid_alive", lambda pid, ctime: True)

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
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = icon
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # Keep fake PIDs alive so orphan-clear is a no-op across both ticks.
    monkeypatch.setattr("foxtray.state.pid_alive", lambda pid, ctime: True)

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
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = icon
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # Keep fake PIDs alive so orphan-clear is a no-op across both ticks.
    monkeypatch.setattr("foxtray.state.pid_alive", lambda pid, ctime: True)

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
    app = tray.TrayApp(cfg, _Broken(), _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
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
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]

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
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
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
    monkeypatch.setattr("foxtray.state.pid_alive", lambda pid, ctime: False)

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
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = icon
    recorded: list[str] = []
    monkeypatch.setattr(
        tray.actions,
        "notify_project_up",
        lambda project, icon, show_toast=None: recorded.append(project.url),
    )
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # pid_exists True so status() considers procs alive
    monkeypatch.setattr("foxtray.state.pid_alive", lambda pid, ctime: True)
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
    app = tray.TrayApp(cfg, orch, pm, toast_manager=_StubToastManager())  # type: ignore[arg-type]
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
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
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
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
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
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = icon
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    monkeypatch.setattr("foxtray.state.pid_alive", lambda pid, ctime: True)
    monkeypatch.setattr("foxtray.project.psutil.pid_exists", lambda pid: True)

    app._poll_tick()

    assert hasattr(icon, "title")
    assert "RUNNING" in icon.title
    assert "A" in icon.title


def _auto_project(name: str) -> config.Project:
    import dataclasses
    return dataclasses.replace(_project(name), auto_restart=True)


def test_poll_tick_auto_restarts_after_healthy_crash(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_auto_project("A")])
    orch = _FakeOrchestrator(
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)},
    )
    icon = _FakeIcon(icon=icons.load("running"))
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = icon
    restarts: list[str] = []
    monkeypatch.setattr(
        tray.actions, "on_restart",
        lambda o, p, i, u, on_done=None: restarts.append(p.name),
    )
    monkeypatch.setattr(
        tray.actions, "notify_project_up",
        lambda project, icon, show_toast=None: None,
    )
    state.save(state.State(active=state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)))
    monkeypatch.setattr("foxtray.state.pid_alive", lambda pid, ctime: True)
    monkeypatch.setattr("foxtray.project.psutil.pid_exists", lambda pid: True)

    app._poll_tick()  # healthy baseline
    orch.next_statuses["A"] = _status(backend_alive=True, frontend_alive=False)  # frontend crash
    app._poll_tick()

    assert restarts == ["A"]
    assert any("auto-restarting A" in message for _t, message in icon.notifications)


def test_poll_tick_auto_restart_gives_up_over_budget(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_auto_project("A")])
    orch = _FakeOrchestrator(
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)},
    )
    icon = _FakeIcon(icon=icons.load("running"))
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = icon
    app._clock = lambda: 1000.0
    app._auto_restart_history["A"] = [999.0, 999.5, 999.8]  # 3 within the 120 s window
    restarts: list[str] = []
    monkeypatch.setattr(tray.actions, "on_restart", lambda *a, **k: restarts.append("x"))
    monkeypatch.setattr(
        tray.actions, "notify_project_up",
        lambda project, icon, show_toast=None: None,
    )
    state.save(state.State(active=state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)))
    monkeypatch.setattr("foxtray.state.pid_alive", lambda pid, ctime: True)
    monkeypatch.setattr("foxtray.project.psutil.pid_exists", lambda pid: True)

    app._poll_tick()  # healthy baseline
    orch.next_statuses["A"] = _status(backend_alive=True, frontend_alive=False)
    app._poll_tick()

    assert restarts == []
    assert any("giving up" in message for _t, message in icon.notifications)


def test_poll_tick_throttles_repeated_identical_crash(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])  # no auto_restart
    orch = _FakeOrchestrator(
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)},
    )
    icon = _FakeIcon(icon=icons.load("running"))
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = icon
    clock = {"v": 0.0}
    app._clock = lambda: clock["v"]
    monkeypatch.setattr(
        tray.actions, "notify_project_up",
        lambda project, icon, show_toast=None: None,
    )
    state.save(state.State(active=state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)))
    monkeypatch.setattr("foxtray.state.pid_alive", lambda pid, ctime: True)
    monkeypatch.setattr("foxtray.project.psutil.pid_exists", lambda pid: True)

    app._poll_tick()  # healthy
    orch.next_statuses["A"] = _status(backend_alive=True, frontend_alive=False)
    app._poll_tick()  # crash #1 at t=0 → fires
    clock["v"] = 5.0
    orch.next_statuses["A"] = _status(backend_alive=True, frontend_alive=True, url_ok=True)
    app._poll_tick()  # recover at t=5
    clock["v"] = 10.0
    orch.next_statuses["A"] = _status(backend_alive=True, frontend_alive=False)
    app._poll_tick()  # crash #2 (identical) at t=10 (<15 s) → suppressed

    crashes = [m for _t, m in icon.notifications if "frontend crashed" in m]
    assert len(crashes) == 1


def test_request_refresh_sets_wake_event(tmp_appdata: Path) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    assert not app._wake_event.is_set()
    app.request_refresh()
    assert app._wake_event.is_set()


def test_stop_handler_wakes_poller_for_immediate_refresh(tmp_appdata: Path) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = _FakeIcon(icon=icons.load("running"))
    app._handlers().on_stop(_project("A"))
    assert app._wake_event.is_set()


def test_start_handler_wakes_poller_for_immediate_refresh(tmp_appdata: Path) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = _FakeIcon(icon=icons.load("stopped"))
    app._handlers().on_start(_project("A"))
    assert app._wake_event.is_set()


def test_stop_all_handler_wakes_poller_for_immediate_refresh(tmp_appdata: Path) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = _FakeIcon(icon=icons.load("running"))
    app._handlers().on_stop_all()
    assert app._wake_event.is_set()


def test_restart_handler_wakes_poller_after_completion(tmp_appdata: Path) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = _FakeIcon(icon=icons.load("running"))
    app._handlers().on_restart(_project("A"))
    import time
    deadline = time.monotonic() + 1.0
    while not app._wake_event.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert app._wake_event.is_set()


def test_poll_loop_ticks_immediately_on_wake(tmp_appdata: Path, monkeypatch: Any) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = _FakeIcon(icon=icons.load("stopped"))

    ticks: list[int] = []

    def fake_tick() -> None:
        ticks.append(1)
        if len(ticks) >= 2:
            # Ask the loop to exit; set wake too so the wait returns at once,
            # keeping the test off the 3 s poll interval.
            app._stop_event.set()
            app._wake_event.set()

    monkeypatch.setattr(app, "_poll_tick", fake_tick)
    # Pre-arm: without early-wake support the loop would block a full poll
    # interval after the first tick and this test would hang ~3 s.
    app._wake_event.set()

    import time
    start = time.monotonic()
    app._poll_loop()
    elapsed = time.monotonic() - start

    assert len(ticks) == 2
    assert elapsed < 1.0  # both ticks happened without waiting out _POLL_INTERVAL_S


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

    app = tray.TrayApp(cfg, _OrchStub(), _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
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
    monkeypatch.setattr("foxtray.state.pid_alive", lambda pid, ctime: True)

    app = tray.TrayApp(cfg, _OrchStub(), _StubProcessManager(), toast_manager=_StubToastManager())  # type: ignore[arg-type]
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
    app = tray.TrayApp(cfg, orch, _StubProcessManager(), config_path=cfg_path, toast_manager=_StubToastManager())  # type: ignore[arg-type]
    app._icon = icon

    app._reload_config()

    assert [p.name for p in app._cfg.projects] == ["B"]
    assert [p.name for p in app._orchestrator._cfg.projects] == ["B"]
    assert icon.menu_updated == 1
