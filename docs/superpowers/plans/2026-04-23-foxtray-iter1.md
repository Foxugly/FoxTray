# FoxTray Iter 1 (CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows CLI tool (`python main.py <cmd>`) that starts/stops Django+Angular project pairs with proper process-tree killing, so the critical Iter 2 tray work rests on validated foundations.

**Architecture:** One `foxtray/` package split by responsibility (config, paths, state, logs, health, process, project). Subprocesses are launched with `CREATE_NEW_PROCESS_GROUP` and killed via `psutil` tree-walk. A single active project is tracked in `%APPDATA%\foxtray\state.json`. Logs are rotated 1-deep per project/component. CLI is a thin `argparse` layer on top of `Project` + `ProjectRegistry`.

**Tech Stack:** Python 3.14, `pystray` (Iter 2 only — not installed yet), `psutil`, `PyYAML`, `requests`, `pytest` (dev).

---

## File Structure

Created files (production):
- `requirements.txt` — runtime deps (psutil, PyYAML, requests)
- `requirements-dev.txt` — dev deps (pytest)
- `README.md` — minimal install/usage doc
- `config.yaml` — three real projects (FoxRunner, QuizOnline, PushIT)
- `main.py` — argparse CLI entry
- `foxtray/__init__.py` — empty marker
- `foxtray/paths.py` — APPDATA/logs/state-file helpers
- `foxtray/config.py` — YAML loader + dataclasses
- `foxtray/logs.py` — rotating file writer for subprocess stdout/stderr
- `foxtray/state.py` — JSON persistence for active project + PIDs
- `foxtray/health.py` — port + HTTP checks, wait-for-free helper
- `foxtray/process.py` — `ProcessManager` with start/stop/kill-tree (critical module)
- `foxtray/project.py` — `Project` class orchestrating backend+frontend
- `foxtray/cli.py` — command implementations (list/start/stop/stop-all/status)

Created files (tests):
- `tests/__init__.py`
- `tests/conftest.py` — shared fixtures (tmp APPDATA, sample config)
- `tests/helpers/__init__.py`
- `tests/helpers/child_tree.py` — helper script that spawns a grandchild to test kill_tree
- `tests/test_paths.py`
- `tests/test_config.py`
- `tests/test_state.py`
- `tests/test_logs.py`
- `tests/test_health.py`
- `tests/test_process.py`
- `tests/test_project.py`

Modified files:
- `BRIEF.MD` — rename "Project Switcher" → "FoxTray"

---

### Task 1: Rename in BRIEF.MD + scaffolding

**Files:**
- Modify: `BRIEF.MD`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `README.md`
- Create: `.gitignore`

- [ ] **Step 1: Rename title in BRIEF.MD**

In `BRIEF.MD` line 1, change:
```
# Project Switcher — Brief technique
```
to:
```
# FoxTray — Brief technique
```

- [ ] **Step 2: Write `requirements.txt`**

```
psutil>=5.9
PyYAML>=6.0
requests>=2.31
```

- [ ] **Step 3: Write `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0
```

- [ ] **Step 4: Write `README.md`**

```markdown
# FoxTray

Windows tray utility to start/stop Django+Angular project pairs.

Iter 1 exposes a CLI only. Iter 2 will add a tray icon.

## Install

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Usage

```powershell
.venv\Scripts\python.exe main.py list
.venv\Scripts\python.exe main.py start FoxRunner
.venv\Scripts\python.exe main.py status FoxRunner
.venv\Scripts\python.exe main.py stop FoxRunner
.venv\Scripts\python.exe main.py stop-all
```

Configuration lives in `config.yaml` at the repo root.
Logs are written to `%APPDATA%\foxtray\logs\`.
```

- [ ] **Step 5: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.idea/
```

- [ ] **Step 6: Commit**

```bash
git add BRIEF.MD requirements.txt requirements-dev.txt README.md .gitignore
git commit -m "chore: rename to FoxTray and add scaffolding"
```

---

### Task 2: Paths helpers

`paths.py` centralises every filesystem location so tests can redirect them via a single env var (`FOXTRAY_APPDATA`). This keeps the rest of the code free of `os.environ` lookups.

**Files:**
- Create: `foxtray/__init__.py` (empty)
- Create: `foxtray/paths.py`
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`
- Create: `tests/test_paths.py`

- [ ] **Step 1: Create empty `foxtray/__init__.py` and `tests/__init__.py`**

Both files: single blank line, no content.

- [ ] **Step 2: Write `tests/conftest.py` with tmp appdata fixture**

```python
import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect FoxTray's APPDATA root to a tmp dir for the duration of a test."""
    monkeypatch.setenv("FOXTRAY_APPDATA", str(tmp_path))
    return tmp_path
```

- [ ] **Step 3: Write failing tests in `tests/test_paths.py`**

