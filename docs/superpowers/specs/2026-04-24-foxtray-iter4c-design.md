# FoxTray Iter 4c — PyInstaller .exe Packaging Design (Skeleton)

> **Status:** design outline only. No implementation plan yet — requires a follow-up brainstorming session to lock decisions on open questions before writing `docs/superpowers/plans/…-foxtray-iter4c.md`.

## Goal

Ship FoxTray as a standalone `FoxTray.exe` that runs without requiring the end user to install Python or pip dependencies. The `.exe` bundles the interpreter, `pystray`, `Pillow`, `PyYAML`, `psutil`, `requests`, and the `foxtray` package + `assets/`.

Target: one binary the user drops next to their `config.yaml` (or at a well-known location) and launches.

## Non-goals (for Iter 4c)

- Installer (MSI / NSIS) — out of scope; the `.exe` is standalone.
- Code signing — deferred (needs a certificate + CI secrets).
- Auto-update — Iter 4e.
- macOS / Linux binaries — Iter 4c is Windows-only.
- Portable mode with side-by-side `%APPDATA%` override — possibly later.

## Architecture overview

PyInstaller in **one-file mode** (`--onefile`) is the starting candidate. Tradeoffs:
- **One-file**: single `FoxTray.exe` (~30 MB). Unpacks to a temp dir on each launch, adds ~500ms startup. Simpler distribution.
- **One-folder** (`--onedir`): `FoxTray/` directory with `FoxTray.exe` + DLLs + `_internal/`. Faster startup, but the user has to distribute the whole folder.

Default recommendation: **one-file** for ergonomics; revisit if the startup lag bothers us.

### Entry point and spec file

PyInstaller requires a `.spec` file to describe the build. Create `foxtray.spec` at repo root:

```python
# foxtray.spec — PyInstaller config
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/*.png', 'assets')],  # bundle tray icons
    hiddenimports=['PIL._tkinter_finder'],  # PyInstaller sometimes misses Pillow extras
    ...
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, ...,
          name='FoxTray', icon='assets/icon_running.png', console=False)
```

`console=False` so the `.exe` launches without a console window.

### Path resolution inside bundled `.exe`

`foxtray/ui/icons.py` currently does:
```python
_ASSETS = Path(__file__).resolve().parent.parent.parent / "assets"
```

In a PyInstaller bundle, `__file__` points into a temp extraction dir (`_MEIPASS`). The `assets/` we bundle goes to `sys._MEIPASS / "assets"`. Update the resolver:

```python
def _assets_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parent.parent.parent / "assets"
```

Equivalent change needed anywhere else we use a "project-root-relative" path (check `foxtray/paths.py`, `foxtray/cli.py` `CONFIG_PATH` default, etc).

### Config path in bundled mode

`foxtray/cli.py` defaults `--config` to `Path(__file__).resolve().parent.parent / "config.yaml"` — which in a bundle points into `_MEIPASS`. That's wrong. Options:
1. **Require `--config`** when running the `.exe` (no default).
2. **Resolve config relative to the `.exe` location** (next to the binary the user drops on disk).
3. **Resolve config from `%APPDATA%\foxtray\config.yaml`** with a "first run" step that writes a template.

Lean toward **(2)**: `config.yaml` sits next to `FoxTray.exe`. Simple mental model, no magic hidden state.

Implementation: when `sys.frozen` is True, default `--config` to `Path(sys.executable).parent / "config.yaml"`.

### Build invocation

New `scripts/build_exe.py` or a Makefile-style doc. Canonical command:

```powershell
pyinstaller --clean --noconfirm foxtray.spec
```

Output lands in `dist/FoxTray.exe`.

### Dependencies

Add to `requirements-dev.txt` (not `requirements.txt` — runtime has no need of PyInstaller):
```
pyinstaller>=6.0
```

## Open questions (to resolve in brainstorming)

1. **One-file vs one-folder?** Default proposal: one-file. User might prefer one-folder for faster startup or easier antivirus whitelist management.
2. **Where does `config.yaml` live by default?** Option 2 above (next to `.exe`) vs %APPDATA%. Probably option 2 but confirm.
3. **Should `state.json` and `logs/` remain in `%APPDATA%\foxtray\`?** Yes — they're per-user runtime data. Unchanged from current behavior.
4. **Icon for the `.exe` itself (Windows Explorer view)?** We have `assets/icon_running.png` (32×32 colored disc). Probably want a proper `.ico` file with multi-resolution (16/32/48/256). Generate from the PNG or draw a new one in `scripts/gen_icons.py`.
5. **Versioning / version resource?** PyInstaller can embed a Windows version resource block. Decide on version scheme (manual? git tag? date?). For now, manual string in `foxtray/__init__.py` that the About dialog already uses.
6. **Antivirus false positives?** Unsigned PyInstaller bundles get flagged by some AVs. Mitigation: UPX disabled, build reproducibly, eventually sign. Document as known limitation.
7. **Test strategy?** PyInstaller builds can't be exercised by pytest realistically. Add a smoke-test script that builds the `.exe`, runs it with `--help` or `list`, asserts exit 0 and expected output. Manual test covers the tray UI.

## File structure (anticipated)

New files:
- `foxtray.spec` — PyInstaller spec.
- `scripts/build_exe.py` OR `docs/packaging.md` — documents the build command.
- `assets/foxtray.ico` — generated multi-resolution icon.

Modified files:
- `foxtray/ui/icons.py` — `_MEIPASS`-aware `_assets_dir()`.
- `foxtray/cli.py` — frozen-aware default for `--config`.
- `foxtray/__init__.py` — `__version__` string (used by About dialog too).
- `requirements-dev.txt` — add `pyinstaller`.
- `.gitignore` — add `dist/`, `build/`, `*.spec.pyc` as needed.

Tests:
- `tests/test_paths_frozen.py` — monkeypatch `sys.frozen` / `sys._MEIPASS` and verify `_assets_dir()` returns the bundled path.
- Manual smoke doc `docs/manual-tests/iter4c.md` — build the `.exe`, verify it launches, tray icon loads, config resolves next to the binary.

## Next step

Hold a short brainstorming session to answer questions 1-7, then write `docs/superpowers/plans/2026-04-24-foxtray-iter4c.md` with the full TDD-style task breakdown.
