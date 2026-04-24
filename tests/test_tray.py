from pathlib import Path

import pytest

from foxtray import config, state
from foxtray.project import ProjectStatus
from foxtray.ui import tray


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


def test_icon_state_stopped_when_no_active() -> None:
    assert tray.compute_icon_state(None, {}) == "stopped"


def test_icon_state_running_when_both_alive() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
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
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, curr_active, curr_statuses, suppressed=set(), pending_starts=set()
    )
    assert [n.message for n in notifications] == ["FoxRunner is up"]


def test_transitions_stopped_to_partial_fires_component_failure() -> None:
    prev_active = None
    curr_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, curr_active, curr_statuses, suppressed=set(), pending_starts=set()
    )
    assert len(notifications) == 1
    assert "FoxRunner" in notifications[0].message
    assert "one component failed" in notifications[0].message


def test_transitions_running_to_partial_names_dead_component() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    notifications = tray.compute_transitions(
        active, prev_statuses, active, curr_statuses, suppressed=set(), pending_starts=set()
    )
    assert len(notifications) == 1
    assert "frontend crashed" in notifications[0].message


def test_transitions_partial_to_running_fires_recovered() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    notifications = tray.compute_transitions(
        active, prev_statuses, active, curr_statuses, suppressed=set(), pending_starts=set()
    )
    assert [n.message for n in notifications] == ["FoxRunner recovered"]


def test_transitions_running_to_stopped_suppressed_is_silent() -> None:
    prev_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    curr_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, None, curr_statuses, suppressed={"FoxRunner"}, pending_starts=set()
    )
    assert notifications == []


def test_transitions_running_to_stopped_unsuppressed_fires_unexpected() -> None:
    prev_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    curr_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, None, curr_statuses, suppressed=set(), pending_starts=set()
    )
    assert len(notifications) == 1
    assert "stopped unexpectedly" in notifications[0].message


def test_transitions_partial_to_stopped_suppressed_is_silent() -> None:
    prev_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    curr_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, None, curr_statuses, suppressed={"FoxRunner"}, pending_starts=set()
    )
    assert notifications == []


def test_transitions_partial_to_stopped_unsuppressed_fires_fully_stopped() -> None:
    prev_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}
    curr_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    notifications = tray.compute_transitions(
        prev_active, prev_statuses, None, curr_statuses, suppressed=set(), pending_starts=set()
    )
    assert len(notifications) == 1
    assert "fully stopped" in notifications[0].message


def test_transitions_no_change_returns_empty() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    notifications = tray.compute_transitions(
        active, statuses, active, statuses, suppressed=set(), pending_starts=set()
    )
    assert notifications == []


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


def _backend_only_project(name: str, url: str = "http://localhost:8000") -> config.Project:
    return config.Project(
        name=name,
        url=url,
        backend=config.Backend(
            path=Path(f"D:\\projects\\{name}-server"),
            venv=".venv",
            command="python manage.py runserver 8000",
            port=8000,
        ),
        frontend=None,
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
        on_run_task=lambda p, t: None,
        on_run_script=lambda s: None,
        on_about=lambda: None,
        on_restart=lambda p: None,
        on_open_logs_folder=lambda: None,
        on_open_config=lambda: None,
        on_reload_config=lambda: None,
        on_copy_url=lambda u: None,
        on_open_log=lambda path: None,
        on_toggle_autostart=lambda: None,
    )


def test_menu_lists_all_projects_in_config_order() -> None:
    cfg = config.Config(projects=[_project("A"), _project("B"), _project("C")])
    statuses = {"A": _status(), "B": _status(), "C": _status()}
    items = tray.build_menu_items(cfg, None, statuses, _noop_handlers(), running_tasks=set())
    project_items = [i for i in items if not i.separator and i.submenu]
    assert [i.text.split(" ")[0] for i in project_items] == ["A", "B", "C"]


def test_menu_stopped_project_shows_start() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers(), running_tasks=set())
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Start" in submenu_texts
    assert "Stop" not in submenu_texts