```python
from pathlib import Path

from foxtray import paths


def test_appdata_root_uses_env_override(tmp_appdata: Path) -> None:
    assert paths.appdata_root() == tmp_appdata


def test_logs_dir_is_under_appdata(tmp_appdata: Path) -> None:
    assert paths.logs_dir() == tmp_appdata / "logs"


def test_state_file_is_under_appdata(tmp_appdata: Path) -> None:
    assert paths.state_file() == tmp_appdata / "state.json"


def test_ensure_dirs_creates_logs_dir(tmp_appdata: Path) -> None:
    paths.ensure_dirs()
    assert (tmp_appdata / "logs").is_dir()


def test_log_file_path_format(tmp_appdata: Path) -> None:
    assert paths.log_file("FoxRunner", "backend") == tmp_appdata / "logs" / "FoxRunner_backend.log"
```

- [ ] **Step 4: Run tests, confirm failure**

```
.venv\Scripts\python.exe -m pytest tests/test_paths.py -v
```
Expected: 5 failures (`ModuleNotFoundError: No module named 'foxtray.paths'`).

- [ ] **Step 5: Implement `foxtray/paths.py`**

```python
"""Filesystem locations used across FoxTray.

All paths derive from a single root (``%APPDATA%\\foxtray`` in production).
Set ``FOXTRAY_APPDATA`` to override for tests.
"""
from __future__ import annotations

import os
from pathlib import Path


def appdata_root() -> Path:
    override = os.environ.get("FOXTRAY_APPDATA")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set; FoxTray is Windows-only")
    return Path(appdata) / "foxtray"


def logs_dir() -> Path:
    return appdata_root() / "logs"


def state_file() -> Path:
    return appdata_root() / "state.json"


def log_file(project: str, component: str) -> Path:
    return logs_dir() / f"{project}_{component}.log"


def ensure_dirs() -> None:
    logs_dir().mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 6: Run tests, confirm pass**

```
.venv\Scripts\python.exe -m pytest tests/test_paths.py -v
```
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add foxtray/__init__.py foxtray/paths.py tests/__init__.py tests/conftest.py tests/test_paths.py
git commit -m "feat(paths): add APPDATA helpers"
```

---

### Task 3: Config loading

Dataclasses give us validation-by-construction and clean autocompletion downstream. `Project.backend_python` is where we bake in the venv-Python trick from the brief.

**Files:**
- Create: `foxtray/config.py`
- Create: `config.yaml`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests in `tests/test_config.py`**

```python
from pathlib import Path

import pytest

from foxtray import config


SAMPLE_YAML = """
projects:
  - name: FoxRunner
    url: http://localhost:4200
    backend:
      path: D:\\\\projects\\\\foxrunner-server
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: D:\\\\projects\\\\foxrunner-frontend
      command: ng serve --port 4200
      port: 4200
"""


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_parses_single_project(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert [p.name for p in cfg.projects] == ["FoxRunner"]
    foxrunner = cfg.projects[0]
    assert foxrunner.url == "http://localhost:4200"
    assert foxrunner.backend.port == 8000
    assert foxrunner.frontend.port == 4200


def test_backend_python_substitutes_venv(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    backend = cfg.projects[0].backend
    assert backend.python_executable == Path("D:\\projects\\foxrunner-server") / ".venv" / "Scripts" / "python.exe"


def test_backend_resolved_command_replaces_python(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    backend = cfg.projects[0].backend
    assert backend.resolved_command[0] == str(backend.python_executable)
    assert backend.resolved_command[1:] == ["manage.py", "runserver", "8000"]


def test_frontend_resolved_command_is_shell_split(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.projects[0].frontend.resolved_command == ["ng", "serve", "--port", "4200"]


def test_project_registry_lookup(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.get("FoxRunner").name == "FoxRunner"
    with pytest.raises(KeyError):
        cfg.get("Nope")


def test_duplicate_project_names_rejected(tmp_path: Path) -> None:
    body = SAMPLE_YAML + SAMPLE_YAML.split("projects:\n")[1]
    with pytest.raises(config.ConfigError, match="duplicate"):
        config.load(write_config(tmp_path, body))


def test_missing_backend_key_rejected(tmp_path: Path) -> None:
    body = """
projects:
  - name: Broken
    url: http://localhost:4200
    frontend:
      path: D:\\\\x
      command: ng serve
      port: 4200
"""
    with pytest.raises(config.ConfigError, match="backend"):
        config.load(write_config(tmp_path, body))
```

- [ ] **Step 2: Run tests, confirm failure**

```
.venv\Scripts\python.exe -m pytest tests/test_config.py -v
```
Expected: all fail with `ModuleNotFoundError: No module named 'foxtray.config'`.

- [ ] **Step 3: Implement `foxtray/config.py`**

