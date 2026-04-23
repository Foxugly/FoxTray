from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from foxtray import config
from foxtray.ui import actions


@dataclass
class _FakeTaskManager:
    runs: list[tuple[str, list[str], Path]] = field(default_factory=list)
    raises: Exception | None = None
    killed_count: int = 0

    def run(self, key: str, command: list[str], cwd: Path) -> None:
        if self.raises:
            raise self.raises
        self.runs.append((key, command, cwd))

    def is_running(self, key: str) -> bool:
        return False

    def kill_all(self) -> int:
        return self.killed_count


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
    pending_starts: set[str] = field(default_factory=set)

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


def test_on_start_adds_to_pending_starts_before_calling_orchestrator() -> None:
    orch = _FakeOrchestrator()
    actions.on_start(orch, _project(), _FakeIcon())
    assert orch.pending_starts == {"Demo"}


def test_on_start_removes_from_pending_starts_on_exception() -> None:
    orch = _FakeOrchestrator(raises=RuntimeError("boom"))
    icon = _FakeIcon()
    actions.on_start(orch, _project(), icon)
    assert orch.pending_starts == set()
    assert icon.notifications == [("FoxTray error", "boom")]


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


def _task() -> config.Task:
    return config.Task(
        name="Migrate", cwd="backend", command="python manage.py migrate"
    )


def _script() -> config.Script:
    return config.Script(
        name="Git pull", path=Path("D:\\proj"), command="git pull"
    )


def test_on_run_task_calls_task_manager_run_with_key_command_cwd() -> None:
    tm = _FakeTaskManager()
    actions.on_run_task(tm, _project(), _task(), _FakeIcon())
    assert len(tm.runs) == 1
    key, command, cwd = tm.runs[0]
    assert key == "task:Demo:Migrate"
    # command: python-swap gives the venv python path
    assert command[0].endswith("python.exe")
    assert command[1:] == ["manage.py", "migrate"]
    assert cwd == _project().backend.path


def test_on_run_task_already_running_notifies() -> None:
    import foxtray.tasks as tasks_mod
    tm = _FakeTaskManager(raises=tasks_mod.TaskAlreadyRunning("task:Demo:Migrate"))
    icon = _FakeIcon()
    actions.on_run_task(tm, _project(), _task(), icon)
    # Balloon content: "Migrate is already running" with title "FoxTray"
    assert any("already running" in message for _title, message in icon.notifications)


def test_on_run_task_unexpected_exception_notifies_error() -> None:
    tm = _FakeTaskManager(raises=RuntimeError("boom"))
    icon = _FakeIcon()
    actions.on_run_task(tm, _project(), _task(), icon)
    assert icon.notifications == [("FoxTray error", "boom")]


def test_on_run_script_calls_task_manager_with_key_and_script_path() -> None:
    tm = _FakeTaskManager()
    actions.on_run_script(tm, _script(), _FakeIcon())
    assert len(tm.runs) == 1
    key, command, cwd = tm.runs[0]
    assert key == "script:Git pull"
    assert command == ["git", "pull"]
    assert cwd == Path("D:\\proj")


def test_on_run_script_already_running_notifies() -> None:
    import foxtray.tasks as tasks_mod
    tm = _FakeTaskManager(raises=tasks_mod.TaskAlreadyRunning("script:Git pull"))
    icon = _FakeIcon()
    actions.on_run_script(tm, _script(), icon)
    assert any("already running" in message for _title, message in icon.notifications)
