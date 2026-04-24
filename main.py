"""Entry point: ``python main.py <command>``."""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path


def _bootstrap_log_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.environ.get("FOXTRAY_APPDATA")
    if override:
        paths.append(Path(override) / "logs" / "bootstrap.log")
    else:
        if getattr(sys, "frozen", False):
            paths.append(Path(sys.executable).resolve().parent / "bootstrap.log")
        appdata = os.environ.get("APPDATA")
        if appdata:
            paths.append(Path(appdata) / "foxtray" / "logs" / "bootstrap.log")
        paths.append(Path(tempfile.gettempdir()) / "foxtray" / "bootstrap.log")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def _write_bootstrap_failure(exc: BaseException) -> None:
    for path in _bootstrap_log_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write("=== FoxTray bootstrap failure ===\n")
                fh.write(f"argv={sys.argv!r}\n")
                fh.write(f"python={sys.executable}\n")
                fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
                fh.write("\n")
            return
        except Exception:
            continue


if __name__ == "__main__":
    try:
        from foxtray import cli
        sys.exit(cli.main())
    except BaseException as exc:
        _write_bootstrap_failure(exc)
        raise
