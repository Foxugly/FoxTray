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
