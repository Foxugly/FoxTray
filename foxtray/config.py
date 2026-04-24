"""Config loading and validation for FoxTray."""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when config.yaml is missing required fields or malformed."""


class ProjectNotFound(KeyError):
    """Raised when Config.get is called with a name that isn't in the config."""


@dataclass(frozen=True)
class Backend:
    path: Path
    venv: str
    command: str
    port: int

    @property
    def python_executable(self) -> Path:
        return self.path / self.venv / "Scripts" / "python.exe"

    @property
    def resolved_command(self) -> list[str]:
        # posix=True is safe here: commands never contain Windows paths (those live in
        # path/venv fields). Default posix mode strips quote characters from tokens,
        # which is what we want before handing the list to subprocess.Popen.
        parts = shlex.split(self.command)
        if not parts:
            raise ConfigError("backend.command is empty")
        if parts[0].lower() != "python":
            raise ConfigError(f"backend.command must start with 'python', got {parts[0]!r}")
        return [str(self.python_executable), *parts[1:]]


@dataclass(frozen=True)
class Frontend:
    path: Path
    command: str
    port: int

    @property
    def resolved_command(self) -> list[str]:
        # See Backend.resolved_command for why posix=True is correct here.
        return shlex.split(self.command)


@dataclass(frozen=True)
class Task:
    name: str
    cwd: str  # "backend" | "frontend"
    command: str

    def resolved_command(self, project: "Project") -> list[str]:
        parts = shlex.split(self.command)
        if not parts:
            raise ConfigError(f"task {self.name!r} command is empty")
        if self.cwd == "backend" and parts[0].lower() == "python":
            return [str(project.backend.python_executable), *parts[1:]]
        return parts

    def resolved_cwd(self, project: "Project") -> Path:
        if self.cwd == "backend":
            return project.backend.path
        if project.frontend is None:
            raise ConfigError(
                f"project {project.name!r} task {self.name!r}: cwd 'frontend' requires a frontend"
            )
        return project.frontend.path


@dataclass(frozen=True)
class Project:
    name: str
    url: str
    backend: Backend
    frontend: Frontend | None
    start_timeout: int = 30
    tasks: tuple[Task, ...] = ()
    path_root: Path | None = None
    health_url: str | None = None


@dataclass(frozen=True)
class Script:
    name: str
    path: Path
    command: str
    venv: str | None = None

    def resolved_command(self) -> list[str]:
        parts = shlex.split(self.command)
        if not parts:
            raise ConfigError(f"script {self.name!r} command is empty")
        if self.venv and parts[0].lower() == "python":
            return [str(self.path / self.venv / "Scripts" / "python.exe"), *parts[1:]]
        return parts


@dataclass(frozen=True)
class Config:
    projects: list[Project] = field(default_factory=list)
    scripts: tuple[Script, ...] = ()
    auto_start: str | None = None
    log_retention: int = 2

    def get(self, name: str) -> Project:
        for project in self.projects:
            if project.name == name:
                return project
        raise ProjectNotFound(name)


def _expand_path(raw: str) -> Path:
    return Path(os.path.expandvars(raw))


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"missing required key {key!r} in {context}")
    return mapping[key]


def _parse_backend(raw: dict[str, Any]) -> Backend:
    backend = Backend(
        path=_expand_path(_require(raw, "path", "backend")),
        venv=_require(raw, "venv", "backend"),
        command=_require(raw, "command", "backend"),
        port=int(_require(raw, "port", "backend")),
    )
    # Trigger validation-by-construction: resolved_command raises ConfigError if invalid.
    _ = backend.resolved_command
    return backend


def _parse_frontend(raw: dict[str, Any] | None) -> Frontend | None:
    if raw is None:
        return None
    return Frontend(
        path=_expand_path(_require(raw, "path", "frontend")),
        command=_require(raw, "command", "frontend"),
        port=int(_require(raw, "port", "frontend")),
    )


def _parse_task(raw: dict[str, Any], project_name: str) -> Task:
    if not isinstance(raw, dict):
        raise ConfigError(f"project {project_name!r}: each task must be a mapping")
    name = _require(raw, "name", f"project {project_name!r} task")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"project {project_name!r}: task name must be a non-empty string")
    cwd = _require(raw, "cwd", f"project {project_name!r} task {name!r}")
    if cwd not in ("backend", "frontend"):
        raise ConfigError(
            f"project {project_name!r} task {name!r}: cwd must be 'backend' or 'frontend', got {cwd!r}"
        )
    command = _require(raw, "command", f"project {project_name!r} task {name!r}")
    if not isinstance(command, str) or not shlex.split(command):
        raise ConfigError(
            f"project {project_name!r} task {name!r}: command must be a non-empty string"
        )
    return Task(name=name, cwd=cwd, command=command)


