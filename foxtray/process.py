"""Windows-aware subprocess lifecycle: start under a new process group, kill the whole tree."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import psutil

from foxtray import logs


class ExecutableNotFound(FileNotFoundError):
    """Raised when the first token of a command cannot be resolved on PATH."""

log = logging.getLogger(__name__)

# On Windows CREATE_NEW_PROCESS_GROUP lets the child detach from our Ctrl+C
# while psutil gives us a portable tree-walk for shutdown.
_CREATION_FLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _resolve_command(command: list[str]) -> list[str]:
    # On Windows, subprocess.Popen with shell=False does NOT honor PATHEXT: calling
    # Popen(['ng', ...]) fails with FileNotFoundError because the real file is 'ng.CMD'.
    # shutil.which walks PATH + PATHEXT and returns the absolute path we need.
    if not command:
        raise ValueError("command must not be empty")
    exe = shutil.which(command[0])
    if exe is None:
        raise ExecutableNotFound(
            f"Executable not found on PATH: {command[0]!r}"
        )
    return [exe, *command[1:]]


class ProcessManager:
    """Starts child processes with stdout+stderr redirected to rotating log files."""

    def start(
        self,
        *,
        project: str,
        component: str,
        command: list[str],
        cwd: Path,
    ) -> subprocess.Popen[bytes]:
        resolved = _resolve_command(command)
        logs.rotate(project, component)
        log_file = logs.open_writer(project, component)
        try:
            return subprocess.Popen(
                resolved,
                cwd=str(cwd),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=_CREATION_FLAGS,
            )
        except Exception:
            log_file.close()
            raise

    def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
        """Terminate the process and every descendant it has."""
        try:
            root = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return

        descendants = root.children(recursive=True)
        victims = [root, *descendants]

        for proc in victims:
            try:
                proc.terminate()
            except psutil.NoSuchProcess:
                continue

        _, still_alive = psutil.wait_procs(victims, timeout=timeout)
        for proc in still_alive:
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                continue
        _, unkillable = psutil.wait_procs(still_alive, timeout=timeout)
        if unkillable:
            log.warning(
                "kill_tree: %d process(es) survived terminate+kill: %s",
                len(unkillable),
                [p.pid for p in unkillable],
            )
