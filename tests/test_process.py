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