def test_menu_running_project_shows_stop() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers(), running_tasks=set())
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Stop" in submenu_texts
    assert "Start" not in submenu_texts


def test_menu_stopped_project_disables_open_in_browser() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers(), running_tasks=set())
    browser_item = next(s for s in items[0].submenu if s.text == "Open in browser")
    assert browser_item.enabled is False


def test_menu_running_project_enables_open_in_browser() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers(), running_tasks=set())
    browser_item = next(s for s in items[0].submenu if s.text == "Open in browser")
    assert browser_item.enabled is True


def test_menu_stop_all_disabled_when_no_active() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers(), running_tasks=set())
    stop_all = next(i for i in items if i.text == "Stop all")
    assert stop_all.enabled is False


def test_menu_stop_all_enabled_when_active() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers(), running_tasks=set())
    stop_all = next(i for i in items if i.text == "Stop all")
    assert stop_all.enabled is True


def test_menu_has_exit_and_stop_all_and_exit() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(cfg, None, {"A": _status()}, _noop_handlers(), running_tasks=set())
    texts = [i.text for i in items if not i.separator]
    assert "Exit" in texts
    assert "Stop all and exit" in texts
    # Dangerous global actions live at the bottom, with Exit last.
    assert texts.index("Stop all and exit") + 1 == texts.index("Exit")


def test_menu_partial_project_shows_stop() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=False)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers(), running_tasks=set())
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Stop" in submenu_texts
    assert "Start" not in submenu_texts
    # Open in browser must be enabled for partial too (one component is alive).
    browser_item = next(s for s in items[0].submenu if s.text == "Open in browser")
    assert browser_item.enabled is True


def test_dead_component_raises_on_invariant_violation() -> None:
    # Both statuses have the same alive pattern → no component "died" between
    # them. Reaching _dead_component in this state means the caller broke its
    # contract; fail loudly.
    with pytest.raises(AssertionError):
        tray._dead_component(_status(), _status())


def test_menu_project_label_reflects_status() -> None:
    cfg = config.Config(projects=[_project("A"), _project("B"), _project("C")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {
        "A": _status(backend_alive=True, frontend_alive=True, url_ok=True),  # RUNNING
        "B": _status(backend_alive=False, frontend_alive=False),              # stopped
        "C": _status(),                                                       # stopped
    }
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers(), running_tasks=set())
    labels_by_name = {i.text.split(" ")[0]: i.text for i in items if i.submenu}
    assert "RUNNING" in labels_by_name["A"]
    assert "stopped" in labels_by_name["B"]
    assert "stopped" in labels_by_name["C"]


def test_menu_partial_project_labelled_partial() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=False)}
    items = tray.build_menu_items(cfg, active, statuses, _noop_handlers(), running_tasks=set())
    assert "PARTIAL" in items[0].text


def test_icon_state_partial_when_both_alive_but_url_not_ok() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": ProjectStatus(
        name="FoxRunner",
        has_frontend=True,
        running=True,
        backend_alive=True,
        frontend_alive=True,
        backend_port_listening=True,
        frontend_port_listening=True,
        url_ok=False,
    )}
    assert tray.compute_icon_state(active, statuses) == "partial"


def test_icon_state_running_requires_url_ok() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": ProjectStatus(
        name="FoxRunner",
        has_frontend=True,
        running=True,
        backend_alive=True,
        frontend_alive=True,
        backend_port_listening=True,
        frontend_port_listening=True,
        url_ok=True,
    )}
    assert tray.compute_icon_state(active, statuses) == "running"


def test_transitions_stopped_to_partial_silent_when_pending_start() -> None:
    prev_active = None
    curr_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}  # url_ok=False
    pending = {"FoxRunner"}
    notes = tray.compute_transitions(
        prev_active, prev_statuses, curr_active, curr_statuses,
        suppressed=set(), pending_starts=pending,
    )
    assert notes == []
    assert pending == {"FoxRunner"}  # NOT consumed yet


