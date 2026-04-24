# FoxTray Iter 4d — Manual Test Log

Prerequisite: Iter 4c passed (you have a built FoxTray.exe).

## Environment
- Date: <fill>
- HEAD: <commit sha>

## Start at login (bundled .exe only)

- [ ] Launch `dist\FoxTray.exe`. Right-click → Start at login. Balloon "Autostart enabled".
- [ ] `reg query HKCU\Software\Microsoft\Windows\CurrentVersion\Run` — has a `FoxTray` value pointing to the .exe path.
- [ ] The menu entry now shows with a checkmark (pystray renders `checked=True`).
- [ ] Right-click → Start at login. Balloon "Autostart disabled". Registry value removed. Checkmark gone next time the menu is painted.
- [ ] Sign out + sign in. If autostart was enabled before sign-out, tray is visible after login.

## Dev mode behavior

- [ ] `./.venv/Scripts/python.exe main.py tray` (not the .exe). Right-click → Start at login. Balloon "Autostart only works for the packaged .exe (dev mode skipped)". Registry NOT modified.

## Known limitations
- Per-user only (HKCU). A different Windows user needs their own toggle.
- If FoxTray.exe moves after enabling autostart, the registry entry points to the old location. User must re-enable from the new location.
- Hotkey feature intentionally not included — pystray has no public API to open its context menu programmatically. Revisit if a hotkey action (e.g., cycle projects, status balloon) becomes valuable.

## Observed issues
_None yet._
