"""foxtray.autostart unit tests — winreg monkeypatched."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from foxtray import autostart


def test_is_enabled_true_when_value_present(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__ = MagicMock(return_value=mock_key)
    mock_key.__exit__ = MagicMock(return_value=False)
    mock_winreg.OpenKey.return_value = mock_key
    mock_winreg.QueryValueEx.return_value = ('"C:\\x.exe" tray', 1)
    monkeypatch.setattr(autostart, "winreg", mock_winreg)
    assert autostart.is_enabled() is True


def test_is_enabled_false_when_value_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__ = MagicMock(return_value=mock_key)
    mock_key.__exit__ = MagicMock(return_value=False)
    mock_winreg.OpenKey.return_value = mock_key
    mock_winreg.QueryValueEx.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", mock_winreg)
    assert autostart.is_enabled() is False


def test_is_enabled_false_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", mock_winreg)
    assert autostart.is_enabled() is False


def test_enable_writes_value(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__ = MagicMock(return_value=mock_key)
    mock_key.__exit__ = MagicMock(return_value=False)
    mock_winreg.CreateKey.return_value = mock_key
    mock_winreg.REG_SZ = 1  # fake constant
    monkeypatch.setattr(autostart, "winreg", mock_winreg)

    autostart.enable(Path("C:\\foxtray\\FoxTray.exe"))

    mock_winreg.SetValueEx.assert_called_once()
    args = mock_winreg.SetValueEx.call_args[0]
    # (key, value_name, reserved, type, value)
    assert args[1] == "FoxTray"
    assert args[3] == 1  # REG_SZ
    assert args[4] == '"C:\\foxtray\\FoxTray.exe" tray'


def test_disable_deletes_value(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_key = MagicMock()
    mock_key.__enter__ = MagicMock(return_value=mock_key)
    mock_key.__exit__ = MagicMock(return_value=False)
    mock_winreg.OpenKey.return_value = mock_key
    mock_winreg.KEY_SET_VALUE = 2
    monkeypatch.setattr(autostart, "winreg", mock_winreg)

    autostart.disable()

    mock_winreg.DeleteValue.assert_called_once_with(mock_key, "FoxTray")


def test_disable_noop_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_winreg = MagicMock()
    mock_winreg.OpenKey.side_effect = FileNotFoundError()
    monkeypatch.setattr(autostart, "winreg", mock_winreg)
    # Should not raise
    autostart.disable()
