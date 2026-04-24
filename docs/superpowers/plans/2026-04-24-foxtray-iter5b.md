# FoxTray Iter 5b (Config Ergonomics) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended).

**Goal:** `validate` CLI, `${ENV}` expansion in paths, optional `health_url` per project, optional `auto_start` top-level.

**Spec:** `docs/superpowers/specs/2026-04-24-foxtray-iter5b-design.md`.

---

## Task 1: `${ENV}` expansion + `health_url` + `auto_start` config parsing

**Files:** `foxtray/config.py`, `tests/test_config.py`.

- [ ] **Step 1: Append tests to `tests/test_config.py`**

```python
import os


def test_backend_path_expands_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FOX_ROOT", "D:\\roots\\foxrunner")
    yaml_body = SAMPLE_YAML.replace(
        "path: D:\\\\projects\\\\foxrunner-server",
        "path: ${FOX_ROOT}",
    )
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.projects[0].backend.path == Path("D:\\roots\\foxrunner")


def test_script_path_expands_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SCRIPT_HOME", "D:\\scripts")
    yaml_body = (
        SAMPLE_YAML.rstrip()
        + "\nscripts:\n"
        + "  - name: Example\n"
        + "    path: ${SCRIPT_HOME}\\migrate\n"
        + "    command: python one_off.py\n"
    )
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.scripts[0].path == Path("D:\\scripts\\migrate")


def test_path_root_expands_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPOS", "D:\\repos")
    yaml_body = SAMPLE_YAML.rstrip() + "\n    path_root: ${REPOS}\\FoxRunner\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.projects[0].path_root == Path("D:\\repos\\FoxRunner")


def test_project_without_health_url_defaults_none(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.projects[0].health_url is None


def test_project_health_url_parsed_when_provided(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    health_url: http://localhost:8000/health\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.projects[0].health_url == "http://localhost:8000/health"


def test_project_health_url_rejects_empty_string(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + '\n    health_url: ""\n'
    with pytest.raises(config.ConfigError, match="health_url"):
        config.load(write_config(tmp_path, yaml_body))


def test_config_without_auto_start_defaults_none(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.auto_start is None


def test_config_auto_start_accepts_existing_project_name(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n\nauto_start: FoxRunner\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.auto_start == "FoxRunner"


def test_config_auto_start_rejects_unknown_project_name(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n\nauto_start: NopeProject\n"
    with pytest.raises(config.ConfigError, match="auto_start"):
        config.load(write_config(tmp_path, yaml_body))
```

- [ ] **Step 2: Run, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```

Expect: ~6 new failures (expansion, health_url fields, auto_start field).

- [ ] **Step 3: Add `os` import + expansion helper in `foxtray/config.py`**

Add `import os` to imports if not present. Add helper near other private helpers:

```python
def _expand_path(raw: str) -> Path:
    return Path(os.path.expandvars(raw))
```

- [ ] **Step 4: Apply expansion in path parsing**

In `_parse_backend`:
```python
path=_expand_path(_require(raw, "path", "backend")),
```

In `_parse_frontend`:
```python
path=_expand_path(_require(raw, "path", "frontend")),
```

In `_parse_project` (path_root):
```python
path_root_raw = raw.get("path_root")
path_root: Path | None = None
if path_root_raw is not None:
    path_root = _expand_path(path_root_raw)
    if not path_root.is_absolute():
        raise ConfigError(
            f"project {name!r}: path_root must be absolute, got {path_root_raw!r}"
        )
```

In `_parse_script`:
```python
path = _expand_path(path_raw)
```

(The rest of the validation — `is_absolute()` — still runs unchanged after expansion.)

- [ ] **Step 5: Add `health_url` field and parsing**

Extend `Project` dataclass:
```python
@dataclass(frozen=True)
class Project:
    name: str
    url: str
    backend: Backend
    frontend: Frontend
    start_timeout: int = 30
    tasks: tuple[Task, ...] = ()
    path_root: Path | None = None
    health_url: str | None = None
```

In `_parse_project`, before the final `return Project(...)`:
```python
health_url_raw = raw.get("health_url")
if health_url_raw is not None and (not isinstance(health_url_raw, str) or not health_url_raw):
    raise ConfigError(
        f"project {name!r}: health_url must be a non-empty string if present"
    )
