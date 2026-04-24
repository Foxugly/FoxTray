# FoxTray Iter 4c — PyInstaller .exe Packaging Design

## Goal

Produce a standalone `FoxTray.exe` that runs without requiring end users to install Python, pip dependencies, or manage a venv. Target: drop `FoxTray.exe` next to a `config.yaml` and launch.

## Non-goals

- Installer (MSI / NSIS) — out of scope; the `.exe` is standalone.
- Code signing — deferred.
- Auto-update — Iter 4e (which is deferred anyway).
- macOS / Linux binaries — Windows-only.

## Decisions (resolved from 4c skeleton open questions)

1. **One-file mode** (`--onefile`). Single `FoxTray.exe` (~30 MB). Startup cost (~500ms unpack to temp) is acceptable.
2. **`config.yaml` default resolved next to the `.exe`** when `sys.frozen` is True. In dev mode, unchanged (`Path(__file__).parent.parent / "config.yaml"`).
3. **`state.json`, `tray.lock`, logs** stay in `%APPDATA%\foxtray\` — unchanged.
4. **Icon for the .exe**: auto-generate a `.ico` file via `scripts/gen_icons.py`. Pillow supports saving multi-resolution ICO (16/32/48/256).
5. **Version**: hardcoded `__version__ = "0.4.0"` in `foxtray/__init__.py`. About dialog shows it. Bump manually on releases.
6. **Antivirus**: document as a known limitation. UPX disabled (`--noupx` in spec) to reduce false-positive probability.
7. **Testing**: unit tests monkeypatch `sys.frozen`/`sys._MEIPASS` to verify path resolution. Manual smoke test builds the exe and verifies it launches.

## Architecture overview

### Entry point

`main.py` already exists and is PyInstaller-compatible. We'll point the spec file at it.

### Spec file

`foxtray.spec` at repo root describes the build:

```python
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),  # bundle the icons folder
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FoxTray',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX triggers false positives in many AV engines
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window when running the tray
    disable_windowed_traceback=False,
    icon='assets/foxtray.ico',
)
```

### Path resolution inside bundled `.exe`

PyInstaller extracts bundled data to `sys._MEIPASS` at runtime. We need to handle:

**`foxtray/ui/icons.py`** — currently:
```python
_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
```

Update to a function-based resolver that checks `sys._MEIPASS`:
```python
def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "assets"
    return Path(__file__).resolve().parent.parent.parent / "assets"


_ASSETS = _assets_dir()
```

`_ASSETS` evaluated at import time is fine because it's computed inside the function.

**`foxtray/cli.py`** — the default `--config` path:
```python
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
```

When frozen, this points into `_MEIPASS` — wrong. Update:
```python
def _default_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config.yaml"
    return Path(__file__).resolve().parent.parent / "config.yaml"


CONFIG_PATH = _default_config_path()
```

### Icon file generation

`scripts/gen_icons.py` already generates the 3 tray PNGs. Extend it to also generate `assets/foxtray.ico` — Pillow's `Image.save(path, format="ICO", sizes=[(16,16),(32,32),(48,48),(256,256)])` handles multi-resolution.

Source image: reuse `icon_running.png` (green disc). Good enough for v1.

### Build invocation

Add `requirements-dev.txt`:
```
pyinstaller>=6.0
```

Document the build command in `docs/packaging.md`:
```
./.venv/Scripts/python.exe scripts/gen_icons.py       # ensure .ico exists
./.venv/Scripts/python.exe -m PyInstaller --clean --noconfirm foxtray.spec
```

Output: `dist/FoxTray.exe`.

### Version

`foxtray/__init__.py`:
```python
__version__ = "0.4.0"
```

`foxtray/ui/actions.py` — update `_ABOUT_BODY` to include the version:
```python
from foxtray import __version__

_ABOUT_BODY = (
    f"FoxTray v{__version__}\n"
    "Windows tray launcher for Django + Angular project pairs.\n\n"
    "Author: Foxugly\n"
    "Website: https://foxugly.com\n"
    "Repository: https://github.com/Foxugly/FoxTray"
)
```

Wait — `_ABOUT_BODY` is a module-level constant. Using `__version__` at import time is fine. Verify no circular import: `foxtray/__init__.py` has no imports from submodules, so importing `foxtray.__version__` from `foxtray.ui.actions` is safe.

## File structure

New files:
- `foxtray.spec` — PyInstaller config.
- `foxtray/__init__.py` — `__version__ = "0.4.0"`.
- `scripts/gen_ico.py` — or extend `scripts/gen_icons.py` to also write `foxtray.ico`.
- `docs/packaging.md` — build instructions.
- `docs/manual-tests/iter4c.md` — smoke test.
- `assets/foxtray.ico` — generated multi-resolution icon.

Modified files:
- `foxtray/ui/icons.py` — `_assets_dir()` frozen-aware.
- `foxtray/cli.py` — `_default_config_path()` frozen-aware.
- `foxtray/ui/actions.py` — `_ABOUT_BODY` includes version.
- `scripts/gen_icons.py` — also produces `.ico`.
- `requirements-dev.txt` — add `pyinstaller`.
- `.gitignore` — add `dist/`, `build/`, `*.spec.pyc`.

Tests:
- `tests/test_icons.py` — new test for `_assets_dir` with `sys.frozen`/`sys._MEIPASS` monkeypatched.
- `tests/test_cli.py` — new test for `_default_config_path` with frozen monkeypatched.
- `tests/test_version.py` (new) — asserts `foxtray.__version__` exists and is a string.

## Testing

Unit tests cover the frozen-path resolution. Manual smoke covers the build + run.

Important: the unit tests monkeypatch `sys.frozen` and `sys._MEIPASS` carefully. pytest runs with `sys.frozen` unset by default, so the dev paths are exercised for existing tests automatically.

## Manual smoke (`docs/manual-tests/iter4c.md`)

- Build: `./.venv/Scripts/python.exe -m PyInstaller --clean --noconfirm foxtray.spec`. No errors. `dist/FoxTray.exe` exists, ~25-35 MB.
- Copy `dist/FoxTray.exe` to a fresh folder + copy `config.yaml` alongside.
- Double-click `FoxTray.exe`. Tray icon appears (grey initially).
- About dialog shows `FoxTray v0.4.0`.
- Start a project from the menu. Angular + Django spawn. URL resolves. Works end-to-end.
- Close FoxTray. `%APPDATA%\foxtray\tray.lock` is cleaned up.
- Run a second `FoxTray.exe`: "FoxTray tray is already running (pid N)" + exit 1.

## Self-review

- Decisions all resolved; no open "TBD" in this spec.
- Pathing: `_assets_dir()` and `_default_config_path()` both guard with `getattr(sys, 'frozen', False)` so dev behavior is strictly unchanged.
- Version single-sourced in `foxtray/__init__.py`, consumed by About dialog. Future: PyPI setup.cfg + dynamic version.
