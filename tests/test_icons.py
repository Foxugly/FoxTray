from pathlib import Path

import pytest
from PIL import Image

from foxtray.ui import icons


def test_load_returns_image_for_running() -> None:
    img = icons.load("running")
    assert isinstance(img, Image.Image)
    assert img.size == (32, 32)


def test_load_returns_image_for_partial() -> None:
    img = icons.load("partial")
    assert isinstance(img, Image.Image)


def test_load_returns_image_for_stopped() -> None:
    img = icons.load("stopped")
    assert isinstance(img, Image.Image)


def test_load_is_cached() -> None:
    first = icons.load("running")
    second = icons.load("running")
    assert first is second


def test_assets_dir_uses_meipass_when_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from foxtray.ui import icons
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)
    assert icons._assets_dir() == tmp_path / "assets"


def test_assets_dir_uses_dev_path_when_not_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from foxtray.ui import icons
    monkeypatch.delattr("sys.frozen", raising=False)
    # Dev path: two parents up from icons.py, then "assets"
    expected = Path(icons.__file__).resolve().parent.parent.parent / "assets"
    assert icons._assets_dir() == expected
