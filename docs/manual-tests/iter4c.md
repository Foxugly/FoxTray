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
