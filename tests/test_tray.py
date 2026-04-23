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


from pathlib import Path


def _project(name: str, url: str = "http://localhost:4200") -> config.Project:
    return config.Project(
        name=name,
        url=url,
        backend=config.Backend(
            path=Path(f"D:\\projects\\{name}-server"),
            venv=".venv",
            command="python manage.py runserver 8000",
            port=8000,
        ),
        frontend=config.Frontend(
            path=Path(f"D:\\projects\\{name}-frontend"),
            command="ng serve --port 4200",
            port=4200,
        ),
    )


def _noop_handlers() -> tray.Handlers:
    return tray.Handlers(
        on_start=lambda p: None,
        on_stop=lambda p: None,
        on_open_browser=lambda p: None,
        on_open_folder=lambda path: None,
        on_stop_all=lambda: None,
        on_exit=lambda: None,
        on_stop_all_and_exit=lambda: None,
    )


def test_menu_lists_all_projects_in_config_order() -> None:
    cfg = config.Config(projects=[_project("A"), _project("B"), _project("C")])
    statuses = {"A": _status(), "B": _status(), "C": _status()}
    items = tray.build_menu_items(cfg, None, statuses, _noop_handlers())
    project_items = [i for i in items if not i.separator and i.submenu]
    assert [i.text.split(" ")[0] for i in project_items] == ["A", "B", "C"]


def test_menu_stopped_project_shows_start() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers())
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Start" in submenu_texts
    assert "Stop" not in submenu_texts


def test_menu_running_project_shows_stop() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers())
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Stop" in submenu_texts
    assert "Start" not in submenu_texts


def test_menu_stopped_project_disables_open_in_browser() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers())
    browser_item = next(s for s in items[0].submenu if s.text == "Open in browser")
    assert browser_item.enabled is False


def test_menu_running_project_enables_open_in_browser() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers())
    browser_item = next(s for s in items[0].submenu if s.text == "Open in browser")
    assert browser_item.enabled is True


def test_menu_stop_all_disabled_when_no_active() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers())
    stop_all = next(i for i in items if i.text == "Stop all")
    assert stop_all.enabled is False


def test_menu_stop_all_enabled_when_active() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers())
    stop_all = next(i for i in items if i.text == "Stop all")
    assert stop_all.enabled is True


def test_menu_has_exit_and_stop_all_and_exit() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers())
    texts = [i.text for i in items if not i.separator]
    assert "Exit" in texts
    assert "Stop all and exit" in texts


def test_menu_project_label_reflects_status() -> None:
    cfg = config.Config(projects=[_project("A"), _project("B"), _project("C")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {
        "A": _status(backend_alive=True, frontend_alive=True),   # RUNNING
        "B": _status(backend_alive=False, frontend_alive=False), # stopped
        "C": _status(),                                          # stopped
    }
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers())
    labels_by_name = {i.text.split(" ")[0]: i.text for i in items if i.submenu}
    assert "RUNNING" in labels_by_name["A"]
    assert "stopped" in labels_by_name["B"]
    assert "stopped" in labels_by_name["C"]


def test_menu_partial_project_labelled_partial() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=False)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers())
    assert "PARTIAL" in items[0].text