```python
"""Config loading and validation for FoxTray."""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when config.yaml is missing required fields or malformed."""


@dataclass(frozen=True)
class Backend:
    path: Path
    venv: str
    command: str
    port: int

    @property
    def python_executable(self) -> Path:
        return self.path / self.venv / "Scripts" / "python.exe"

    @property
    def resolved_command(self) -> list[str]:
        parts = shlex.split(self.command, posix=False)
        if not parts:
            raise ConfigError("backend.command is empty")
        if parts[0].lower() != "python":
            raise ConfigError(f"backend.command must start with 'python', got {parts[0]!r}")
        return [str(self.python_executable), *parts[1:]]


@dataclass(frozen=True)
class Frontend:
    path: Path
    command: str
    port: int

    @property
    def resolved_command(self) -> list[str]:
        return shlex.split(self.command, posix=False)


@dataclass(frozen=True)
class Project:
    name: str
    url: str
    backend: Backend
    frontend: Frontend


@dataclass(frozen=True)
class Config:
    projects: list[Project] = field(default_factory=list)

    def get(self, name: str) -> Project:
        for project in self.projects:
            if project.name == name:
                return project
        raise KeyError(name)


def _require(mapping: dict[str, Any], key: str, context: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"missing required key {key!r} in {context}")
    return mapping[key]


def _parse_backend(raw: dict[str, Any]) -> Backend:
    return Backend(
        path=Path(_require(raw, "path", "backend")),
        venv=_require(raw, "venv", "backend"),
        command=_require(raw, "command", "backend"),
        port=int(_require(raw, "port", "backend")),
    )


def _parse_frontend(raw: dict[str, Any]) -> Frontend:
    return Frontend(
        path=Path(_require(raw, "path", "frontend")),
        command=_require(raw, "command", "frontend"),
        port=int(_require(raw, "port", "frontend")),
    )


def _parse_project(raw: dict[str, Any]) -> Project:
    name = _require(raw, "name", "project")
    return Project(
        name=name,
        url=_require(raw, "url", f"project {name!r}"),
        backend=_parse_backend(_require(raw, "backend", f"project {name!r}")),
        frontend=_parse_frontend(_require(raw, "frontend", f"project {name!r}")),
    )


def load(path: Path) -> Config:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    projects_raw = raw.get("projects", [])
    if not isinstance(projects_raw, list):
        raise ConfigError("'projects' must be a list")
    projects = [_parse_project(p) for p in projects_raw]
    names = [p.name for p in projects]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ConfigError(f"duplicate project names: {sorted(duplicates)}")
    return Config(projects=projects)
```

- [ ] **Step 4: Run tests, confirm pass**

```
.venv\Scripts\python.exe -m pytest tests/test_config.py -v
```
Expected: all 7 pass.

- [ ] **Step 5: Write `config.yaml` with the three real projects**

```yaml
projects:
  - name: FoxRunner
    url: http://localhost:4200
    backend:
      path: D:\PycharmProjects\FoxRunner_server
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: C:\Users\Renaud\WebstormProjects\FoxRunner_frontend
      command: ng serve --port 4200
      port: 4200

  - name: QuizOnline
    url: http://localhost:4200
    backend:
      path: D:\PycharmProjects\QuizOnline\quizonline-server
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: D:\PycharmProjects\QuizOnline\quizonline-frontend
      command: ng serve --port 4200
      port: 4200

  - name: PushIT
    url: http://localhost:4200
    backend:
      path: D:\PycharmProjects\PushIT_server
      venv: .venv
      command: python manage.py runserver 8000
      port: 8000
    frontend:
      path: C:\Users\Renaud\WebstormProjects\PushIT_frontend
      command: ng serve --port 4200
      port: 4200
```

- [ ] **Step 6: Sanity-check config loads**

```
.venv\Scripts\python.exe -c "from foxtray import config; print([p.name for p in config.load(__import__('pathlib').Path('config.yaml')).projects])"
```
Expected: `['FoxRunner', 'QuizOnline', 'PushIT']`.

- [ ] **Step 7: Commit**

```bash
git add foxtray/config.py config.yaml tests/test_config.py
git commit -m "feat(config): load projects from YAML with validation"
```

---

### Task 4: State persistence

`state.py` owns the `state.json` file. The rest of the code reads/writes through its typed API so nobody else juggles raw JSON.

**Files:**
- Create: `foxtray/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write failing tests in `tests/test_state.py`**

```python
from pathlib import Path

from foxtray import state


def test_load_returns_empty_when_missing(tmp_appdata: Path) -> None:
    assert state.load() == state.State(active=None)


def test_save_then_load_roundtrip(tmp_appdata: Path) -> None:
    snapshot = state.State(active=state.ActiveProject(name="FoxRunner", backend_pid=1234, frontend_pid=5678))
    state.save(snapshot)
    assert state.load() == snapshot


def test_clear_removes_active(tmp_appdata: Path) -> None:
    state.save(state.State(active=state.ActiveProject(name="X", backend_pid=1, frontend_pid=2)))
    state.clear()
    assert state.load().active is None


def test_load_recovers_from_corrupt_file(tmp_appdata: Path) -> None:
    state_path = tmp_appdata / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not json", encoding="utf-8")
    assert state.load().active is None
