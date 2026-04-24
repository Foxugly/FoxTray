import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from foxtray import process


HELPER = Path(__file__).parent / "helpers" / "child_tree.py"


@pytest.fixture
def manager(tmp_appdata: Path) -> process.ProcessManager:
    return process.ProcessManager()


def _spawn_tree() -> subprocess.Popen:
    popen = subprocess.Popen(
        [sys.executable, str(HELPER)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    # Wait until helper has printed the grandchild PID so the tree exists.
    popen.stdout.readline()
    return popen


def test_kill_tree_reaps_child_and_grandchild(manager: process.ProcessManager) -> None:
    popen = _spawn_tree()
    root_pid = popen.pid
    descendants = psutil.Process(root_pid).children(recursive=True)
    assert len(descendants) >= 1, "test helper should have spawned a grandchild"
    descendant_pids = [p.pid for p in descendants]

    manager.kill_tree(root_pid, timeout=5.0)

    assert not psutil.pid_exists(root_pid)
    for pid in descendant_pids:
        assert not psutil.pid_exists(pid)


def test_kill_tree_on_missing_pid_is_noop(manager: process.ProcessManager) -> None:
    # 1 is never a valid PID on Windows.
    manager.kill_tree(1, timeout=0.5)


def test_kill_tree_sweeps_until_no_new_descendants(
    manager: process.ProcessManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: a descendant that appears *after* the initial snapshot must
    still be terminated. Reproduces the `npm → ng → node` late-spawn scenario
    deterministically via a fake that reveals the grandchild only on sweep #2.
    """

    class FakeProc:
        def __init__(self, pid: int) -> None:
            self.pid = pid
            self.terminated = False
            self.killed = False

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def is_running(self) -> bool:
            return False

        def wait(self, timeout: float | None = None) -> int:
            return 0

    late = FakeProc(pid=5002)
    root = FakeProc(pid=5000)

    class Enumerator:
        def __init__(self) -> None:
            self.sweep = 0
            self.snapshots = [
                [],          # sweep 1: no descendants yet
                [late],      # sweep 2: late-spawned grandchild appears
                [late],      # sweep 3: stable -> loop exits
                [],          # tail re-enumeration
            ]

        def children(self, recursive: bool = True) -> list[FakeProc]:
            snap = self.snapshots[min(self.sweep, len(self.snapshots) - 1)]
            self.sweep += 1
            return snap

    root_enum = Enumerator()
    root.children = root_enum.children  # type: ignore[attr-defined]

    def _process(pid: int) -> FakeProc:
        if pid == root.pid:
            return root
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", _process)
    monkeypatch.setattr(psutil, "wait_procs", lambda procs, timeout=None: ([], []))

    manager.kill_tree(root.pid, timeout=5.0)

    assert root.terminated, "root must be terminated"
    assert late.terminated, (
        "late-spawned descendant must be terminated on a subsequent sweep — "
        "kill_tree used to snapshot once and leak late arrivals"
    )


def test_start_returns_popen_and_writes_log(
    manager: process.ProcessManager, tmp_appdata: Path
) -> None:
    popen = manager.start(
        project="UnitTest",
        component="backend",
        command=[sys.executable, "-c", "print('hello'); import sys; sys.stdout.flush()"],
        cwd=Path.cwd(),
    )
    popen.wait(timeout=5.0)

    log_path = tmp_appdata / "logs" / "UnitTest_backend.log"
    # Give the OS a beat to flush.
    for _ in range(20):
        if log_path.exists() and log_path.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.1)
    assert "hello" in log_path.read_text(encoding="utf-8")


def test_start_resolves_bare_executable_name(
    manager: process.ProcessManager, tmp_appdata: Path
) -> None:
    """Regression: on Windows Popen(['ng', ...]) fails — _resolve_command must find ng.CMD.

    We use 'python' (no extension) which is guaranteed on PATH wherever this test runs.
    The plain 'python' string would fail inside Popen on Windows the same way 'ng' did.
    """
    popen = manager.start(
        project="UnitTest",
        component="backend",
        command=["python", "-c", "pass"],
        cwd=Path.cwd(),
    )
    popen.wait(timeout=5.0)
    assert popen.returncode == 0


def test_start_raises_executable_not_found_for_missing_bin(
    manager: process.ProcessManager, tmp_appdata: Path
) -> None:
    with pytest.raises(process.ExecutableNotFound, match="not found on PATH"):
        manager.start(
            project="UnitTest",
            component="backend",
            command=["not-a-real-binary-xyzzy", "--help"],
            cwd=Path.cwd(),
        )


def test_start_raises_executable_not_found_for_missing_absolute_path(
    manager: process.ProcessManager, tmp_appdata: Path, tmp_path: Path
) -> None:
    # Missing venv scenario: config points to a python.exe that doesn't exist.
    # Error message must say "does not exist", not "not found on PATH", since
    # PATH is irrelevant for absolute paths.
    missing = tmp_path / "nonexistent" / "python.exe"
    with pytest.raises(process.ExecutableNotFound, match="does not exist"):
        manager.start(
            project="UnitTest",
            component="backend",
            command=[str(missing), "manage.py", "runserver"],
            cwd=Path.cwd(),
        )


def test_start_rotates_previous_log(
    manager: process.ProcessManager, tmp_appdata: Path
) -> None:
    logs_dir = tmp_appdata / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "UnitTest_backend.log").write_text("OLD", encoding="utf-8")

    popen = manager.start(
        project="UnitTest",
        component="backend",
        command=[sys.executable, "-c", "pass"],
        cwd=Path.cwd(),
    )
    popen.wait(timeout=5.0)

    assert (logs_dir / "UnitTest_backend.log.1").read_text(encoding="utf-8") == "OLD"


def test_port_in_use_is_a_runtime_error() -> None:
    from foxtray.process import PortInUse
    exc = PortInUse("port 8000 still in use")
    assert isinstance(exc, RuntimeError)
    assert "8000" in str(exc)


def test_spawn_with_log_runs_command_and_redirects_output(tmp_path: Path) -> None:
    from foxtray import process

    log_file = (tmp_path / "out.log").open("w", encoding="utf-8", buffering=1)
    popen = process.spawn_with_log(
        [sys.executable, "-c", "print('hello')"],
        cwd=tmp_path,
        log_file=log_file,
    )
    popen.wait()
    log_file.close()
    content = (tmp_path / "out.log").read_text(encoding="utf-8")
    assert "hello" in content


def test_spawn_with_log_closes_log_file_on_popen_failure(tmp_path: Path) -> None:
    from foxtray import process

    log_file = (tmp_path / "out.log").open("w", encoding="utf-8", buffering=1)
    with pytest.raises(process.ExecutableNotFound):
        process.spawn_with_log(
            ["definitely-not-a-real-binary-abc123"],
            cwd=tmp_path,
            log_file=log_file,
        )
    # log_file should be closed after the raise
    assert log_file.closed


def test_spawn_with_log_closes_parent_fd_on_success(tmp_path: Path) -> None:
    """The parent's log_file handle must be closed after Popen succeeds.
    The child inherits its own duplicated handle via CreateProcess, so the
    parent's reference is a pure leak for the life of the Popen."""
    from foxtray import process

    log_file = (tmp_path / "out.log").open("w", encoding="utf-8", buffering=1)
    popen = process.spawn_with_log(
        [sys.executable, "-c", "print('hello')"],
        cwd=tmp_path,
        log_file=log_file,
    )
    try:
        popen.wait(timeout=5)
    finally:
        if popen.poll() is None:
            popen.kill()
    assert log_file.closed, "parent log_file must be closed after spawn"
    # Child's writes must still land despite parent-side close.
    assert "hello" in (tmp_path / "out.log").read_text(encoding="utf-8")


def test_process_manager_passes_log_retention_to_rotate(
    tmp_appdata: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from foxtray import logs, process
    rotate_calls: list[tuple[str, str, int]] = []
    def _fake_rotate(project: str, component: str, keep: int = 2) -> None:
        rotate_calls.append((project, component, keep))
    monkeypatch.setattr(logs, "rotate", _fake_rotate)
    # Still need a valid log file writer
    monkeypatch.setattr(logs, "open_writer", lambda p, c: (tmp_path / "x.log").open("w"))
    # Spawn fails because command is bogus — but that's AFTER rotate is called
    def _fake_spawn(*args, **kwargs):
        raise RuntimeError("stop here")
    monkeypatch.setattr(process, "spawn_with_log", _fake_spawn)
    mgr = process.ProcessManager(log_retention=5)
    try:
        mgr.start(project="X", component="b", command=["x"], cwd=tmp_path)
    except RuntimeError:
        pass
    assert rotate_calls == [("X", "b", 5)]
