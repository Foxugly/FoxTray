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


def test_transitions_stopped_to_running_fires_up() -> None:
    prev_active = None
    curr_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses: dict[str, ProjectStatus] = {
        "FoxRunner": _status(),
    }
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, curr_active, curr_statuses, suppressed=set()
    )
    assert [n.message for n in notifications] == ["FoxRunner is up"]


def test_transitions_stopped_to_partial_fires_component_failure() -> None:
    prev_active = None
    curr_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, curr_active, curr_statuses, suppressed=set()
    )
    assert len(notifications) == 1
    assert "FoxRunner" in notifications[0].message
    assert "one component failed" in notifications[0].message


def test_transitions_running_to_partial_names_dead_component() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    notifications = tray.compute_transitions(
        active, prev_statuses, active, curr_statuses, suppressed=set()
    )
    assert len(notifications) == 1
    assert "frontend crashed" in notifications[0].message


def test_transitions_partial_to_running_fires_recovered() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    notifications = tray.compute_transitions(
        active, prev_statuses, active, curr_statuses, suppressed=set()
    )
    assert [n.message for n in notifications] == ["FoxRunner recovered"]


def test_transitions_running_to_stopped_suppressed_is_silent() -> None:
    prev_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    curr_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, None, curr_statuses, suppressed={"FoxRunner"}
    )
    assert notifications == []


def test_transitions_running_to_stopped_unsuppressed_fires_unexpected() -> None:
    prev_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    curr_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, None, curr_statuses, suppressed=set()
    )
    assert len(notifications) == 1
    assert "stopped unexpectedly" in notifications[0].message


def test_transitions_no_change_returns_empty() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}
    notifications = tray.compute_transitions(
        active, statuses, active, statuses, suppressed=set()
    )
    assert notifications == []
