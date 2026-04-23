# FoxTray Iter 3 (Reliability) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close four reliability gaps so FoxTray no longer says "started" before a URL actually responds, no longer races on port reuse, and never leaves `state.json` pointing at dead PIDs.

**Architecture:** `Orchestrator` gains a `wait_healthy()` method and a `pending_starts: set[str]` field (used only by the tray poller). `Orchestrator.start` pre-checks port freedom and raises `PortInUse`; `Orchestrator.stop` post-waits for ports to free (warn on timeout). `state.clear_if_orphaned()` wipes stale `active` entries when both recorded PIDs are dead — called from `cli.main()` and from `TrayApp.run()` / `_poll_tick`. Tray icon state upgraded to require `url_ok` for `running`; `compute_transitions` receives `pending_starts` to route the "X is up" / "failed to start" balloons correctly.

**Tech Stack:** existing only — `psutil` (PID checks), `requests` (inside `health.http_ok`), `pystray` (unchanged surface).

**Spec:** `docs/superpowers/specs/2026-04-23-foxtray-iter3-design.md`.

---

## File structure

Modified production files:
- `foxtray/config.py` — `Project.start_timeout` default 30
- `foxtray/state.py` — `clear_if_orphaned()`
- `foxtray/process.py` — `PortInUse` exception class
- `foxtray/project.py` — `Orchestrator.__init__(manager, cfg)`, `pending_starts`, `_project_by_name`, `wait_healthy`, `start` port pre-check, `stop` port post-wait
- `foxtray/cli.py` — `_orchestrator(cfg)`, `cmd_start` wait_healthy, `main()` clear_if_orphaned, `PortInUse` mapping
- `foxtray/ui/tray.py` — `_status_to_icon_state` requires `url_ok`, `compute_transitions` gains `pending_starts`, `TrayApp.run` and `_poll_tick` call `clear_if_orphaned`
- `foxtray/ui/actions.py` — `on_start` populates `pending_starts`

Modified tests:
- `tests/test_config.py` — `start_timeout` parsing
- `tests/test_state.py` — `clear_if_orphaned` cases
- `tests/test_process.py` — `PortInUse` smoke
- `tests/test_project.py` — all existing `Orchestrator(manager=...)` calls updated; new tests for `wait_healthy`, port-free, `pending_starts` field
- `tests/test_cli.py` — `cmd_start` health flow, `clear_if_orphaned` wired, `PortInUse` exit 2
- `tests/test_tray.py` — icon state with `url_ok`, `compute_transitions` with `pending_starts`
- `tests/test_tray_actions.py` — `on_start` pending_starts behavior (FakeOrchestrator gains `pending_starts`)
- `tests/test_tray_app.py` — orphan clear in `_poll_tick`, pending_starts wiring

New files:
- `docs/manual-tests/iter3.md`

Unchanged: `foxtray/health.py`, `foxtray/logs.py`, `foxtray/paths.py`, `foxtray/ui/icons.py`, `foxtray/ui/__init__.py`, `main.py`, `assets/*.png`, `scripts/gen_icons.py`, `requirements.txt`.

---

## Task 1: `start_timeout` in config

**Files:**
- Modify: `foxtray/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Append failing tests to `tests/test_config.py`**

```python
def test_start_timeout_defaults_to_30(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.projects[0].start_timeout == 30


def test_start_timeout_parsed_when_provided(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    start_timeout: 60\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.projects[0].start_timeout == 60


def test_start_timeout_rejects_zero(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    start_timeout: 0\n"
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml_body))


def test_start_timeout_rejects_negative(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n    start_timeout: -5\n"
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml_body))


def test_start_timeout_rejects_non_integer(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + '\n    start_timeout: "nope"\n'
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml_body))
```

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```

Expected: 5 new failures (`AttributeError: 'Project' object has no attribute 'start_timeout'` on the first; `ConfigError` not raised on the others because unknown YAML keys are silently ignored today).

- [ ] **Step 3: Add `start_timeout` to `Project` dataclass**

Edit `foxtray/config.py`. Change the `Project` dataclass:

```python
@dataclass(frozen=True)
class Project:
    name: str
    url: str
    backend: Backend
    frontend: Frontend
    start_timeout: int = 30
```

- [ ] **Step 4: Parse and validate `start_timeout` in `_parse_project`**

Edit `_parse_project` in `foxtray/config.py`:

```python
def _parse_project(raw: dict[str, Any]) -> Project:
    name = _require(raw, "name", "project")
    start_timeout_raw = raw.get("start_timeout", 30)
    if not isinstance(start_timeout_raw, int) or isinstance(start_timeout_raw, bool):
        raise ConfigError(
            f"project {name!r}: start_timeout must be a positive integer, got {start_timeout_raw!r}"
        )
    if start_timeout_raw <= 0:
        raise ConfigError(
            f"project {name!r}: start_timeout must be > 0, got {start_timeout_raw}"
        )
    return Project(
        name=name,
        url=_require(raw, "url", f"project {name!r}"),
        backend=_parse_backend(_require(raw, "backend", f"project {name!r}")),
        frontend=_parse_frontend(_require(raw, "frontend", f"project {name!r}")),
        start_timeout=start_timeout_raw,
    )
```

Note: the `isinstance(..., bool)` guard catches the Python quirk where `bool` is a subclass of `int` — `True`/`False` in YAML shouldn't pass silently as `1`/`0`.

- [ ] **Step 5: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```

Expected: all green.

- [ ] **Step 6: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: still all green (no other file depends on `Project` having a fixed field count).

- [ ] **Step 7: Commit**

```bash
git add foxtray/config.py tests/test_config.py
git commit -m "feat(config): Project.start_timeout with validation (default 30)"
```

---

## Task 2: `state.clear_if_orphaned`

**Files:**
- Modify: `foxtray/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Append failing tests to `tests/test_state.py`**

