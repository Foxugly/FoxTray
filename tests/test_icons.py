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
