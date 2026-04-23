from pathlib import Path

import pytest


@pytest.fixture
def tmp_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect FoxTray's APPDATA root to a tmp dir for the duration of a test."""
    monkeypatch.setenv("FOXTRAY_APPDATA", str(tmp_path))
    return tmp_path
