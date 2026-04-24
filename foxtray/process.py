"""Windows-aware subprocess lifecycle: start under a new process group, kill the whole tree."""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path

import psutil

from foxtray import logs


class ExecutableNotFound(FileNotFoundError):
    """Raised when the first token of a command cannot be resolved on PATH."""


class PortInUse(RuntimeError):
    """Raised by Orchestrator.start when a required port is still occupied."""


log = logging.getLogger(__name__)

# On Windows keep a separate process group for clean shutdowns and suppress
# child console windows because output is already redirected to log files.
_CREATION_FLAGS = (
    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
)


def _resolve_command(command: list[str]) -> list[str]:
    # On Windows, subprocess.Popen with shell=False does NOT honor PATHEXT: calling
    # Popen(['ng', ...]) fails with FileNotFoundError because the real file is 'ng.CMD'.
    # shutil.which walks PATH + PATHEXT and returns the absolute path we need; for
    # an absolute path it returns the path unchanged if the file exists, else None.
    if not command:
        raise ValueError("command must not be empty")
    raw = command[0]
    exe = shutil.which(raw)
    if exe is None:
        # Distinguish "bare name that PATH doesn't resolve" from "absolute path
        # that points at a nonexistent file" — the latter is usually a config
        # issue (missing venv) and deserves a clearer error.
        if Path(raw).is_absolute() or "/" in raw or "\\" in raw:
            raise ExecutableNotFound(f"Executable does not exist: {raw}")
        raise ExecutableNotFound(f"Executable not found on PATH: {raw!r}")
    return [exe, *command[1:]]


def spawn_with_log(
    command: list[str], cwd: Path, log_file
) -> subprocess.Popen[bytes]:
    """Spawn a process with stdout+stderr redirected to log_file.

    Resolves the command via the same _resolve_command path used by
    ProcessManager.start (so PATHEXT / absolute-path quirks behave the same),
    closes log_file (success AND failure) so the parent doesn't leak a fd —
    the child inherits its own duplicated handle via CreateProcess and keeps
    writing to the log independently. Uses the module's _CREATION_FLAGS.
    Caller owns the Popen's lifecycle.
    """
    try:
        resolved = _resolve_command(command)
        popen = subprocess.Popen(
            resolved,
            cwd=str(cwd),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=_CREATION_FLAGS,
        )
    except Exception:
        log_file.close()
        raise
    log_file.close()
    return popen


class ProcessManager:
    """Starts child processes with stdout+stderr redirected to rotating log files."""

    def __init__(self, log_retention: int = 2) -> None:
        self._log_retention = log_retention

    def start(
        self,
        *,
        project: str,
        component: str,
        command: list[str],
        cwd: Path,
    ) -> subprocess.Popen[bytes]:
        logs.rotate(project, component, keep=self._log_retention)
        log_file = logs.open_writer(project, component)
        return spawn_with_log(command, cwd, log_file)

    def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
        """Terminate the process and every descendant it has.

        Sweeps ``root.children(recursive=True)`` repeatedly so that descendants
        spawned *after* the initial snapshot are still caught — the classic
        ``npm → ng → node.exe`` late-spawn case that leaks orphans when the
        snapshot is taken only once. Always performs at least two sweeps
        (empty-after-activity) before declaring the tree quiet. Any survivor
        from the union of all PIDs seen is then force-killed.
        """
        try:
            root = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return

        deadline = time.monotonic() + timeout
        seen: dict[int, psutil.Process] = {pid: root}

        max_sweeps = 8
        for sweep in range(max_sweeps):
            if time.monotonic() >= deadline:
                break
            try:
                descendants = root.children(recursive=True)
            except psutil.NoSuchProcess:
                descendants = []
            new_procs = [p for p in descendants if p.pid not in seen]
            # First sweep always terminates root too; subsequent sweeps terminate
            # only newly-seen descendants (root is already marked in `seen`).
            batch = ([root] + new_procs) if sweep == 0 else new_procs
            for proc in batch:
                seen.setdefault(proc.pid, proc)
                try:
                    proc.terminate()
                except psutil.NoSuchProcess:
                    continue
            psutil.wait_procs(batch, timeout=0.2)
            # Exit when at least one follow-up sweep has seen no newcomers —
            # gives a late spawner one window to fire.
            if sweep >= 1 and not new_procs:
                break

        wait_budget = max(deadline - time.monotonic(), 0.5)
        _, still_alive = psutil.wait_procs(list(seen.values()), timeout=wait_budget)
        for proc in still_alive:
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                continue
        _, unkillable = psutil.wait_procs(
            still_alive, timeout=max(deadline - time.monotonic(), 0.5)
        )
        if unkillable:
            log.warning(
                "kill_tree: %d process(es) survived terminate+kill: %s",
                len(unkillable),
                [p.pid for p in unkillable],
            )
