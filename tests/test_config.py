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
    with pytest.raises(config.ProjectNotFound):
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


def test_start_timeout_defaults_to_30(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.projects[0].start_timeout == 30


def test_start_timeout_parsed_when_provided(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    start_timeout: 60\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.projects[0].start_timeout == 60


def test_start_timeout_rejects_zero(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    start_timeout: 0\n"
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml_body))


def test_start_timeout_rejects_negative(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    start_timeout: -5\n"
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml_body))


def test_start_timeout_rejects_non_integer(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + '\n    start_timeout: "nope"\n'
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml_body))


TASKS_YAML = """
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
    tasks:
      - name: Migrate
        cwd: backend
        command: python manage.py migrate
      - name: Collect static
        cwd: backend
        command: python manage.py collectstatic --noinput
      - name: NG test
        cwd: frontend
        command: ng test --watch=false
"""


def test_project_without_tasks_has_empty_tuple(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.projects[0].tasks == ()


def test_project_parses_tasks_in_order(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, TASKS_YAML))
    task_names = [t.name for t in cfg.projects[0].tasks]
    assert task_names == ["Migrate", "Collect static", "NG test"]


def test_task_backend_cwd_swaps_python(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, TASKS_YAML))
    project = cfg.projects[0]
    migrate = next(t for t in project.tasks if t.name == "Migrate")
    cmd = migrate.resolved_command(project)
    assert cmd[0] == str(project.backend.python_executable)
    assert cmd[1:] == ["manage.py", "migrate"]


def test_task_backend_cwd_does_not_swap_non_python(tmp_path: Path) -> None:
    yaml = TASKS_YAML.replace(
        "command: python manage.py migrate",
        "command: pytest tests/",
    )
    cfg = config.load(write_config(tmp_path, yaml))
    migrate = cfg.projects[0].tasks[0]
    assert migrate.resolved_command(cfg.projects[0]) == ["pytest", "tests/"]


def test_task_frontend_cwd_never_swaps(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, TASKS_YAML))
    ng_test = next(t for t in cfg.projects[0].tasks if t.name == "NG test")
    assert ng_test.resolved_command(cfg.projects[0])[0] == "ng"


def test_task_resolved_cwd_backend(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, TASKS_YAML))
    project = cfg.projects[0]
    migrate = project.tasks[0]
    assert migrate.resolved_cwd(project) == project.backend.path


def test_task_resolved_cwd_frontend(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, TASKS_YAML))
    project = cfg.projects[0]
    ng_test = project.tasks[2]
    assert ng_test.resolved_cwd(project) == project.frontend.path


def test_task_rejects_invalid_cwd(tmp_path: Path) -> None:
    yaml = TASKS_YAML.replace("cwd: backend", "cwd: sideways")
    with pytest.raises(config.ConfigError, match="cwd"):
        config.load(write_config(tmp_path, yaml))


def test_task_rejects_empty_command(tmp_path: Path) -> None:
    yaml = TASKS_YAML.replace("command: python manage.py migrate", 'command: ""')
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml))


def test_task_rejects_duplicate_names_within_project(tmp_path: Path) -> None:
    yaml = TASKS_YAML.replace("name: Collect static", "name: Migrate")
    with pytest.raises(config.ConfigError, match="duplicate"):
        config.load(write_config(tmp_path, yaml))


def test_task_rejects_missing_name(tmp_path: Path) -> None:
    yaml = TASKS_YAML.replace("- name: Migrate\n        cwd: backend", "- cwd: backend")
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml))


SCRIPTS_YAML = """
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

scripts:
  - name: Git pull all
    path: D:\\\\PycharmProjects
    command: git pull --recurse
  - name: Run migrations
    path: D:\\\\scripts\\\\migrations
    venv: .venv
    command: python one_off.py
"""


def test_config_without_scripts_has_empty_tuple(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.scripts == ()


def test_config_parses_scripts(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SCRIPTS_YAML))
    names = [s.name for s in cfg.scripts]
    assert names == ["Git pull all", "Run migrations"]


