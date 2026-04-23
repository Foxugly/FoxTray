"""Per-project/component log files with one-deep rotation."""
from __future__ import annotations

from typing import IO

from foxtray import paths


def _previous_path(project: str, component: str):
    current = paths.log_file(project, component)
    return current.parent / f"{current.stem}.log.1"


def rotate(project: str, component: str) -> None:
    paths.ensure_dirs()
    current = paths.log_file(project, component)
    if not current.exists():
        return
    previous = _previous_path(project, component)
    if previous.exists():
        previous.unlink()
    current.rename(previous)


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