```

Add `health_url=health_url_raw,` to the `Project(...)` constructor.

- [ ] **Step 6: Add `auto_start` field and validation**

Extend `Config` dataclass:
```python
@dataclass(frozen=True)
class Config:
    projects: list[Project] = field(default_factory=list)
    scripts: tuple[Script, ...] = ()
    auto_start: str | None = None
```

In `load()`, after parsing scripts but before `return Config(...)`:
```python
auto_start_raw = raw.get("auto_start")
if auto_start_raw is not None:
    if not isinstance(auto_start_raw, str) or not auto_start_raw:
        raise ConfigError("auto_start must be a non-empty string if present")
    if auto_start_raw not in [p.name for p in projects]:
        raise ConfigError(
            f"auto_start references unknown project {auto_start_raw!r}"
        )
```

Add `auto_start=auto_start_raw,` to the `Config(...)` constructor.

- [ ] **Step 7: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add foxtray/config.py tests/test_config.py
git commit -m "feat(config): \${ENV} path expansion + health_url + auto_start"
```

Full message:
```
feat(config): ${ENV} path expansion + health_url + auto_start

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 2: `Orchestrator.status` respects `health_url`

**Files:** `foxtray/project.py`, `tests/test_project.py`.

- [ ] **Step 1: Append failing test to `tests/test_project.py`**

```python
def test_status_uses_health_url_when_set(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    custom_url = "http://localhost:9000/health"
    proj_with_health = config.Project(
        name=sample_project.name,
        url=sample_project.url,
        backend=sample_project.backend,
        frontend=sample_project.frontend,
        start_timeout=sample_project.start_timeout,
        tasks=sample_project.tasks,
        path_root=sample_project.path_root,
        health_url=custom_url,
    )
    state.save(state.State(active=state.ActiveProject(
        name=proj_with_health.name, backend_pid=1, frontend_pid=2
    )))
    monkeypatch.setattr(project.psutil, "pid_exists", lambda pid: True)
    captured: list[str] = []
    def _fake_http_ok(url: str, timeout: float = 1.0) -> bool:
        captured.append(url)
        return True
    monkeypatch.setattr(project.health, "http_ok", _fake_http_ok)

    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(proj_with_health))
    orch.status(proj_with_health)
    assert captured == [custom_url]


