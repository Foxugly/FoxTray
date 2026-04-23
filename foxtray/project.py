"""Orchestrates a backend+frontend pair on top of ProcessManager and state."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Protocol

import psutil

from foxtray import config, health, state

log = logging.getLogger(__name__)


class _ManagerProtocol(Protocol):
    def start(
        self, *, project: str, component: str, command: list[str], cwd
    ) -> subprocess.Popen[bytes]: ...

    def kill_tree(self, pid: int, timeout: float = 5.0) -> None: ...


@dataclass(frozen=True)
class ProjectStatus:
    name: str
    running: bool
    backend_alive: bool
    frontend_alive: bool
    backend_port_listening: bool
    frontend_port_listening: bool
    url_ok: bool


class Orchestrator:
    def __init__(self, manager: _ManagerProtocol) -> None:
        self._manager = manager

    def start(self, project: config.Project) -> None:
        current = state.load().active
        if current is not None:
            log.info("Stopping active project %s before starting %s", current.name, project.name)
            self._kill_pair(current.backend_pid, current.frontend_pid)
            state.clear()

        backend_popen = self._manager.start(
            project=project.name,
            component="backend",
            command=project.backend.resolved_command,
            cwd=project.backend.path,
        )
        try:
            frontend_popen = self._manager.start(
                project=project.name,
                component="frontend",
                command=project.frontend.resolved_command,
                cwd=project.frontend.path,
            )
        except Exception:
            self._manager.kill_tree(backend_popen.pid)
            raise
        state.save(
            state.State(
                active=state.ActiveProject(
                    name=project.name,
                    backend_pid=backend_popen.pid,
                    frontend_pid=frontend_popen.pid,
                )
            )
        )

    def stop(self, name: str) -> None:
        current = state.load().active
        if current is None or current.name != name:
            return
        self._kill_pair(current.backend_pid, current.frontend_pid)
        state.clear()

    def stop_all(self) -> None:
        current = state.load().active
        if current is None:
            return
        self._kill_pair(current.backend_pid, current.frontend_pid)
        state.clear()

    def status(self, project: config.Project) -> ProjectStatus:
        current = state.load().active
        is_this_active = current is not None and current.name == project.name
        backend_alive = is_this_active and psutil.pid_exists(current.backend_pid)
        frontend_alive = is_this_active and psutil.pid_exists(current.frontend_pid)
        return ProjectStatus(
            name=project.name,
            running=backend_alive and frontend_alive,
            backend_alive=backend_alive,
            frontend_alive=frontend_alive,
            backend_port_listening=health.port_listening(project.backend.port) if backend_alive else False,
            frontend_port_listening=health.port_listening(project.frontend.port) if frontend_alive else False,
            url_ok=health.http_ok(project.url) if (backend_alive and frontend_alive) else False,
        )

    def _kill_pair(self, backend_pid: int, frontend_pid: int) -> None:
        self._manager.kill_tree(backend_pid)
        self._manager.kill_tree(frontend_pid)
