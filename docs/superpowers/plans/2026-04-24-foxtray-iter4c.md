# FoxTray Iter 4c (PyInstaller Packaging) Implementation Plan

**Goal:** Produce a standalone `FoxTray.exe` via PyInstaller.

**Spec:** `docs/superpowers/specs/2026-04-24-foxtray-iter4c-design.md`.

---

## Task 1: `__version__` + About body update

**Files:** `foxtray/__init__.py`, `foxtray/ui/actions.py`, `tests/test_version.py`, `tests/test_tray_actions.py`.

- [ ] **Step 1: Create `tests/test_version.py`**

```python
def test_version_is_string() -> None:
    from foxtray import __version__
    assert isinstance(__version__, str)
    assert len(__version__) > 0
```

- [ ] **Step 2: Append test to `tests/test_tray_actions.py`**

```python
def test_about_body_includes_version() -> None:
    from foxtray import __version__
    assert __version__ in actions._ABOUT_BODY
```

- [ ] **Step 3: Run, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_version.py tests/test_tray_actions.py -v -k "version"
```

- [ ] **Step 4: Write `foxtray/__init__.py`**

Full file content (overwrite empty or add if missing):

```python
"""FoxTray — Windows tray launcher for Django + Angular project pairs."""
__version__ = "0.4.0"
```

- [ ] **Step 5: Update `_ABOUT_BODY` in `foxtray/ui/actions.py`**

Add at the top-of-module imports (after existing imports):
```python
from foxtray import __version__
```

Replace the existing `_ABOUT_BODY` constant with:
```python
_ABOUT_BODY = (
    f"FoxTray v{__version__}\n"
    "Windows tray launcher for Django + Angular project pairs.\n\n"
    "Author: Foxugly\n"
    "Website: https://foxugly.com\n"
    "Repository: https://github.com/Foxugly/FoxTray"
)
```

- [ ] **Step 6: Run full suite** — expect all green.

- [ ] **Step 7: Commit**

```
feat: __version__ in foxtray package; About dialog shows version

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 2: Frozen-aware path resolution in `icons.py` and `cli.py`

**Files:** `foxtray/ui/icons.py`, `foxtray/cli.py`, `tests/test_icons.py`, `tests/test_cli.py`.

- [ ] **Step 1: Append failing tests to `tests/test_icons.py`**

```python
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
```

Add `from pathlib import Path` and `import pytest` to the top of `test_icons.py` if not already.

- [ ] **Step 2: Append failing tests to `tests/test_cli.py`**

```python
def test_default_config_path_uses_exe_dir_when_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from foxtray import cli as cli_mod
    fake_exe = tmp_path / "FoxTray.exe"
    fake_exe.write_bytes(b"")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(fake_exe), raising=False)
    assert cli_mod._default_config_path() == tmp_path / "config.yaml"


def test_default_config_path_uses_dev_path_when_not_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from foxtray import cli as cli_mod
    monkeypatch.delattr("sys.frozen", raising=False)
    expected = Path(cli_mod.__file__).resolve().parent.parent / "config.yaml"
    assert cli_mod._default_config_path() == expected
```

- [ ] **Step 3: Run, confirm failures**

- [ ] **Step 4: Update `foxtray/ui/icons.py`**

Add `import sys` near the top. Replace:

```python
_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
```

with:

```python
def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
        return base / "assets"
    return Path(__file__).resolve().parent.parent.parent / "assets"


_ASSETS = _assets_dir()
```

- [ ] **Step 5: Update `foxtray/cli.py`**

Add `import sys` (already likely there). Replace:

```python
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
```

with:

```python
def _default_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config.yaml"
    return Path(__file__).resolve().parent.parent / "config.yaml"


CONFIG_PATH = _default_config_path()
```

- [ ] **Step 6: Run full suite** — expect all green.

- [ ] **Step 7: Commit**

```
refactor: frozen-aware path resolution for assets + default config

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 3: Icon `.ico` generator + `foxtray.spec` + build doc

**Files:** `scripts/gen_icons.py`, `foxtray.spec`, `docs/packaging.md`, `requirements-dev.txt`, `.gitignore`.

No tests for this task — it's build tooling. Manual smoke covers it.

- [ ] **Step 1: Read `scripts/gen_icons.py`** — current content generates 3 PNG tray icons. We extend it.

- [ ] **Step 2: Update `scripts/gen_icons.py`**

Add a function that writes `assets/foxtray.ico`. After the existing PNG generation loop, add:

```python
def _write_ico() -> None:
    """Write assets/foxtray.ico — multi-resolution from the running (green) disc."""
    from PIL import Image
    # Reuse the running PNG as the icon source
    src = _ASSETS / "icon_running.png"
    img = Image.open(src)
    # Resize to 256×256 so ICO can derive smaller sizes cleanly
    img = img.resize((256, 256), Image.Resampling.LANCZOS)
    ico_path = _ASSETS / "foxtray.ico"
    img.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print(f"wrote {ico_path}")