def test_transitions_partial_to_running_fires_is_up_when_pending() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}  # url_ok=False
    curr = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    pending = {"FoxRunner"}
    notes = tray.compute_transitions(
        active, prev, active, curr,
        suppressed=set(), pending_starts=pending,
    )
    assert [n.message for n in notes] == ["FoxRunner is up"]
    assert pending == set()  # consumed


def test_transitions_partial_to_running_fires_recovered_when_not_pending() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}  # crashed
    curr = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    pending: set[str] = set()
    notes = tray.compute_transitions(
        active, prev, active, curr,
        suppressed=set(), pending_starts=pending,
    )
    assert [n.message for n in notes] == ["FoxRunner recovered"]


def test_transitions_partial_to_stopped_fires_failed_to_start_when_pending() -> None:
    prev_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}  # url_ok=False (partial)
    curr: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    pending = {"FoxRunner"}
    notes = tray.compute_transitions(
        prev_active, prev, None, curr,
        suppressed=set(), pending_starts=pending,
    )
    assert len(notes) == 1
    assert "failed to start" in notes[0].message
    assert pending == set()


def test_transitions_stopped_to_running_consumes_pending() -> None:
    prev_active = None
    curr_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    curr = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    pending = {"FoxRunner"}
    notes = tray.compute_transitions(
        prev_active, prev, curr_active, curr,
        suppressed=set(), pending_starts=pending,
    )
    assert [n.message for n in notes] == ["FoxRunner is up"]
    assert pending == set()


def _project_with_tasks(name: str = "A") -> config.Project:
    base = _project(name)
    return config.Project(
        name=base.name,
        url=base.url,
        backend=base.backend,
        frontend=base.frontend,
        start_timeout=base.start_timeout,
        tasks=(
            config.Task(name="Migrate", cwd="backend", command="python manage.py migrate"),
            config.Task(name="NG test", cwd="frontend", command="ng test --watch=false"),
        ),
    )


def _noop_handlers_with_tasks() -> tray.Handlers:
    return tray.Handlers(
        on_start=lambda p: None,
        on_stop=lambda p: None,
        on_open_browser=lambda p: None,
        on_open_folder=lambda path: None,
        on_stop_all=lambda: None,
        on_exit=lambda: None,
        on_stop_all_and_exit=lambda: None,
        on_run_task=lambda p, t: None,
        on_run_script=lambda s: None,
        on_about=lambda: None,
        on_restart=lambda p: None,
        on_open_logs_folder=lambda: None,
        on_open_config=lambda: None,
        on_reload_config=lambda: None,
        on_copy_url=lambda u: None,
        on_open_log=lambda path: None,
        on_toggle_autostart=lambda: None,
    )


def test_menu_project_without_tasks_has_no_tasks_submenu() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Tasks" not in submenu_texts


