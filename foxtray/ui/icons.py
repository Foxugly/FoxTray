"""Tray icon images by state, cached once on first load."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from PIL import Image

IconState = Literal["running", "partial", "stopped"]

def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
        return base / "assets"
    return Path(__file__).resolve().parent.parent.parent / "assets"


_ASSETS = _assets_dir()

# Not guarded by a lock. The GIL prevents corruption of the dict, and Image
# objects are never mutated after creation, so the worst race case is two
# threads briefly holding different in-memory copies of the same pixel data —
# harmless for our read-only consumers (pystray's image serialiser).
_cache: dict[IconState, Image.Image] = {}


def load(state: IconState) -> Image.Image:
    if state not in _cache:
        path = _ASSETS / f"icon_{state}.png"
        _cache[state] = Image.open(path).copy()
    return _cache[state]
