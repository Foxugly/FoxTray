"""Single-instance lock unit tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from foxtray import paths, singleton


def test_acquire_writes_current_pid(tmp_appdata: Path) -> None:
    singleton.acquire_lock()
    assert paths.tray_lock_file().exists()
    assert paths.tray_lock_file().read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_succeeds_when_no_existing_lock(tmp_appdata: Path) -> None:
    singleton.acquire_lock()
    singleton.release_lock()


def test_acquire_raises_lockheld_when_holder_alive(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.tray_lock_file().parent.mkdir(parents=True, exist_ok=True)
    other_pid = os.getpid() + 1 if os.getpid() != 99 else 100
    paths.tray_lock_file().write_text(str(other_pid), encoding="utf-8")
    monkeypatch.setattr(singleton.psutil, "pid_exists", lambda pid: pid == other_pid)
    with pytest.raises(singleton.LockHeldError, match="already running"):
        singleton.acquire_lock()


def test_acquire_overwrites_stale_lock(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.tray_lock_file().parent.mkdir(parents=True, exist_ok=True)
    paths.tray_lock_file().write_text("99999", encoding="utf-8")
    monkeypatch.setattr(singleton.psutil, "pid_exists", lambda pid: False)
    singleton.acquire_lock()
    assert paths.tray_lock_file().read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_tolerates_same_pid_rewrite(tmp_appdata: Path) -> None:
    paths.tray_lock_file().parent.mkdir(parents=True, exist_ok=True)
    paths.tray_lock_file().write_text(str(os.getpid()), encoding="utf-8")
    singleton.acquire_lock()
    assert paths.tray_lock_file().read_text(encoding="utf-8").strip() == str(os.getpid())


def test_acquire_tolerates_corrupt_lock_file(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.tray_lock_file().parent.mkdir(parents=True, exist_ok=True)
    paths.tray_lock_file().write_text("garbage-not-an-int", encoding="utf-8")
    monkeypatch.setattr(singleton.psutil, "pid_exists", lambda pid: True)
    singleton.acquire_lock()
    assert paths.tray_lock_file().read_text(encoding="utf-8").strip() == str(os.getpid())


def test_release_deletes_lock_when_ours(tmp_appdata: Path) -> None:
    singleton.acquire_lock()
    singleton.release_lock()
    assert not paths.tray_lock_file().exists()


def test_release_noop_when_file_missing(tmp_appdata: Path) -> None:
    singleton.release_lock()


def test_release_noop_when_other_pid_holds(tmp_appdata: Path) -> None:
    paths.tray_lock_file().parent.mkdir(parents=True, exist_ok=True)
    paths.tray_lock_file().write_text("99999", encoding="utf-8")
    singleton.release_lock()
    assert paths.tray_lock_file().exists()
    assert paths.tray_lock_file().read_text(encoding="utf-8").strip() == "99999"
