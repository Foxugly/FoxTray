# FoxTray Iter 3 — Reliability (Health Check, Port Free, Orphan Clear, Crash Detection) Design

## Goal

Close four reliability gaps that Iter 1 and Iter 2 explicitly deferred:

1. **Health-check wait after `start`.** `start` is no longer "OK" until the project's URL actually responds. Prevents false-positive success when Django boots but Angular crashes seconds later.
2. **`wait_port_free` around `stop`/`start`.** A `stop` does not return until its ports are free (with a cap); a `start` refuses to spawn onto a still-listening port.
3. **Orphan `state.json` clear at startup.** If `state.json` claims a project is active but its recorded PIDs are dead, the next CLI command or tray startup wipes the stale entry.
4. **Crash detection in the tray poller.** If the poller sees both components of the active project dead, `state.json.active` is cleared automatically (the existing "stopped unexpectedly" balloon continues to fire).

## Non-goals (deferred to later iterations)

- Single-instance lock for `python main.py tray` — Iter 4.
- `git pull` / `pip install` / `npm install` / `python manage.py migrate` "Update" action — Iter 4.
- `.exe` packaging with PyInstaller — Iter 4.
- Global keyboard shortcut to open the menu — Iter 4.
- In-tray log viewer — deferred indefinitely.
- Hot-reload of `config.yaml` while the tray is running — deferred.
- Cross-process sharing of `pending_starts` between a running tray and a simultaneous CLI `start` — see Known Limitations.

## Architecture overview

Four features, five files modified, no new packages, no new public classes.

| Feature | Primary change site | Callers / consumers |
|---|---|---|
| Health-check wait | `Orchestrator.wait_healthy()` new method on `foxtray/project.py`; `compute_icon_state` upgraded to include `url_ok`; `pending_starts` set added to `Orchestrator` | `cmd_start`, `TrayApp._poll_tick` via `compute_transitions`, `actions.on_start` |
| Port-free wait | `Orchestrator.start()` gains pre-spawn `wait_port_free` (3s, raises on fail); `Orchestrator.stop()` gains post-kill `wait_port_free` (10s, warn on fail) | All `start`/`stop` paths |
| Orphan clear at startup | `state.clear_if_orphaned()` new function | `cli.main()` (or first line of each `cmd_*`), `TrayApp.run()` |
| Crash detection | `TrayApp._poll_tick` end-of-tick call to `state.clear_if_orphaned()` | Implicit via poller |

`foxtray/health.py` is untouched (`wait_port_free` and `http_ok` already exist from Iter 1). `foxtray/process.py` gains one new exception class (`PortInUse`). `foxtray/logs.py`, `foxtray/paths.py` unchanged.

## File structure

Modified files:
- `foxtray/config.py` — add optional `start_timeout: int = 30` to `Project`; parse from YAML.
- `foxtray/state.py` — add `clear_if_orphaned() -> bool`.
- `foxtray/process.py` — add `PortInUse(RuntimeError)` exception class.
- `foxtray/project.py` — add `pending_starts: set[str]` field; add `wait_healthy()` method; `start()` pre-check + `stop()` post-wait.
- `foxtray/cli.py` — `cmd_start` calls `wait_healthy` after `start`; `main()` calls `clear_if_orphaned()` before dispatch; map `PortInUse` to a user-friendly error.
- `foxtray/ui/tray.py` — `_status_to_icon_state` and `compute_icon_state` require `url_ok`; `compute_transitions` accepts and mutates `pending_starts`; `TrayApp.run()` calls `clear_if_orphaned()`; `_poll_tick` calls it at end.
- `foxtray/ui/actions.py` — `on_start` populates `orchestrator.pending_starts` before spawn, removes on exception.

Modified tests:
- `tests/test_config.py` — `start_timeout` parsing.
- `tests/test_state.py` — `clear_if_orphaned` cases.
- `tests/test_project.py` — `wait_healthy` + port-free checks.
- `tests/test_tray.py` — `compute_icon_state` with `url_ok`, `compute_transitions` with `pending_starts`.
- `tests/test_tray_actions.py` — `on_start` pending_starts behavior.
- `tests/test_tray_app.py` — orphan clear on poll tick.
- `tests/test_cli.py` — `cmd_start` wait_healthy path (success and timeout), `clear_if_orphaned` called.