# In main(), after the for loop:
def main() -> None:
    _ASSETS.mkdir(parents=True, exist_ok=True)
    # ... existing PNG loop ...
    _write_ico()
```

- [ ] **Step 3: Run the generator**

```
./.venv/Scripts/python.exe scripts/gen_icons.py
```

Expected: prints 3 PNG + 1 ICO paths. `assets/foxtray.ico` exists (~10-50 KB).

- [ ] **Step 4: Create `foxtray.spec` at repo root**

```python
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/foxtray.ico',
)
```

- [ ] **Step 5: Append to `requirements-dev.txt`**

```
pyinstaller>=6.0
```

- [ ] **Step 6: Update `.gitignore`** — add if not already present:

```
dist/
build/
```

- [ ] **Step 7: Create `docs/packaging.md`**

```markdown
# FoxTray Packaging

FoxTray ships as a standalone `FoxTray.exe` built with PyInstaller.

## Build

```powershell
# Ensure the multi-resolution .ico is up to date
./.venv/Scripts/python.exe scripts/gen_icons.py

# Build
./.venv/Scripts/python.exe -m PyInstaller --clean --noconfirm foxtray.spec
```

Output: `dist/FoxTray.exe` (~25-35 MB).

## Run

Copy `FoxTray.exe` and a `config.yaml` to the same folder. Double-click the `.exe`.
Tray icon appears.

Runtime state (`state.json`, `tray.lock`, `logs/`) lives in `%APPDATA%\foxtray\`
regardless of where the `.exe` is launched from.

## Known limitations

- Unsigned: Windows Defender and some AV engines may flag it. UPX is disabled
  in the spec (`upx=False`) to reduce false-positive probability. Signing is
  deferred to a future iteration.
- One-file mode has ~500ms startup overhead (PyInstaller extracts to a temp dir).
```

- [ ] **Step 8: Run full pytest suite** (should still be green — no runtime code changed in this task).

- [ ] **Step 9: Commit**

```
feat(packaging): PyInstaller spec + ico generator + build docs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 4: Manual smoke doc

**Files:** `docs/manual-tests/iter4c.md`.

Content:

```markdown
# FoxTray Iter 4c — Manual Test Log

Prerequisite: Iter 5c passed.

## Environment
- Date: <fill>
- HEAD: <commit sha>
- PyInstaller version: `./.venv/Scripts/python.exe -m PyInstaller --version`

## Build

- [ ] `./.venv/Scripts/python.exe scripts/gen_icons.py` — generates 3 PNGs + `foxtray.ico`, no error.
- [ ] `./.venv/Scripts/python.exe -m PyInstaller --clean --noconfirm foxtray.spec` — completes, no ImportError, warnings OK.
- [ ] `dist/FoxTray.exe` exists, 25-35 MB, has the green-disc icon in Explorer (256×256 visible).

## Run

- [ ] Copy `dist/FoxTray.exe` to `C:\tmp\foxtray-test\`. Copy `config.yaml` alongside.
- [ ] Double-click `FoxTray.exe`. Tray icon appears within 2s (grey).
- [ ] Right-click → About. Dialog shows `FoxTray v0.4.0`.
- [ ] Right-click → FoxRunner ▸ Start. Within ~15s, icon turns green, balloon "FoxRunner is up".
- [ ] Stop FoxRunner, then Exit. Tray disappears cleanly.
- [ ] Check `%APPDATA%\foxtray\tray.lock` — absent (cleaned up).
- [ ] Launch the `.exe` a second time: "FoxTray tray is already running (pid N)" stderr, exit 1. No second tray icon.

## CLI in bundled mode

- [ ] From a shell in `C:\tmp\foxtray-test\`: `FoxTray.exe list` — prints all 3 projects, exit 0. Confirms CLI subcommands also work in bundled mode.
- [ ] `FoxTray.exe validate` — prints "Config OK: 3 project(s), 0 script(s)", exit 0.

## Known limitations

- Windows Defender scan on first launch adds ~1-2s to startup (one-time). Subsequent launches are faster once the file is whitelisted.
- If the `.exe` is distributed (not just copied locally), some AV engines may quarantine it. Workaround: sign the binary (deferred).

## Observed issues
_None yet._
```

Commit:
```
docs(iter4c): manual smoke checklist for PyInstaller build

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Self-review

- Task 1 only adds constants + imports; no behavior change for non-about paths.
- Task 2 adds frozen-path helpers; in dev mode (`sys.frozen` absent) behavior is strictly unchanged.
- Task 3 is tooling only — no Python runtime code changes. Tests still pass.
- Task 4 is documentation.