```python
def test_clear_if_orphaned_noop_when_no_active(tmp_appdata: Path) -> None:
    state.save(state.State(active=None))
    assert state.clear_if_orphaned() is False
    assert state.load().active is None


def test_clear_if_orphaned_noop_when_backend_alive(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="X", backend_pid=111, frontend_pid=222
    )))
    monkeypatch.setattr(
        state.psutil, "pid_exists", lambda pid: pid == 111
    )
    assert state.clear_if_orphaned() is False
    assert state.load().active is not None
    assert state.load().active.name == "X"


def test_clear_if_orphaned_noop_when_frontend_alive(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="X", backend_pid=111, frontend_pid=222
    )))
    monkeypatch.setattr(
        state.psutil, "pid_exists", lambda pid: pid == 222
    )
    assert state.clear_if_orphaned() is False
    assert state.load().active is not None


def test_clear_if_orphaned_clears_when_both_dead(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="X", backend_pid=111, frontend_pid=222
    )))
    monkeypatch.setattr(state.psutil, "pid_exists", lambda pid: False)
    assert state.clear_if_orphaned() is True
    assert state.load().active is None
```

Add `import pytest` and `from foxtray import state` at the top of the test file if not already present (they should be). The `tmp_appdata` fixture is provided by the existing `tests/conftest.py`.

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_state.py -v
```

Expected: 4 new failures (`AttributeError: module 'foxtray.state' has no attribute 'clear_if_orphaned'`, and `AttributeError: module 'foxtray.state' has no attribute 'psutil'` after the first is fixed).

- [ ] **Step 3: Implement `clear_if_orphaned` in `foxtray/state.py`**

Add `import psutil` near the top (alongside `import json`). Append at the end of the file:

```python
def clear_if_orphaned() -> bool:
    """Clear state.json.active if both recorded PIDs are dead.

    Returns True if a clear was performed, False otherwise.
    """
    s = load()
    if s.active is None:
        return False
    if psutil.pid_exists(s.active.backend_pid) or psutil.pid_exists(s.active.frontend_pid):
        return False
    save(State(active=None))
    return True
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_state.py -v
```

Expected: all green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: still all green.

- [ ] **Step 6: Commit**

```bash
git add foxtray/state.py tests/test_state.py
git commit -m "feat(state): clear_if_orphaned wipes active when both PIDs are dead"
```

---

## Task 3: `PortInUse` exception

**Files:**
- Modify: `foxtray/process.py`
- Modify: `tests/test_process.py`

- [ ] **Step 1: Append failing test to `tests/test_process.py`**

```python
def test_port_in_use_is_a_runtime_error() -> None:
    from foxtray.process import PortInUse
    exc = PortInUse("port 8000 still in use")
    assert isinstance(exc, RuntimeError)
    assert "8000" in str(exc)
```

- [ ] **Step 2: Run test, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_process.py::test_port_in_use_is_a_runtime_error -v
```

Expected: FAIL (`ImportError: cannot import name 'PortInUse'`).

- [ ] **Step 3: Add `PortInUse` to `foxtray/process.py`**

Insert just below the existing `ExecutableNotFound` class:

```python
class PortInUse(RuntimeError):
    """Raised by Orchestrator.start when a required port is still occupied."""
```

- [ ] **Step 4: Run test, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_process.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add foxtray/process.py tests/test_process.py
git commit -m "feat(process): PortInUse exception class"
```

---

## Task 4: `Orchestrator` gains `cfg` and `pending_starts` (plumbing)

This is a mechanical signature change before we can add features. No behavior change — just wire the `Config` in and expose `pending_starts`.

**Files:**
- Modify: `foxtray/project.py`
- Modify: `foxtray/cli.py` (just the `_orchestrator` helper)
- Modify: `tests/test_project.py` (every existing `Orchestrator(manager=...)` call)

- [ ] **Step 1: Update `Orchestrator.__init__` in `foxtray/project.py`**

Change the class:

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

(The rest of the class stays as-is for now.)

- [ ] **Step 2: Update `_orchestrator` helper in `foxtray/cli.py`**

Change the current:
```python
def _orchestrator() -> project.Orchestrator:
    return project.Orchestrator(manager=process.ProcessManager())
```

To:
```python
def _orchestrator(cfg: config.Config) -> project.Orchestrator:
    return project.Orchestrator(manager=process.ProcessManager(), cfg=cfg)
