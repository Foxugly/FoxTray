"""Tray icon images by state, cached once on first load."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image

IconState = Literal["running", "partial", "stopped"]

# This file sits at `foxtray/ui/icons.py` — three .parent hops reach the repo root.
# If this file ever moves, adjust the depth to keep _ASSETS pointing at <repo>/assets.
_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"

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
