import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil
import pytest

from foxtray import config, process, project, state


@dataclass
class _FakeManager:
    killed: list[int] = field(default_factory=list)
    started: list[dict[str, Any]] = field(default_factory=list)
    fake_pid: int = 42

    def start(self, *, project: str, component: str, command: list[str], cwd: Path):
        self.started.append(
            {"project": project, "component": component, "command": command, "cwd": cwd}
        )
        popen = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
        )
        return popen

    def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
        self.killed.append(pid)


def _cfg_with(project: config.Project) -> config.Config:
    return config.Config(projects=[project])


@pytest.fixture
def sample_project(tmp_path: Path) -> config.Project:
    return config.Project(
        name="Demo",
        url="http://localhost:4200",
        backend=config.Backend(
            path=tmp_path, venv=".venv", command="python manage.py runserver 8000", port=8000
        ),
        frontend=config.Frontend(
            path=tmp_path, command="ng serve --port 4200", port=4200
        ),
    )


def test_start_records_pids_in_state(tmp_appdata: Path, sample_project: config.Project) -> None:
    manager = _FakeManager()
    orchestrator = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))

    orchestrator.start(sample_project)

    active = state.load().active
    assert active is not None
    assert active.name == "Demo"
    assert active.backend_pid > 0
    assert active.frontend_pid > 0

    # Cleanup: our fake started real sleep() processes, kill them via psutil.
    for pid in (active.backend_pid, active.frontend_pid):
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            pass


def test_start_stops_existing_active_first(
    tmp_appdata: Path, sample_project: config.Project
) -> None:
    state.save(state.State(active=state.ActiveProject(name="Prev", backend_pid=11, frontend_pid=22)))
    manager = _FakeManager()
    orchestrator = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))

    orchestrator.start(sample_project)

    try:
        assert 11 in manager.killed and 22 in manager.killed
    finally:
        active = state.load().active
        if active is not None:
            for pid in (active.backend_pid, active.frontend_pid):
                try:
                    psutil.Process(pid).kill()
                except psutil.NoSuchProcess:
                    pass


def test_stop_clears_state_and_kills_tree(
    tmp_appdata: Path, sample_project: config.Project
) -> None:
    state.save(state.State(active=state.ActiveProject(name="Demo", backend_pid=77, frontend_pid=88)))
    manager = _FakeManager()
    orchestrator = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))

    orchestrator.stop("Demo")

    assert manager.killed == [77, 88]
    assert state.load().active is None


def test_stop_noop_when_not_active(tmp_appdata: Path, sample_project: config.Project) -> None:
    manager = _FakeManager()
    orchestrator = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))

    orchestrator.stop("Demo")

    assert manager.killed == []
    assert state.load().active is None


def test_status_is_stopped_when_state_empty(sample_project: config.Project, tmp_appdata: Path) -> None:
    status = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project)).status(sample_project)
    assert status.running is False
    assert status.backend_alive is False
    assert status.frontend_alive is False


def test_status_alive_when_pids_exist(
    tmp_appdata: Path, sample_project: config.Project
) -> None:
    backend_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    frontend_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        state.save(
            state.State(
                active=state.ActiveProject(
                    name="Demo",
                    backend_pid=backend_proc.pid,
                    frontend_pid=frontend_proc.pid,
                )
            )
        )
        status = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project)).status(sample_project)
        assert status.running is True
        assert status.backend_alive is True
        assert status.frontend_alive is True
    finally:
        backend_proc.kill()
        frontend_proc.kill()
        backend_proc.wait(timeout=5)
        frontend_proc.wait(timeout=5)


def test_start_kills_backend_if_frontend_launch_fails(
    tmp_appdata: Path, sample_project: config.Project
) -> None:
    class _BrokenFrontendManager:
        def __init__(self) -> None:
            self.killed: list[int] = []
            self._calls = 0

        def start(self, *, project: str, component: str, command: list[str], cwd: Path):
            self._calls += 1
            if self._calls == 1:
                return subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                )
            raise RuntimeError("frontend start exploded")

        def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
            self.killed.append(pid)
            try:
                psutil.Process(pid).kill()
            except psutil.NoSuchProcess:
                pass

    manager = _BrokenFrontendManager()
    orchestrator = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))

    with pytest.raises(RuntimeError, match="frontend start exploded"):
        orchestrator.start(sample_project)

    assert len(manager.killed) == 1, "backend should have been killed when frontend failed"
    assert state.load().active is None, "state should not record a partial start"