```

- [ ] **Step 2: Run tests, confirm failure**

```
.venv\Scripts\python.exe -m pytest tests/test_state.py -v
```
Expected: 4 failures (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `foxtray/state.py`**

```python
"""Persistence of the currently-active project and its subprocess PIDs."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from foxtray import paths

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActiveProject:
    name: str
    backend_pid: int
    frontend_pid: int


@dataclass(frozen=True)
class State:
    active: ActiveProject | None


def load() -> State:
    path = paths.state_file()
    if not path.exists():
        return State(active=None)
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("state.json is unreadable; treating as empty", exc_info=True)
        return State(active=None)
    active_raw = raw.get("active")
    if not active_raw:
        return State(active=None)
    return State(active=ActiveProject(**active_raw))


def save(state: State) -> None:
    paths.ensure_dirs()
    path = paths.state_file()
    payload = {"active": asdict(state.active) if state.active else None}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear() -> None:
    save(State(active=None))
```

- [ ] **Step 4: Run tests, confirm pass**

```
.venv\Scripts\python.exe -m pytest tests/test_state.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add foxtray/state.py tests/test_state.py
git commit -m "feat(state): persist active project + PIDs to state.json"
```

---

### Task 5: Log files with simple rotation

Per the brief: one file per (project, component), keep current + previous (`.log` + `.log.1`). The rotation is done at start time — we rotate _before_ opening the new file for subprocess stdout/stderr.

**Files:**
- Create: `foxtray/logs.py`
- Create: `tests/test_logs.py`

- [ ] **Step 1: Write failing tests in `tests/test_logs.py`**

```python
from pathlib import Path

from foxtray import logs, paths


def test_rotate_with_no_existing_log_is_noop(tmp_appdata: Path) -> None:
    logs.rotate("FoxRunner", "backend")
    assert not paths.log_file("FoxRunner", "backend").exists()


def test_rotate_moves_current_to_dot_one(tmp_appdata: Path) -> None:
    paths.ensure_dirs()
    current = paths.log_file("FoxRunner", "backend")
    current.write_text("run A", encoding="utf-8")
    logs.rotate("FoxRunner", "backend")
    assert not current.exists()
    assert (current.parent / "FoxRunner_backend.log.1").read_text(encoding="utf-8") == "run A"


def test_rotate_overwrites_existing_dot_one(tmp_appdata: Path) -> None:
    paths.ensure_dirs()
    current = paths.log_file("FoxRunner", "backend")
    old = current.parent / "FoxRunner_backend.log.1"
    old.write_text("run OLD", encoding="utf-8")
    current.write_text("run NEW", encoding="utf-8")
    logs.rotate("FoxRunner", "backend")
    assert old.read_text(encoding="utf-8") == "run NEW"


def test_open_returns_write_handle(tmp_appdata: Path) -> None:
    handle = logs.open_writer("FoxRunner", "backend")
    try:
        handle.write("hello\n")
    finally:
        handle.close()
    assert paths.log_file("FoxRunner", "backend").read_text(encoding="utf-8") == "hello\n"


def test_tail_returns_last_n_lines(tmp_appdata: Path) -> None:
    paths.ensure_dirs()
    log_path = paths.log_file("FoxRunner", "backend")
    log_path.write_text("\n".join(f"line {i}" for i in range(10)) + "\n", encoding="utf-8")
    assert logs.tail("FoxRunner", "backend", lines=3) == ["line 7", "line 8", "line 9"]
```

- [ ] **Step 2: Run tests, confirm failure**

```
.venv\Scripts\python.exe -m pytest tests/test_logs.py -v
```
Expected: all fail.

- [ ] **Step 3: Implement `foxtray/logs.py`**

```python
"""Per-project/component log files with one-deep rotation."""
from __future__ import annotations

from typing import IO

from foxtray import paths


def _previous_path(project: str, component: str):
    current = paths.log_file(project, component)
    return current.parent / f"{current.stem}.log.1"


def rotate(project: str, component: str) -> None:
    paths.ensure_dirs()
    current = paths.log_file(project, component)
    if not current.exists():
        return
    previous = _previous_path(project, component)
    if previous.exists():
        previous.unlink()
    current.rename(previous)


def open_writer(project: str, component: str) -> IO[str]:
    """Open the current log file for writing. Caller is responsible for closing."""
    paths.ensure_dirs()
    return paths.log_file(project, component).open("w", encoding="utf-8", buffering=1)


def tail(project: str, component: str, lines: int = 200) -> list[str]:
    path = paths.log_file(project, component)
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8").splitlines()
    return content[-lines:]
```

- [ ] **Step 4: Run tests, confirm pass**

```
.venv\Scripts\python.exe -m pytest tests/test_logs.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add foxtray/logs.py tests/test_logs.py
git commit -m "feat(logs): rotating per-component log writer"
```

---

### Task 6: Health checks

Two functions: `port_listening(port)` (TCP connect) and `http_ok(url)` (GET with short timeout). `wait_port_free` polls until a port is no longer listening so we can do atomic switches.

**Files:**
- Create: `foxtray/health.py`
- Create: `tests/test_health.py`

- [ ] **Step 1: Write failing tests in `tests/test_health.py`**

```python
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from foxtray import health


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def tcp_server():
    port = _free_port()
    server = socket.socket()
    server.bind(("127.0.0.1", port))
    server.listen(1)
    yield port
    server.close()


def test_port_listening_true_when_socket_open(tcp_server: int) -> None:
    assert health.port_listening(tcp_server) is True


def test_port_listening_false_when_nothing_there() -> None:
    assert health.port_listening(_free_port()) is False


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args, **kwargs) -> None:
        pass


@pytest.fixture
def http_server():
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _OkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


def test_http_ok_true_on_200(http_server: int) -> None:
    assert health.http_ok(f"http://127.0.0.1:{http_server}/") is True


def test_http_ok_false_on_connection_refused() -> None:
    assert health.http_ok(f"http://127.0.0.1:{_free_port()}/") is False


def test_wait_port_free_returns_true_when_already_free() -> None:
    assert health.wait_port_free(_free_port(), timeout=1.0) is True


def test_wait_port_free_returns_false_when_still_listening(tcp_server: int) -> None:
    start = time.monotonic()
    assert health.wait_port_free(tcp_server, timeout=0.3) is False
    assert time.monotonic() - start >= 0.3
```

- [ ] **Step 2: Run tests, confirm failure**

```
.venv\Scripts\python.exe -m pytest tests/test_health.py -v
```
Expected: all fail (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `foxtray/health.py`**

```python
"""Port and HTTP health checks."""
from __future__ import annotations

import socket
import time

import requests


def port_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    with socket.socket() as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except OSError:
            return False
        return True


def http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException:
        return False
    return 200 <= response.status_code < 500


def wait_port_free(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_listening(port):
            return True
        time.sleep(interval)
    return not port_listening(port)
```

- [ ] **Step 4: Run tests, confirm pass**

```
.venv\Scripts\python.exe -m pytest tests/test_health.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add foxtray/health.py tests/test_health.py
git commit -m "feat(health): TCP and HTTP checks plus wait_port_free"
```

---

### Task 7: ProcessManager (critical module)

This is the piece the whole project rests on. We test the kill-tree with a real process tree: a tiny helper script spawns a grandchild and both must die. On Windows we use `CREATE_NEW_PROCESS_GROUP` so the tree can receive CTRL_BREAK (for Iter 1 we just kill, but the flag also ensures detached process-group semantics).

**Files:**
- Create: `tests/helpers/__init__.py` (empty)
- Create: `tests/helpers/child_tree.py`
- Create: `foxtray/process.py`
- Create: `tests/test_process.py`

- [ ] **Step 1: Create `tests/helpers/__init__.py`** (empty)

- [ ] **Step 2: Write `tests/helpers/child_tree.py`**

```python
"""Test helper: spawn a grandchild then sleep, so kill_tree has a real tree to reap."""
from __future__ import annotations

import subprocess
import sys
import time

if __name__ == "__main__":
    grandchild = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
    )
    print(grandchild.pid, flush=True)
    time.sleep(120)
```

- [ ] **Step 3: Write failing tests in `tests/test_process.py`**

```python
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from foxtray import process


HELPER = Path(__file__).parent / "helpers" / "child_tree.py"


@pytest.fixture
def manager(tmp_appdata: Path) -> process.ProcessManager:
    return process.ProcessManager()


def _spawn_tree() -> subprocess.Popen:
    popen = subprocess.Popen(
        [sys.executable, str(HELPER)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    # Wait until helper has printed the grandchild PID so the tree exists.
    popen.stdout.readline()
    return popen


def test_kill_tree_reaps_child_and_grandchild(manager: process.ProcessManager) -> None:
    popen = _spawn_tree()
    root_pid = popen.pid
    descendants = psutil.Process(root_pid).children(recursive=True)
    assert len(descendants) >= 1, "test helper should have spawned a grandchild"
    descendant_pids = [p.pid for p in descendants]

    manager.kill_tree(root_pid, timeout=5.0)

    assert not psutil.pid_exists(root_pid)
    for pid in descendant_pids:
        assert not psutil.pid_exists(pid)


def test_kill_tree_on_missing_pid_is_noop(manager: process.ProcessManager) -> None:
    # 1 is never a valid PID on Windows.
    manager.kill_tree(1, timeout=0.5)


def test_start_returns_popen_and_writes_log(
    manager: process.ProcessManager, tmp_appdata: Path
) -> None:
    popen = manager.start(
        project="UnitTest",
        component="backend",
        command=[sys.executable, "-c", "print('hello'); import sys; sys.stdout.flush()"],
        cwd=Path.cwd(),
    )
    popen.wait(timeout=5.0)

    log_path = tmp_appdata / "logs" / "UnitTest_backend.log"
    # Give the OS a beat to flush.
    for _ in range(20):
        if log_path.exists() and log_path.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.1)
    assert "hello" in log_path.read_text(encoding="utf-8")


def test_start_rotates_previous_log(
    manager: process.ProcessManager, tmp_appdata: Path
) -> None:
    logs_dir = tmp_appdata / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "UnitTest_backend.log").write_text("OLD", encoding="utf-8")

    popen = manager.start(
        project="UnitTest",
        component="backend",
        command=[sys.executable, "-c", "pass"],
        cwd=Path.cwd(),
    )
    popen.wait(timeout=5.0)

    assert (logs_dir / "UnitTest_backend.log.1").read_text(encoding="utf-8") == "OLD"
```

- [ ] **Step 4: Run tests, confirm failure**

```
.venv\Scripts\python.exe -m pytest tests/test_process.py -v
```
Expected: all fail (`ModuleNotFoundError: No module named 'foxtray.process'`).

- [ ] **Step 5: Implement `foxtray/process.py`**

```python
"""Windows-aware subprocess lifecycle: start under a new process group, kill the whole tree."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import psutil