```

Update the four callers inside `foxtray/cli.py` (`cmd_list`, `cmd_start`, `cmd_stop`, `cmd_stop_all`, `cmd_status`, `cmd_tray`) to pass `cfg`:

```python
def cmd_list(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    orchestrator = _orchestrator(cfg)
    ...

def cmd_start(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    proj = cfg.get(args.name)
    _orchestrator(cfg).start(proj)
    ...

def cmd_stop(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    cfg.get(args.name)  # validates
    ...
    _orchestrator(cfg).stop(args.name)
    ...

def cmd_stop_all(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    _orchestrator(cfg).stop_all()
    ...

def cmd_status(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    proj = cfg.get(args.name)
    status = _orchestrator(cfg).status(proj)
    ...

def cmd_tray(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    tray_module.TrayApp(cfg, _orchestrator(cfg)).run()
    return 0
```

Note: `cmd_stop_all` currently doesn't load config. Now it will — cheap and consistent.

- [ ] **Step 3: Update every `Orchestrator(manager=...)` in `tests/test_project.py`**

Add a helper near the top of the file (just below the `_FakeManager` dataclass):

```python
def _cfg_with(project: config.Project) -> config.Config:
    return config.Config(projects=[project])
```

Then change every existing construction. Find each of these lines:
```python
orchestrator = project.Orchestrator(manager=manager)
```

Replace with:
```python
orchestrator = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))
```

For the two lines that construct an orchestrator without a test-scoped project (the `.status(sample_project)` one-liners), use:
```python
project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project)).status(sample_project)
```

Count: there are 7 `Orchestrator(manager=...)` call sites in `tests/test_project.py` to update.

- [ ] **Step 4: Run the affected tests, confirm green**

```
./.venv/Scripts/python.exe -m pytest tests/test_project.py tests/test_cli.py -v
```

Expected: all green.

- [ ] **Step 5: Append a new test that `pending_starts` starts empty**

In `tests/test_project.py`:

```python
def test_orchestrator_pending_starts_initially_empty(sample_project: config.Project) -> None:
    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    assert orch.pending_starts == set()
```

- [ ] **Step 6: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green (1 more than before).

- [ ] **Step 7: Commit**

```bash
git add foxtray/project.py foxtray/cli.py tests/test_project.py
git commit -m "refactor(project): Orchestrator takes Config; add pending_starts field"
```

---

## Task 5: `Orchestrator.wait_healthy`

**Files:**
- Modify: `foxtray/project.py`
- Modify: `tests/test_project.py`

- [ ] **Step 1: Append failing tests to `tests/test_project.py`**

```python
def test_wait_healthy_returns_true_immediately_on_url_ok(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seed state so status() treats the project as active and both PIDs alive
    state.save(state.State(active=state.ActiveProject(
        name="Demo", backend_pid=1, frontend_pid=2
    )))
    monkeypatch.setattr(project.psutil, "pid_exists", lambda pid: True)
    monkeypatch.setattr(project.health, "http_ok", lambda url, timeout=1.0: True)

    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    assert orch.wait_healthy(sample_project, timeout=5.0) is True


def test_wait_healthy_returns_false_on_timeout(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="Demo", backend_pid=1, frontend_pid=2
    )))
    monkeypatch.setattr(project.psutil, "pid_exists", lambda pid: True)
    monkeypatch.setattr(project.health, "http_ok", lambda url, timeout=1.0: False)

    # Fake clock: time jumps forward by 5s on every sleep() call.
    clock = {"t": 0.0}
    monkeypatch.setattr(project.time, "monotonic", lambda: clock["t"])
    def _fake_sleep(s: float) -> None:
        clock["t"] += s
    monkeypatch.setattr(project.time, "sleep", _fake_sleep)

    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    assert orch.wait_healthy(sample_project, timeout=3.0, interval=1.0) is False
```

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_project.py -v -k wait_healthy
```

Expected: 2 failures (`AttributeError: 'Orchestrator' object has no attribute 'wait_healthy'`; likely also `AttributeError: module 'foxtray.project' has no attribute 'time'` — fix in next step).

- [ ] **Step 3: Implement `wait_healthy` in `foxtray/project.py`**

Add `import time` to the top imports. Append this method to `Orchestrator`:

```python
def wait_healthy(
    self,
    project: config.Project,
    timeout: float = 30.0,
    interval: float = 1.0,
) -> bool:
    """Poll self.status(project).url_ok until True or timeout elapses.

    Returns the final url_ok value (True if the URL responded within the
    window, False otherwise).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if self.status(project).url_ok:
            return True
        time.sleep(interval)
    return self.status(project).url_ok
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_project.py -v -k wait_healthy
```

Expected: both green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add foxtray/project.py tests/test_project.py
git commit -m "feat(project): Orchestrator.wait_healthy polls url_ok with timeout"
```

---

## Task 6: `Orchestrator.stop` port-free post-wait

**Files:**
- Modify: `foxtray/project.py`
- Modify: `tests/test_project.py`

- [ ] **Step 1: Append failing tests to `tests/test_project.py`**

```python
def test_stop_waits_for_port_free_on_both_ports(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="Demo", backend_pid=1, frontend_pid=2
    )))
    called: list[tuple[int, float]] = []
    def _fake_wait(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
        called.append((port, timeout))
        return True
    monkeypatch.setattr(project.health, "wait_port_free", _fake_wait)

    manager = _FakeManager()
    orch = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))
    orch.stop("Demo")

    # Both backend and frontend ports should have been waited on with the 10s timeout
    assert (sample_project.backend.port, 10.0) in called
    assert (sample_project.frontend.port, 10.0) in called


def test_stop_logs_warning_when_port_stays_busy(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="Demo", backend_pid=1, frontend_pid=2
    )))
    monkeypatch.setattr(project.health, "wait_port_free", lambda port, **_: False)

    manager = _FakeManager()
    orch = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))
    with caplog.at_level("WARNING", logger="foxtray.project"):
        orch.stop("Demo")

    messages = [r.message for r in caplog.records]
    assert any("still listening" in m for m in messages)


