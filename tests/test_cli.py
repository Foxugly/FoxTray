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
