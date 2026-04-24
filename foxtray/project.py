"""Orchestrates a backend+frontend pair on top of ProcessManager and state."""
from __future__ import annotations

import logging
import subprocess
import threading
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
        # url_ok cache — status() is called on the tray poll thread (every 3s),
        # and a synchronous http_ok inside it would block the tick up to 1s.
        # refresh_url_ok (called by a dedicated worker thread in TrayApp, or
        # synchronously from wait_healthy in the CLI) updates the cache;
        # status() reads it without blocking.
        self._url_ok: dict[str, bool] = {}
        self._url_ok_lock = threading.Lock()

    def _project_by_name(self, name: str) -> config.Project | None:
        for p in self._cfg.projects:
            if p.name == name:
                return p
        return None

    def start(self, project: config.Project) -> None:
        current = state.load().active
        if current is not None:
            log.info("Stopping active project %s before starting %s", current.name, project.name)
            self._kill_pair(current)
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
        # Capture create_time immediately — this is the identity marker that
        # defeats Windows PID reuse. If the process died before we could read
        # it, treat the spawn as failed and let the caller retry.
        try:
            backend_ctime = psutil.Process(backend_popen.pid).create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            self._manager.kill_tree(backend_popen.pid)
            raise RuntimeError(
                f"backend for {project.name!r} exited before its identity could be captured"
            ) from exc
        frontend_pid: int | None = None
        frontend_ctime: float | None = None
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
            try:
                frontend_ctime = psutil.Process(frontend_popen.pid).create_time()
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                self._manager.kill_tree(backend_popen.pid)
                self._manager.kill_tree(frontend_popen.pid)
                raise RuntimeError(
                    f"frontend for {project.name!r} exited before its identity could be captured"
                ) from exc
            frontend_pid = frontend_popen.pid
        state.save(
            state.State(
                active=state.ActiveProject(
                    name=project.name,
                    backend_pid=backend_popen.pid,
                    backend_create_time=backend_ctime,
                    frontend_pid=frontend_pid,
                    frontend_create_time=frontend_ctime,
                )
            )
        )

    def stop(self, name: str) -> None:
        current = state.load().active
        if current is None or current.name != name:
            return
        self._kill_pair(current)
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
        self._kill_pair(current)
        state.clear()

    def status(self, project: config.Project) -> ProjectStatus:
        current = state.load().active
        is_this_active = current is not None and current.name == project.name
        backend_alive = is_this_active and state.pid_alive(
            current.backend_pid, current.backend_create_time
        )
        has_frontend = project.frontend is not None
        frontend_alive = (
            is_this_active
            and current.frontend_pid is not None
            and current.frontend_create_time is not None
            and state.pid_alive(current.frontend_pid, current.frontend_create_time)
        )
        # url_ok comes from the cache — an http probe here would block the
        # 3s tray poll tick. If the process is not alive, force-False so the
        # stale cache cannot outlive the process it described.
        if backend_alive and (frontend_alive or not has_frontend):
            with self._url_ok_lock:
                url_ok = self._url_ok.get(project.name, False)
        else:
            url_ok = False
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

    def refresh_url_ok(self, project: config.Project) -> bool:
        """Fetch ``http_ok`` for ``project`` and update the cache. Blocking.

        Meant to be called from a dedicated worker thread (see TrayApp's
        ``_url_refresh_loop``) or synchronously from CLI ``wait_healthy`` —
        never from the tray poll thread.
        """
        ok = health.http_ok(project.health_url or project.url)
        with self._url_ok_lock:
            self._url_ok[project.name] = ok
        return ok

    def wait_healthy(
        self,
        project: config.Project,
        timeout: float = 30.0,
        interval: float = 1.0,
    ) -> bool:
        """Poll url_ok until True or timeout elapses.

        Returns the final url_ok value (True if the URL responded within the
        window, False otherwise). Drives ``refresh_url_ok`` directly so the
        CLI path does not depend on a tray-side worker being alive.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.refresh_url_ok(project):
                return True
            time.sleep(interval)
        return self.refresh_url_ok(project)

    def _kill_pair(self, active: state.ActiveProject) -> None:
        """Kill the stored backend+frontend — but only if the PID's create_time
        still matches what we captured at spawn. Refusing to kill a PID whose
        identity we can no longer verify is what prevents us from killing an
        unrelated process that happens to inherit a recycled Windows PID.
        """
        if state.pid_alive(active.backend_pid, active.backend_create_time):
            self._manager.kill_tree(active.backend_pid)
        else:
            log.info(
                "_kill_pair: skipping backend pid %s for %s — identity no longer matches",
                active.backend_pid, active.name,
            )
        if active.frontend_pid is not None and active.frontend_create_time is not None:
            if state.pid_alive(active.frontend_pid, active.frontend_create_time):
                self._manager.kill_tree(active.frontend_pid)
            else:
                log.info(
                    "_kill_pair: skipping frontend pid %s for %s — identity no longer matches",
                    active.frontend_pid, active.name,
                )