from foxtray import logs

log = logging.getLogger(__name__)

# On Windows CREATE_NEW_PROCESS_GROUP lets the child detach from our Ctrl+C
# while psutil gives us a portable tree-walk for shutdown.
_CREATION_FLAGS = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class ProcessManager:
    """Starts child processes with stdout+stderr redirected to rotating log files."""

    def start(
        self,
        *,
        project: str,
        component: str,
        command: list[str],
        cwd: Path,
    ) -> subprocess.Popen[bytes]:
        logs.rotate(project, component)
        log_file = logs.open_writer(project, component)
        try:
            return subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=_CREATION_FLAGS,
                close_fds=False,
            )
        except Exception:
            log_file.close()
            raise

    def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
        """Terminate the process and every descendant it has."""
        try:
            root = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return

        descendants = root.children(recursive=True)
        victims = [root, *descendants]

        for proc in victims:
            try:
                proc.terminate()
            except psutil.NoSuchProcess:
                continue

        _, still_alive = psutil.wait_procs(victims, timeout=timeout)
        for proc in still_alive:
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                continue
        psutil.wait_procs(still_alive, timeout=timeout)
```

- [ ] **Step 6: Run tests, confirm pass**

```
.venv\Scripts\python.exe -m pytest tests/test_process.py -v
```
Expected: 4 passed. (If `test_kill_tree_reaps_child_and_grandchild` is flaky, raise `timeout` to 10.0 before making any other change.)

- [ ] **Step 7: Commit**

```bash
git add foxtray/process.py tests/helpers/__init__.py tests/helpers/child_tree.py tests/test_process.py
git commit -m "feat(process): start detached children and kill whole tree"
```

---

### Task 8: Project orchestration

`Project` composes backend + frontend. It's the only place that touches `ProcessManager`, `state`, `health` together, so the CLI stays dumb.

**Files:**
- Create: `foxtray/project.py`
- Create: `tests/test_project.py`

- [ ] **Step 1: Write failing tests in `tests/test_project.py`**

```python
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil
import pytest

