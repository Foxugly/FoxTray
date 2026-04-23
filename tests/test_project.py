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
    orchestrator = project.Orchestrator(manager=manager)

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
    orchestrator = project.Orchestrator(manager=manager)

    orchestrator.start(sample_project)

    assert 11 in manager.killed and 22 in manager.killed


def test_stop_clears_state_and_kills_tree(
    tmp_appdata: Path, sample_project: config.Project
) -> None:
    state.save(state.State(active=state.ActiveProject(name="Demo", backend_pid=77, frontend_pid=88)))
    manager = _FakeManager()
    orchestrator = project.Orchestrator(manager=manager)

    orchestrator.stop("Demo")

    assert manager.killed == [77, 88]
    assert state.load().active is None


def test_stop_noop_when_not_active(tmp_appdata: Path) -> None:
    manager = _FakeManager()
    orchestrator = project.Orchestrator(manager=manager)

    orchestrator.stop("Demo")

    assert manager.killed == []
    assert state.load().active is None


def test_status_is_stopped_when_state_empty(sample_project: config.Project, tmp_appdata: Path) -> None:
    status = project.Orchestrator(manager=_FakeManager()).status(sample_project)
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
        status = project.Orchestrator(manager=_FakeManager()).status(sample_project)
        assert status.running is True
        assert status.backend_alive is True
        assert status.frontend_alive is True
    finally:
        backend_proc.kill()
        frontend_proc.kill()
        backend_proc.wait(timeout=5)
        frontend_proc.wait(timeout=5)
