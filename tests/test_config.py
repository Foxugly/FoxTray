from pathlib import Path

import pytest

from foxtray import config


SAMPLE_YAML = """
projects:
  - name: FoxRunner
    url: http://localhost:4200
    backend:
      path: D:\\\\projects\\\\foxrunner-server
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: D:\\\\projects\\\\foxrunner-frontend
      command: ng serve --port 4200
      port: 4200
"""


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_parses_single_project(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert [p.name for p in cfg.projects] == ["FoxRunner"]
    foxrunner = cfg.projects[0]
    assert foxrunner.url == "http://localhost:4200"
    assert foxrunner.backend.port == 8000
    assert foxrunner.frontend.port == 4200


def test_backend_python_substitutes_venv(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    backend = cfg.projects[0].backend
    assert backend.python_executable == Path("D:\\projects\\foxrunner-server") / ".venv" / "Scripts" / "python.exe"


def test_backend_resolved_command_replaces_python(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    backend = cfg.projects[0].backend
    assert backend.resolved_command[0] == str(backend.python_executable)
    assert backend.resolved_command[1:] == ["manage.py", "runserver", "8000"]


def test_frontend_resolved_command_is_shell_split(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.projects[0].frontend.resolved_command == ["ng", "serve", "--port", "4200"]


def test_project_registry_lookup(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.get("FoxRunner").name == "FoxRunner"
    with pytest.raises(KeyError):
        cfg.get("Nope")


def test_duplicate_project_names_rejected(tmp_path: Path) -> None:
    body = SAMPLE_YAML + SAMPLE_YAML.split("projects:\n")[1]
    with pytest.raises(config.ConfigError, match="duplicate"):
        config.load(write_config(tmp_path, body))


def test_missing_backend_key_rejected(tmp_path: Path) -> None:
    body = """
projects:
  - name: Broken
    url: http://localhost:4200
    frontend:
      path: D:\\\\x
      command: ng serve
      port: 4200
"""
    with pytest.raises(config.ConfigError, match="backend"):
        config.load(write_config(tmp_path, body))


def test_backend_non_python_command_rejected_at_load_time(tmp_path: Path) -> None:
    body = SAMPLE_YAML.replace(
        "python manage.py runserver 8000", "node server.js"
    )
    with pytest.raises(config.ConfigError, match="must start with 'python'"):
        config.load(write_config(tmp_path, body))