from foxtray import config, process, project, state


@dataclass
class _FakeManager:
    killed: list[int] = field(default_factory=list)
    started: list[dict[str, Any]] = field(default_factory=list)
    fake_pid: int = 42

    def start(self, *, project: str, component: str, command: list[str], cwd: Path):
        self.started.append(
            {"project": project, "component": component, "command": command, "cwd": cwd}
        )
        popen = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
        )
        return popen

    def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
        self.killed.append(pid)


@pytest.fixture
def sample_project(tmp_path: Path) -> config.Project:
    return config.Project(
        name="Demo",
        url="http://localhost:4200",
        backend=config.Backend(
            path=tmp_path, venv=".venv", command="python manage.py runserver 8000", port=8000
        ),
        frontend=config.Frontend(
            path=tmp_path, command="ng serve --port 4200", port=4200
        ),
    )


def test_start_records_pids_in_state(tmp_appdata: Path, sample_project: config.Project) -> None:
    manager = _FakeManager()
    orchestrator = project.Orchestrator(manager=manager)

    orchestrator.start(sample_project)

    active = state.load().active
    assert active is not None
    assert active.name == "Demo"
    assert active.backend_pid > 0
    assert active.frontend_pid > 0

    # Cleanup: our fake started real sleep() processes, kill them via psutil.
    for pid in (active.backend_pid, active.frontend_pid):
        try:
            psutil.Process(pid).kill()
        except psutil.NoSuchProcess:
            pass


def test_start_stops_existing_active_first(
    tmp_appdata: Path, sample_project: config.Project
) -> None:
    state.save(state.State(active=state.ActiveProject(name="Prev", backend_pid=11, frontend_pid=22)))
    manager = _FakeManager()
    orchestrator = project.Orchestrator(manager=manager)

    orchestrator.start(sample_project)

    assert 11 in manager.killed and 22 in manager.killed


def test_stop_clears_state_and_kills_tree(
    tmp_appdata: Path, sample_project: config.Project
) -> None:
    state.save(state.State(active=state.ActiveProject(name="Demo", backend_pid=77, frontend_pid=88)))
    manager = _FakeManager()
    orchestrator = project.Orchestrator(manager=manager)

    orchestrator.stop("Demo")

    assert manager.killed == [77, 88]
    assert state.load().active is None


def test_stop_noop_when_not_active(tmp_appdata: Path) -> None:
    manager = _FakeManager()
    orchestrator = project.Orchestrator(manager=manager)

    orchestrator.stop("Demo")

    assert manager.killed == []
    assert state.load().active is None


def test_status_is_stopped_when_state_empty(sample_project: config.Project, tmp_appdata: Path) -> None:
    status = project.Orchestrator(manager=_FakeManager()).status(sample_project)
    assert status.running is False
    assert status.backend_alive is False
    assert status.frontend_alive is False


def test_status_alive_when_pids_exist(
    tmp_appdata: Path, sample_project: config.Project
) -> None:
    backend_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    frontend_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        state.save(
            state.State(
                active=state.ActiveProject(
                    name="Demo",
                    backend_pid=backend_proc.pid,
                    frontend_pid=frontend_proc.pid,
                )
            )
        )
        status = project.Orchestrator(manager=_FakeManager()).status(sample_project)
        assert status.running is True
        assert status.backend_alive is True
        assert status.frontend_alive is True
    finally:
        backend_proc.kill()
        frontend_proc.kill()
        backend_proc.wait(timeout=5)
        frontend_proc.wait(timeout=5)