def test_script_without_venv_does_not_swap(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SCRIPTS_YAML))
    git_pull = cfg.scripts[0]
    assert git_pull.resolved_command() == ["git", "pull", "--recurse"]


def test_script_with_venv_swaps_python(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SCRIPTS_YAML))
    migration = cfg.scripts[1]
    cmd = migration.resolved_command()
    assert cmd[0] == str(Path("D:\\scripts\\migrations") / ".venv" / "Scripts" / "python.exe")
    assert cmd[1:] == ["one_off.py"]


def test_script_with_venv_but_non_python_command_no_swap(tmp_path: Path) -> None:
    yaml = SCRIPTS_YAML.replace("command: python one_off.py", "command: bash script.sh")
    cfg = config.load(write_config(tmp_path, yaml))
    migration = cfg.scripts[1]
    assert migration.resolved_command() == ["bash", "script.sh"]


def test_script_rejects_relative_path(tmp_path: Path) -> None:
    yaml = SCRIPTS_YAML.replace("path: D:\\\\PycharmProjects", "path: relative/path")
    with pytest.raises(config.ConfigError, match="absolute"):
        config.load(write_config(tmp_path, yaml))


def test_script_rejects_duplicate_names(tmp_path: Path) -> None:
    yaml = SCRIPTS_YAML.replace("name: Run migrations", "name: Git pull all")
    with pytest.raises(config.ConfigError, match="duplicate"):
        config.load(write_config(tmp_path, yaml))


def test_script_rejects_empty_command(tmp_path: Path) -> None:
    yaml = SCRIPTS_YAML.replace("command: git pull --recurse", 'command: ""')
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml))


def test_script_rejects_empty_venv_string(tmp_path: Path) -> None:
    yaml = SCRIPTS_YAML.replace("venv: .venv", 'venv: ""')
    with pytest.raises(config.ConfigError, match="venv"):
        config.load(write_config(tmp_path, yaml))


def test_project_without_path_root_defaults_none(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.projects[0].path_root is None


def test_project_path_root_accepts_absolute(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    path_root: D:\\\\projects\\\\foxrunner\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.projects[0].path_root == Path("D:\\projects\\foxrunner")


def test_project_path_root_rejects_relative(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    path_root: relative/path\n"
    with pytest.raises(config.ConfigError, match="absolute"):
        config.load(write_config(tmp_path, yaml_body))


import os


def test_backend_path_expands_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FOX_ROOT", "D:\\roots\\foxrunner")
    yaml_body = SAMPLE_YAML.replace(
        "path: D:\\\\projects\\\\foxrunner-server",
        "path: ${FOX_ROOT}",
    )
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.projects[0].backend.path == Path("D:\\roots\\foxrunner")


def test_script_path_expands_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCRIPT_HOME", "D:\\scripts")
    yaml_body = (
        SAMPLE_YAML.rstrip()
        + "\nscripts:\n"
        + "  - name: Example\n"
        + "    path: ${SCRIPT_HOME}\\migrate\n"
        + "    command: python one_off.py\n"
    )
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.scripts[0].path == Path("D:\\scripts\\migrate")


def test_path_root_expands_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOS", "D:\\repos")
    yaml_body = SAMPLE_YAML.rstrip() + "\n    path_root: ${REPOS}\\FoxRunner\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.projects[0].path_root == Path("D:\\repos\\FoxRunner")


def test_project_without_health_url_defaults_none(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.projects[0].health_url is None


def test_project_health_url_parsed_when_provided(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    health_url: http://localhost:8000/health\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.projects[0].health_url == "http://localhost:8000/health"


def test_project_health_url_rejects_empty_string(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + '\n    health_url: ""\n'
    with pytest.raises(config.ConfigError, match="health_url"):
        config.load(write_config(tmp_path, yaml_body))


def test_config_without_auto_start_defaults_none(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.auto_start is None


def test_config_auto_start_accepts_existing_project_name(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n\nauto_start: FoxRunner\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.auto_start == "FoxRunner"


def test_config_auto_start_rejects_unknown_project_name(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n\nauto_start: NopeProject\n"
    with pytest.raises(config.ConfigError, match="auto_start"):
        config.load(write_config(tmp_path, yaml_body))
