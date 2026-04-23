from pathlib import Path

import pytest

from foxtray import cli


CONFIG_YAML = """
projects:
  - name: Demo
    url: http://127.0.0.1:9
    backend:
      path: {path}
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: {path}
      command: ng serve --port 4200
      port: 4200
"""


@pytest.fixture
def demo_config(tmp_path: Path) -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(CONFIG_YAML.format(path=str(tmp_path).replace("\\", "\\\\")), encoding="utf-8")
    return cfg_path


def test_list_exit_code_zero(demo_config: Path, tmp_appdata: Path, capsys: pytest.CaptureFixture) -> None:
    assert cli.main(["--config", str(demo_config), "list"]) == 0
    out = capsys.readouterr().out
    assert "Demo" in out
    assert "stopped" in out


def test_status_unknown_project_returns_2(
    demo_config: Path, tmp_appdata: Path, capsys: pytest.CaptureFixture
) -> None:
    rc = cli.main(["--config", str(demo_config), "status", "NopeProject"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Unknown project" in err


def test_config_error_returns_2(tmp_appdata: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # Invalid YAML → ConfigError path
    broken = tmp_path / "broken.yaml"
    broken.write_text("projects: not-a-list", encoding="utf-8")
    rc = cli.main(["--config", str(broken), "list"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Config error" in err


def test_missing_config_file_returns_2(tmp_appdata: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    missing = tmp_path / "does-not-exist.yaml"
    rc = cli.main(["--config", str(missing), "list"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Cannot open config" in err


def test_unrelated_keyerror_is_not_swallowed(
    demo_config: Path, tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A KeyError from inside command execution that is NOT a ProjectNotFound must propagate."""
    original_load = cli.config.load

    def _load_raising_bare_keyerror(*args, **kwargs):
        # Simulate some internal subsystem raising a bare KeyError
        raise KeyError("not-a-project-name")

    monkeypatch.setattr(cli.config, "load", _load_raising_bare_keyerror)
    with pytest.raises(KeyError, match="not-a-project-name"):
        cli.main(["--config", str(demo_config), "list"])


def test_stop_reports_noop_when_not_active(
    demo_config: Path, tmp_appdata: Path, capsys: pytest.CaptureFixture
) -> None:
    rc = cli.main(["--config", str(demo_config), "stop", "Demo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "was not active" in out
    assert "Stopped Demo" not in out


def test_tray_command_parses_and_dispatches(
    demo_config: Path, tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []

    class _FakeTray:
        def __init__(self, cfg, orchestrator) -> None:  # type: ignore[no-untyped-def]
            called.append(f"init:{len(cfg.projects)}")

        def run(self) -> None:
            called.append("run")

    from foxtray.ui import tray as tray_mod
    monkeypatch.setattr(tray_mod, "TrayApp", _FakeTray)

    rc = cli.main(["--config", str(demo_config), "tray"])
    assert rc == 0
    assert called == ["init:1", "run"]


def test_main_calls_clear_if_orphaned_before_dispatch(
    demo_config: Path, tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from foxtray import state
    called: list[bool] = []
    def _fake_clear() -> bool:
        called.append(True)
        return False
    monkeypatch.setattr(state, "clear_if_orphaned", _fake_clear)

    rc = cli.main(["--config", str(demo_config), "list"])
    assert rc == 0
    assert called == [True]


def test_cmd_start_prints_healthy_on_success(
    demo_config: Path,
    tmp_appdata: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from foxtray import project as project_mod

    def _fake_start(self, proj): return None
    def _fake_wait_healthy(self, proj, timeout=30.0, interval=1.0): return True

    monkeypatch.setattr(project_mod.Orchestrator, "start", _fake_start)
    monkeypatch.setattr(project_mod.Orchestrator, "wait_healthy", _fake_wait_healthy)

    rc = cli.main(["--config", str(demo_config), "start", "Demo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Started Demo" in out
    assert "healthy" in out


def test_cmd_start_stops_and_returns_1_on_timeout(
    demo_config: Path,
    tmp_appdata: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from foxtray import project as project_mod

    stopped: list[str] = []
    def _fake_start(self, proj): return None
    def _fake_wait_healthy(self, proj, timeout=30.0, interval=1.0): return False
    def _fake_stop(self, name): stopped.append(name)

    monkeypatch.setattr(project_mod.Orchestrator, "start", _fake_start)
    monkeypatch.setattr(project_mod.Orchestrator, "wait_healthy", _fake_wait_healthy)
    monkeypatch.setattr(project_mod.Orchestrator, "stop", _fake_stop)

    rc = cli.main(["--config", str(demo_config), "start", "Demo"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "failed to become healthy" in err
    assert stopped == ["Demo"]


def test_cmd_start_maps_port_in_use_to_exit_2(
    demo_config: Path,
    tmp_appdata: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from foxtray import process as process_mod
    from foxtray import project as project_mod

    def _fake_start(self, proj):
        raise process_mod.PortInUse("backend port 8000 still in use")
    monkeypatch.setattr(project_mod.Orchestrator, "start", _fake_start)

    rc = cli.main(["--config", str(demo_config), "start", "Demo"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "8000" in err