```

- [ ] **Step 2: Run tests, confirm failure**

```
.venv\Scripts\python.exe -m pytest tests/test_project.py -v
```
Expected: all fail.

- [ ] **Step 3: Implement `foxtray/project.py`**

```python
"""Orchestrates a backend+frontend pair on top of ProcessManager and state."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import psutil

from foxtray import config, health, state

log = logging.getLogger(__name__)


class _ManagerProtocol(Protocol):
    def start(self, *, project: str, component: str, command: list[str], cwd): ...

    def kill_tree(self, pid: int, timeout: float = 5.0) -> None: ...


@dataclass(frozen=True)
class ProjectStatus:
    name: str
    running: bool
    backend_alive: bool
    frontend_alive: bool
    backend_port_listening: bool
    frontend_port_listening: bool
    url_ok: bool


class Orchestrator:
    def __init__(self, manager: _ManagerProtocol) -> None:
        self._manager = manager

    def start(self, project: config.Project) -> None:
        current = state.load().active
        if current is not None:
            log.info("Stopping active project %s before starting %s", current.name, project.name)
            self._kill_pair(current.backend_pid, current.frontend_pid)
            state.clear()

        backend_popen = self._manager.start(
            project=project.name,
            component="backend",
            command=project.backend.resolved_command,
            cwd=project.backend.path,
        )
        frontend_popen = self._manager.start(
            project=project.name,
            component="frontend",
            command=project.frontend.resolved_command,
            cwd=project.frontend.path,
        )
        state.save(
            state.State(
                active=state.ActiveProject(
                    name=project.name,
                    backend_pid=backend_popen.pid,
                    frontend_pid=frontend_popen.pid,
                )
            )
        )

    def stop(self, name: str) -> None:
        current = state.load().active
        if current is None or current.name != name:
            return
        self._kill_pair(current.backend_pid, current.frontend_pid)
        state.clear()

    def stop_all(self) -> None:
        current = state.load().active
        if current is None:
            return
        self._kill_pair(current.backend_pid, current.frontend_pid)
        state.clear()

    def status(self, project: config.Project) -> ProjectStatus:
        current = state.load().active
        is_this_active = current is not None and current.name == project.name
        backend_alive = is_this_active and psutil.pid_exists(current.backend_pid)
        frontend_alive = is_this_active and psutil.pid_exists(current.frontend_pid)
        return ProjectStatus(
            name=project.name,
            running=backend_alive and frontend_alive,
            backend_alive=backend_alive,
            frontend_alive=frontend_alive,
            backend_port_listening=health.port_listening(project.backend.port),
            frontend_port_listening=health.port_listening(project.frontend.port),
            url_ok=health.http_ok(project.url),
        )

    def _kill_pair(self, backend_pid: int, frontend_pid: int) -> None:
        self._manager.kill_tree(backend_pid)
        self._manager.kill_tree(frontend_pid)
```

- [ ] **Step 4: Run tests, confirm pass**

```
.venv\Scripts\python.exe -m pytest tests/test_project.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add foxtray/project.py tests/test_project.py
git commit -m "feat(project): orchestrate backend+frontend lifecycle"
```

---

### Task 9: CLI (argparse) + main.py

Keep `main.py` as the entry point; all command logic lives in `foxtray/cli.py` so we can test it.

**Files:**
- Create: `foxtray/cli.py`
- Create: `main.py`

- [ ] **Step 1: Write `foxtray/cli.py`**

```python
"""CLI command implementations for FoxTray."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from foxtray import config, process, project, state

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def _orchestrator() -> project.Orchestrator:
    return project.Orchestrator(manager=process.ProcessManager())