def test_menu_project_with_tasks_adds_tasks_submenu() -> None:
    cfg = config.Config(projects=[_project_with_tasks("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks=set(),
    )
    tasks_item = next(s for s in items[0].submenu if s.text == "Tasks")
    assert len(tasks_item.submenu) == 2
    assert [t.text for t in tasks_item.submenu] == ["Migrate", "NG test"]


def test_menu_running_task_shows_disabled_suffix() -> None:
    cfg = config.Config(projects=[_project_with_tasks("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks={"task:A:Migrate"},
    )
    tasks_item = next(s for s in items[0].submenu if s.text == "Tasks")
    migrate = next(t for t in tasks_item.submenu if t.text.startswith("Migrate"))
    assert migrate.text == "Migrate (running…)"
    assert migrate.enabled is False


def test_menu_config_without_scripts_has_no_scripts_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks=set(),
    )
    texts = [i.text for i in items if not i.separator]
    assert "Scripts" not in texts


def test_menu_config_with_scripts_adds_scripts_submenu() -> None:
    cfg = config.Config(
        projects=[_project("A")],
        scripts=(
            config.Script(
                name="Git pull", path=Path("D:\\x"), command="git pull"
            ),
        ),
    )
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks=set(),
    )
    scripts_item = next(i for i in items if i.text == "Scripts")
    assert [s.text for s in scripts_item.submenu] == ["Git pull"]


def test_menu_running_script_shows_disabled_suffix() -> None:
    cfg = config.Config(
        projects=[_project("A")],
        scripts=(
            config.Script(name="Git pull", path=Path("D:\\x"), command="git pull"),
        ),
    )
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks={"script:Git pull"},
    )
    scripts_item = next(i for i in items if i.text == "Scripts")
    git_pull = scripts_item.submenu[0]
    assert git_pull.text == "Git pull (running…)"
    assert git_pull.enabled is False


def test_menu_scripts_item_placed_before_stop_all() -> None:
    cfg = config.Config(
        projects=[_project("A")],
        scripts=(config.Script(name="S", path=Path("D:\\x"), command="git pull"),),
    )
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks=set(),
    )
    # Order: project items, separator, Scripts, separator, Stop all, ...
    non_sep = [i for i in items if not i.separator]
    scripts_idx = next(i for i, e in enumerate(non_sep) if e.text == "Scripts")
    stop_all_idx = next(i for i, e in enumerate(non_sep) if e.text == "Stop all")
    assert scripts_idx < stop_all_idx


def test_menu_has_about_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    non_sep = [i for i in items if not i.separator]
    texts = [i.text for i in non_sep]
    assert "About" in texts
    assert texts.index("About") < texts.index("Stop all")


def test_menu_running_project_has_restart_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    items = tray.build_menu_items(
        cfg, active, statuses, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Restart" in submenu_texts


def test_menu_stopped_project_has_no_restart_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Restart" not in submenu_texts


def test_menu_project_always_has_copy_url_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Copy URL" in submenu_texts


def test_menu_project_without_path_root_has_no_open_project_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Open project folder" not in submenu_texts


def test_menu_project_with_path_root_has_open_project_entry() -> None:
    base = _project("A")
    project_with_root = config.Project(
        name=base.name, url=base.url, backend=base.backend, frontend=base.frontend,
        start_timeout=base.start_timeout, tasks=base.tasks,
        path_root=Path("D:\\\\repos\\\\A"),
    )
    cfg = config.Config(projects=[project_with_root])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Open project folder" in submenu_texts


def test_menu_root_has_open_logs_folder_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    root_texts = [i.text for i in items if not i.separator and not i.submenu]
    assert "Open logs folder" in root_texts


def test_menu_root_has_open_and_reload_config_entries() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    root_texts = [i.text for i in items if not i.separator and not i.submenu]
    assert "Open config.yaml" in root_texts
    assert "Reload config.yaml" in root_texts


def test_menu_project_has_open_backend_log_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Open backend log" in submenu_texts
    assert "Open frontend log" in submenu_texts


def test_menu_backend_only_project_hides_frontend_entries() -> None:
    cfg = config.Config(projects=[_backend_only_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status(has_frontend=False)}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Open backend folder" in submenu_texts
    assert "Open frontend folder" not in submenu_texts
    assert "Open frontend log" not in submenu_texts


def test_menu_has_start_at_login_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    non_sep = [i for i in items if not i.separator]
    texts = [i.text for i in non_sep]
    assert "Start at login" in texts
    # Placed BEFORE About
    assert texts.index("Start at login") < texts.index("About")


def test_menu_project_submenu_groups_primary_actions_first() -> None:
    cfg = config.Config(projects=[_project("A")])
    active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    statuses = {"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    items = tray.build_menu_items(
        cfg, active, statuses, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu if not s.separator]
    assert submenu_texts[:4] == ["Stop", "Restart", "Open in browser", "Copy URL"]


def test_menu_project_submenu_places_logs_after_folders() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu if not s.separator]
    assert submenu_texts.index("Open backend folder") < submenu_texts.index("Open backend log")
    assert submenu_texts.index("Open frontend folder") < submenu_texts.index("Open frontend log")
