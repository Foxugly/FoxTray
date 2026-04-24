# FoxTray Iter 5b — Config Ergonomics Design

## Goal

Four config-side features that make `config.yaml` more portable and fail-fast on mistakes.

1. **`python main.py validate`** — CLI subcommand that loads config, checks each project's paths + venv python exist, reports issues, exits 0 on clean or 2 on any issue.
2. **`${ENV}` expansion** in path fields — `os.path.expandvars` applied to `backend.path`, `frontend.path`, `path_root`, and `scripts[].path` before absolute-path validation. Enables portable configs (`${USERPROFILE}\projects\FoxRunner_server`).
3. **`health_url` per project** — optional override for the URL used by `wait_healthy` / `url_ok`. Defaults to `project.url`. Lets the homepage differ from a lightweight health endpoint.
4. **`auto_start:` top-level** — optional name of the project to auto-start when `tray` launches. No-op if the project is already active.

## Non-goals

- `${ENV}` expansion in `command:` strings (only paths for now).
- Env expansion in `config.yaml` string fields other than paths.
- Auto-start with a delay or conditional logic.
- Validate command doesn't check `health_url` reachability (network-dependent).

## File structure

Modified:
- `foxtray/config.py` — `expandvars` in `_parse_backend` / `_parse_frontend` / `_parse_project` path fields and `_parse_script.path`; `Project.health_url: str | None = None`; `Config.auto_start: str | None = None`; validation of `auto_start` against project names.
- `foxtray/project.py` — `Orchestrator.status()` and `wait_healthy()` use `project.health_url or project.url`.
- `foxtray/cli.py` — `cmd_validate` + subparser; minor import.
- `foxtray/ui/tray.py` — `TrayApp.run()` spawns a background thread calling `orchestrator.start(project)` if `cfg.auto_start` resolves and no project is active.
- `tests/test_config.py` — expandvars + health_url + auto_start parsing.
- `tests/test_project.py` — `status()` uses `health_url` when present.
- `tests/test_cli.py` — `cmd_validate` happy + error paths.
- `tests/test_tray_app.py` — auto_start triggers on run.

New:
- `docs/manual-tests/iter5b.md`.

## Components

### `config.py` — env expansion

Helper:
```python
def _expand_path(raw: str) -> Path:
    return Path(os.path.expandvars(raw))
```

Apply in `_parse_backend`, `_parse_frontend`, `_parse_project` (for `path_root`), and `_parse_script` (for `path`).

### `config.py` — `Project.health_url`

```python
@dataclass(frozen=True)
class Project:
    # ... existing fields ...
    path_root: Path | None = None
    health_url: str | None = None  # NEW
```

`_parse_project` reads optional `health_url`, validates it's a non-empty string if present.

### `config.py` — `Config.auto_start`

```python
@dataclass(frozen=True)
class Config:
    projects: list[Project] = field(default_factory=list)
    scripts: tuple[Script, ...] = ()
    auto_start: str | None = None  # NEW
```

`load()` reads top-level `auto_start`, validates it's a string that matches one of the project names (raises `ConfigError` if not).

### `project.py` — respect `health_url`

`Orchestrator.status()`:
```python
health_target = project.health_url or project.url
url_ok=health.http_ok(health_target) if (backend_alive and frontend_alive) else False,
```

`wait_healthy` doesn't need direct change — it polls `self.status(project).url_ok` which already uses the right URL.

### `cli.py` — `cmd_validate`

```python
def cmd_validate(args: argparse.Namespace) -> int:
    try:
        cfg = config.load(args.config)
    except config.ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    issues: list[str] = []
    for proj in cfg.projects:
        if not proj.backend.path.exists():
            issues.append(f"{proj.name}: backend.path does not exist: {proj.backend.path}")
        elif not proj.backend.python_executable.exists():
            issues.append(
                f"{proj.name}: backend venv python missing: {proj.backend.python_executable}"
            )
        if not proj.frontend.path.exists():
            issues.append(f"{proj.name}: frontend.path does not exist: {proj.frontend.path}")
        if proj.path_root is not None and not proj.path_root.exists():
            issues.append(f"{proj.name}: path_root does not exist: {proj.path_root}")
    for script in cfg.scripts:
        if not script.path.exists():
            issues.append(f"script {script.name!r}: path does not exist: {script.path}")

    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 2
    print(f"Config OK: {len(cfg.projects)} project(s), {len(cfg.scripts)} script(s)")
    return 0
```

Register subparser:
```python
sub.add_parser("validate", help="Validate config.yaml — paths, venvs, script targets").set_defaults(func=cmd_validate)
```

### `tray.py` — auto-start

Inside `TrayApp.run()`, after `state.clear_if_orphaned()` and before creating `pystray.Icon`:

```python
self._schedule_auto_start()
```

```python
def _schedule_auto_start(self) -> None:
    if self._cfg.auto_start is None:
        return
    if state_mod.load().active is not None:
        return  # A project is already active (e.g., restarted tray mid-session)
    project = next((p for p in self._cfg.projects if p.name == self._cfg.auto_start), None)
    if project is None:
        log.warning("auto_start references unknown project %r", self._cfg.auto_start)
        return
    threading.Thread(
        target=self._auto_start_project, args=(project,),
        name=f"auto-start-{project.name}", daemon=True,
    ).start()


def _auto_start_project(self, project: config_mod.Project) -> None:
    self._orchestrator.pending_starts.add(project.name)
    try:
        self._orchestrator.start(project)
    except Exception:  # noqa: BLE001
        self._orchestrator.pending_starts.discard(project.name)
        log.warning("auto_start failed for %s", project.name, exc_info=True)
```