def cmd_list(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    orchestrator = _orchestrator()
    for proj in cfg.projects:
        status = orchestrator.status(proj)
        label = "RUNNING" if status.running else "stopped"
        print(f"{proj.name:<20} {label}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    proj = cfg.get(args.name)
    _orchestrator().start(proj)
    print(f"Started {proj.name}")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    config.load(args.config).get(args.name)  # validates name exists
    _orchestrator().stop(args.name)
    print(f"Stopped {args.name}")
    return 0


def cmd_stop_all(args: argparse.Namespace) -> int:
    _orchestrator().stop_all()
    print("Stopped all")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    proj = cfg.get(args.name)
    status = _orchestrator().status(proj)
    print(f"name:               {status.name}")
    print(f"running:            {status.running}")
    print(f"backend alive:      {status.backend_alive}")
    print(f"frontend alive:     {status.frontend_alive}")
    print(f"backend port open:  {status.backend_port_listening}")
    print(f"frontend port open: {status.frontend_port_listening}")
    print(f"url responds:       {status.url_ok}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="foxtray")
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to config.yaml (default: repo root)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List projects and their state").set_defaults(func=cmd_list)

    p_start = sub.add_parser("start", help="Start a project (auto-stops the active one)")
    p_start.add_argument("name")
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="Stop a project and kill its process tree")
    p_stop.add_argument("name")
    p_stop.set_defaults(func=cmd_stop)

    sub.add_parser("stop-all", help="Stop the currently active project").set_defaults(func=cmd_stop_all)

    p_status = sub.add_parser("status", help="Detailed health for one project")
    p_status.add_argument("name")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except config.ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except KeyError as exc:
        print(f"Unknown project: {exc.args[0]}", file=sys.stderr)
        return 2
```

- [ ] **Step 2: Write `main.py`**

```python
"""Entry point: ``python main.py <command>``."""
from __future__ import annotations

import sys

from foxtray import cli


if __name__ == "__main__":
    sys.exit(cli.main())
```

- [ ] **Step 3: Smoke-test `list`**

```
.venv\Scripts\python.exe main.py list
```
Expected output:
```
FoxRunner            stopped
QuizOnline           stopped
PushIT               stopped
```
(If any project has running processes from a prior test session, the corresponding row may show `RUNNING` — that is fine here.)

- [ ] **Step 4: Smoke-test `status FoxRunner` with nothing running**

```
.venv\Scripts\python.exe main.py status FoxRunner
```
Expected: `running: False`, all ports `False`, `url responds: False`.

- [ ] **Step 5: Smoke-test unknown project name**

```
.venv\Scripts\python.exe main.py status NopeProject
```
Expected: prints `Unknown project: NopeProject` to stderr, exit code 2.

- [ ] **Step 6: Commit**

```bash
git add foxtray/cli.py main.py
git commit -m "feat(cli): add list/start/stop/stop-all/status commands"
```

---

### Task 10: End-to-end manual validation + test-matrix commit

This is the Iter 1 success criterion from the brief: after `stop`, no stray `node.exe` and port 4200 free.

**Files:**
- Create: `docs/manual-tests/iter1.md`

- [ ] **Step 1: Run the full test suite**

```
.venv\Scripts\python.exe -m pytest -v
```
Expected: every test above passes.

- [ ] **Step 2: Execute real project smoke test (FoxRunner)**

Use a real project that exists on disk (FoxRunner per the brief). If not available locally, skip to Step 4 and document the skip.

```
.venv\Scripts\python.exe main.py start FoxRunner
```
Wait ~10 seconds for Angular to boot, then:
```
.venv\Scripts\python.exe main.py status FoxRunner
```
Expected: `running: True`, both ports listening, `url responds: True`.

Open Task Manager manually and confirm `python.exe` (Django) and `node.exe` (ng serve) are present.

- [ ] **Step 3: Stop it and confirm Node really dies**

```
.venv\Scripts\python.exe main.py stop FoxRunner
```
In Task Manager: zero `node.exe` processes belonging to this user within 5 seconds.
Re-check port:
```
.venv\Scripts\python.exe -c "from foxtray.health import port_listening; print(port_listening(4200))"
```
Expected: `False`.

- [ ] **Step 4: Record observations in `docs/manual-tests/iter1.md`**

```markdown
# FoxTray Iter 1 — Manual Test Log

Date: 2026-04-23
Python: 3.14 (`python --version`)
OS: Windows 11 Pro

## Scenarios

- [ ] `list` shows three projects, all stopped
- [ ] `start FoxRunner`: backend log `%APPDATA%\foxtray\logs\FoxRunner_backend.log` contains Django boot output
- [ ] `start FoxRunner`: frontend log `%APPDATA%\foxtray\logs\FoxRunner_frontend.log` contains Angular dev server output
- [ ] `status FoxRunner`: `running: True` after ~15s
- [ ] Task Manager shows at least one `python.exe` (Django) and `node.exe` (ng serve)
- [ ] `stop FoxRunner`: within 5s, no `node.exe` remains
- [ ] Port 4200 is free after stop
- [ ] `start QuizOnline` while FoxRunner is running: FoxRunner is stopped first automatically
- [ ] After second start, `list` shows QuizOnline running, FoxRunner stopped
- [ ] `stop-all` stops QuizOnline cleanly

## Issues / Notes
(fill in during run)
```

- [ ] **Step 5: Final commit**

```bash
git add docs/manual-tests/iter1.md
git commit -m "docs: Iter 1 manual test checklist"
```

---

## Self-Review Summary

- **Spec coverage:** rename (Task 1), kill-tree technique (Task 7), venv Python substitution (Task 3), auto-stop on switch (Task 8), atomic switch via wait_port_free (Task 6 — used from cli.start in a follow-up if flakiness appears; basic switch semantics are handled by `Orchestrator.start` killing the previous tree before spawning the new one), logs path + rotation (Task 5), state file (Task 4), CLI commands list/start/stop/stop-all/status (Task 9), manual test (Task 10).
- **Intentional omissions:** `url` is checked by `status` but `list` keeps it simple (PID + nothing else) to keep `list` fast. Health-check-based promotion from PID-alive to "fully up" can be added in Iter 3 when the tray UI needs it.
- **Placeholders:** none — every code block is complete.
- **Type consistency:** `ActiveProject(name, backend_pid, frontend_pid)` is used identically in state.py, project.py and cli.py.
