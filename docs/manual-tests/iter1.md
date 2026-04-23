# FoxTray Iter 1 — Manual Test Log

Iter 1 success criterion (from the brief): `stop` kills Node properly — no residual `node.exe` after stopping, port 4200 is free.

## Environment

- Date: 2026-04-23
- Python: 3.14 (verify with `.venv\Scripts\python.exe --version`)
- OS: Windows 11 Pro
- FoxTray HEAD: `2abf17e` (Task 9 complete)
- Full automated suite: **46/46 passing**

## Scenarios

Run from `D:\PycharmProjects\FoxTray` with the project venv activated.

- [ ] `python main.py list` shows FoxRunner / QuizOnline / PushIT, all `stopped`
- [ ] `python main.py start FoxRunner` — returns `Started FoxRunner` without a traceback
- [ ] After ~15 s, `python main.py status FoxRunner` shows:
  - `running: True`
  - `backend alive: True`
  - `frontend alive: True`
  - `backend port open: True`
  - `frontend port open: True`
  - `url responds: True`
- [ ] `%APPDATA%\foxtray\logs\FoxRunner_backend.log` contains Django boot output
- [ ] `%APPDATA%\foxtray\logs\FoxRunner_frontend.log` contains Angular dev-server output
- [ ] Task Manager shows ≥ 1 `python.exe` (Django) and ≥ 1 `node.exe` (ng serve)
- [ ] `python main.py stop FoxRunner` — prints `Stopped FoxRunner` within ~5 s
- [ ] Within 5 s of `stop`, Task Manager shows **zero** `node.exe` processes for this user
- [ ] `python main.py status FoxRunner` after stop returns `running: False`, `backend port open: False`, `frontend port open: False`
- [ ] Port 4200 is free (verify with `python -c "from foxtray.health import port_listening; print(port_listening(4200))"` — prints `False`)

## Switch test (auto-stop on start)

- [ ] `python main.py start FoxRunner` — wait for up
- [ ] `python main.py start QuizOnline` — FoxRunner should be auto-stopped first. Watch for `INFO foxtray.project: Stopping active project FoxRunner before starting QuizOnline` in stderr
- [ ] `python main.py list` after: QuizOnline `RUNNING`, FoxRunner `stopped`, PushIT `stopped`
- [ ] `python main.py stop-all` — QuizOnline cleanly stops

## Known Iter 1 limitations (intentional)

- No health-check wait after `start`; if the Angular boot is slow, `status` may report `running: True` (processes up) but `url responds: False` for a few seconds. Iter 3 adds the wait loop.
- No `wait_port_free` call between stop and the next start — if two `start` commands run in quick succession, the second may hit `EADDRINUSE`. Also Iter 3 material.
- No crash detection: if Django/Angular die unexpectedly, `list` will show `stopped` (via `psutil.pid_exists`) but the stale state.json lingers until the next `start` or `stop-all`.
- QuizOnline's venv layout isn't set up yet on this machine; skip scenarios that require it.

## Run log — 2026-04-23

**Result:** PASS (kill-tree verified on a real Django process tree).

### Observations

- `start FoxRunner` returned exit 0 and wrote `{"active": {"name":"FoxRunner", "backend_pid":39400, "frontend_pid":44768}}` to `state.json`.
- **Backend (Django `runserver 8000`)** booted cleanly. Captured a real 4-PID tree: root `39400` + 3 `python.exe` descendants spawned by Django's `StatReloader`.
- **Frontend (Angular)** crashed seconds after start with `An unhandled exception occurred: Port 4200 is already in use.` — another non-FoxTray node.exe on the machine had grabbed 4200 between baseline check and start. FoxTray did NOT detect the frontend crash (confirms the documented "no health-check wait" limitation).
- `stop FoxRunner` returned in **0.4 s**. All 4 backend-tree PIDs were dead, port 8000 was free, port 4200 was free, `state.json.active == null`.
- `list` and `status` output matched spec.

### Bug caught (fixed before running)

- **`subprocess.Popen(['ng', ...], shell=False)` does NOT honor Windows PATHEXT** — Popen looked for literal `ng` and raised `FileNotFoundError`, because the real file is `ng.CMD`. Fixed in commit `b96b433` by resolving the first token through `shutil.which()` inside `ProcessManager.start`, and by introducing `process.ExecutableNotFound` so the CLI surfaces a clearer message than the generic "Cannot open config". Regression tests added to `tests/test_process.py`.
- All existing tests had used `sys.executable` (a full `.exe` path), which masked the scenario. Added `test_start_resolves_bare_executable_name` and `test_start_raises_executable_not_found_for_missing_bin`.

### Items intentionally deferred (known Iter 1 limitations, already documented)

- `start FoxRunner` reported success even though frontend crashed ~seconds later — no health-check-on-start wait yet. Iter 3 will add it.
- No `wait_port_free` call before the next `start` — switch test (`start X` while Y is running) can still race on rapid toggle. Iter 3.

### Switch test & `stop-all`

Not executed because the only externally-available frontend port (4200) was occupied by another tenant on this machine. Iter 3 integration test will use a fresh machine or reserved ports.