Note: no icon balloon for auto-start failure (the icon isn't created yet at this point — actually it IS, because `_schedule_auto_start` is called BEFORE `pystray.Icon(...)`). Let me fix that ordering: call `_schedule_auto_start()` AFTER `self._icon = pystray.Icon(...)` but BEFORE `self._icon.run()` so balloon is possible via existing poll-tick + watcher pattern (the natural "stopped → partial → running" transitions).

Actually simplest: schedule the start AFTER the poller thread starts, so the thread can run concurrently with `icon.run()`. Let me refine:

```python
def run(self) -> None:
    state_mod.clear_if_orphaned()
    self._icon = pystray.Icon(
        name="FoxTray",
        icon=icons.load("stopped"),
        title="FoxTray",
        menu=pystray.Menu(self._build_menu),
    )
    poller = threading.Thread(target=self._poll_loop, name="foxtray-poller", daemon=True)
    poller.start()
    self._schedule_auto_start()  # spawns start() in its own daemon thread
    try:
        self._icon.run()
    finally:
        self._stop_event.set()
        poller.join(timeout=_POLL_INTERVAL_S + 1.0)
```

The start thread runs `orchestrator.start(project)` which spawns backend + frontend. The poller picks up the state transition stopped → partial → running and fires balloons as usual. `pending_starts` is populated so the "X is up" balloon fires correctly (same mechanism as manual Start click).

## Data flow

**`python main.py validate`**: load config (with expandvars) → for each project check `backend.path`, `backend.python_executable`, `frontend.path`, `path_root`; for each script check `path` → print OK or list of issues → exit 0 or 2.

**`${ENV}` in a path**: `os.path.expandvars("${USERPROFILE}\\projects\\FoxRunner_server")` → `"C:\\Users\\Renaud\\projects\\FoxRunner_server"` (on Windows) → `Path(...)` → `is_absolute()` → True → kept. Unknown variables are left literal (e.g., `${UNDEFINED}\\x` stays as is) per `expandvars` standard behavior.

**`health_url`**: `cfg.projects[0].health_url = "http://localhost:8000/health"`. `Orchestrator.status()` calls `health.http_ok("http://localhost:8000/health")` instead of `http://localhost:4200`. Rest of lifecycle unchanged.

**`auto_start: FoxRunner`**: `TrayApp.run()` starts pystray and poller, then a daemon thread calls `orch.start(FoxRunner)`. 3 seconds later the poller tick sees state transition, fires "FoxRunner is up" balloon (via existing `pending_starts` mechanism).

## Error handling

| Failure | Behavior |
|---|---|
| `${ENV}` references undefined variable | `expandvars` leaves it literal; `Path.is_absolute()` may fail validation later if placeholder remains (user sees clear ConfigError) |
| `validate` config load fails | Prints `"Config error: ..."`, exit 2 |
| `validate` sees non-existent path | Printed to stderr, exit 2 |
| `auto_start` name not in projects | Top-level `ConfigError` at load time, exit 2 |
| `auto_start` succeeds but `start()` raises | Logged warning, no balloon (icon may or may not be up); user sees it in logs |
| Existing `Orchestrator.status()` error | Unchanged |

## Testing

Unit tests added to the relevant files. Manual smoke covers validate CLI output, env expansion, and auto_start end-to-end.

### Key tests:

**`test_config.py`:**
- `test_backend_path_expands_environment_variable` — `${USERPROFILE}` expansion.
- `test_script_path_expands_environment_variable`.
- `test_path_root_expands_environment_variable`.
- `test_project_without_health_url_defaults_none`.
- `test_project_health_url_parsed_when_provided`.
- `test_config_without_auto_start_defaults_none`.
- `test_config_auto_start_accepts_existing_project_name`.
- `test_config_auto_start_rejects_unknown_project_name` → `ConfigError`.

**`test_project.py`:**
- `test_status_uses_health_url_when_set` — monkeypatch `health.http_ok` to capture URL; assert health_url is passed when set, `url` when not.

**`test_cli.py`:**
- `test_cmd_validate_exits_0_on_clean_config` — use a config with real tmp_path paths that exist.
- `test_cmd_validate_exits_2_on_missing_backend_path`.
- `test_cmd_validate_exits_2_on_missing_venv_python`.
- `test_cmd_validate_reports_multiple_issues` — multiple projects with different issues.
- `test_cmd_validate_succeeds_with_scripts` — scripts present with existing paths.

**`test_tray_app.py`:**
- `test_run_schedules_auto_start_when_configured` — monkeypatch `pystray.Icon` stub + capture the start call.
- `test_run_skips_auto_start_when_active_project_exists` — seed state.json.active; auto_start should no-op.

## Self-review

- Placeholder scan: clean.
- Internal consistency: `auto_start` validated at load time prevents the tray from silently misbehaving.
- `expandvars` is idempotent (no-op on already-expanded paths).
- `health_url` respects existing `url_ok` propagation via `ProjectStatus` — no deeper refactor needed.
- Auto-start uses same `pending_starts` mechanism as manual Start, so the "X is up" balloon fires exactly like a user click.