def test_stop_skips_port_wait_for_unknown_project(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # state.json.active.name doesn't match any project in cfg; stop should early-return
    # and never touch wait_port_free.
    called: list[int] = []
    def _fake_wait(port: int, **_):
        called.append(port)
        return True
    monkeypatch.setattr(project.health, "wait_port_free", _fake_wait)

    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    orch.stop("NotInConfig")  # state.active is None anyway
    assert called == []
```

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_project.py -v -k "stop_waits or stop_logs or stop_skips"
```

Expected: 2 failures (the third — `stop_skips_port_wait` — may coincidentally pass because current `stop` early-returns on mismatched name; that's fine — it'll still pass after the change).

- [ ] **Step 3: Modify `Orchestrator.stop` to post-wait**

Replace the current body of `stop`:

```python
def stop(self, name: str) -> None:
    current = state.load().active
    if current is None or current.name != name:
        return
    self._kill_pair(current.backend_pid, current.frontend_pid)
    state.clear()
    cfg_project = self._project_by_name(name)
    if cfg_project is None:
        return
    if not health.wait_port_free(cfg_project.backend.port, timeout=10.0):
        log.warning(
            "stop: backend port %s still listening after timeout",
            cfg_project.backend.port,
        )
    if not health.wait_port_free(cfg_project.frontend.port, timeout=10.0):
        log.warning(
            "stop: frontend port %s still listening after timeout",
            cfg_project.frontend.port,
        )
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_project.py -v -k "stop_waits or stop_logs or stop_skips"
```

Expected: all three green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add foxtray/project.py tests/test_project.py
git commit -m "feat(project): stop waits for ports to free (10s, warn on timeout)"
```

---

## Task 7: `Orchestrator.start` port-free pre-check

**Files:**
- Modify: `foxtray/project.py`
- Modify: `tests/test_project.py`

- [ ] **Step 1: Append failing tests to `tests/test_project.py`**

```python
def test_start_raises_port_in_use_when_backend_port_busy(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_wait(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
        return port != sample_project.backend.port  # backend port stays busy
    monkeypatch.setattr(project.health, "wait_port_free", _fake_wait)

    manager = _FakeManager()
    orch = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))
    with pytest.raises(process.PortInUse) as excinfo:
        orch.start(sample_project)
    assert str(sample_project.backend.port) in str(excinfo.value)
    # Popen should NOT have been called
    assert manager.started == []


def test_start_raises_port_in_use_when_frontend_port_busy(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_wait(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
        return port != sample_project.frontend.port  # frontend port stays busy
    monkeypatch.setattr(project.health, "wait_port_free", _fake_wait)

    manager = _FakeManager()
    orch = project.Orchestrator(manager=manager, cfg=_cfg_with(sample_project))
    with pytest.raises(process.PortInUse) as excinfo:
        orch.start(sample_project)
    assert str(sample_project.frontend.port) in str(excinfo.value)
    # Popen was called for backend only (it failed AFTER backend was "freed"), but we
    # want to assert NO spawns at all: the frontend check runs BEFORE any Popen.
    assert manager.started == []


def test_start_calls_wait_port_free_with_3s_timeout(
    tmp_appdata: Path,
    sample_project: config.Project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, float]] = []
    def _fake_wait(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
        calls.append((port, timeout))
        return True
    monkeypatch.setattr(project.health, "wait_port_free", _fake_wait)

    orch = project.Orchestrator(manager=_FakeManager(), cfg=_cfg_with(sample_project))
    orch.start(sample_project)
    # Pre-check uses 3.0s timeout on both ports
    assert (sample_project.backend.port, 3.0) in calls
    assert (sample_project.frontend.port, 3.0) in calls

    # Cleanup (_FakeManager.start spawns a real sleep() — reuse the existing cleanup
    # pattern from test_start_records_pids_in_state)
    active = state.load().active
    assert active is not None
    for pid in (active.backend_pid, active.frontend_pid):
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            pass
```

Add `from foxtray import process` at the top of `tests/test_project.py` if not already imported.

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_project.py -v -k "start_raises or start_calls_wait"
```

Expected: 3 failures.

- [ ] **Step 3: Modify `Orchestrator.start` to pre-check**

Add `from foxtray import process` to the top of `foxtray/project.py` (alongside other foxtray imports). Then update `start`:

```python
def start(self, project: config.Project) -> None:
    current = state.load().active
    if current is not None:
        log.info("Stopping active project %s before starting %s", current.name, project.name)
        self._kill_pair(current.backend_pid, current.frontend_pid)
        state.clear()

    if not health.wait_port_free(project.backend.port, timeout=3.0):
        raise process.PortInUse(
            f"backend port {project.backend.port} still in use"
        )
    if not health.wait_port_free(project.frontend.port, timeout=3.0):
        raise process.PortInUse(
            f"frontend port {project.frontend.port} still in use"
        )

    backend_popen = self._manager.start(
        project=project.name,
        component="backend",
        command=project.backend.resolved_command,
        cwd=project.backend.path,
    )
    try:
        frontend_popen = self._manager.start(
            project=project.name,
            component="frontend",
            command=project.frontend.resolved_command,
            cwd=project.frontend.path,
        )
    except Exception:
        self._manager.kill_tree(backend_popen.pid)
        raise
    state.save(
        state.State(
            active=state.ActiveProject(
                name=project.name,
                backend_pid=backend_popen.pid,
                frontend_pid=frontend_popen.pid,
            )
        )
    )
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_project.py -v -k "start_raises or start_calls_wait"
```

Expected: all green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add foxtray/project.py tests/test_project.py
git commit -m "feat(project): start raises PortInUse on occupied port (3s pre-check)"
```

---

## Task 8: CLI — `clear_if_orphaned`, `cmd_start` wait_healthy, `PortInUse` mapping

**Files:**
- Modify: `foxtray/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Append failing tests to `tests/test_cli.py`**

```python
def test_main_calls_clear_if_orphaned_before_dispatch(
    demo_config: Path, tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from foxtray import state
    called: list[bool] = []
    def _fake_clear() -> bool:
        called.append(True)
        return False
    monkeypatch.setattr(state, "clear_if_orphaned", _fake_clear)

    rc = cli.main(["--config", str(demo_config), "list"])
    assert rc == 0
    assert called == [True]


def test_cmd_start_prints_healthy_on_success(
    demo_config: Path,
    tmp_appdata: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from foxtray import project as project_mod

    def _fake_start(self, proj): return None
    def _fake_wait_healthy(self, proj, timeout=30.0, interval=1.0): return True

    monkeypatch.setattr(project_mod.Orchestrator, "start", _fake_start)
    monkeypatch.setattr(project_mod.Orchestrator, "wait_healthy", _fake_wait_healthy)

    rc = cli.main(["--config", str(demo_config), "start", "Demo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Started Demo" in out
    assert "healthy" in out


def test_cmd_start_stops_and_returns_1_on_timeout(
    demo_config: Path,
    tmp_appdata: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from foxtray import project as project_mod

    stopped: list[str] = []
    def _fake_start(self, proj): return None
    def _fake_wait_healthy(self, proj, timeout=30.0, interval=1.0): return False
    def _fake_stop(self, name): stopped.append(name)

    monkeypatch.setattr(project_mod.Orchestrator, "start", _fake_start)
    monkeypatch.setattr(project_mod.Orchestrator, "wait_healthy", _fake_wait_healthy)
    monkeypatch.setattr(project_mod.Orchestrator, "stop", _fake_stop)

    rc = cli.main(["--config", str(demo_config), "start", "Demo"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "failed to become healthy" in err
    assert stopped == ["Demo"]


def test_cmd_start_maps_port_in_use_to_exit_2(
    demo_config: Path,
    tmp_appdata: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    from foxtray import process as process_mod
    from foxtray import project as project_mod

    def _fake_start(self, proj):
        raise process_mod.PortInUse("backend port 8000 still in use")
    monkeypatch.setattr(project_mod.Orchestrator, "start", _fake_start)

    rc = cli.main(["--config", str(demo_config), "start", "Demo"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "8000" in err
```

Add `import pytest` at the top of the file if not already present.

- [ ] **Step 2: Run tests, confirm failure**

```
./.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k "clear_if_orphaned or healthy or port_in_use"
```

Expected: 4 failures.

- [ ] **Step 3: Update `foxtray/cli.py`**

Add `from foxtray import state` to the imports at the top if not already there (it is). Update `main()`:

```python
def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    state.clear_if_orphaned()
    try:
        return args.func(args)
    except config.ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except process.PortInUse as exc:
        print(f"Port in use: {exc}", file=sys.stderr)
        return 2
    except process.ExecutableNotFound as exc:
        print(f"Cannot launch subprocess: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Cannot open config: {exc}", file=sys.stderr)
        return 2
    except config.ProjectNotFound as exc:
        print(f"Unknown project: {exc.args[0]}", file=sys.stderr)
        return 2
```

Update `cmd_start`:

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
        f"{proj.name} failed to become healthy within {proj.start_timeout}s; stopping",
        file=sys.stderr,
    )
    orch.stop(proj.name)
    return 1
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_cli.py -v
```

Expected: all green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add foxtray/cli.py tests/test_cli.py
git commit -m "feat(cli): cmd_start wait_healthy; clear orphaned state; map PortInUse"
```

---

## Task 9: Tray icon state requires `url_ok`

**Files:**
- Modify: `foxtray/ui/tray.py`
- Modify: `tests/test_tray.py`

- [ ] **Step 1: Append failing tests to `tests/test_tray.py`**

```python
def test_icon_state_partial_when_both_alive_but_url_not_ok() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": ProjectStatus(
        name="FoxRunner",
        running=True,
        backend_alive=True,
        frontend_alive=True,
        backend_port_listening=True,
        frontend_port_listening=True,
        url_ok=False,
    )}
    assert tray.compute_icon_state(active, statuses) == "partial"


def test_icon_state_running_requires_url_ok() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    statuses = {"FoxRunner": ProjectStatus(
        name="FoxRunner",
        running=True,
        backend_alive=True,
        frontend_alive=True,
        backend_port_listening=True,
        frontend_port_listening=True,
        url_ok=True,
    )}
    assert tray.compute_icon_state(active, statuses) == "running"
```

Also update the existing test helper `_status` in `tests/test_tray.py` — it currently defaults `url_ok=False` and is used by the existing "running" assertion. Change the existing test `test_icon_state_running_when_both_alive` (or whatever it's called) to pass `url_ok=True`. Inspect the file; the helper signature is:

```python
def _status(*, backend_alive: bool = False, frontend_alive: bool = False) -> ProjectStatus:
```

Extend it:

```python
def _status(*, backend_alive: bool = False, frontend_alive: bool = False, url_ok: bool = False) -> ProjectStatus:
    return ProjectStatus(
        name="X",
        running=backend_alive and frontend_alive,
        backend_alive=backend_alive,
        frontend_alive=frontend_alive,
        backend_port_listening=False,
        frontend_port_listening=False,
        url_ok=url_ok,
    )
```

Find every existing test that expects "running" (e.g. `test_icon_state_running_when_both_alive`, `test_menu_running_project_shows_stop`, `test_menu_project_label_reflects_status`, etc.) and add `url_ok=True` to the `_status(...)` call for those cases. The "partial" cases stay as they are.

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: the two new tests fail, AND existing "running" tests fail (they'll now compute `partial` because `_status()` still returns `url_ok=False`).

- [ ] **Step 3: Update `_status_to_icon_state` in `foxtray/ui/tray.py`**

Replace the existing body:

```python
def _status_to_icon_state(status: ProjectStatus) -> IconState:
    if status.backend_alive and status.frontend_alive and status.url_ok:
        return "running"
    if status.backend_alive or status.frontend_alive:
        return "partial"
    return "stopped"
```

- [ ] **Step 4: Update existing tests' `_status(...)` calls**

For every existing `_status(backend_alive=True, frontend_alive=True)` call in `tests/test_tray.py` where the expected icon state is `"running"` (or the submenu label is `"RUNNING"`), change it to `_status(backend_alive=True, frontend_alive=True, url_ok=True)`.

Same for `tests/test_tray_app.py` — the `_status` helper there is duplicated. Apply the same extension and same update rule.

- [ ] **Step 5: Run tray tests, confirm green**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py tests/test_tray_app.py -v
```

Expected: all green.

- [ ] **Step 6: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add foxtray/ui/tray.py tests/test_tray.py tests/test_tray_app.py
git commit -m "feat(ui/tray): icon state requires url_ok for running"
```

---

## Task 10: `compute_transitions` with `pending_starts`

**Files:**
- Modify: `foxtray/ui/tray.py`
- Modify: `tests/test_tray.py`

- [ ] **Step 1: Append failing tests to `tests/test_tray.py`**

```python
def test_transitions_stopped_to_partial_silent_when_pending_start() -> None:
    prev_active = None
    curr_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev_statuses: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    curr_statuses = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}  # url_ok=False
    pending = {"FoxRunner"}
    notes = tray.compute_transitions(
        prev_active, prev_statuses, curr_active, curr_statuses,
        suppressed=set(), pending_starts=pending,
    )
    assert notes == []
    assert pending == {"FoxRunner"}  # NOT consumed yet


def test_transitions_partial_to_running_fires_is_up_when_pending() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}  # url_ok=False
    curr = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    pending = {"FoxRunner"}
    notes = tray.compute_transitions(
        active, prev, active, curr,
        suppressed=set(), pending_starts=pending,
    )
    assert [n.message for n in notes] == ["FoxRunner is up"]
    assert pending == set()  # consumed


def test_transitions_partial_to_running_fires_recovered_when_not_pending() -> None:
    active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev = {"FoxRunner": _status(backend_alive=True, frontend_alive=False)}  # crashed
    curr = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    pending: set[str] = set()
    notes = tray.compute_transitions(
        active, prev, active, curr,
        suppressed=set(), pending_starts=pending,
    )
    assert [n.message for n in notes] == ["FoxRunner recovered"]


def test_transitions_partial_to_stopped_fires_failed_to_start_when_pending() -> None:
    prev_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev = {"FoxRunner": _status(backend_alive=True, frontend_alive=True)}  # url_ok=False (partial)
    curr: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    pending = {"FoxRunner"}
    notes = tray.compute_transitions(
        prev_active, prev, None, curr,
        suppressed=set(), pending_starts=pending,
    )
    assert len(notes) == 1
    assert "failed to start" in notes[0].message
    assert pending == set()


def test_transitions_stopped_to_running_consumes_pending() -> None:
    prev_active = None
    curr_active = state.ActiveProject(name="FoxRunner", backend_pid=1, frontend_pid=2)
    prev: dict[str, ProjectStatus] = {"FoxRunner": _status()}
    curr = {"FoxRunner": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    pending = {"FoxRunner"}
    notes = tray.compute_transitions(
        prev_active, prev, curr_active, curr,
        suppressed=set(), pending_starts=pending,
    )
    assert [n.message for n in notes] == ["FoxRunner is up"]
    assert pending == set()
```

Also update the existing `compute_transitions` test calls throughout `tests/test_tray.py` to pass the new `pending_starts=set()` kwarg. Find every existing call to `tray.compute_transitions(...)` and add `pending_starts=set()` as a keyword argument (the existing positional `suppressed=set()` stays; if it was positional, switch it to keyword for clarity).

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: new tests fail (`TypeError: compute_transitions() got an unexpected keyword argument 'pending_starts'`).

- [ ] **Step 3: Update `compute_transitions` in `foxtray/ui/tray.py`**

Replace the existing function:

```python
def compute_transitions(
    prev_active: state_mod.ActiveProject | None,
    prev_statuses: dict[str, ProjectStatus],
    curr_active: state_mod.ActiveProject | None,
    curr_statuses: dict[str, ProjectStatus],
    suppressed: set[str],
    pending_starts: set[str],
) -> list[Notification]:
    # Every project name that appears in either snapshot is checked.
    names = set(prev_statuses) | set(curr_statuses)
    if prev_active is not None:
        names.add(prev_active.name)
    if curr_active is not None:
        names.add(curr_active.name)

    notifications: list[Notification] = []
    for name in sorted(names):
        prev_state = _project_icon_state(name, prev_active, prev_statuses.get(name))
        curr_state = _project_icon_state(name, curr_active, curr_statuses.get(name))
        if prev_state == curr_state:
            continue

        if prev_state == "stopped" and curr_state == "running":
            notifications.append(Notification("FoxTray", f"{name} is up"))
            pending_starts.discard(name)
        elif prev_state == "stopped" and curr_state == "partial":
            if name not in pending_starts:
                notifications.append(
                    Notification("FoxTray", f"{name} started but one component failed")
                )
            # else: silent — we're still booting
        elif prev_state == "running" and curr_state == "partial":
            dead = _dead_component(prev_statuses[name], curr_statuses[name])
            notifications.append(
                Notification("FoxTray", f"⚠ {name}: {dead} crashed")
            )
        elif prev_state == "partial" and curr_state == "running":
            if name in pending_starts:
                notifications.append(Notification("FoxTray", f"{name} is up"))
                pending_starts.discard(name)
            else:
                notifications.append(Notification("FoxTray", f"{name} recovered"))
        elif prev_state == "running" and curr_state == "stopped":
            if name not in suppressed:
                notifications.append(
                    Notification("FoxTray", f"⚠ {name} stopped unexpectedly")
                )
        elif prev_state == "partial" and curr_state == "stopped":
            if name in pending_starts:
                notifications.append(
                    Notification("FoxTray", f"⚠ {name} failed to start")
                )
                pending_starts.discard(name)
            elif name not in suppressed:
                notifications.append(
                    Notification("FoxTray", f"⚠ {name} fully stopped")
                )

    return notifications
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: all green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: test_tray_app.py will fail because it calls `compute_transitions` through `_poll_tick` which passes only 5 args. That is fixed in Task 12. Expect failures in `tests/test_tray_app.py`.

If `tests/test_tray_app.py` fails with "missing keyword argument pending_starts", that's the expected state until Task 12 wires it up. To keep the suite green in the meantime, temporarily pass `pending_starts=set()` via `TrayApp._poll_tick` — but don't do that here. Instead, verify the failure is only in `tests/test_tray_app.py` and proceed to commit this task's changes.

- [ ] **Step 6: Commit**

```bash
git add foxtray/ui/tray.py tests/test_tray.py
git commit -m "feat(ui/tray): compute_transitions consumes pending_starts for start balloons"
```

---

## Task 11: `actions.on_start` populates `pending_starts`

**Files:**
- Modify: `foxtray/ui/actions.py`
- Modify: `tests/test_tray_actions.py`

- [ ] **Step 1: Append failing tests to `tests/test_tray_actions.py`**

First extend the `_FakeOrchestrator` at the top of the file to have a `pending_starts` field:

```python
@dataclass
class _FakeOrchestrator:
    started: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    stop_all_called: int = 0
    raises: Exception | None = None
    pending_starts: set[str] = field(default_factory=set)

    def start(self, project: Any) -> None:
        if self.raises:
            raise self.raises
        self.started.append(project.name)

    def stop(self, name: str) -> None:
        if self.raises:
            raise self.raises
        self.stopped.append(name)

    def stop_all(self) -> None:
        if self.raises:
            raise self.raises
        self.stop_all_called += 1
```

Then append:

```python
def test_on_start_adds_to_pending_starts_before_calling_orchestrator() -> None:
    orch = _FakeOrchestrator()
    actions.on_start(orch, _project(), _FakeIcon())
    assert orch.pending_starts == {"Demo"}


def test_on_start_removes_from_pending_starts_on_exception() -> None:
    orch = _FakeOrchestrator(raises=RuntimeError("boom"))
    icon = _FakeIcon()
    actions.on_start(orch, _project(), icon)
    assert orch.pending_starts == set()
    assert icon.notifications == [("FoxTray error", "boom")]
```

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_actions.py -v -k pending_starts
```

Expected: 2 failures (current `on_start` doesn't touch `pending_starts`).

- [ ] **Step 3: Update `on_start` in `foxtray/ui/actions.py`**

Replace the body:

```python
def on_start(orchestrator: Orchestrator, project: config.Project, icon: _Notifier) -> None:
    orchestrator.pending_starts.add(project.name)
    try:
        orchestrator.start(project)
    except Exception as exc:  # noqa: BLE001 — tray must survive any handler error
        orchestrator.pending_starts.discard(project.name)
        _notify_error(icon, exc)
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_actions.py -v
```

Expected: all green.

- [ ] **Step 5: Run full suite (still expect test_tray_app failures until Task 12)**

```
./.venv/Scripts/python.exe -m pytest -v
```

- [ ] **Step 6: Commit**

```bash
git add foxtray/ui/actions.py tests/test_tray_actions.py
git commit -m "feat(ui/actions): on_start tracks pending_starts (add before start, discard on error)"
```

---

## Task 12: `TrayApp` wiring — `pending_starts`, orphan clear on run and on tick

**Files:**
- Modify: `foxtray/ui/tray.py`
- Modify: `tests/test_tray_app.py`

- [ ] **Step 1: Append failing tests to `tests/test_tray_app.py`**

Extend the `_FakeOrchestrator` in this file too with `pending_starts`:

```python
@dataclass
class _FakeOrchestrator:
    next_statuses: dict[str, ProjectStatus] = field(default_factory=dict)
    next_active: state.ActiveProject | None = None
    pending_starts: set[str] = field(default_factory=set)

    def status(self, project: config.Project) -> ProjectStatus:
        return self.next_statuses[project.name]

    def start(self, project: config.Project) -> None: ...
    def stop(self, name: str) -> None: ...
    def stop_all(self) -> None: ...
```

Then append:

```python
def test_run_calls_clear_if_orphaned(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    from foxtray import state as state_mod
    called: list[bool] = []
    monkeypatch.setattr(state_mod, "clear_if_orphaned", lambda: called.append(True) or False)

    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    app = tray.TrayApp(cfg, orch)  # type: ignore[arg-type]

    # We can't actually run pystray in a test. Monkeypatch pystray.Icon to a stub
    # that immediately returns from .run() so TrayApp.run() finishes.
    import pystray
    class _StubIcon:
        def __init__(self, **kwargs): self._kwargs = kwargs
        def run(self): return None
        def notify(self, message, title=""): pass
        icon = None
    monkeypatch.setattr(pystray, "Icon", _StubIcon)

    app.run()
    assert called == [True]


def test_poll_tick_clears_orphan_at_end(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    # Both PIDs dead: status() returns both_alive=False, url_ok=False
    orch = _FakeOrchestrator(next_statuses={"A": _status()})
    icon = _FakeIcon(icon=icons.load("running"))  # starts as running
    app = tray.TrayApp(cfg, orch)  # type: ignore[arg-type]
    app._icon = icon
    # Seed prev_active so _poll_tick sees a running → stopped transition
    app._prev_active = state.ActiveProject(name="A", backend_pid=1, frontend_pid=2)
    app._prev_statuses = {"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)}
    app._prev_icon_state = "running"

    # state.json says A is still active with dead PIDs
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # pid_exists returns False for both → clear_if_orphaned will fire
    monkeypatch.setattr("foxtray.state.psutil.pid_exists", lambda pid: False)

    app._poll_tick()

    # The "stopped unexpectedly" balloon should have fired
    assert any("stopped unexpectedly" in n[1] for n in icon.notifications)
    # state.json.active is now None
    assert state.load().active is None
    # _prev_active was reset after orphan clear
    assert app._prev_active is None


def test_poll_tick_passes_pending_starts_into_compute_transitions(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(
        next_statuses={"A": _status(backend_alive=True, frontend_alive=True, url_ok=True)},
    )
    orch.pending_starts.add("A")
    icon = _FakeIcon(icon=icons.load("stopped"))
    app = tray.TrayApp(cfg, orch)  # type: ignore[arg-type]
    app._icon = icon
    state.save(state.State(active=state.ActiveProject(
        name="A", backend_pid=1, frontend_pid=2
    )))
    # pid_exists True so status() considers procs alive
    monkeypatch.setattr("foxtray.state.psutil.pid_exists", lambda pid: True)
    monkeypatch.setattr("foxtray.project.psutil.pid_exists", lambda pid: True)

    app._poll_tick()

    # Should have fired "A is up" (stopped → running, pending_starts contained A)
    assert any("A is up" in n[1] for n in icon.notifications)
    # pending_starts consumed
    assert orch.pending_starts == set()
```

Update any existing tests in `tests/test_tray_app.py` that patch `pid_exists` or rely on state.json being read — the new orphan-clear at tick end may interact with them. If an existing test expects `state.json.active` to remain populated across the tick, monkeypatch `psutil.pid_exists` to return True so orphan-clear is a no-op.

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_app.py -v
```

Expected: new tests fail; existing ones may fail due to the `pending_starts` kwarg change in `compute_transitions` (Task 10 left those broken intentionally).

- [ ] **Step 3: Wire `pending_starts` and orphan clear in `TrayApp`**

In `foxtray/ui/tray.py`, update `TrayApp.run` and `_poll_tick`:

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
    try:
        self._icon.run()
    finally:
        self._stop_event.set()
        poller.join(timeout=_POLL_INTERVAL_S + 1.0)

def _poll_tick(self) -> None:
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

        # Orphan reconciliation — runs AFTER transition computation so that the
        # "stopped unexpectedly" balloon still fires for the dying tick.
        if state_mod.clear_if_orphaned():
            log.info(
                "poll tick cleared orphaned state for %s",
                curr_active.name if curr_active else "?",
            )
            self._prev_active = None
    except Exception:  # noqa: BLE001 — poll loop must never die
        log.warning("poll tick failed", exc_info=True)
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_app.py -v
```

Expected: all green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: ALL green. This is the end of the reliability implementation.

- [ ] **Step 6: Commit**

```bash
git add foxtray/ui/tray.py tests/test_tray_app.py
git commit -m "feat(ui/tray): TrayApp wires pending_starts and orphan clear into poll tick"
```

---

## Task 13: Manual smoke test document

**Files:**
- Create: `docs/manual-tests/iter3.md`

- [ ] **Step 1: Write the checklist**

Create `docs/manual-tests/iter3.md` with the following content:

```markdown
# FoxTray Iter 3 — Manual Test Log

Prerequisite: Iter 2 manual test (`docs/manual-tests/iter2.md`) passed once on this machine.

## Environment

- Date: <fill>
- HEAD: <commit sha>
- Full test suite: `./.venv/Scripts/python.exe -m pytest -v` (must show all green)

## CLI scenarios

- [ ] `python main.py start FoxRunner` — prints `Started FoxRunner, waiting for health...`, then `FoxRunner is healthy` within the `start_timeout` (default 30s). Exit 0.
- [ ] With a broken backend command (edit `config.yaml`, replace `python manage.py runserver 8000` with `python -c "import sys; sys.exit(1)"`): `python main.py start FoxRunner` — after 30s, prints to stderr `FoxRunner failed to become healthy within 30s; stopping`. Exit 1. `state.json.active` is null.
- [ ] Occupy port 8000 manually: `python -m http.server 8000` in another shell. `python main.py start FoxRunner` — within 3s prints `Port in use: backend port 8000 still in use`. Exit 2. No python children spawned for FoxRunner.
- [ ] After a clean stop, immediately start again: `python main.py stop FoxRunner && python main.py start FoxRunner` — no `EADDRINUSE`.

## Orphan-clear scenarios

- [ ] Edit `%APPDATA%\foxtray\state.json` to set `active: {"name": "FoxRunner", "backend_pid": 99999, "frontend_pid": 99998}`. Run `python main.py list` — prints all stopped; `state.json.active` is now `null`.
- [ ] With the same bogus state, run `python main.py tray` — tray launches with grey icon. Menu reflects all projects stopped.

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
<!-- Fill during run. Link to follow-up fix commits. -->

_None yet._
```

- [ ] **Step 2: Commit**

```bash
git add docs/manual-tests/iter3.md
git commit -m "docs(iter3): manual smoke test checklist for reliability iteration"
```

---

## Self-Review Summary

- **Spec coverage:**
  - Goal, four features — covered by Tasks 2 (orphan), 5 (wait_healthy), 6+7 (port-free), 8 (CLI), 9+10+12 (tray integration).
  - Non-goals — not in plan (by design).
  - File structure — every entry in spec's "File structure" section has a Task that touches it.
  - Components — each method/function in the spec is implemented in a dedicated Task.
  - Data flow per feature (spec §Data flow) — Tasks 8 and 12 implement the CLI and tray paths respectively; Task 9 implements the icon-state rule; Task 10 implements the transition table.
  - Error handling — each row of the spec's error-handling table maps to a Task: config validation (1), PortInUse mapping (8), wait_healthy timeout (8), stop warn (6), orphan clear failure (implicit — existing `except Exception` covers it).
  - Testing — every spec test bullet becomes a test in the corresponding Task.
  - Manual tests — Task 13.
- **Placeholder scan:** no "TBD", no "similar to", no "handle edge cases". Every code block is complete and consistent with earlier task definitions.
- **Type consistency:**
  - `Orchestrator.__init__(manager, cfg)` introduced in Task 4; every subsequent task's code and test uses this signature.
  - `pending_starts: set[str]` on `Orchestrator` (Task 4); mutated by `compute_transitions` via `.discard(name)` (Task 10) and by `actions.on_start` via `.add/.discard` (Task 11); read by `TrayApp._poll_tick` (Task 12).
  - `PortInUse(RuntimeError)` defined in Task 3; raised in Task 7; caught in Task 8.
  - `ProjectStatus.url_ok` field — existing since Iter 1; newly used by `_status_to_icon_state` (Task 9) and by `wait_healthy` via `status()` (Task 5).
  - `Project.start_timeout: int = 30` — Task 1; read by `cmd_start` in Task 8.
- **Scope:** one iteration, one plan, single sequential build-up. Task 10 intentionally leaves `tests/test_tray_app.py` temporarily broken; Task 12 fixes it. Any executor following tasks in order is never more than one task away from full suite green.