def test_orchestrator_pending_starts_initially_empty(sample_project: config.Project) -> None:
    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    assert orch.pending_starts == set()


def test_wait_healthy_returns_true_immediately_on_url_ok(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seed state so status() treats the project as active and both PIDs alive
    state.save(state.State(active=state.ActiveProject(
        name="Demo", backend_pid=1, frontend_pid=2
    )))
    monkeypatch.setattr(project.psutil, "pid_exists", lambda pid: True)
    monkeypatch.setattr(project.health, "http_ok", lambda url, timeout=1.0: True)

    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    assert orch.wait_healthy(sample_project, timeout=5.0) is True


def test_wait_healthy_returns_false_on_timeout(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="Demo", backend_pid=1, frontend_pid=2
    )))
    monkeypatch.setattr(project.psutil, "pid_exists", lambda pid: True)
    monkeypatch.setattr(project.health, "http_ok", lambda url, timeout=1.0: False)

    # Fake clock: time jumps forward by 5s on every sleep() call.
    clock = {"t": 0.0}
    monkeypatch.setattr(project.time, "monotonic", lambda: clock["t"])
    def _fake_sleep(s: float) -> None:
        clock["t"] += s
    monkeypatch.setattr(project.time, "sleep", _fake_sleep)

    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    assert orch.wait_healthy(sample_project, timeout=3.0, interval=1.0) is False


def test_stop_waits_for_port_free_on_both_ports(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="Demo", backend_pid=1, frontend_pid=2
    )))
    called: list[tuple[int, float]] = []
    def _fake_wait(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
        called.append((port, timeout))
        return True
    monkeypatch.setattr(project.health, "wait_port_free", _fake_wait)

    manager = _FakeManager()
    orch = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))
    orch.stop("Demo")

    # Both backend and frontend ports should have been waited on with the 10s timeout
    assert (sample_project.backend.port, 10.0) in called
    assert (sample_project.frontend.port, 10.0) in called


def test_stop_logs_warning_when_port_stays_busy(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="Demo", backend_pid=1, frontend_pid=2
    )))
    monkeypatch.setattr(project.health, "wait_port_free", lambda port, **_: False)

    manager = _FakeManager()
    orch = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))
    with caplog.at_level("WARNING", logger="foxtray.project"):
        orch.stop("Demo")

    messages = [r.message for r in caplog.records]
    assert any("still listening" in m for m in messages)


def test_stop_skips_port_wait_for_unknown_project(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # state.json.active.name doesn't match any project in cfg; stop should early-return
    # and never touch wait_port_free.
    called: list[int] = []
    def _fake_wait(port: int, **_):
        called.append(port)
        return True
    monkeypatch.setattr(project.health, "wait_port_free", _fake_wait)

    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    orch.stop("NotInConfig")  # state.active is None anyway
    assert called == []


def test_start_raises_port_in_use_when_backend_port_busy(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_wait(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
        return port != sample_project.backend.port  # backend port stays busy
    monkeypatch.setattr(project.health, "wait_port_free", _fake_wait)

    manager = _FakeManager()
    orch = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))
    with pytest.raises(process.PortInUse) as excinfo:
        orch.start(sample_project)
    assert str(sample_project.backend.port) in str(excinfo.value)
    # Popen should NOT have been called
    assert manager.started == []


def test_start_raises_port_in_use_when_frontend_port_busy(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_wait(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
        return port != sample_project.frontend.port  # frontend port stays busy
    monkeypatch.setattr(project.health, "wait_port_free", _fake_wait)

    manager = _FakeManager()
    orch = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))
    with pytest.raises(process.PortInUse) as excinfo:
        orch.start(sample_project)
    assert str(sample_project.frontend.port) in str(excinfo.value)
    # Both port checks must run before ANY Popen — the frontend-busy raise
    # should short-circuit before the backend process is spawned.
    assert manager.started == []


def test_start_calls_wait_port_free_with_3s_timeout(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, float]] = []
    def _fake_wait(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
        calls.append((port, timeout))
        return True
    monkeypatch.setattr(project.health, "wait_port_free", _fake_wait)

    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    orch.start(sample_project)
    # Pre-check uses 3.0s timeout on both ports
    assert (sample_project.backend.port, 3.0) in calls
    assert (sample_project.frontend.port, 3.0) in calls

    # Cleanup (_FakeManager.start spawns a real sleep() — reuse the existing cleanup
    # pattern from test_start_records_pids_in_state)
    active = state.load().active
    assert active is not None
    for pid in (active.backend_pid, active.frontend_pid):
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            pass
