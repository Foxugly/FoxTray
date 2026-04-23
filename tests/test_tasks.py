"""TaskManager unit tests with real short-lived Popens."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from foxtray import tasks


def _python_exit(code: int) -> list[str]:
    return [sys.executable, "-c", f"import sys; sys.exit({code})"]


def _python_sleep(seconds: float) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def _collect_completions(expected: int, timeout: float = 5.0):
    """Return (callback, done_event, completions_list). done_event fires when
    `expected` completions have been recorded."""
    done = threading.Event()
    completions: list[tuple[str, int]] = []

    def _cb(key: str, exit_code: int) -> None:
        completions.append((key, exit_code))
        if len(completions) >= expected:
            done.set()

    return _cb, done, completions


def test_run_spawns_and_registers(tmp_appdata: Path, tmp_path: Path) -> None:
    kills: list[int] = []
    cb, done, completions = _collect_completions(1)
    tm = tasks.TaskManager(kill_tree=kills.append, on_complete=cb)
    tm.run("task:A:Test", _python_exit(0), tmp_path)
    assert done.wait(5.0), "completion callback did not fire"
    assert completions == [("task:A:Test", 0)]
    assert not tm.is_running("task:A:Test")


def test_run_second_time_same_key_raises(
    tmp_appdata: Path, tmp_path: Path
) -> None:
    cb, _done, _completions = _collect_completions(1)
    tm = tasks.TaskManager(kill_tree=lambda pid: None, on_complete=cb)
    tm.run("task:A:Sleep", _python_sleep(2), tmp_path)
    with pytest.raises(tasks.TaskAlreadyRunning):
        tm.run("task:A:Sleep", _python_sleep(2), tmp_path)
    tm.kill_all()  # cleanup


def test_is_running_and_running_keys(tmp_appdata: Path, tmp_path: Path) -> None:
    cb, _done, _completions = _collect_completions(1)
    tm = tasks.TaskManager(kill_tree=lambda pid: None, on_complete=cb)
    tm.run("task:A:Sleep", _python_sleep(2), tmp_path)
    assert tm.is_running("task:A:Sleep")
    assert tm.running_keys() == {"task:A:Sleep"}
    tm.kill_all()


def test_on_complete_gets_nonzero_exit(tmp_appdata: Path, tmp_path: Path) -> None:
    cb, done, completions = _collect_completions(1)
    tm = tasks.TaskManager(kill_tree=lambda pid: None, on_complete=cb)
    tm.run("task:A:Fail", _python_exit(1), tmp_path)
    assert done.wait(5.0)
    assert completions == [("task:A:Fail", 1)]


def test_kill_all_kills_tracked_popens_and_returns_count(
    tmp_appdata: Path, tmp_path: Path
) -> None:
    killed_pids: list[int] = []
    cb, _done, _completions = _collect_completions(2)
    tm = tasks.TaskManager(kill_tree=killed_pids.append, on_complete=cb)
    tm.run("task:A:One", _python_sleep(10), tmp_path)
    tm.run("task:A:Two", _python_sleep(10), tmp_path)
    killed = tm.kill_all()
    assert killed == 2
    assert len(killed_pids) == 2
    # After kill_all, running_keys should be empty immediately (dict cleared
    # before kill_tree calls).
    assert tm.running_keys() == set()


def test_on_complete_exception_does_not_crash_watcher(
    tmp_appdata: Path, tmp_path: Path
) -> None:
    def _bad_cb(key: str, exit_code: int) -> None:
        raise RuntimeError("boom")

    tm = tasks.TaskManager(kill_tree=lambda pid: None, on_complete=_bad_cb)
    tm.run("task:A:Test", _python_exit(0), tmp_path)
    # Give the watcher time to complete and hit the except
    deadline = time.monotonic() + 3.0
    while tm.is_running("task:A:Test") and time.monotonic() < deadline:
        time.sleep(0.05)
    # The watcher should have removed the key even though the callback raised
    assert not tm.is_running("task:A:Test")
