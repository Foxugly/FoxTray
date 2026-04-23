"""Config loading and validation for FoxTray."""
from __future__ import annotations

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
class Project:
    name: str
    url: str
    backend: Backend
    frontend: Frontend
    start_timeout: int = 30


@dataclass(frozen=True)
class Config:
    projects: list[Project] = field(default_factory=list)

    def get(self, name: str) -> Project:
        for project in self.projects:
            if project.name == name:
                return project
        raise ProjectNotFound(name)


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"missing required key {key!r} in {context}")
    return mapping[key]


def _parse_backend(raw: dict[str, Any]) -> Backend:
    backend = Backend(
        path=Path(_require(raw, "path", "backend")),
        venv=_require(raw, "venv", "backend"),
        command=_require(raw, "command", "backend"),
        port=int(_require(raw, "port", "backend")),
    )
    # Trigger validation-by-construction: resolved_command raises ConfigError if invalid.
    _ = backend.resolved_command
    return backend


def _parse_frontend(raw: dict[str, Any]) -> Frontend:
    return Frontend(
        path=Path(_require(raw, "path", "frontend")),
        command=_require(raw, "command", "frontend"),
        port=int(_require(raw, "port", "frontend")),
    )


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
    return Project(
        name=name,
        url=_require(raw, "url", f"project {name!r}"),
        backend=_parse_backend(_require(raw, "backend", f"project {name!r}")),
        frontend=_parse_frontend(_require(raw, "frontend", f"project {name!r}")),
        start_timeout=start_timeout_raw,
    )


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
    return Config(projects=projects)