def test_status_falls_back_to_url_when_no_health_url(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # sample_project has health_url=None
    state.save(state.State(active=state.ActiveProject(
        name=sample_project.name, backend_pid=1, frontend_pid=2
    )))
    monkeypatch.setattr(project.psutil, "pid_exists", lambda pid: True)
    captured: list[str] = []
    def _fake_http_ok(url: str, timeout: float = 1.0) -> bool:
        captured.append(url)
        return True
    monkeypatch.setattr(project.health, "http_ok", _fake_http_ok)

    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    orch.status(sample_project)
    assert captured == [sample_project.url]
```

- [ ] **Step 2: Run, confirm failures**

- [ ] **Step 3: Update `foxtray/project.py` `status()`**

Find the line:
```python
url_ok=health.http_ok(project.url) if (backend_alive and frontend_alive) else False,
```

Replace with:
```python
url_ok=health.http_ok(project.health_url or project.url) if (backend_alive and frontend_alive) else False,
```

- [ ] **Step 4: Run full suite**

- [ ] **Step 5: Commit**

```bash
git add foxtray/project.py tests/test_project.py
git commit -m "feat(project): status respects Project.health_url fallback to url"
```

Full message with Co-Authored-By.

---

## Task 3: `cmd_validate` CLI command

**Files:** `foxtray/cli.py`, `tests/test_cli.py`.

- [ ] **Step 1: Append failing tests to `tests/test_cli.py`**

```python
def test_cmd_validate_exits_0_on_clean_config(
    tmp_path: Path, tmp_appdata: Path, capsys: pytest.CaptureFixture,
) -> None:
    # Build a config where all paths exist
    backend_dir = tmp_path / "back"
    frontend_dir = tmp_path / "front"
    venv_scripts = backend_dir / ".venv" / "Scripts"
    backend_dir.mkdir()
    frontend_dir.mkdir()
    venv_scripts.mkdir(parents=True)
    (venv_scripts / "python.exe").write_bytes(b"")  # dummy file to make exists() True

    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        f"""
projects:
  - name: X
    url: http://127.0.0.1:9
    backend:
      path: {str(backend_dir).replace(chr(92), chr(92) + chr(92))}
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: {str(frontend_dir).replace(chr(92), chr(92) + chr(92))}
      command: ng serve --port 4200
      port: 4200
""",
        encoding="utf-8",
    )
    rc = cli.main(["--config", str(cfg_path), "validate"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out


def test_cmd_validate_exits_2_on_missing_backend_path(
    tmp_path: Path, tmp_appdata: Path, capsys: pytest.CaptureFixture,
) -> None:
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        """
projects:
  - name: X
    url: http://127.0.0.1:9
    backend:
      path: D:\\\\nonexistent_backend_xyz
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: D:\\\\nonexistent_frontend_xyz
      command: ng serve --port 4200
      port: 4200
""",
        encoding="utf-8",
    )
    rc = cli.main(["--config", str(cfg_path), "validate"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "backend.path does not exist" in err
    assert "frontend.path does not exist" in err


def test_cmd_validate_exits_2_on_missing_venv_python(
    tmp_path: Path, tmp_appdata: Path, capsys: pytest.CaptureFixture,
) -> None:
    backend_dir = tmp_path / "back"
    frontend_dir = tmp_path / "front"
    backend_dir.mkdir()
    frontend_dir.mkdir()
    # No .venv inside backend_dir

    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        f"""
projects:
  - name: X
    url: http://127.0.0.1:9
    backend:
      path: {str(backend_dir).replace(chr(92), chr(92) + chr(92))}
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: {str(frontend_dir).replace(chr(92), chr(92) + chr(92))}
      command: ng serve --port 4200
      port: 4200
""",
        encoding="utf-8",
    )
    rc = cli.main(["--config", str(cfg_path), "validate"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "venv python missing" in err
```

- [ ] **Step 2: Run, confirm failures**

- [ ] **Step 3: Add `cmd_validate` to `foxtray/cli.py`**

Add before `build_parser`:

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

Register in `build_parser` (add right before `return parser`):

```python
sub.add_parser(
    "validate",
    help="Validate config.yaml — paths, venvs, script targets",
).set_defaults(func=cmd_validate)
```

- [ ] **Step 4: Run full suite**

- [ ] **Step 5: Commit**

```bash
git add foxtray/cli.py tests/test_cli.py
git commit -m "feat(cli): validate subcommand for path + venv checks"
```

Full message with Co-Authored-By.

---

## Task 4: `auto_start` wiring in `TrayApp.run()`

**Files:** `foxtray/ui/tray.py`, `tests/test_tray_app.py`.

- [ ] **Step 1: Append failing tests to `tests/test_tray_app.py`**

```python
def test_run_schedules_auto_start_when_configured(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(
        projects=[_project("A")],
        auto_start="A",
    )

    started: list[str] = []

    class _OrchStub:
        pending_starts: set[str] = set()
        def start(self, project): started.append(project.name)
        def stop(self, name): ...
        def stop_all(self): ...
        def status(self, project): ...

    import pystray
    class _StubIcon:
        def __init__(self, **kwargs): pass
        def run(self): return None
        def notify(self, message, title=""): pass
        icon = None
        title = "FoxTray"

    monkeypatch.setattr(pystray, "Icon", _StubIcon)

    app = tray.TrayApp(cfg, _OrchStub(), _StubProcessManager())  # type: ignore[arg-type]
    app.run()

    # The auto-start thread is a daemon; give it a moment to run
    import time
    deadline = time.monotonic() + 1.0
    while not started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started == ["A"]


def test_run_skips_auto_start_when_active_project_exists(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(
        projects=[_project("A")],
        auto_start="A",
    )
    # Seed an active project
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))

    started: list[str] = []

    class _OrchStub:
        pending_starts: set[str] = set()
        def start(self, project): started.append(project.name)
        def stop(self, name): ...
        def stop_all(self): ...
        def status(self, project): ...

    import pystray
    class _StubIcon:
        def __init__(self, **kwargs): pass
        def run(self): return None
        def notify(self, message, title=""): pass
        icon = None
        title = "FoxTray"
    monkeypatch.setattr(pystray, "Icon", _StubIcon)
    # Make clear_if_orphaned think the PIDs are alive so state is preserved
    monkeypatch.setattr("foxtray.state.psutil.pid_exists", lambda pid: True)

    app = tray.TrayApp(cfg, _OrchStub(), _StubProcessManager())  # type: ignore[arg-type]
    app.run()

    import time
    time.sleep(0.3)
    assert started == []
```

- [ ] **Step 2: Run, confirm failures**

- [ ] **Step 3: Add `_schedule_auto_start` and `_auto_start_project` to `TrayApp`**

In `foxtray/ui/tray.py`, add these two methods to `TrayApp`:

```python
def _schedule_auto_start(self) -> None:
    if self._cfg.auto_start is None:
        return
    if state_mod.load().active is not None:
        return
    project = next(
        (p for p in self._cfg.projects if p.name == self._cfg.auto_start), None
    )
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

Update `run()` to call `_schedule_auto_start()` after the poller starts:

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
    self._schedule_auto_start()
    try:
        self._icon.run()
    finally:
        self._stop_event.set()
        poller.join(timeout=_POLL_INTERVAL_S + 1.0)
```

- [ ] **Step 4: Run full suite**

- [ ] **Step 5: Commit**

```bash
git add foxtray/ui/tray.py tests/test_tray_app.py
git commit -m "feat(ui/tray): TrayApp.run auto-starts Config.auto_start project"
```

Full message with Co-Authored-By.

---

## Task 5: `validate` subcommand subparser registration check + manual smoke doc

**Files:** `docs/manual-tests/iter5b.md`.

- [ ] **Step 1: Create `docs/manual-tests/iter5b.md`**

```markdown
# FoxTray Iter 5b — Manual Test Log

Prerequisite: Iter 5a passed.

## Environment
- Date: <fill>
- HEAD: <commit sha>

## validate CLI

- [ ] `python main.py validate` — on a clean config, prints `Config OK: 3 project(s), 0 script(s)`, exit 0.
- [ ] Temporarily rename `D:\PycharmProjects\FoxRunner_server` to break the path. Run `python main.py validate` — prints `FoxRunner: backend.path does not exist: ...`, exit 2. Rename back.
- [ ] Temporarily rename FoxRunner's `.venv` folder. `python main.py validate` — prints `FoxRunner: backend venv python missing: ...`, exit 2.
- [ ] With a clean config, `python main.py validate --help` shows the subcommand description.

## ${ENV} expansion

- [ ] Replace a hardcoded path in `config.yaml` with `${USERPROFILE}\WebstormProjects\FoxRunner_frontend` (or equivalent). `validate` still succeeds. `tray` still starts the project correctly.

## health_url

- [ ] Add `health_url: http://localhost:4200/something/lighter` to FoxRunner in config.yaml.
- [ ] `start FoxRunner` — wait_healthy polls the new URL. If it responds, "FoxRunner is healthy". Verify via `foxtray_backend.log` or Fiddler/Wireshark.

## auto_start

- [ ] Add `auto_start: FoxRunner` at the top level of config.yaml.
- [ ] Launch `python main.py tray` — after ~3s, FoxRunner spawns automatically. Icon turns orange then green. Balloon "FoxRunner is up".
- [ ] Stop FoxRunner via menu. Verify balloon "stopped" behavior is unchanged.
- [ ] Remove `auto_start:`, restart tray — no auto-start occurs.

## Known limitations
- `${ENV}` expansion only applies to path fields, not to `command` or `url` strings.
- `auto_start` failures (e.g., port busy) are logged but not surfaced via balloon (happens before icon is fully ready).

## Observed issues
_None yet._
```

- [ ] **Step 2: Commit**

```bash
git add docs/manual-tests/iter5b.md
git commit -m "docs(iter5b): manual smoke checklist"
```

Full message with Co-Authored-By.

---

## Self-review

- Task 1 ordering: expansion first (keeps existing tests passing since expandvars no-ops on already-absolute literal paths), then new fields.
- No transient failures expected between tasks.
- `auto_start` test uses `_StubProcessManager` helper from test_tray_app.py (existing from Iter 4a).
