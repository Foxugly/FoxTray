# FoxTray Iter 5a — Manual Test Log

Prerequisite: Iter 4b passed.

## Environment

- Date: <fill>
- HEAD: <commit sha>
- pytest: all green

## Restart

- [ ] Start FoxRunner, wait green.
- [ ] Right-click → FoxRunner ▸ Restart. Menu closes immediately (no 10s freeze).
- [ ] Within ~10s icon cycles: green → grey → orange → green. Expected balloon sequence depends on transitions (probably "FoxRunner is up" once healthy again).
- [ ] `state.json.active` points to FoxRunner throughout (no gap).

## Copy URL

- [ ] Right-click → FoxRunner ▸ Copy URL. Balloon "URL copied: http://localhost:4200".
- [ ] Paste in a browser address bar. URL matches.

## Open logs folder

- [ ] Right-click → Open logs folder (bottom of root menu, before Stop all).
- [ ] Explorer opens at `%APPDATA%\foxtray\logs\`. Shows `FoxRunner_backend.log`, etc.

## Open project folder (requires `path_root`)

- [ ] Add `path_root: D:\PycharmProjects\FoxRunner` to the FoxRunner YAML entry. Restart tray.
- [ ] Right-click → FoxRunner ▸ Open project folder. Explorer opens at the root.
- [ ] Remove the line, restart tray. The entry is gone from the submenu.

## Icon tooltip

- [ ] With no project active, hover icon → tooltip "FoxTray — idle".
- [ ] Start FoxRunner → tooltip "FoxTray — FoxRunner RUNNING" (after health check passes).
- [ ] Kill the frontend node.exe via Task Manager → tooltip "FoxTray — FoxRunner PARTIAL (frontend down)" within 3s.
- [ ] Click Stop. Tooltip returns to "FoxTray — FoxRunner stopped" briefly, then "FoxTray — idle" on next tick once state clears.

## Known limitations

- Tooltip updates at the 3s poll cadence, not instantly.
- `clip.exe` requires Windows (no graceful fallback elsewhere).

## Observed issues
_None yet._