def _parse_project(raw: dict[str, Any]) -> Project:
    name = _require(raw, "name", "project")
    start_timeout_raw = raw.get("start_timeout", 30)
    if not isinstance(start_timeout_raw, int) or isinstance(start_timeout_raw, bool):
        raise ConfigError(
            f"project {name!r}: start_timeout must be a positive integer, got {start_timeout_raw!r}"
        )
    if start_timeout_raw <= 0:
        raise ConfigError(
            f"project {name!r}: start_timeout must be > 0, got {start_timeout_raw}"
        )
    frontend = _parse_frontend(raw.get("frontend"))
    tasks_raw = raw.get("tasks", [])
    if not isinstance(tasks_raw, list):
        raise ConfigError(f"project {name!r}: tasks must be a list")
    tasks = tuple(_parse_task(t, name) for t in tasks_raw)
    task_names = [t.name for t in tasks]
    duplicate_tasks = {n for n in task_names if task_names.count(n) > 1}
    if duplicate_tasks:
        raise ConfigError(
            f"project {name!r}: duplicate task names: {sorted(duplicate_tasks)}"
        )
    if frontend is None and any(task.cwd == "frontend" for task in tasks):
        raise ConfigError(
            f"project {name!r}: frontend tasks require a configured frontend"
        )
    path_root_raw = raw.get("path_root")
    path_root: Path | None = None
    if path_root_raw is not None:
        path_root = _expand_path(path_root_raw)
        if not path_root.is_absolute():
            raise ConfigError(
                f"project {name!r}: path_root must be absolute, got {path_root_raw!r}"
            )
    health_url_raw = raw.get("health_url")
    if health_url_raw is not None and (not isinstance(health_url_raw, str) or not health_url_raw):
        raise ConfigError(
            f"project {name!r}: health_url must be a non-empty string if present"
        )
    return Project(
        name=name,
        url=_require(raw, "url", f"project {name!r}"),
        backend=_parse_backend(_require(raw, "backend", f"project {name!r}")),
        frontend=frontend,
        start_timeout=start_timeout_raw,
        tasks=tasks,
        path_root=path_root,
        health_url=health_url_raw,
    )


def _parse_script(raw: dict[str, Any]) -> Script:
    if not isinstance(raw, dict):
        raise ConfigError("each script must be a mapping")
    name = _require(raw, "name", "script")
    if not isinstance(name, str) or not name:
        raise ConfigError("script name must be a non-empty string")
    path_raw = _require(raw, "path", f"script {name!r}")
    path = _expand_path(path_raw)
    if not path.is_absolute():
        raise ConfigError(f"script {name!r}: path must be absolute, got {path_raw!r}")
    command = _require(raw, "command", f"script {name!r}")
    if not isinstance(command, str) or not shlex.split(command):
        raise ConfigError(f"script {name!r}: command must be a non-empty string")
    venv = raw.get("venv")
    if venv is not None and (not isinstance(venv, str) or not venv):
        raise ConfigError(f"script {name!r}: venv must be a non-empty string if present")
    return Script(name=name, path=path, command=command, venv=venv)


def load(path: Path) -> Config:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    projects_raw = raw.get("projects", [])
    if not isinstance(projects_raw, list):
        raise ConfigError("'projects' must be a list")
    projects = [_parse_project(p) for p in projects_raw]
    names = [p.name for p in projects]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ConfigError(f"duplicate project names: {sorted(duplicates)}")
    scripts_raw = raw.get("scripts", [])
    if not isinstance(scripts_raw, list):
        raise ConfigError("'scripts' must be a list")
    scripts = tuple(_parse_script(s) for s in scripts_raw)
    script_names = [s.name for s in scripts]
    dup_scripts = {n for n in script_names if script_names.count(n) > 1}
    if dup_scripts:
        raise ConfigError(f"duplicate script names: {sorted(dup_scripts)}")
    auto_start_raw = raw.get("auto_start")
    if auto_start_raw is not None:
        if not isinstance(auto_start_raw, str) or not auto_start_raw:
            raise ConfigError("auto_start must be a non-empty string if present")
        if auto_start_raw not in [p.name for p in projects]:
            raise ConfigError(
                f"auto_start references unknown project {auto_start_raw!r}"
            )
    log_retention_raw = raw.get("log_retention", 2)
    if not isinstance(log_retention_raw, int) or isinstance(log_retention_raw, bool) or log_retention_raw < 1:
        raise ConfigError(
            f"log_retention must be a positive integer, got {log_retention_raw!r}"
        )
    return Config(projects=projects, scripts=scripts, auto_start=auto_start_raw, log_retention=log_retention_raw)
