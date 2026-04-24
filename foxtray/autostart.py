"""Windows registry Run key for per-user autostart."""
from __future__ import annotations

import logging
import winreg
from pathlib import Path

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "FoxTray"


def is_enabled() -> bool:
    """True if HKCU\\...\\Run\\FoxTray is set."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        log.warning("autostart.is_enabled: OSError reading registry", exc_info=True)
        return False


def enable(exe_path: Path) -> None:
    """Register exe_path + ' tray' in the HKCU Run key under name 'FoxTray'."""
    value = f'"{exe_path}" tray'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, value)


def disable() -> None:
    """Remove HKCU\\...\\Run\\FoxTray. Best-effort."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        return
    except OSError:
        log.warning("autostart.disable: OSError modifying registry", exc_info=True)
