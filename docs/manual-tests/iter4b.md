# FoxTray Iter 4b — Manual Test Log

Prerequisite: Iter 4a manual test (`docs/manual-tests/iter4a.md`) passed.

## Environment

- Date: <fill>
- HEAD: <commit sha>
- Full test suite: `./.venv/Scripts/python.exe -m pytest -v` (must show all green)

## Single-instance lock

- [ ] Clean state: delete `%APPDATA%\foxtray\tray.lock` if present.
- [ ] Launch `python main.py tray` in shell #1. Tray icon appears.
- [ ] In shell #2: `python main.py tray` — within a second prints `FoxTray tray is already running (pid N)` to stderr, exits with code 1. No second tray icon appears.
- [ ] Check `%APPDATA%\foxtray\tray.lock` — contains the PID of shell #1's Python.
- [ ] Right-click icon → Exit in shell #1. Tray disappears. `tray.lock` is deleted.
- [ ] Launch `python main.py tray` in shell #1 again. Successful.
- [ ] Kill Python in shell #1 via Task Manager (End Task, not menu Exit). Tray disappears but `tray.lock` remains (stale).
- [ ] Launch `python main.py tray` in shell #2: succeeds. `tray.lock` is overwritten with new PID.
- [ ] Exit cleanly. Lock file deleted.

## About popup

- [ ] With tray running, right-click icon → click `About` (at the bottom of the menu).
- [ ] Native Windows MessageBox appears with title `About FoxTray` and body containing:
  - Line 1: `FoxTray`
  - Line 2: `Windows tray launcher for Django + Angular project pairs.`
  - `Author: Foxugly`
  - `Website: https://foxugly.com`
  - `Repository: https://github.com/Foxugly/FoxTray`
- [ ] Click OK. Dialog disappears. Tray icon and menu still responsive.
- [ ] While dialog is open, verify clicking the icon in the notification area still works (can open menu in parallel). pystray continues running.

## Known Iter 4b limitations (intentional)

- Lock is per-user, not per-machine. A second user logged in via RDP or fast user switching can still launch their own tray.
- Lock file is cleaned up only on clean exit. Kill-9 / power-cycle leaves a stale lock that is auto-reclaimed on the next launch.
- About MessageBox URLs are not clickable (native Windows MessageBox limitation).

## Observed issues
<!-- Fill during run. -->

_None yet._
