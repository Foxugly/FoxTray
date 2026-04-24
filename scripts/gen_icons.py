"""One-off icon generator. Re-run to update placeholder PNGs.

Usage:
    python scripts/gen_icons.py

Writes three 32x32 RGBA PNGs into assets/.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_SIZE = 32
_PADDING = 2  # leave a 2px margin so the disc doesn't touch the bounding box
_COLORS = {
    "running": (0x33, 0xAA, 0x33, 0xFF),   # green
    "partial": (0xEE, 0x99, 0x00, 0xFF),   # orange
    "stopped": (0x88, 0x88, 0x88, 0xFF),   # grey
}


def _write_ico() -> None:
    """Write assets/foxtray.ico — multi-resolution from the running (green) disc."""
    from PIL import Image
    src = _ASSETS / "icon_running.png"
    img = Image.open(src)
    img = img.resize((256, 256), Image.Resampling.LANCZOS)
    ico_path = _ASSETS / "foxtray.ico"
    img.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print(f"wrote {ico_path}")


def main() -> None:
    _ASSETS.mkdir(parents=True, exist_ok=True)
    for state, color in _COLORS.items():
        img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse(
            (_PADDING, _PADDING, _SIZE - _PADDING - 1, _SIZE - _PADDING - 1),
            fill=color,
        )
        out = _ASSETS / f"icon_{state}.png"
        img.save(out, format="PNG")
        print(f"wrote {out}")
    _write_ico()


if __name__ == "__main__":
    main()
