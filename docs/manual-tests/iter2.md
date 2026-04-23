# FoxTray Iter 2 — Manual Test Log

Prerequisite: Iter 1 manual test (`docs/manual-tests/iter1.md`) passed once on this machine.

## Environment

- Date: <fill>
- HEAD: <commit sha>
- pystray version: `./.venv/Scripts/python.exe -c "import pystray; print(pystray.__version__)"`
- Full test suite: `./.venv/Scripts/python.exe -m pytest -v` (must show 91 passed)

## Scenarios

- [ ] `python main.py tray` — a grey disc icon appears in the Windows notification area
- [ ] Right-click the icon — root menu lists FoxRunner / QuizOnline / PushIT, each followed by `(stopped)`; `Stop all` is greyed; `Stop all and exit` is greyed
- [ ] Hover FoxRunner submenu — shows `Start`, separator, `Open in browser` (greyed), `Open backend folder`, `Open frontend folder`
- [ ] Click Start on FoxRunner. Within ≤20 s the icon turns green AND a balloon notification "FoxRunner is up" shows
- [ ] Right-click icon — FoxRunner submenu now shows `Stop` instead of `Start`; `Open in browser` is enabled
- [ ] Click Open in browser — default browser opens `http://localhost:4200`
- [ ] Click Open backend folder — Explorer opens at `D:\PycharmProjects\FoxRunner_server`
- [ ] Open Task Manager. Find and End one child python.exe of the Django tree (not the root). Within ~3 s icon turns orange AND a balloon "⚠ FoxRunner: backend crashed" shows
- [ ] Click Stop. Icon turns grey. **No balloon** (user-initiated stop is silent)
- [ ] Click Exit. Icon disappears. `python main.py list` shows all stopped
- [ ] `python main.py tray` again → click Start FoxRunner → Stop all and exit → within 5 s icon disappears and `python main.py list` shows all stopped

## Partial-state visual check

- [ ] After step "icon turns orange", the orange tone should be visually distinct from the green tone (not a slight variation). If it's hard to distinguish, revisit colors in `scripts/gen_icons.py` and regenerate.

## Switch test (auto-stop on start)

- [ ] `python main.py tray` — grey icon
- [ ] Start FoxRunner → wait green
- [ ] Start QuizOnline (click it in the menu) — FoxRunner should be auto-stopped first; icon transitions grey briefly then green; balloon "QuizOnline is up"
- [ ] Menu reflects: QuizOnline (RUNNING), FoxRunner (stopped), PushIT (stopped)
- [ ] `Stop all` — icon grey, `state.json` cleared

## Known Iter 2 limitations (intentional)

- **No single-instance lock.** Running `python main.py tray` twice is not prevented. Iter 4.
- **No health-check wait.** "FoxRunner is up" may fire before Django/Angular actually serve 200s. Iter 3.
- **No auto-clear of orphaned state.** If state.json has an active project but no PIDs are alive at startup, the tray shows `stopped` but state.json is not cleared until the next user action. Iter 3.
- **Partial transitions on cold start.** If a project is already running when the tray starts, the first tick announces "X is up" even though it was already running. This is the correct behavior (the tray announces what it discovers) but worth knowing.

## Observed issues
<!-- Fill during run. Link to follow-up fix commits. -->

_None yet._
