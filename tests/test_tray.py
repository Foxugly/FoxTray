from foxtray import config, state
from foxtray.project import ProjectStatus
from foxtray.ui import tray


def _status(*, backend_alive: bool = False, frontend_alive: bool = False) -> ProjectStatus:
    return ProjectStatus(
        name="X",
        running=backend_alive and frontend_alive,
        backend_alive=backend_alive,
        frontend_alive=frontend_alive,
        backend_port_listening=False,
        frontend_port_listening=False,
        url_ok=False,
    )


def test_icon_state_stopped_when_no_active() -> None:
    assert tray.compute_icon_state(None, {}) == "stopped"


def test_icon_state_running_when_both_alive() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    assert tray.compute_icon_state(active, statuses) == "running"


def test_icon_state_partial_when_only_backend_alive() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    assert tray.compute_icon_state(active, statuses) == "partial"


def test_icon_state_partial_when_only_frontend_alive() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=False, frontend_alive=True)}
    assert tray.compute_icon_state(active, statuses) == "partial"


def test_icon_state_stopped_when_active_but_both_dead() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=False, frontend_alive=False)}
    assert tray.compute_icon_state(active, statuses) == "stopped"