New files:
- `docs/manual-tests/iter3.md` — smoke-test checklist (extends iter2.md).

Unchanged: `foxtray/health.py`, `foxtray/logs.py`, `foxtray/paths.py`, `foxtray/ui/icons.py`, `foxtray/ui/__init__.py`, `main.py`, `assets/*.png`, `scripts/gen_icons.py`.

## Components

### `foxtray/config.py`

Add one optional field to `Project`:

```python
@dataclass(frozen=True)
class Project:
    name: str
    url: str
    backend: Backend
    frontend: Frontend
    start_timeout: int = 30
```

`_parse_project` reads `start_timeout` if present (integer, > 0), defaults to 30 otherwise. A non-integer or non-positive value raises `ConfigError`.

### `foxtray/state.py`

```python
def clear_if_orphaned() -> bool:
    """Clear state.json.active if the recorded PIDs are both dead.

    Returns True if a clear was performed, False otherwise (no active project,
    or at least one PID is still alive). Safe to call repeatedly.
    """
```

Uses `psutil.pid_exists(backend_pid) or psutil.pid_exists(frontend_pid)`. If **both** are dead, `save(State(active=None))` is called. If either is alive, no write.

Rationale for "both dead, not just one": a one-component failure is a partial crash, not orphan state — the tray's crash-balloon plus the user-triggered Stop still need the other PID to do their job.

### `foxtray/process.py`

```python
class PortInUse(RuntimeError):
    """Raised by Orchestrator.start when a required port is still occupied."""
```

Placed next to `ExecutableNotFound`. No other changes to `process.py`.

### `foxtray/project.py`

```python
class Orchestrator:
    def __init__(self, manager: _ManagerProtocol) -> None:
        self._manager = manager
        self.pending_starts: set[str] = set()  # names awaiting url_ok

    def start(self, project: config.Project) -> None:
        # ... existing auto-stop-active logic ...
        # After stop finishes (which now waits for port-free):
        if not health.wait_port_free(project.backend.port, timeout=3.0):
            raise process.PortInUse(
                f"backend port {project.backend.port} still in use"
            )
        if not health.wait_port_free(project.frontend.port, timeout=3.0):
            raise process.PortInUse(
                f"frontend port {project.frontend.port} still in use"
            )
        # ... existing Popen + state.save logic ...

    def stop(self, name: str) -> None:
        # ... existing kill_tree logic ...
        # After state.clear():
        cfg_project = self._project_by_name(name)  # helper; returns Project or None
        if cfg_project is not None:
            if not health.wait_port_free(cfg_project.backend.port, timeout=10.0):
                log.warning("stop: backend port %s still listening after timeout",
                            cfg_project.backend.port)
            if not health.wait_port_free(cfg_project.frontend.port, timeout=10.0):
                log.warning("stop: frontend port %s still listening after timeout",
                            cfg_project.frontend.port)

    def wait_healthy(
        self,
        project: config.Project,
        timeout: float = 30.0,
        interval: float = 1.0,
    ) -> bool:
        """Poll self.status(project).url_ok until True or timeout elapses."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.status(project).url_ok:
                return True
            time.sleep(interval)
        return self.status(project).url_ok
```

**`_project_by_name` helper:** `Orchestrator` currently takes only a `_ManagerProtocol`, not the `Config`. Two options:
- (A) Pass `Config` to `Orchestrator.__init__`, making it a second dependency.
- (B) Have `stop(name)` accept an optional `project: Project | None = None` argument that the CLI / tray pass in; if `None`, port-free wait is skipped.

