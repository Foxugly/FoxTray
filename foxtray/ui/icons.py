"""Tray icon images by state, cached once on first load."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image

IconState = Literal["running", "partial", "stopped"]

_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
_cache: dict[IconState, Image.Image] = {}


def load(state: IconState) -> Image.Image:
    if state not in _cache:
        path = _ASSETS / f"icon_{state}.png"
        _cache[state] = Image.open(path).copy()
    return _cache[state]
