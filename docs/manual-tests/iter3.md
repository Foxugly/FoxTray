# FoxTray Iter 3 — Manual Test Log

Prerequisite: Iter 2 manual test (`docs/manual-tests/iter2.md`) passed once on this machine.

## Environment

- Date: 2026-04-23 (partial automated smoke)
- HEAD: `4e5754c`
- Full test suite: 129 passed

## CLI scenarios

- [x] `python main.py start FoxRunner` — prints `Started FoxRunner, waiting for health...`, then `FoxRunner is healthy` within the `start_timeout` (default 30s). Exit 0. **Observed: 8.4s to healthy.**
- [ ] With a broken backend command (edit `config.yaml`, replace `python manage.py runserver 8000` with `python -c "import sys; sys.exit(1)"`): `python main.py start FoxRunner` — after 30s, prints to stderr `FoxRunner failed to become healthy within 30s; stopping`. Exit 1. `state.json.active` is null. *(Indirectly observed during a flaky PortInUse test attempt: the 30s timeout fired correctly, the expected stderr message printed, exit 1, state cleared. Still needs a dedicated run with a formally-broken command.)*
- [ ] Occupy port 8000 manually: `python -m http.server 8000` in another shell. `python main.py start FoxRunner` — within 3s prints `Port in use: backend port 8000 still in use`. Exit 2. No python children spawned for FoxRunner. *(Automated test was flaky on Windows because a socket that never calls accept() fills its listen backlog, tricking `port_listening` into reporting "free". Against a real accepting server (like http.server running in a separate shell), the code path works. Unit tests cover the `PortInUse` exception via monkeypatch. Verify interactively with two shells.)*
- [x] After a clean stop, immediately start again: `python main.py stop FoxRunner && python main.py start FoxRunner` — no `EADDRINUSE`. **Observed: stop 1.1s; re-start reaches healthy in 8.4s; both ports free afterwards.**

## Orphan-clear scenarios

- [x] Edit `%APPDATA%\foxtray\state.json` to set `active: {"name": "FoxRunner", "backend_pid": 99999, "frontend_pid": 99998}`. Run `python main.py list` — prints all stopped; `state.json.active` is now `null`. **Observed: cleared after a single `list` invocation.**
- [ ] With the same bogus state, run `python main.py tray` — tray launches with grey icon. Menu reflects all projects stopped. *(Tray scenarios need human observation.)*

## Tray health-flow scenarios

- [ ] Launch `python main.py tray` — grey icon.
- [ ] Click Start FoxRunner. Icon turns orange within ~3s (procs are up, URL not yet). After ~10–20s, icon turns green AND a single balloon "FoxRunner is up" appears. No earlier "X started but one component failed" balloon, no "X recovered" balloon.
- [ ] With FoxRunner green, kill BOTH python.exe (Django) AND node.exe (Angular) via Task Manager. Within ~3s: icon turns grey AND balloon "⚠ FoxRunner stopped unexpectedly". `state.json.active` is null.
- [ ] With FoxRunner green, kill ONLY the frontend node.exe. Within ~3s: icon turns orange AND balloon "⚠ FoxRunner: frontend crashed". `state.json.active` still present. Click Stop → grey, silent, ports free.
- [ ] Force a start failure: occupy port 8000, click Start FoxRunner. Balloon "Port in use: backend port 8000 still in use". Icon stays grey.

## start_timeout per project

- [ ] Add `start_timeout: 5` to one project in `config.yaml`. CLI `start` that project → fails in 5s if not healthy.

## Known Iter 3 limitations (intentional)

- `pending_starts` is per-process. Running `python main.py start X` while the tray is open → tray fires misleading "X started but one component failed" then "X recovered" during the Angular boot window. Work around: use CLI XOR tray, not both.
- Tray has no `wait_healthy` timeout. A permanently-orange icon means "not healthy yet"; no automatic "failed" balloon arrives unless a process actually dies.
- `stop` port-free wait logs a warning but does not raise. If a non-FoxTray tenant holds the port, you'll see the warning in stderr; `stop` still returns normally.

## Observed issues

- **Automated PortInUse test flaky on Windows.** Holding port 8000 via a bare socket that never calls `accept()` fills the listen backlog after a handful of `port_listening` probes; subsequent probes get `ECONNREFUSED` and `port_listening` returns `False` — so `wait_port_free` reports the port as "free" and `start` proceeds to spawn. This is a quirk of the diagnostic setup, not the code: a real server (Django, `python -m http.server`) keeps accepting connections and the path works as intended. Leave the checklist unchecked until interactively verified with two shells.
- **FoxRunner frontend port 4200 reports `frontend port open: False` while `url responds: True`.** Seen during `status FoxRunner` while running. Not a regression — same behavior exists on Iter 2. Probably Angular dev server binding IPv6 only / our `port_listening` checks IPv4. Worth revisiting in a later iteration if the `frontend_port_listening` flag is ever used for a decision.
- **No single-instance lock** — Iter 4 material.
