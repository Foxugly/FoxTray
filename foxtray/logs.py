"""Per-project/component log files with one-deep rotation."""
from __future__ import annotations

from pathlib import Path
from typing import IO

from foxtray import paths


def _previous_path(project: str, component: str) -> Path:
    current = paths.log_file(project, component)
    return current.parent / f"{current.stem}.log.1"


def rotate(project: str, component: str, keep: int = 2) -> None:
    """Rotate X.log → X.log.1 → … → X.log.{keep-1}. Oldest is unlinked.

    keep <= 1 is a no-op (no rotation). keep == 2 = current + 1 backup
    (existing default behavior)."""
    if keep <= 1:
        return
    paths.ensure_dirs()
    current = paths.log_file(project, component)
    if not current.exists():
        return
    stem_dir = current.parent
    base = current.stem
    oldest = stem_dir / f"{base}.log.{keep - 1}"
    if oldest.exists():
        oldest.unlink()
    for i in range(keep - 2, 0, -1):
        src = stem_dir / f"{base}.log.{i}"
        dst = stem_dir / f"{base}.log.{i + 1}"
        if src.exists():
            src.rename(dst)
    current.rename(stem_dir / f"{base}.log.1")


def open_writer(project: str, component: str) -> IO[str]:
    """Open the current log file for writing. Caller is responsible for closing."""
    paths.ensure_dirs()
    return paths.log_file(project, component).open("w", encoding="utf-8", buffering=1)


def tail(project: str, component: str, lines: int = 200) -> list[str]:
    path = paths.log_file(project, component)
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8").splitlines()
    return content[-lines:]


def _previous_task_path(key: str) -> Path:
    current = paths.task_log_file(key)
    return current.parent / f"{current.stem}.log.1"


def rotate_task(key: str) -> None:
    """Rotate the log file for a task/script key. Creates the tasks/ subdir."""
    current = paths.task_log_file(key)
    current.parent.mkdir(parents=True, exist_ok=True)
    if not current.exists():
        return
    previous = _previous_task_path(key)
    if previous.exists():
        previous.unlink()
    current.rename(previous)


def open_task_writer(key: str) -> IO[str]:
    """Open the current task log file for writing. Caller closes."""
    path = paths.task_log_file(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8", buffering=1)
