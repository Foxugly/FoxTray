"""Orchestrates a backend+frontend pair on top of ProcessManager and state."""
from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from typing import Protocol

import psutil

from foxtray import config, health, process, state

log = logging.getLogger(__name__)


class _ManagerProtocol(Protocol):
    def start(
        self, *, project: str, component: str, command: list[str], cwd
    ) -> subprocess.Popen[bytes]: ...

    def kill_tree(self, pid: int, timeout: float = 5.0) -> None: ...


@dataclass(frozen=True)
class ProjectStatus:
    name: str
    has_frontend: bool
    running: bool
    backend_alive: bool
    frontend_alive: bool
    backend_port_listening: bool
    frontend_port_listening: bool
    url_ok: bool


class Orchestrator:
    def __init__(self, manager: _ManagerProtocol, cfg: config.Config) -> None:
        self._manager = manager
        self._cfg = cfg
        # Names of projects the user just asked to start but whose URL has not
        # yet responded healthy. Written by tray menu handlers (add on click,
        # discard on handler-level exception); read-and-discarded by the tray
        # poller in compute_transitions. Single-operation set mutations
        # (add/discard/in) are GIL-atomic in CPython — no lock needed because
        # the consumer never iterates concurrently with a writer.
        self.pending_starts: set[str] = set()

    def _project_by_name(self, name: str) -> config.Project | None:
        for p in self._cfg.projects:
            if p.name == name:
                return p
        return None

    def start(self, project: config.Project) -> None:
        current = state.load().active
        if current is not None:
            log.info("Stopping active project %s before starting %s", current.name, project.name)
            self._kill_pair(current.backend_pid, current.frontend_pid)
            state.clear()

        if not health.wait_port_free(project.backend.port, timeout=3.0):
            raise process.PortInUse(
                f"backend port {project.backend.port} still in use"
            )
        if project.frontend is not None and not health.wait_port_free(project.frontend.port, timeout=3.0):
            raise process.PortInUse(
                f"frontend port {project.frontend.port} still in use"
            )

        backend_popen = self._manager.start(
            project=project.name,
            component="backend",
            command=project.backend.resolved_command,
            cwd=project.backend.path,
        )
        frontend_pid: int | None = None
        if project.frontend is not None:
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
            frontend_pid = frontend_popen.pid
        state.save(
            state.State(
                active=state.ActiveProject(
                    name=project.name,
                    backend_pid=backend_popen.pid,
                    frontend_pid=frontend_pid,
                )
            )
        )

    def stop(self, name: str) -> None:
        current = state.load().active
        if current is None or current.name != name:
            return
        self._kill_pair(current.backend_pid, current.frontend_pid)
        state.clear()
        cfg_project = self._project_by_name(name)
        if cfg_project is None:
            return
        if not health.wait_port_free(cfg_project.backend.port, timeout=10.0):
            log.warning(
                "stop: backend port %s still listening after timeout",
                cfg_project.backend.port,
            )
        if cfg_project.frontend is not None and not health.wait_port_free(cfg_project.frontend.port, timeout=10.0):
            log.warning(
                "stop: frontend port %s still listening after timeout",
                cfg_project.frontend.port,
            )

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
        has_frontend = project.frontend is not None
        frontend_alive = (
            is_this_active
            and current.frontend_pid is not None
            and psutil.pid_exists(current.frontend_pid)
        )
        url_ok = health.http_ok(project.health_url or project.url) if (backend_alive and (frontend_alive or not has_frontend)) else False
        return ProjectStatus(
            name=project.name,
            has_frontend=has_frontend,
            running=backend_alive and (frontend_alive or not has_frontend),
            backend_alive=backend_alive,
            frontend_alive=frontend_alive,
            backend_port_listening=health.port_listening(project.backend.port) if backend_alive else False,
            frontend_port_listening=health.port_listening(project.frontend.port) if (has_frontend and frontend_alive) else False,
            url_ok=url_ok,
        )

    def wait_healthy(
        self,
        project: config.Project,
        timeout: float = 30.0,
        interval: float = 1.0,
    ) -> bool:
        """Poll self.status(project).url_ok until True or timeout elapses.

        Returns the final url_ok value (True if the URL responded within the
        window, False otherwise).
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.status(project).url_ok:
                return True
            time.sleep(interval)
        return self.status(project).url_ok

    def _kill_pair(self, backend_pid: int, frontend_pid: int | None) -> None:
        self._manager.kill_tree(backend_pid)
        if frontend_pid is not None:
            self._manager.kill_tree(frontend_pid)