**Decision: A.** Pass the `Config` in. The orchestrator already encapsulates "everything about running projects"; knowing the port map fits cleanly. All call sites construct the orchestrator inline (CLI's `_orchestrator()` helper; `TrayApp.__init__`), so the change is mechanical.

```python
class Orchestrator:
    def __init__(self, manager: _ManagerProtocol, cfg: config.Config) -> None:
        self._manager = manager
        self._cfg = cfg
        self.pending_starts: set[str] = set()

    def _project_by_name(self, name: str) -> config.Project | None:
        for p in self._cfg.projects:
            if p.name == name:
                return p
        return None
```

Callers update:
- `cli.py`: `_orchestrator(cfg)` — takes the already-loaded `Config`.
- `tray.py`: `TrayApp.__init__` already holds `cfg` — it now passes it into `Orchestrator` instead of receiving the orchestrator pre-built. But to keep the test seam of injecting a fake orchestrator in `test_tray_app.py`, we keep the current signature `TrayApp(cfg, orchestrator)` and require the caller to pre-build the orchestrator with the config. CLI does `Orchestrator(ProcessManager(), cfg)` then `TrayApp(cfg, orch)`.

### `foxtray/cli.py`

- `main()` calls `state.clear_if_orphaned()` immediately after `parse_args()` and before `args.func(args)`. Runs once per CLI invocation, for every subcommand whose argparse validated successfully.
- `_orchestrator(cfg)` now takes the loaded config.
- `cmd_start`:
  ```python
  def cmd_start(args: argparse.Namespace) -> int:
      cfg = config.load(args.config)
      proj = cfg.get(args.name)
      orch = _orchestrator(cfg)
      orch.start(proj)
      print(f"Started {proj.name}, waiting for health...")
      if orch.wait_healthy(proj, timeout=proj.start_timeout):
          print(f"{proj.name} is healthy")
          return 0
      print(
          f"{proj.name} failed to become healthy within {proj.start_timeout}s; "
          f"stopping",
          file=sys.stderr,
      )
      orch.stop(proj.name)
      return 1
  ```
  Note: CLI does NOT touch `pending_starts`. That set is only consumed by `compute_transitions` in the tray poller. CLI `wait_healthy` is synchronous and reports its own outcome.
- `main()` exception handlers: add a clause mapping `process.PortInUse` to exit code 2 with a clear message.

### `foxtray/ui/tray.py`

**`_status_to_icon_state` and `compute_icon_state`:** a project is `running` only when both processes are alive *and* `url_ok` is True. Otherwise `partial` if at least one process alive, else `stopped`.

```python
def _status_to_icon_state(status: ProjectStatus) -> IconState:
    if status.backend_alive and status.frontend_alive and status.url_ok:
        return "running"
    if status.backend_alive or status.frontend_alive:
        return "partial"
    return "stopped"
```

`compute_icon_state` body is unchanged — it delegates to `_status_to_icon_state` via `_project_icon_state`.

**`compute_transitions`** gains a `pending_starts: set[str]` parameter. New dispatch table:

| prev → curr | pending_starts? | Notification | Side effect |
|---|---|---|---|
| stopped → running | yes or no | `"X is up"` | discard(name) if present |
| stopped → partial | yes | *silent* | — |
| stopped → partial | no | `"X started but one component failed"` | — |
| partial → running | yes | `"X is up"` | discard(name) |
| partial → running | no | `"X recovered"` | — |
| partial → stopped | yes | `"⚠ X failed to start"` | discard(name) |
| partial → stopped | no, suppressed | *silent* | — |
| partial → stopped | no, not suppressed | `"⚠ X fully stopped"` | — |
| running → partial | any | `"⚠ X: {dead} crashed"` | — |
| running → stopped | suppressed | *silent* | — |
| running → stopped | not suppressed | `"⚠ X stopped unexpectedly"` | — |

The function mutates `pending_starts` in place via `.discard(name)` whenever it consumes a pending-start. Rationale: mirrors the existing `.discard` / `.add` pattern used on `suppressed` and `user_initiated_stop` elsewhere. Concurrency is handled by GIL atomicity of `set.discard()`; no swap required because names accumulate and are consumed individually, unlike `suppressed` which is reset per tick.

**`TrayApp`:**
```python
class TrayApp:
    def __init__(self, cfg, orchestrator):
        # ... existing ...
        # orchestrator.pending_starts is owned by the orchestrator; TrayApp reads it.

    def run(self):
        state.clear_if_orphaned()  # NEW
        # ... existing ...

    def _poll_tick(self):
        if self._icon is None:
            return
        try:
            curr_active = state_mod.load().active
            curr_statuses = {
                p.name: self._orchestrator.status(p) for p in self._cfg.projects
            }

            suppressed = self._user_initiated_stop
            self._user_initiated_stop = set()

            for note in compute_transitions(
                self._prev_active, self._prev_statuses,
                curr_active, curr_statuses,
                suppressed=suppressed,
                pending_starts=self._orchestrator.pending_starts,
            ):
                self._icon.notify(note.message, title=note.title)

            new_icon_state = compute_icon_state(curr_active, curr_statuses)
            if new_icon_state != self._prev_icon_state:
                self._icon.icon = icons.load(new_icon_state)
                self._prev_icon_state = new_icon_state

            self._prev_active = curr_active
            self._prev_statuses = curr_statuses

            # NEW — crash detection / orphan reconciliation.
            if state.clear_if_orphaned():
                log.info("poll tick cleared orphaned state for %s",
                         curr_active.name if curr_active else "?")
                self._prev_active = None
        except Exception:
            log.warning("poll tick failed", exc_info=True)
```

Note: `clear_if_orphaned()` runs **after** the transition computation for this tick. This preserves the "⚠ X stopped unexpectedly" balloon (fires via `running → stopped` using `prev_active` = the dead project, `curr_active` = still the dead project in `state.json` at this tick). The clear happens at the *end*, so the *next* tick sees `curr_active = None` and stays silent.

### `foxtray/ui/actions.py`

```python
def on_start(orchestrator: Orchestrator, project: config.Project, icon: _Notifier) -> None:
    orchestrator.pending_starts.add(project.name)
    try:
        orchestrator.start(project)
    except Exception as exc:  # noqa: BLE001
        orchestrator.pending_starts.discard(project.name)
        _notify_error(icon, exc)
```

The rest of `actions.py` is unchanged.

## Data flow per feature

### Feature 1: CLI `start FoxRunner`

1. `cli.main()` calls `state.clear_if_orphaned()` (no-op in clean case).
2. `cmd_start` loads config, resolves `FoxRunner`.
3. `Orchestrator.__init__(manager, cfg)`.
4. `orchestrator.start(project)`:
   - auto-stops active project (if any), which internally calls `wait_port_free` on *its* ports.
   - `wait_port_free(backend.port, 3.0)` and `wait_port_free(frontend.port, 3.0)` — raise `PortInUse` if either fails.
   - `Popen` both components, write `state.json`.
5. Print `"Started FoxRunner, waiting for health..."`.
6. `orchestrator.wait_healthy(project, timeout=project.start_timeout)`:
   - loop: `status(project).url_ok`; if True, return True.
   - `time.sleep(1.0)`; check deadline.
   - on timeout: return False.
7. If True: print `"FoxRunner is healthy"`, return 0.
8. If False: print error to stderr, call `orchestrator.stop("FoxRunner")` (which waits for port-free), return 1.

### Feature 1 variant: tray menu Start FoxRunner

1. `actions.on_start(orch, project, icon)`:
   - `orch.pending_starts.add("FoxRunner")`.
   - `orch.start(project)` — may raise `PortInUse`, caught → balloon + discard.
   - on success: returns immediately; does NOT call `wait_healthy` (poller handles it).
2. Poller tick T+3s: status shows backend/frontend alive, `url_ok` still False → icon_state = `partial`.
   - `compute_transitions`: prev = stopped, curr = partial, `"FoxRunner" in pending_starts` → *silent*.
3. Poller tick T+6s: `url_ok` still False → still `partial` → no transition, silent.
4. Poller tick T+9s: Django is fully up, Angular is fully up, URL responds 200 → `url_ok` True → icon_state = `running`.
   - `compute_transitions`: prev = partial, curr = running, `"FoxRunner" in pending_starts` → `"FoxRunner is up"` balloon, `discard("FoxRunner")`.
5. Icon image swaps to green.

### Feature 1 failure variant: tray Start, but URL never responds

1. Steps 1–3 as above.
2. The user sees a persistent orange icon. No "failed to start" balloon (no timeout in the tray path — that would require time-based state we said we wouldn't add in Iter 3).
3. User diagnoses via logs (`%APPDATA%\foxtray\logs\FoxRunner_frontend.log`) or clicks Stop and retries.
4. If eventually one of the procs dies, `partial → stopped` with `"FoxRunner" in pending_starts` fires `"⚠ FoxRunner failed to start"` and discards.

### Feature 2: stop + immediate start cycle

1. User runs `stop FoxRunner` (CLI) or clicks Stop (tray).
2. `orchestrator.stop("FoxRunner")`:
   - `kill_tree(backend_pid)`, `kill_tree(frontend_pid)`.
   - `state.clear()`.
   - `wait_port_free(backend.port, 10.0)` — typically returns True within ~200ms.
   - `wait_port_free(frontend.port, 10.0)`.
3. User immediately runs `start FoxRunner`:
   - `wait_port_free(backend.port, 3.0)` — already free, returns immediately.
   - `wait_port_free(frontend.port, 3.0)` — same.
   - `Popen` both components.

### Feature 3: orphan clear at startup

1. User kills the Python interpreter running FoxTray mid-flight (Task Manager, reboot, etc). Children die with it (via CREATE_NEW_PROCESS_GROUP... actually no, Windows child processes survive unless explicitly killed; this is the `state.json` stale case).
2. Next invocation `python main.py list`:
   - `cli.main()` calls `state.clear_if_orphaned()`:
     - `state.load()` → active = `ActiveProject(name="FoxRunner", backend_pid=39400, frontend_pid=44768)`.
     - `psutil.pid_exists(39400)` → False. `psutil.pid_exists(44768)` → False.
     - `save(State(active=None))`.
     - return True.
   - Dispatch to `cmd_list`.
   - All projects print as `stopped`.

### Feature 4: crash detection in running tray

1. Tray is running, FoxRunner active and green.
2. Both Django and Angular die (OS OOM-kill, manual Task Manager End, etc).
3. Poller tick at T+3s:
   - `status(FoxRunner)` → `backend_alive=False, frontend_alive=False, url_ok=False`.
   - `compute_transitions`: prev = running (from last tick), curr = stopped, `"FoxRunner"` NOT in suppressed (user didn't Stop) → fires `"⚠ FoxRunner stopped unexpectedly"`.
   - Icon swaps to grey.
   - End of tick: `clear_if_orphaned()` → both PIDs dead → `save(State(active=None))` → returns True → `self._prev_active = None`.
4. Next tick: `state.load().active = None`. `curr_active = None`. `compute_transitions`: prev_active = None (reset), curr_active = None → no transitions. Silent.

## Error handling

| Failure | Detection | Behavior |
|---|---|---|
| `start_timeout` YAML value invalid (non-int / <=0) | `config._parse_project` | `ConfigError` at startup |
| `start()` finds port still busy after 3s wait | `health.wait_port_free` returns False | `PortInUse` raised; CLI prints + exits 2; tray catches and balloons |
| `stop()` fails to free port within 10s | `health.wait_port_free` returns False | `log.warning` only; `stop` returns normally (kill already happened) |
| `wait_healthy` times out (CLI) | deadline reached | `cmd_start` prints error, calls `orchestrator.stop(name)`, returns 1 |
| `wait_healthy` never succeeds (tray, no timeout) | n/a — tray has no CLI wait path | Icon stays orange indefinitely; pending_starts retains name until `partial → stopped` transition fires `"failed to start"` |
| `state.clear_if_orphaned` raises (filesystem error) | `psutil` / `state.save` | Propagates up; tray's `_poll_tick` catches, logs, continues; CLI's `main()` lets it bubble to existing `OSError` handler |
| `orchestrator.status()` raises during `wait_healthy` | any | Propagates out of `cmd_start` (rare; surfaces real bug) |
| Poller tick exception (including new orphan-clear path) | existing `except Exception` at `_poll_tick` tail | Logged; next tick retries |

## Testing

### Unit tests (pytest)

**`tests/test_config.py`:**
- `start_timeout` absent → defaults to 30.
- `start_timeout: 60` → parsed as 60.
- `start_timeout: 0` or `-5` → `ConfigError`.
- `start_timeout: "x"` → `ConfigError`.

**`tests/test_state.py`:**
- `clear_if_orphaned` with `active=None` → False, no write.
- `clear_if_orphaned` with both PIDs alive (monkeypatch `psutil.pid_exists` returning True) → False, no write.
- `clear_if_orphaned` with one PID alive, one dead → False, no write (both-dead rule).
- `clear_if_orphaned` with both PIDs dead → True, `state.json` now has `active: null`.

**`tests/test_project.py`:**
- `Orchestrator.__init__` accepts `(manager, cfg)`.
- `wait_healthy` returns True immediately if `status().url_ok` is True (fake orchestrator or monkeypatched `health.http_ok`).
- `wait_healthy` returns False after `timeout` seconds if `url_ok` stays False. Use monkeypatched `time.monotonic` and `time.sleep` to avoid real waits.
- `start` raises `PortInUse` if `wait_port_free(backend.port, 3.0)` returns False (monkeypatch `health.wait_port_free`).
- `start` raises `PortInUse` for frontend port similarly.
- `start` does NOT spawn (Popen not called) when `PortInUse` is raised.
- `stop` calls `wait_port_free` on both ports after `kill_tree`; timeout is logged via `caplog`, not raised.
- `stop(name)` for a name not in config is tolerated (`_project_by_name` returns None; port-free wait is skipped).
- `pending_starts` starts empty on `__init__`.

**`tests/test_tray.py`:**
- `_status_to_icon_state` (via `compute_icon_state`):
  - both alive + `url_ok=True` → `running`.
  - both alive + `url_ok=False` → `partial` (new behavior).
  - one alive → `partial`.
  - neither alive → `stopped`.
- `compute_transitions` with `pending_starts`:
  - stopped → partial, name in pending_starts → no notification, pending_starts unchanged (still in set).
  - stopped → partial, name NOT in pending_starts → `"X started but one component failed"`.
  - partial → running, name in pending_starts → `"X is up"`, name removed from pending_starts.
  - partial → running, name NOT in pending_starts → `"X recovered"`.
  - partial → stopped, name in pending_starts → `"⚠ X failed to start"`, name removed.
  - partial → stopped, name NOT in pending_starts, NOT in suppressed → `"⚠ X fully stopped"`.
  - stopped → running (cold-start case) → `"X is up"`, name removed from pending_starts if present.

**`tests/test_tray_actions.py`:**
- `on_start` adds to `orchestrator.pending_starts` BEFORE calling `orchestrator.start`.
- `on_start` on success: pending_starts contains name (removal happens later via transitions, not here).
- `on_start` on exception: pending_starts no longer contains name; error is notified.

**`tests/test_tray_app.py`:**
- `TrayApp.run()` calls `state.clear_if_orphaned()` on entry (monkeypatch, verify call).
- `_poll_tick` with orphaned state: after tick, `state.json.active is None`, a `"stopped unexpectedly"` notification fired, and `_prev_active` reset.
- `_poll_tick` end-to-end: stopped → partial (silent, pending_starts populated by test) → running (fires "is up", removes from pending_starts).
- `_poll_tick` passes `orchestrator.pending_starts` into `compute_transitions` (via spy on `compute_transitions`).

**`tests/test_cli.py`:**
- `cmd_start` success path: `wait_healthy` returns True → exit 0, prints "healthy".
- `cmd_start` timeout path: `wait_healthy` returns False → `orchestrator.stop` called, exit 1, stderr has "failed to become healthy".
- `cli.main()` calls `state.clear_if_orphaned()` exactly once before dispatch, for every subcommand including `--help` (or every subcommand that passes argparse — if argparse exits before dispatch we skip; confirm in test).
- `PortInUse` raised in `cmd_start` → exit 2, stderr message.

### Manual smoke test (`docs/manual-tests/iter3.md`)

- [ ] `python main.py start FoxRunner` — prints "waiting for health...", ~15s later prints "FoxRunner is healthy", exit 0.
- [ ] Break `config.yaml` (e.g., backend command `python -c "import sys;sys.exit(1)"`). `start FoxRunner` → times out after 30s, prints "failed to become healthy; stopping", exit 1. `state.json.active` is null.
- [ ] Occupy port 8000 (`python -m http.server 8000`). `start FoxRunner` → `PortInUse` error within 3s, no Popen children spawned, exit 2.
- [ ] Start FoxRunner, then immediately stop, then start again. No `EADDRINUSE` (ports are free by the time `stop` returns).
- [ ] **Tray** — launch tray, click Start FoxRunner. Icon goes orange for ~15s, then green + balloon "FoxRunner is up" (single balloon).
- [ ] **Tray crash detection** — with FoxRunner green, kill BOTH `python.exe` (Django) and `node.exe` (ng serve) via Task Manager. Within ~3s: orange briefly (one component dies first), then grey + balloon "⚠ FoxRunner stopped unexpectedly". `state.json.active` is null.
- [ ] **Tray partial crash** — with FoxRunner green, kill ONLY the frontend. Within ~3s: orange + balloon "⚠ FoxRunner: frontend crashed". `state.json.active` still present. Click Stop → grey, silent, `state.json` cleared, ports free.
- [ ] **Orphan startup** — edit `state.json` manually to set `active` to a bogus project with fake PIDs. Run `python main.py list` — prints all stopped; verify `state.json.active` is now null.
- [ ] **Orphan tray startup** — same as above, then run `python main.py tray` — grey icon, no phantom "active" state.
- [ ] `start_timeout` customisation — add `start_timeout: 5` to one project's YAML. `start` on it → fails faster if not healthy in 5s.

### Known Iter 3 limitations (intentional)

- **`pending_starts` is per-process.** If `python main.py start FoxRunner` runs while a tray is also open, the tray does not see the CLI's `pending_starts`. The tray will emit `"FoxRunner started but one component failed"` during the Angular boot window (wrong but harmless), then `"FoxRunner recovered"` when `url_ok` flips. Both balloons are technically misleading; neither blocks work. Fixing requires cross-process state (shared-memory file, socket, or merging CLI into the tray process) — out of scope for Iter 3.
- **No `wait_healthy` timeout in tray path.** A permanently-orange tray is a UX smell we accept. Adding a time-based timeout in the tray would require tracking "start time per pending project" with its own cleanup logic; not worth the complexity for Iter 3.
- **`stop()` port-free timeout logs but doesn't raise.** If a port stays occupied after 10s it's almost certainly a non-FoxTray tenant (another process on the same port). Raising would break the caller's `finally` cleanup flow. Log + continue is the pragmatic choice.
- **`clear_if_orphaned` only fires "both PIDs dead".** A zombie where one PID is alive but unresponsive (hung Angular) won't trigger clear. Correct — one alive component is still something the user can Stop.
- **No stale log rotation in Iter 3.** `logs.rotate` runs on every `start`, which is fine as long as the process doesn't accumulate starts across weeks without a restart; no change here.
- **Config hot-reload still deferred.** Changing `start_timeout` in YAML while the tray is running requires restarting the tray.

## Self-review

- **Placeholders scan:** no TBD / TODO / "similar to" references in this design.
- **Internal consistency:** `ProjectStatus.running` field semantics (`backend_alive and frontend_alive`) is **unchanged** — the new `url_ok` criterion lives in `_status_to_icon_state` and `wait_healthy`, not in `ProjectStatus.running`. `cmd_status` and `cmd_list` still display `running` by the old rule, which matches the existing manual test script for Iter 1. If we ever want `cmd_list` to show health too, that's an Iter 4 UI change, not a semantic one.
- **Scope check:** single iteration, single plan.
- **Ambiguity check:**
  - "Orphan" = both PIDs dead, documented in `state.clear_if_orphaned` and in Known Limitations.
  - `pending_starts` mutation rule: `.discard(name)` in `compute_transitions` on consumption; caller never resets it. Documented.
  - `wait_healthy` polls via `self.status(project)` which re-reads `state.json` and process liveness each call — intentional, so that if the process dies mid-wait, we see `url_ok=False` naturally (since `status` short-circuits `url_ok` when procs are dead).
