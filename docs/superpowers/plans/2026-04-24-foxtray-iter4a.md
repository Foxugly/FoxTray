# FoxTray Iter 4a (Per-Project Tasks + Standalone Scripts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users run one-shot commands (`python manage.py migrate`, `pytest`, `git pull`, …) from the tray menu as async tasks and scripts, with completion balloons and log files, all fully orthogonal to the project lifecycle.

**Architecture:** Two new `config.yaml` shapes (`projects[].tasks` and top-level `scripts`), a new `TaskManager` class (`foxtray/tasks.py`) that owns running Popens + watcher threads, a shared `process.spawn_with_log` helper extracted from `ProcessManager.start`, and tray menu extensions that render `Tasks ▸` / `Scripts ▸` submenus with disabled "(running…)" entries.

**Tech Stack:** Existing only — `pystray`, `Pillow`, `psutil`, `PyYAML`. No new deps.

**Spec:** `docs/superpowers/specs/2026-04-24-foxtray-iter4a-design.md`.

---

## File structure

New production files:
- `foxtray/tasks.py` — `TaskManager` class + `TaskAlreadyRunning` exception.

Modified production files:
- `foxtray/config.py` — add `Task`, `Script` dataclasses; parse and validate; extend `Project` and `Config`.
- `foxtray/process.py` — extract `spawn_with_log` free function; `ProcessManager.start` uses it.
- `foxtray/logs.py` — add `rotate_task(key)` and `open_task_writer(key)` that target `logs/tasks/` with colon-safe sanitisation.
- `foxtray/ui/tray.py` — `Handlers` gains `on_run_task` / `on_run_script`; `build_menu_items` accepts `running_tasks` and renders `Tasks ▸` / `Scripts ▸` submenus; `TrayApp.__init__` takes a `ProcessManager`; `TrayApp._on_task_complete` fires completion balloons; `_spec_to_pystray` honours `enabled=False` entries unchanged but entries labelled "(running…)" are disabled.
- `foxtray/ui/actions.py` — `on_run_task`, `on_run_script`, and updates to `on_exit` / `on_stop_all_and_exit` to `kill_all` tasks first.
- `foxtray/cli.py` — `cmd_tray` builds a `ProcessManager`, passes it to `TrayApp` and `Orchestrator`.

Modified tests:
- `tests/test_config.py` — new task + script parsing tests.
- `tests/test_process.py` — smoke test for `spawn_with_log` free function.
- `tests/test_logs.py` — new, if it doesn't exist; OR append to existing. Tests `rotate_task` / `open_task_writer`.
- `tests/test_tasks.py` — new; TaskManager unit tests with real Popens against short `sys.exit(n)` scripts.
- `tests/test_tray.py` — menu rendering with tasks/scripts/running suffix.
- `tests/test_tray_actions.py` — new handler tests; exit-kills-tasks tests.
- `tests/test_tray_app.py` — `TrayApp(cfg, orch, manager)` signature update; `_on_task_complete` balloons.
- `tests/test_cli.py` — `cmd_tray` constructs ProcessManager and passes it to TrayApp.

New doc:
- `docs/manual-tests/iter4a.md`

Unchanged: `foxtray/state.py`, `foxtray/health.py`, `foxtray/paths.py`, `foxtray/project.py`, `foxtray/ui/icons.py`, `main.py`, `config.yaml` (no rewrite — user opts in by adding `tasks:` / `scripts:` themselves).

---

## Task 1: `Task` dataclass + parsing

**Files:**
- Modify: `foxtray/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Append failing tests to `tests/test_config.py`**

```python
TASKS_YAML = """
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
    tasks:
      - name: Migrate
        cwd: backend
        command: python manage.py migrate
      - name: Collect static
        cwd: backend
        command: python manage.py collectstatic --noinput
      - name: NG test
        cwd: frontend
        command: ng test --watch=false
"""


def test_project_without_tasks_has_empty_tuple(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.projects[0].tasks == ()


def test_project_parses_tasks_in_order(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, TASKS_YAML))
    task_names = [t.name for t in cfg.projects[0].tasks]
    assert task_names == ["Migrate", "Collect static", "NG test"]


def test_task_backend_cwd_swaps_python(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, TASKS_YAML))
    project = cfg.projects[0]
    migrate = next(t for t in project.tasks if t.name == "Migrate")
    cmd = migrate.resolved_command(project)
    assert cmd[0] == str(project.backend.python_executable)
    assert cmd[1:] == ["manage.py", "migrate"]


def test_task_backend_cwd_does_not_swap_non_python(tmp_path: Path) -> None:
    yaml = TASKS_YAML.replace(
        "command: python manage.py migrate",
        "command: pytest tests/",
    )
    cfg = config.load(write_config(tmp_path, yaml))
    migrate = cfg.projects[0].tasks[0]
    assert migrate.resolved_command(cfg.projects[0]) == ["pytest", "tests/"]


def test_task_frontend_cwd_never_swaps(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, TASKS_YAML))
    ng_test = next(t for t in cfg.projects[0].tasks if t.name == "NG test")
    assert ng_test.resolved_command(cfg.projects[0])[0] == "ng"


def test_task_resolved_cwd_backend(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, TASKS_YAML))
    project = cfg.projects[0]
    migrate = project.tasks[0]
    assert migrate.resolved_cwd(project) == project.backend.path


def test_task_resolved_cwd_frontend(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, TASKS_YAML))
    project = cfg.projects[0]
    ng_test = project.tasks[2]
    assert ng_test.resolved_cwd(project) == project.frontend.path


def test_task_rejects_invalid_cwd(tmp_path: Path) -> None:
    yaml = TASKS_YAML.replace("cwd: backend", "cwd: sideways")
    with pytest.raises(config.ConfigError, match="cwd"):
        config.load(write_config(tmp_path, yaml))


def test_task_rejects_empty_command(tmp_path: Path) -> None:
    yaml = TASKS_YAML.replace("command: python manage.py migrate", 'command: ""')
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml))


def test_task_rejects_duplicate_names_within_project(tmp_path: Path) -> None:
    yaml = TASKS_YAML.replace("name: Collect static", "name: Migrate")
    with pytest.raises(config.ConfigError, match="duplicate"):
        config.load(write_config(tmp_path, yaml))


def test_task_rejects_missing_name(tmp_path: Path) -> None:
    yaml = TASKS_YAML.replace("- name: Migrate\n        cwd: backend", "- cwd: backend")
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml))
```

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_config.py -v -k "task or tasks"
```

Expected: many failures (`Task` dataclass does not exist; `Project.tasks` attribute missing).

- [ ] **Step 3: Add `Task` dataclass to `foxtray/config.py`**

Insert right after the existing `Frontend` dataclass (before `Project`):

```python
@dataclass(frozen=True)
class Task:
    name: str
    cwd: str  # "backend" | "frontend"
    command: str

    def resolved_command(self, project: "Project") -> list[str]:
        parts = shlex.split(self.command)
        if not parts:
            raise ConfigError(f"task {self.name!r} command is empty")
        if self.cwd == "backend" and parts[0].lower() == "python":
            return [str(project.backend.python_executable), *parts[1:]]
        return parts

    def resolved_cwd(self, project: "Project") -> Path:
        return project.backend.path if self.cwd == "backend" else project.frontend.path
```

- [ ] **Step 4: Extend `Project` with `tasks` field**

Update the existing `Project` dataclass:

```python
@dataclass(frozen=True)
class Project:
    name: str
    url: str
    backend: Backend
    frontend: Frontend
    start_timeout: int = 30
    tasks: tuple[Task, ...] = ()
```

- [ ] **Step 5: Add `_parse_task` and extend `_parse_project`**

Add this helper just below `_parse_frontend`:

```python
def _parse_task(raw: dict[str, Any], project_name: str) -> Task:
    if not isinstance(raw, dict):
        raise ConfigError(f"project {project_name!r}: each task must be a mapping")
    name = _require(raw, "name", f"project {project_name!r} task")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"project {project_name!r}: task name must be a non-empty string")
    cwd = _require(raw, "cwd", f"project {project_name!r} task {name!r}")
    if cwd not in ("backend", "frontend"):
        raise ConfigError(
            f"project {project_name!r} task {name!r}: cwd must be 'backend' or 'frontend', got {cwd!r}"
        )
    command = _require(raw, "command", f"project {project_name!r} task {name!r}")
    if not isinstance(command, str) or not shlex.split(command):
        raise ConfigError(
            f"project {project_name!r} task {name!r}: command must be a non-empty string"
        )
    return Task(name=name, cwd=cwd, command=command)
```

Update `_parse_project` to parse the optional `tasks` list. Replace the existing function body:

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
    tasks_raw = raw.get("tasks", [])
    if not isinstance(tasks_raw, list):
        raise ConfigError(f"project {name!r}: tasks must be a list")
    tasks = tuple(_parse_task(t, name) for t in tasks_raw)
    task_names = [t.name for t in tasks]
    duplicate_tasks = {n for n in task_names if task_names.count(n) > 1}
    if duplicate_tasks:
        raise ConfigError(
            f"project {name!r}: duplicate task names: {sorted(duplicate_tasks)}"
        )
    return Project(
        name=name,
        url=_require(raw, "url", f"project {name!r}"),
        backend=_parse_backend(_require(raw, "backend", f"project {name!r}")),
        frontend=_parse_frontend(_require(raw, "frontend", f"project {name!r}")),
        start_timeout=start_timeout_raw,
        tasks=tasks,
    )
```

- [ ] **Step 6: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```

Expected: all green including the new task tests.

- [ ] **Step 7: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add foxtray/config.py tests/test_config.py
git commit -m "feat(config): Project.tasks with Task dataclass + validation"
```

Full message:
```
feat(config): Project.tasks with Task dataclass + validation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 2: `Script` dataclass + parsing

**Files:**
- Modify: `foxtray/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Append failing tests to `tests/test_config.py`**

```python
SCRIPTS_YAML = """
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

scripts:
  - name: Git pull all
    path: D:\\\\PycharmProjects
    command: git pull --recurse
  - name: Run migrations
    path: D:\\\\scripts\\\\migrations
    venv: .venv
    command: python one_off.py
"""


def test_config_without_scripts_has_empty_tuple(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.scripts == ()


def test_config_parses_scripts(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SCRIPTS_YAML))
    names = [s.name for s in cfg.scripts]
    assert names == ["Git pull all", "Run migrations"]


def test_script_without_venv_does_not_swap(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SCRIPTS_YAML))
    git_pull = cfg.scripts[0]
    assert git_pull.resolved_command() == ["git", "pull", "--recurse"]


def test_script_with_venv_swaps_python(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SCRIPTS_YAML))
    migration = cfg.scripts[1]
    cmd = migration.resolved_command()
    assert cmd[0] == str(Path("D:\\scripts\\migrations") / ".venv" / "Scripts" / "python.exe")
    assert cmd[1:] == ["one_off.py"]


def test_script_with_venv_but_non_python_command_no_swap(tmp_path: Path) -> None:
    yaml = SCRIPTS_YAML.replace("command: python one_off.py", "command: bash script.sh")
    cfg = config.load(write_config(tmp_path, yaml))
    migration = cfg.scripts[1]
    assert migration.resolved_command() == ["bash", "script.sh"]


def test_script_rejects_relative_path(tmp_path: Path) -> None:
    yaml = SCRIPTS_YAML.replace("path: D:\\\\PycharmProjects", "path: relative/path")
    with pytest.raises(config.ConfigError, match="absolute"):
        config.load(write_config(tmp_path, yaml))


def test_script_rejects_duplicate_names(tmp_path: Path) -> None:
    yaml = SCRIPTS_YAML.replace("name: Run migrations", "name: Git pull all")
    with pytest.raises(config.ConfigError, match="duplicate"):
        config.load(write_config(tmp_path, yaml))


def test_script_rejects_empty_command(tmp_path: Path) -> None:
    yaml = SCRIPTS_YAML.replace("command: git pull --recurse", 'command: ""')
    with pytest.raises(config.ConfigError):
        config.load(write_config(tmp_path, yaml))


def test_script_rejects_empty_venv_string(tmp_path: Path) -> None:
    yaml = SCRIPTS_YAML.replace("venv: .venv", 'venv: ""')
    with pytest.raises(config.ConfigError, match="venv"):
        config.load(write_config(tmp_path, yaml))
```

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_config.py -v -k script
```

Expected: failures (`Script` and `Config.scripts` don't exist).

- [ ] **Step 3: Add `Script` dataclass**

Insert in `foxtray/config.py` just after the `Task` dataclass:

```python
@dataclass(frozen=True)
class Script:
    name: str
    path: Path
    command: str
    venv: str | None = None

    def resolved_command(self) -> list[str]:
        parts = shlex.split(self.command)
        if not parts:
            raise ConfigError(f"script {self.name!r} command is empty")
        if self.venv and parts[0].lower() == "python":
            return [str(self.path / self.venv / "Scripts" / "python.exe"), *parts[1:]]
        return parts
```

- [ ] **Step 4: Extend `Config` with `scripts` field**

Update the existing `Config` dataclass:

```python
@dataclass(frozen=True)
class Config:
    projects: list[Project] = field(default_factory=list)
    scripts: tuple[Script, ...] = ()

    def get(self, name: str) -> Project:
        for project in self.projects:
            if project.name == name:
                return project
        raise ProjectNotFound(name)
```

- [ ] **Step 5: Add `_parse_script` and extend `load`**

Add this helper just below `_parse_project`:

```python
def _parse_script(raw: dict[str, Any]) -> Script:
    if not isinstance(raw, dict):
        raise ConfigError("each script must be a mapping")
    name = _require(raw, "name", "script")
    if not isinstance(name, str) or not name:
        raise ConfigError("script name must be a non-empty string")
    path_raw = _require(raw, "path", f"script {name!r}")
    path = Path(path_raw)
    if not path.is_absolute():
        raise ConfigError(f"script {name!r}: path must be absolute, got {path_raw!r}")
    command = _require(raw, "command", f"script {name!r}")
    if not isinstance(command, str) or not shlex.split(command):
        raise ConfigError(f"script {name!r}: command must be a non-empty string")
    venv = raw.get("venv")
    if venv is not None and (not isinstance(venv, str) or not venv):
        raise ConfigError(f"script {name!r}: venv must be a non-empty string if present")
    return Script(name=name, path=path, command=command, venv=venv)
```

Update `load` to parse scripts and validate uniqueness:

```python
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
    scripts_raw = raw.get("scripts", [])
    if not isinstance(scripts_raw, list):
        raise ConfigError("'scripts' must be a list")
    scripts = tuple(_parse_script(s) for s in scripts_raw)
    script_names = [s.name for s in scripts]
    dup_scripts = {n for n in script_names if script_names.count(n) > 1}
    if dup_scripts:
        raise ConfigError(f"duplicate script names: {sorted(dup_scripts)}")
    return Config(projects=projects, scripts=scripts)
```

- [ ] **Step 6: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```

Expected: all green.

- [ ] **Step 7: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add foxtray/config.py tests/test_config.py
git commit -m "feat(config): top-level scripts with Script dataclass + validation"
```

Full message:
```
feat(config): top-level scripts with Script dataclass + validation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 3: Extract `process.spawn_with_log`

No behaviour change — pure refactor. `ProcessManager.start` continues to pass all existing tests; `spawn_with_log` becomes the reusable primitive for `TaskManager` (Task 5).

**Files:**
- Modify: `foxtray/process.py`
- Modify: `tests/test_process.py`

- [ ] **Step 1: Append a failing unit test for the new free function**

Append to `tests/test_process.py`:

```python
def test_spawn_with_log_runs_command_and_redirects_output(tmp_path: Path) -> None:
    from foxtray import process

    log_file = (tmp_path / "out.log").open("w", encoding="utf-8", buffering=1)
    popen = process.spawn_with_log(
        [sys.executable, "-c", "print('hello')"],
        cwd=tmp_path,
        log_file=log_file,
    )
    popen.wait()
    log_file.close()
    content = (tmp_path / "out.log").read_text(encoding="utf-8")
    assert "hello" in content


def test_spawn_with_log_closes_log_file_on_popen_failure(tmp_path: Path) -> None:
    from foxtray import process

    log_file = (tmp_path / "out.log").open("w", encoding="utf-8", buffering=1)
    with pytest.raises(process.ExecutableNotFound):
        process.spawn_with_log(
            ["definitely-not-a-real-binary-abc123"],
            cwd=tmp_path,
            log_file=log_file,
        )
    # log_file should be closed after the raise
    assert log_file.closed
```

Add `import sys` and `from pathlib import Path` to the top of `tests/test_process.py` if not already present.

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_process.py -v -k spawn_with_log
```

Expected: 2 failures (`ImportError: cannot import name 'spawn_with_log'` or `AttributeError`).

- [ ] **Step 3: Extract `spawn_with_log` in `foxtray/process.py`**

Insert this free function just below `_resolve_command` (before the `ProcessManager` class):

```python
def spawn_with_log(
    command: list[str], cwd: Path, log_file
) -> subprocess.Popen[bytes]:
    """Spawn a process with stdout+stderr redirected to log_file.

    Resolves the command via the same _resolve_command path used by
    ProcessManager.start (so PATHEXT / absolute-path quirks behave the same),
    closes log_file on Popen failure, and uses the module's _CREATION_FLAGS.
    Caller owns the Popen's lifecycle.
    """
    resolved = _resolve_command(command)
    try:
        return subprocess.Popen(
            resolved,
            cwd=str(cwd),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=_CREATION_FLAGS,
        )
    except Exception:
        log_file.close()
        raise
```

Now refactor `ProcessManager.start` to call the new helper:

```python
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
    return spawn_with_log(command, cwd, log_file)
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_process.py -v
```

Expected: all green (new spawn_with_log tests + existing ProcessManager tests).

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green (no regressions — ProcessManager.start behaviour is preserved).

- [ ] **Step 6: Commit**

```bash
git add foxtray/process.py tests/test_process.py
git commit -m "refactor(process): extract spawn_with_log as reusable helper"
```

Full message:
```
refactor(process): extract spawn_with_log as reusable helper

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 4: `logs.rotate_task` + `logs.open_task_writer`

**Files:**
- Modify: `foxtray/logs.py`
- Modify: `foxtray/paths.py` (add `task_log_file` helper)
- Create: `tests/test_logs.py` (if absent) or append to existing

- [ ] **Step 1: Append failing tests to `tests/test_logs.py`**

Check whether `tests/test_logs.py` exists. If not, create it with the preamble; if it does, append. (Use this preamble if creating:)

```python
from pathlib import Path

from foxtray import logs, paths


def test_rotate_task_creates_tasks_subdir_and_sanitizes_key(tmp_appdata: Path) -> None:
    # No existing log file — rotate is a no-op but creates the dir
    logs.rotate_task("task:FoxRunner:Migrate")
    tasks_dir = paths.app_data_dir() / "logs" / "tasks"
    assert tasks_dir.exists()


def test_open_task_writer_writes_to_sanitized_path(tmp_appdata: Path) -> None:
    fh = logs.open_task_writer("task:FoxRunner:Migrate")
    fh.write("hello task log\n")
    fh.close()
    expected = paths.app_data_dir() / "logs" / "tasks" / "task_FoxRunner_Migrate.log"
    assert expected.exists()
    assert "hello task log" in expected.read_text(encoding="utf-8")


def test_rotate_task_moves_existing_log_to_dot1(tmp_appdata: Path) -> None:
    fh = logs.open_task_writer("script:Git pull all")
    fh.write("first run\n")
    fh.close()

    logs.rotate_task("script:Git pull all")

    rotated = paths.app_data_dir() / "logs" / "tasks" / "script_Git pull all.log.1"
    assert rotated.exists()
    assert "first run" in rotated.read_text(encoding="utf-8")
```

The `tmp_appdata` fixture is already provided by `tests/conftest.py` and redirects `paths.app_data_dir()` to a tmp directory.

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_logs.py -v
```

Expected: failures (`rotate_task`, `open_task_writer` don't exist).

- [ ] **Step 3: Add `task_log_file` helper to `foxtray/paths.py`**

Inspect the current `foxtray/paths.py` first. Look for the existing `log_file` function. Add this helper right after it:

```python
def task_log_file(key: str) -> Path:
    """Path to the log file for a task/script key. Colons in the key are
    replaced with underscores for Windows filesystem safety."""
    sanitized = key.replace(":", "_")
    return app_data_dir() / "logs" / "tasks" / f"{sanitized}.log"
```

Also update `ensure_dirs` (if present and if needed) to create the `tasks/` subdir. If `ensure_dirs` currently creates `logs/`, add a line that also creates `logs/tasks/`. Alternatively, the `logs.rotate_task` helper can create it on demand — preferred to keep `paths.ensure_dirs` stable.

- [ ] **Step 4: Add `rotate_task` and `open_task_writer` to `foxtray/logs.py`**

Append at the end of `foxtray/logs.py`:

```python
def _previous_task_path(key: str) -> Path:
    current = paths.task_log_file(key)
    return current.parent / f"{current.stem}.log.1"


def rotate_task(key: str) -> None:
    """Rotate the log file for a task/script key. Creates the tasks/ subdir."""
    current = paths.task_log_file(key)
    current.parent.mkdir(parents=True, exist_ok=True)
    if not current.exists():
        return
    previous = _previous_task_path(key)
    if previous.exists():
        previous.unlink()
    current.rename(previous)


def open_task_writer(key: str) -> IO[str]:
    """Open the current task log file for writing. Caller closes."""
    path = paths.task_log_file(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("w", encoding="utf-8", buffering=1)
```

- [ ] **Step 5: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_logs.py -v
```

Expected: all green.

- [ ] **Step 6: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add foxtray/logs.py foxtray/paths.py tests/test_logs.py
git commit -m "feat(logs): rotate_task + open_task_writer for tasks/ subdir"
```

Full message:
```
feat(logs): rotate_task + open_task_writer for tasks/ subdir

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 5: `TaskManager` + `TaskAlreadyRunning`

**Files:**
- Create: `foxtray/tasks.py`
- Create: `tests/test_tasks.py`

- [ ] **Step 1: Write failing tests in `tests/test_tasks.py`**

```python
"""TaskManager unit tests with real short-lived Popens."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from foxtray import tasks


def _python_exit(code: int) -> list[str]:
    return [sys.executable, "-c", f"import sys; sys.exit({code})"]


def _python_sleep(seconds: float) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds})"]


def _collect_completions(expected: int, timeout: float = 5.0):
    """Return (callback, done_event, completions_list). done_event fires when
    `expected` completions have been recorded."""
    done = threading.Event()
    completions: list[tuple[str, int]] = []

    def _cb(key: str, exit_code: int) -> None:
        completions.append((key, exit_code))
        if len(completions) >= expected:
            done.set()

    return _cb, done, completions


def test_run_spawns_and_registers(tmp_appdata: Path, tmp_path: Path) -> None:
    kills: list[int] = []
    cb, done, completions = _collect_completions(1)
    tm = tasks.TaskManager(kill_tree=kills.append, on_complete=cb)
    tm.run("task:A:Test", _python_exit(0), tmp_path)
    assert done.wait(5.0), "completion callback did not fire"
    assert completions == [("task:A:Test", 0)]
    assert not tm.is_running("task:A:Test")


def test_run_second_time_same_key_raises(
    tmp_appdata: Path, tmp_path: Path
) -> None:
    cb, _done, _completions = _collect_completions(1)
    tm = tasks.TaskManager(kill_tree=lambda pid: None, on_complete=cb)
    tm.run("task:A:Sleep", _python_sleep(2), tmp_path)
    with pytest.raises(tasks.TaskAlreadyRunning):
        tm.run("task:A:Sleep", _python_sleep(2), tmp_path)
    tm.kill_all()  # cleanup


def test_is_running_and_running_keys(tmp_appdata: Path, tmp_path: Path) -> None:
    cb, _done, _completions = _collect_completions(1)
    tm = tasks.TaskManager(kill_tree=lambda pid: None, on_complete=cb)
    tm.run("task:A:Sleep", _python_sleep(2), tmp_path)
    assert tm.is_running("task:A:Sleep")
    assert tm.running_keys() == {"task:A:Sleep"}
    tm.kill_all()


def test_on_complete_gets_nonzero_exit(tmp_appdata: Path, tmp_path: Path) -> None:
    cb, done, completions = _collect_completions(1)
    tm = tasks.TaskManager(kill_tree=lambda pid: None, on_complete=cb)
    tm.run("task:A:Fail", _python_exit(1), tmp_path)
    assert done.wait(5.0)
    assert completions == [("task:A:Fail", 1)]


def test_kill_all_kills_tracked_popens_and_returns_count(
    tmp_appdata: Path, tmp_path: Path
) -> None:
    killed_pids: list[int] = []
    cb, _done, _completions = _collect_completions(2)
    tm = tasks.TaskManager(kill_tree=killed_pids.append, on_complete=cb)
    tm.run("task:A:One", _python_sleep(10), tmp_path)
    tm.run("task:A:Two", _python_sleep(10), tmp_path)
    killed = tm.kill_all()
    assert killed == 2
    assert len(killed_pids) == 2
    # After kill_all, running_keys should be empty immediately (dict cleared
    # before kill_tree calls).
    assert tm.running_keys() == set()


def test_on_complete_exception_does_not_crash_watcher(
    tmp_appdata: Path, tmp_path: Path
) -> None:
    def _bad_cb(key: str, exit_code: int) -> None:
        raise RuntimeError("boom")

    tm = tasks.TaskManager(kill_tree=lambda pid: None, on_complete=_bad_cb)
    tm.run("task:A:Test", _python_exit(0), tmp_path)
    # Give the watcher time to complete and hit the except
    deadline = time.monotonic() + 3.0
    while tm.is_running("task:A:Test") and time.monotonic() < deadline:
        time.sleep(0.05)
    # The watcher should have removed the key even though the callback raised
    assert not tm.is_running("task:A:Test")
```

Add `tmp_appdata` to `tests/conftest.py` if not already a project-level fixture — it already is (it exists and redirects paths.app_data_dir); no change needed here.

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tasks.py -v
```

Expected: failures (`foxtray.tasks` module does not exist).

- [ ] **Step 3: Create `foxtray/tasks.py`**

```python
"""One-shot command execution independent of project lifecycle.

A TaskManager owns a dict of running Popens keyed by a string, spawns each
via process.spawn_with_log + logs.rotate_task/open_task_writer, and fires a
completion callback from a watcher thread when each Popen exits.
"""
from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import Callable

from foxtray import logs, process

log = logging.getLogger(__name__)


class TaskAlreadyRunning(RuntimeError):
    """Raised when .run() is called for a key that is already running."""


class TaskManager:
    def __init__(
        self,
        kill_tree: Callable[[int], None],
        on_complete: Callable[[str, int], None],
    ) -> None:
        self._kill_tree = kill_tree
        self._on_complete = on_complete
        self._running: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def is_running(self, key: str) -> bool:
        with self._lock:
            return key in self._running

    def running_keys(self) -> set[str]:
        with self._lock:
            return set(self._running)

    def run(self, key: str, command: list[str], cwd: Path) -> None:
        with self._lock:
            if key in self._running:
                raise TaskAlreadyRunning(key)
        logs.rotate_task(key)
        log_file = logs.open_task_writer(key)
        popen = process.spawn_with_log(command, cwd, log_file)
        with self._lock:
            self._running[key] = popen
        threading.Thread(
            target=self._watch,
            args=(key, popen),
            name=f"task-{key}",
            daemon=True,
        ).start()

    def _watch(self, key: str, popen: subprocess.Popen[bytes]) -> None:
        exit_code = popen.wait()
        with self._lock:
            self._running.pop(key, None)
        try:
            self._on_complete(key, exit_code)
        except Exception:  # noqa: BLE001 — callback must not crash watcher
            log.warning("task %s on_complete callback failed", key, exc_info=True)

    def kill_all(self) -> int:
        with self._lock:
            victims = list(self._running.items())
            self._running.clear()
        for key, popen in victims:
            try:
                self._kill_tree(popen.pid)
            except Exception:  # noqa: BLE001
                log.warning("kill_all: failed to kill %s", key, exc_info=True)
        return len(victims)
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tasks.py -v
```

Expected: all green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add foxtray/tasks.py tests/test_tasks.py
git commit -m "feat(tasks): TaskManager + TaskAlreadyRunning for async utility commands"
```

Full message:
```
feat(tasks): TaskManager + TaskAlreadyRunning for async utility commands

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 6: `Handlers` extension + `build_menu_items` signature

Extends `Handlers` dataclass with `on_run_task` and `on_run_script`, updates `build_menu_items` to accept `running_tasks` and render `Tasks ▸` / `Scripts ▸` submenus with "(running…)" suffix for running entries.

**Files:**
- Modify: `foxtray/ui/tray.py`
- Modify: `tests/test_tray.py`

- [ ] **Step 1: Append failing tests to `tests/test_tray.py`**

```python
def _project_with_tasks(name: str = "A") -> config.Project:
    base = _project(name)
    return config.Project(
        name=base.name,
        url=base.url,
        backend=base.backend,
        frontend=base.frontend,
        start_timeout=base.start_timeout,
        tasks=(
            config.Task(name="Migrate", cwd="backend", command="python manage.py migrate"),
            config.Task(name="NG test", cwd="frontend", command="ng test --watch=false"),
        ),
    )


def _noop_handlers_with_tasks() -> tray.Handlers:
    return tray.Handlers(
        on_start=lambda p: None,
        on_stop=lambda p: None,
        on_open_browser=lambda p: None,
        on_open_folder=lambda path: None,
        on_stop_all=lambda: None,
        on_exit=lambda: None,
        on_stop_all_and_exit=lambda: None,
        on_run_task=lambda p, t: None,
        on_run_script=lambda s: None,
    )


def test_menu_project_without_tasks_has_no_tasks_submenu() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Tasks" not in submenu_texts


def test_menu_project_with_tasks_adds_tasks_submenu() -> None:
    cfg = config.Config(projects=[_project_with_tasks("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks=set(),
    )
    tasks_item = next(s for s in items[0].submenu if s.text == "Tasks")
    assert len(tasks_item.submenu) == 2
    assert [t.text for t in tasks_item.submenu] == ["Migrate", "NG test"]


def test_menu_running_task_shows_disabled_suffix() -> None:
    cfg = config.Config(projects=[_project_with_tasks("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks={"task:A:Migrate"},
    )
    tasks_item = next(s for s in items[0].submenu if s.text == "Tasks")
    migrate = next(t for t in tasks_item.submenu if t.text.startswith("Migrate"))
    assert migrate.text == "Migrate (running…)"
    assert migrate.enabled is False


def test_menu_config_without_scripts_has_no_scripts_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks=set(),
    )
    texts = [i.text for i in items if not i.separator]
    assert "Scripts" not in texts


def test_menu_config_with_scripts_adds_scripts_submenu() -> None:
    cfg = config.Config(
        projects=[_project("A")],
        scripts=(
            config.Script(
                name="Git pull", path=Path("D:\\\\x"), command="git pull"
            ),
        ),
    )
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks=set(),
    )
    scripts_item = next(i for i in items if i.text == "Scripts")
    assert [s.text for s in scripts_item.submenu] == ["Git pull"]


def test_menu_running_script_shows_disabled_suffix() -> None:
    cfg = config.Config(
        projects=[_project("A")],
        scripts=(
            config.Script(name="Git pull", path=Path("D:\\\\x"), command="git pull"),
        ),
    )
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks={"script:Git pull"},
    )
    scripts_item = next(i for i in items if i.text == "Scripts")
    git_pull = scripts_item.submenu[0]
    assert git_pull.text == "Git pull (running…)"
    assert git_pull.enabled is False


def test_menu_scripts_item_placed_before_stop_all() -> None:
    cfg = config.Config(
        projects=[_project("A")],
        scripts=(config.Script(name="S", path=Path("D:\\\\x"), command="git pull"),),
    )
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers_with_tasks(),
        running_tasks=set(),
    )
    # Order: project items, separator, Scripts, separator, Stop all, ...
    non_sep = [i for i in items if not i.separator]
    scripts_idx = next(i for i, e in enumerate(non_sep) if e.text == "Scripts")
    stop_all_idx = next(i for i, e in enumerate(non_sep) if e.text == "Stop all")
    assert scripts_idx < stop_all_idx
```

Also update the existing `_noop_handlers` helper in `tests/test_tray.py` to include `on_run_task` and `on_run_script` as no-ops. Find the existing definition:

```python
def _noop_handlers() -> tray.Handlers:
    return tray.Handlers(
        on_start=lambda p: None,
        on_stop=lambda p: None,
        on_open_browser=lambda p: None,
        on_open_folder=lambda path: None,
        on_stop_all=lambda: None,
        on_exit=lambda: None,
        on_stop_all_and_exit=lambda: None,
    )
```

Replace with:

```python
def _noop_handlers() -> tray.Handlers:
    return tray.Handlers(
        on_start=lambda p: None,
        on_stop=lambda p: None,
        on_open_browser=lambda p: None,
        on_open_folder=lambda path: None,
        on_stop_all=lambda: None,
        on_exit=lambda: None,
        on_stop_all_and_exit=lambda: None,
        on_run_task=lambda p, t: None,
        on_run_script=lambda s: None,
    )
```

Also every existing call to `tray.build_menu_items(cfg, active, statuses, handlers)` in `tests/test_tray.py` needs `running_tasks=set()` added. Find every call and append the kwarg. (Count: about 12 call sites.)

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: failures: new tests fail on signature or absent submenu; existing tests fail on `Handlers(...)` missing new fields.

- [ ] **Step 3: Extend `Handlers` dataclass in `foxtray/ui/tray.py`**

Find the existing `Handlers` dataclass (around line 38 of `foxtray/ui/tray.py`). Add two fields:

```python
@dataclass
class Handlers:
    """Menu-action callbacks. Intentionally mutable: TrayApp rebuilds a fresh
    instance per menu paint, so callers should not cache instances."""

    on_start: Callable[[config_mod.Project], None]
    on_stop: Callable[[config_mod.Project], None]
    on_open_browser: Callable[[config_mod.Project], None]
    on_open_folder: Callable[[Path], None]
    on_stop_all: Callable[[], None]
    on_exit: Callable[[], None]
    on_stop_all_and_exit: Callable[[], None]
    on_run_task: Callable[[config_mod.Project, config_mod.Task], None]
    on_run_script: Callable[[config_mod.Script], None]
```

- [ ] **Step 4: Update `_project_submenu` to append Tasks submenu**

Replace the existing `_project_submenu` function body:

```python
def _project_submenu(
    project: config_mod.Project,
    icon_state: IconState,
    handlers: Handlers,
    running_tasks: set[str],
) -> tuple[MenuItemSpec, ...]:
    is_stopped = icon_state == "stopped"
    if is_stopped:
        start_or_stop = MenuItemSpec(
            text="Start", action=lambda p=project: handlers.on_start(p)
        )
    else:
        start_or_stop = MenuItemSpec(
            text="Stop", action=lambda p=project: handlers.on_stop(p)
        )
    entries: list[MenuItemSpec] = [
        start_or_stop,
        MenuItemSpec(text="", separator=True),
        MenuItemSpec(
            text="Open in browser",
            action=lambda p=project: handlers.on_open_browser(p),
            enabled=not is_stopped,
        ),
        MenuItemSpec(
            text="Open backend folder",
            action=lambda path=project.backend.path: handlers.on_open_folder(path),
        ),
        MenuItemSpec(
            text="Open frontend folder",
            action=lambda path=project.frontend.path: handlers.on_open_folder(path),
        ),
    ]
    if project.tasks:
        task_specs = tuple(
            _task_spec(project, task, handlers, running_tasks)
            for task in project.tasks
        )
        entries.append(MenuItemSpec(text="Tasks", submenu=task_specs))
    return tuple(entries)


def _task_spec(
    project: config_mod.Project,
    task: config_mod.Task,
    handlers: Handlers,
    running_tasks: set[str],
) -> MenuItemSpec:
    key = f"task:{project.name}:{task.name}"
    if key in running_tasks:
        return MenuItemSpec(
            text=f"{task.name} (running…)", enabled=False,
        )
    return MenuItemSpec(
        text=task.name,
        action=lambda p=project, t=task: handlers.on_run_task(p, t),
    )
```

- [ ] **Step 5: Update `build_menu_items` to accept `running_tasks` and render scripts**

Replace the existing `build_menu_items`:

```python
def build_menu_items(
    cfg: config_mod.Config,
    active: state_mod.ActiveProject | None,
    statuses: dict[str, ProjectStatus],
    handlers: Handlers,
    running_tasks: set[str],
) -> list[MenuItemSpec]:
    items: list[MenuItemSpec] = []
    for project in cfg.projects:
        proj_state = _project_icon_state(project.name, active, statuses.get(project.name))
        label = _project_label(proj_state)
        items.append(
            MenuItemSpec(
                text=f"{project.name} ({label})",
                submenu=_project_submenu(project, proj_state, handlers, running_tasks),
            )
        )
    if cfg.scripts:
        items.append(MenuItemSpec(text="", separator=True))
        script_specs = tuple(
            _script_spec(script, handlers, running_tasks) for script in cfg.scripts
        )
        items.append(MenuItemSpec(text="Scripts", submenu=script_specs))
    items.append(MenuItemSpec(text="", separator=True))
    items.append(
        MenuItemSpec(
            text="Stop all",
            action=handlers.on_stop_all,
            enabled=active is not None,
        )
    )
    items.append(MenuItemSpec(text="", separator=True))
    items.append(MenuItemSpec(text="Exit", action=handlers.on_exit))
    items.append(
        MenuItemSpec(
            text="Stop all and exit",
            action=handlers.on_stop_all_and_exit,
            enabled=active is not None,
        )
    )
    return items


def _script_spec(
    script: config_mod.Script,
    handlers: Handlers,
    running_tasks: set[str],
) -> MenuItemSpec:
    key = f"script:{script.name}"
    if key in running_tasks:
        return MenuItemSpec(
            text=f"{script.name} (running…)", enabled=False,
        )
    return MenuItemSpec(
        text=script.name,
        action=lambda s=script: handlers.on_run_script(s),
    )
```

- [ ] **Step 6: Run tray tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray.py -v
```

Expected: all green.

- [ ] **Step 7: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: ALL EXCEPT `tests/test_tray_app.py` green. `TrayApp._build_menu` still calls `build_menu_items(…)` without `running_tasks` — that breaks Task 12's tests. Fix in Task 9. Note the expected transient failures and proceed.

- [ ] **Step 8: Commit**

```bash
git add foxtray/ui/tray.py tests/test_tray.py
git commit -m "feat(ui/tray): Tasks▸/Scripts▸ submenus with running-state rendering"
```

Full message:
```
feat(ui/tray): Tasks▸/Scripts▸ submenus with running-state rendering

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 7: `actions.on_run_task` + `actions.on_run_script`

**Files:**
- Modify: `foxtray/ui/actions.py`
- Modify: `tests/test_tray_actions.py`

- [ ] **Step 1: Append failing tests to `tests/test_tray_actions.py`**

First, extend the existing `_FakeOrchestrator` to still satisfy tests. Then add a `_FakeTaskManager` dataclass near the top of the file:

```python
@dataclass
class _FakeTaskManager:
    runs: list[tuple[str, list[str], Path]] = field(default_factory=list)
    raises: Exception | None = None
    killed_count: int = 0

    def run(self, key: str, command: list[str], cwd: Path) -> None:
        if self.raises:
            raise self.raises
        self.runs.append((key, command, cwd))

    def is_running(self, key: str) -> bool:
        return False

    def kill_all(self) -> int:
        return self.killed_count
```

Then append tests:

```python
def _task() -> config.Task:
    return config.Task(
        name="Migrate", cwd="backend", command="python manage.py migrate"
    )


def _script() -> config.Script:
    return config.Script(
        name="Git pull", path=Path("D:\\proj"), command="git pull"
    )


def test_on_run_task_calls_task_manager_run_with_key_command_cwd() -> None:
    tm = _FakeTaskManager()
    actions.on_run_task(tm, _project(), _task(), _FakeIcon())
    assert len(tm.runs) == 1
    key, command, cwd = tm.runs[0]
    assert key == "task:Demo:Migrate"
    # command: python-swap gives the venv python path
    assert command[0].endswith("python.exe")
    assert command[1:] == ["manage.py", "migrate"]
    assert cwd == _project().backend.path


def test_on_run_task_already_running_notifies() -> None:
    import foxtray.tasks as tasks_mod
    tm = _FakeTaskManager(raises=tasks_mod.TaskAlreadyRunning("task:Demo:Migrate"))
    icon = _FakeIcon()
    actions.on_run_task(tm, _project(), _task(), icon)
    # Balloon content: "Migrate is already running" with title "FoxTray"
    assert any("already running" in message for _title, message in icon.notifications)


def test_on_run_task_unexpected_exception_notifies_error() -> None:
    tm = _FakeTaskManager(raises=RuntimeError("boom"))
    icon = _FakeIcon()
    actions.on_run_task(tm, _project(), _task(), icon)
    assert icon.notifications == [("FoxTray error", "boom")]


def test_on_run_script_calls_task_manager_with_key_and_script_path() -> None:
    tm = _FakeTaskManager()
    actions.on_run_script(tm, _script(), _FakeIcon())
    assert len(tm.runs) == 1
    key, command, cwd = tm.runs[0]
    assert key == "script:Git pull"
    assert command == ["git", "pull"]
    assert cwd == Path("D:\\proj")


def test_on_run_script_already_running_notifies() -> None:
    import foxtray.tasks as tasks_mod
    tm = _FakeTaskManager(raises=tasks_mod.TaskAlreadyRunning("script:Git pull"))
    icon = _FakeIcon()
    actions.on_run_script(tm, _script(), icon)
    assert any("already running" in message for _title, message in icon.notifications)
```

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_actions.py -v -k "run_task or run_script"
```

Expected: failures (functions don't exist yet).

- [ ] **Step 3: Add `on_run_task` and `on_run_script` to `foxtray/ui/actions.py`**

Append to `foxtray/ui/actions.py` (after the existing handlers; the existing `Orchestrator` and Protocol imports still apply):

```python
# Imports to add at top if not present:
# from foxtray import config, tasks


class _TaskRunnerProtocol(Protocol):
    def run(self, key: str, command: list[str], cwd: Path) -> None: ...
    def is_running(self, key: str) -> bool: ...
    def kill_all(self) -> int: ...


def on_run_task(
    task_manager: _TaskRunnerProtocol,
    project: config.Project,
    task: config.Task,
    icon: _Notifier,
) -> None:
    key = f"task:{project.name}:{task.name}"
    try:
        task_manager.run(
            key, task.resolved_command(project), task.resolved_cwd(project)
        )
    except tasks.TaskAlreadyRunning:
        icon.notify(f"{task.name} is already running", title="FoxTray")
    except Exception as exc:  # noqa: BLE001 — tray must survive any handler error
        _notify_error(icon, exc)


def on_run_script(
    task_manager: _TaskRunnerProtocol,
    script: config.Script,
    icon: _Notifier,
) -> None:
    key = f"script:{script.name}"
    try:
        task_manager.run(key, script.resolved_command(), script.path)
    except tasks.TaskAlreadyRunning:
        icon.notify(f"{script.name} is already running", title="FoxTray")
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)
```

Make sure `from foxtray import tasks` is added near the top if not already. Also `from pathlib import Path` if it isn't imported already.

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_actions.py -v
```

Expected: new tests green; existing tests also green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: same state as after Task 6 — all green EXCEPT `tests/test_tray_app.py` (fixed in Task 9). Proceed.

- [ ] **Step 6: Commit**

```bash
git add foxtray/ui/actions.py tests/test_tray_actions.py
git commit -m "feat(ui/actions): on_run_task + on_run_script with already-running balloon"
```

Full message:
```
feat(ui/actions): on_run_task + on_run_script with already-running balloon

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 8: `on_exit` and `on_stop_all_and_exit` kill tasks

**Files:**
- Modify: `foxtray/ui/actions.py`
- Modify: `tests/test_tray_actions.py`

- [ ] **Step 1: Append failing tests to `tests/test_tray_actions.py`**

```python
def test_on_exit_calls_kill_all_and_notifies_if_nonzero() -> None:
    tm = _FakeTaskManager(killed_count=3)

    class _Icon:
        def __init__(self) -> None:
            self.stopped = False
            self.notifications: list[tuple[str, str]] = []
        def notify(self, message: str, title: str = "") -> None:
            self.notifications.append((title, message))
        def stop(self) -> None:
            self.stopped = True

    icon = _Icon()
    actions.on_exit(icon, tm)
    assert icon.stopped is True
    assert any("3" in message and "killed" in message for _t, message in icon.notifications)


def test_on_exit_silent_if_zero_tasks_killed() -> None:
    tm = _FakeTaskManager(killed_count=0)

    class _Icon:
        def __init__(self) -> None:
            self.stopped = False
            self.notifications: list[tuple[str, str]] = []
        def notify(self, message: str, title: str = "") -> None:
            self.notifications.append((title, message))
        def stop(self) -> None:
            self.stopped = True

    icon = _Icon()
    actions.on_exit(icon, tm)
    assert icon.stopped is True
    assert icon.notifications == []


def test_on_stop_all_and_exit_calls_kill_all_and_stop_all() -> None:
    tm = _FakeTaskManager(killed_count=0)
    orch = _FakeOrchestrator()
    user_initiated: set[str] = set()

    class _Icon:
        def __init__(self) -> None:
            self.stopped = False
            self.notifications: list[tuple[str, str]] = []
        def notify(self, message: str, title: str = "") -> None:
            self.notifications.append((title, message))
        def stop(self) -> None:
            self.stopped = True

    icon = _Icon()
    actions.on_stop_all_and_exit(
        orch, icon, user_initiated, active_names=["FoxRunner"], task_manager=tm,
    )
    assert orch.stop_all_called == 1
    assert icon.stopped is True
    # kill_all was invoked (0 in this case — silent)
```

Also **update the existing** `test_on_exit_calls_icon_stop` test: change its signature to pass a `_FakeTaskManager` as the second argument, matching the new signature.

```python
def test_on_exit_calls_icon_stop() -> None:
    class _Icon:
        def __init__(self) -> None:
            self.stopped = False
        def stop(self) -> None:
            self.stopped = True

    icon = _Icon()
    actions.on_exit(icon, _FakeTaskManager())
    assert icon.stopped is True
```

And update `test_on_stop_all_and_exit_stops_then_exits` to pass `task_manager=_FakeTaskManager()` kwarg.

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_actions.py -v
```

Expected: the new tests fail because `on_exit` has old signature.

- [ ] **Step 3: Update `on_exit` and `on_stop_all_and_exit` in `foxtray/ui/actions.py`**

Replace the existing functions:

```python
def on_exit(icon: _Closable, task_manager: _TaskRunnerProtocol) -> None:
    killed = task_manager.kill_all()
    if killed > 0:
        try:
            icon.notify(f"{killed} task(s) killed", title="FoxTray")
        except Exception:  # noqa: BLE001
            pass
    icon.stop()


def on_stop_all_and_exit(
    orchestrator: Orchestrator,
    icon: _Closable,
    user_initiated: set[str],
    active_names: Sequence[str],
    task_manager: _TaskRunnerProtocol,
) -> None:
    for name in active_names:
        user_initiated.add(name)
    try:
        orchestrator.stop_all()
    except Exception as exc:  # noqa: BLE001
        if hasattr(icon, "notify"):
            _notify_error(icon, exc)  # type: ignore[arg-type]
    killed = task_manager.kill_all()
    if killed > 0:
        try:
            icon.notify(f"{killed} task(s) killed", title="FoxTray")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    icon.stop()
```

- [ ] **Step 4: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_actions.py -v
```

Expected: all green.

- [ ] **Step 5: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: same state as Task 7 — test_tray_app.py still failing due to `build_menu_items` and `TrayApp` calls that don't yet pass `running_tasks`/`task_manager`. Task 9 fixes.

- [ ] **Step 6: Commit**

```bash
git add foxtray/ui/actions.py tests/test_tray_actions.py
git commit -m "feat(ui/actions): on_exit and on_stop_all_and_exit kill running tasks"
```

Full message:
```
feat(ui/actions): on_exit and on_stop_all_and_exit kill running tasks

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 9: `TrayApp` integration — TaskManager wiring + `_on_task_complete` + CLI adjustment

This is the task that closes all transient failures from Tasks 6–8 by wiring `TaskManager` into `TrayApp`, updating the constructor signature, adjusting `_build_menu` and `_handlers`, and plumbing a new `ProcessManager` parameter through `cmd_tray`.

**Files:**
- Modify: `foxtray/ui/tray.py`
- Modify: `foxtray/cli.py`
- Modify: `tests/test_tray_app.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Append failing tests to `tests/test_tray_app.py`**

```python
def test_trayapp_creates_task_manager_with_kill_tree_from_process_manager(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})

    class _StubProcessManager:
        def __init__(self) -> None:
            self.kills: list[int] = []
        def kill_tree(self, pid: int, timeout: float = 5.0) -> None:
            self.kills.append(pid)
        # ProcessManager.start is not called by TaskManager construction
        def start(self, **kwargs): raise RuntimeError("should not be called")

    pm = _StubProcessManager()
    app = tray.TrayApp(cfg, orch, pm)  # type: ignore[arg-type]
    assert app._task_manager is not None


def test_on_task_complete_fires_done_balloon_on_zero_exit(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})

    class _StubProcessManager:
        def kill_tree(self, pid: int, timeout: float = 5.0) -> None: pass
        def start(self, **kwargs): raise RuntimeError

    icon = _FakeIcon(icon=None)
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon  # type: ignore[assignment]

    app._on_task_complete("task:A:Migrate", 0)
    assert any(message == "Migrate done" for _t, message in icon.notifications)


def test_on_task_complete_fires_failed_balloon_on_nonzero(
    tmp_appdata: Path, monkeypatch: Any
) -> None:
    cfg = config.Config(projects=[_project("A")])
    orch = _FakeOrchestrator(next_statuses={"A": _status()})

    class _StubProcessManager:
        def kill_tree(self, pid: int, timeout: float = 5.0) -> None: pass
        def start(self, **kwargs): raise RuntimeError

    icon = _FakeIcon(icon=None)
    app = tray.TrayApp(cfg, orch, _StubProcessManager())  # type: ignore[arg-type]
    app._icon = icon  # type: ignore[assignment]

    app._on_task_complete("script:Git pull", 2)
    assert any("Git pull failed" in message for _t, message in icon.notifications)
```

Also **update every existing test in `tests/test_tray_app.py`** that constructs `tray.TrayApp(cfg, orch)` to now pass a fake `ProcessManager` as the 3rd arg. Easiest: add a module-level helper:

```python
class _StubProcessManager:
    def kill_tree(self, pid: int, timeout: float = 5.0) -> None: pass
    def start(self, **kwargs): raise RuntimeError("ProcessManager.start unused in tests")
```

And change `tray.TrayApp(cfg, orch)` to `tray.TrayApp(cfg, orch, _StubProcessManager())` in each existing test.

- [ ] **Step 2: Run tests, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_app.py -v
```

Expected: new tests fail; existing tests may fail due to signature mismatch.

- [ ] **Step 3: Update `TrayApp.__init__` in `foxtray/ui/tray.py`**

Add import near the top:

```python
from foxtray import tasks
from foxtray.process import ProcessManager
```

Update the constructor:

```python
class TrayApp:
    """Integrates pystray + 3s poller on top of the pure helpers above."""

    def __init__(
        self,
        cfg: config_mod.Config,
        orchestrator: Orchestrator,
        process_manager: ProcessManager,
    ) -> None:
        self._cfg = cfg
        self._orchestrator = orchestrator
        self._icon: pystray.Icon | None = None
        self._prev_active: state_mod.ActiveProject | None = None
        self._prev_statuses: dict[str, ProjectStatus] = {
            p.name: _zero_status(p.name) for p in cfg.projects
        }
        self._prev_icon_state: IconState = "stopped"
        self._user_initiated_stop: set[str] = set()
        self._stop_event = threading.Event()
        self._task_manager = tasks.TaskManager(
            kill_tree=process_manager.kill_tree,
            on_complete=self._on_task_complete,
        )
```

- [ ] **Step 4: Add `_on_task_complete` method**

Add inside `TrayApp`:

```python
def _on_task_complete(self, key: str, exit_code: int) -> None:
    if self._icon is None:
        return
    display_name = key.rsplit(":", 1)[-1]
    try:
        if exit_code == 0:
            self._icon.notify(f"{display_name} done", title="FoxTray")
        else:
            log_path = paths.task_log_file(key)
            self._icon.notify(
                f"⚠ {display_name} failed — see {log_path}",
                title="FoxTray",
            )
    except Exception:
        log.warning("notify after task %s completion failed", key, exc_info=True)
    try:
        self._icon.update_menu()
    except Exception:
        log.warning("update_menu after task %s failed", key, exc_info=True)
```

Add the import `from foxtray import paths` near the top of `foxtray/ui/tray.py` if not already present.

- [ ] **Step 5: Update `_build_menu` to pass `running_tasks`**

Find the existing `_build_menu` method. Change its body to pass `running_tasks=self._task_manager.running_keys()` to `build_menu_items`:

```python
def _build_menu(self) -> tuple[pystray.MenuItem, ...]:
    try:
        active = state_mod.load().active
        statuses = {
            p.name: self._orchestrator.status(p) for p in self._cfg.projects
        }
    except Exception:
        log.warning("menu build failed", exc_info=True)
        return (pystray.MenuItem("FoxTray error", None, enabled=False),)
    handlers = self._handlers()
    specs = build_menu_items(
        self._cfg, active, statuses, handlers,
        running_tasks=self._task_manager.running_keys(),
    )
    return tuple(_spec_to_pystray(s) for s in specs)
```

- [ ] **Step 6: Update `_handlers` to pass `task_manager` to action wrappers**

Replace the existing `_handlers` method:

```python
def _handlers(self) -> Handlers:
    icon = self._icon
    assert icon is not None
    orch = self._orchestrator
    tm = self._task_manager

    def _active_names() -> list[str]:
        a = state_mod.load().active
        return [a.name] if a is not None else []

    return Handlers(
        on_start=lambda p: actions.on_start(orch, p, icon),
        on_stop=lambda p: actions.on_stop(orch, p, icon, self._user_initiated_stop),
        on_open_browser=lambda p: actions.on_open_browser(p, icon),
        on_open_folder=lambda path: actions.on_open_folder(path, icon),
        on_stop_all=lambda: actions.on_stop_all(
            orch, icon, self._user_initiated_stop, _active_names()
        ),
        on_exit=lambda: actions.on_exit(icon, tm),
        on_stop_all_and_exit=lambda: actions.on_stop_all_and_exit(
            orch, icon, self._user_initiated_stop, _active_names(), tm,
        ),
        on_run_task=lambda p, t: actions.on_run_task(tm, p, t, icon),
        on_run_script=lambda s: actions.on_run_script(tm, s, icon),
    )
```

- [ ] **Step 7: Update `cmd_tray` in `foxtray/cli.py`**

Change `cmd_tray`:

```python
def cmd_tray(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    manager = process.ProcessManager()
    orchestrator = project.Orchestrator(manager=manager, cfg=cfg)
    tray_module.TrayApp(cfg, orchestrator, manager).run()
    return 0
```

Also update `_orchestrator` helper. Since `cmd_tray` now builds its own `ProcessManager`, `_orchestrator(cfg)` should continue to exist for the other `cmd_*` functions (list, start, stop, etc.). Keep `_orchestrator(cfg)` as-is:

```python
def _orchestrator(cfg: config.Config) -> project.Orchestrator:
    return project.Orchestrator(manager=process.ProcessManager(), cfg=cfg)
```

(Leaves an inconsistency: `cmd_tray` constructs `ProcessManager` inline; other commands go through `_orchestrator`. Acceptable: `cmd_tray` needs two references to the same manager.)

- [ ] **Step 8: Update `tests/test_cli.py`**

The existing `test_tray_command_parses_and_dispatches` test monkeypatches `tray_mod.TrayApp`. Update the fake class to accept 3 positional args:

```python
def test_tray_command_parses_and_dispatches(
    demo_config: Path, tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []

    class _FakeTray:
        def __init__(self, cfg, orchestrator, process_manager) -> None:  # type: ignore[no-untyped-def]
            called.append(f"init:{len(cfg.projects)}")

        def run(self) -> None:
            called.append("run")

    from foxtray.ui import tray as tray_mod
    monkeypatch.setattr(tray_mod, "TrayApp", _FakeTray)

    rc = cli.main(["--config", str(demo_config), "tray"])
    assert rc == 0
    assert called == ["init:1", "run"]
```

- [ ] **Step 9: Run tests, confirm pass**

```
./.venv/Scripts/python.exe -m pytest tests/test_tray_app.py tests/test_cli.py -v
```

Expected: all green.

- [ ] **Step 10: Run full suite**

```
./.venv/Scripts/python.exe -m pytest -v
```

Expected: FULL GREEN. This closes Iter 4a's implementation.

- [ ] **Step 11: Commit**

```bash
git add foxtray/ui/tray.py foxtray/cli.py tests/test_tray_app.py tests/test_cli.py
git commit -m "feat(ui/tray): TrayApp integrates TaskManager; cmd_tray passes ProcessManager"
```

Full message:
```
feat(ui/tray): TrayApp integrates TaskManager; cmd_tray passes ProcessManager

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Task 10: Manual smoke test document

**Files:**
- Create: `docs/manual-tests/iter4a.md`

- [ ] **Step 1: Create `docs/manual-tests/iter4a.md`**

Content:

```markdown
# FoxTray Iter 4a — Manual Test Log

Prerequisite: Iter 3 manual test (`docs/manual-tests/iter3.md`) passed.

## Environment

- Date: <fill>
- HEAD: <commit sha>
- Full test suite: `./.venv/Scripts/python.exe -m pytest -v` (must show all green)

## Setup — add some tasks and scripts to `config.yaml`

Add this to the FoxRunner project entry:

```yaml
    tasks:
      - name: Show Python
        cwd: backend
        command: python -c "import sys; print(sys.version)"
      - name: Quick pytest
        cwd: backend
        command: pytest -q
      - name: NG version
        cwd: frontend
        command: ng version
```

Add this top-level section:

```yaml
scripts:
  - name: Tree FoxTray
    path: D:\PycharmProjects\FoxTray
    command: cmd /c dir /s /b | findstr /r "\.py$"
  - name: Slow sleep
    path: D:\PycharmProjects\FoxTray
    command: python -c "import time; time.sleep(10); print('done')"
    venv: .venv
```

## CLI sanity

- [ ] `python main.py list` — still prints the 3 projects (FoxRunner / QuizOnline / PushIT), no regression from extra YAML.
- [ ] `python main.py start FoxRunner` — still works end-to-end (Iter 3 flow).
- [ ] `python main.py stop FoxRunner` — still clean.

## Tray — tasks submenu

- [ ] Launch `python main.py tray` — grey icon.
- [ ] Right-click → FoxRunner ▸ — a new `Tasks ▸` entry appears at the end of the submenu.
- [ ] FoxRunner ▸ Tasks ▸ — shows `Show Python`, `Quick pytest`, `NG version`.
- [ ] Click `Show Python`. Within a few seconds balloon `Show Python done`. Log file exists at `%APPDATA%\foxtray\logs\tasks\task_FoxRunner_Show Python.log` with the Python version output.
- [ ] Click `Quick pytest`. The entry becomes `Quick pytest (running…)` and is disabled. Balloon `Quick pytest done` at completion (or `⚠ Quick pytest failed` if non-zero exit).
- [ ] While `Quick pytest` is running, try clicking it again — the menu shows it as disabled. If you can trigger a click somehow (racey menu rebuild), you get balloon `Quick pytest is already running`.
- [ ] Click `NG version`. Balloon `NG version done`. Log contains `Angular CLI:` output.

## Tray — tasks while project is running

- [ ] Click `Start` on FoxRunner. Wait for green icon.
- [ ] Click Tasks ▸ Show Python. Task runs successfully; icon stays green; project state unchanged.
- [ ] Click `Stop` on FoxRunner. Icon turns grey. **Tasks that were running are NOT affected** (they're orthogonal — verify by having `Slow sleep` script running when you click Stop; it continues and fires a balloon 10s later).

## Tray — scripts submenu

- [ ] Right-click icon. Root menu: after the 3 projects, a new `Scripts ▸` entry appears **before** `Stop all`.
- [ ] Scripts ▸ — shows `Tree FoxTray`, `Slow sleep`.
- [ ] Click `Tree FoxTray`. Balloon `Tree FoxTray done`. Log file at `%APPDATA%\foxtray\logs\tasks\script_Tree FoxTray.log` contains the list of `.py` files.
- [ ] Click `Slow sleep`. Entry becomes `Slow sleep (running…)` for ~10s, then balloon `Slow sleep done`.

## Tray — exit kills tasks

- [ ] Click `Slow sleep` to start a 10s task.
- [ ] While running, click `Exit`. Balloon `1 task(s) killed` (best-effort — may or may not render depending on pystray exit timing). Tray disappears.
- [ ] In Task Manager, no `python.exe` orphan from the killed task.

- [ ] Click `Slow sleep` to start another 10s task.
- [ ] Click `Start` on FoxRunner, wait green.
- [ ] Click `Stop all and exit`. Orchestrator stops project cleanly, task is killed (balloon `1 task(s) killed`), tray exits.

## Error paths

- [ ] Add a task with a broken command (`python definitely_does_not_exist.py`). Click it. Balloon `⚠ DoesNotExist failed — see {path}`. Log file contains Python's `FileNotFoundError` traceback.
- [ ] Add a task with a command whose executable is not on PATH (`mysterytool arg`). Click it. Balloon indicates error (ExecutableNotFound).

## Config validation

- [ ] Add a task with `cwd: sideways`. `python main.py tray` fails to start with `Config error: ... cwd must be 'backend' or 'frontend'`. Exit 2.
- [ ] Add a script with a relative path (e.g., `path: scripts`). Same: exits 2 with a `path must be absolute` message.
- [ ] Duplicate task names in the same project: exits 2.
- [ ] Duplicate script names globally: exits 2.

## Known Iter 4a limitations (intentional)

- Tasks do not have a CLI entry point (`python main.py task FoxRunner Migrate` does not exist).
- No progress bar or live log tail; open the log file if you want details.
- No dependencies or sequencing between tasks; compose with `cmd /c "cmd1 && cmd2"` if needed.
- `Stop all` leaves running tasks untouched. Only `Exit` and `Stop all and exit` kill them.
- Tasks are in-memory; restarting the tray forgets all running tasks (and kills them on exit).

## Observed issues
<!-- Fill during run. -->

_None yet._
```

- [ ] **Step 2: Commit**

```bash
git add docs/manual-tests/iter4a.md
git commit -m "docs(iter4a): manual smoke test checklist for tasks + scripts"
```

Full message:
```
docs(iter4a): manual smoke test checklist for tasks + scripts

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Self-Review Summary

- **Spec coverage:**
  - `Task` and `Script` dataclasses + validation — Tasks 1 and 2.
  - Shared `spawn_with_log` helper — Task 3.
  - `logs.rotate_task` / `open_task_writer` with colon-safe filenames — Task 4.
  - `TaskManager` + `TaskAlreadyRunning` — Task 5.
  - Menu rendering with `Tasks ▸` / `Scripts ▸` submenus and "(running…)" state — Task 6.
  - `actions.on_run_task` / `on_run_script` — Task 7.
  - `on_exit` / `on_stop_all_and_exit` kill tasks — Task 8.
  - `TrayApp` integration + CLI wiring — Task 9.
  - Manual smoke — Task 10.
- **Placeholder scan:** no "TBD", no "similar to", no "add appropriate error handling". Every code block is complete.
- **Type consistency:**
  - `TaskManager.__init__(kill_tree, on_complete)` defined in Task 5; consumed by `TrayApp` in Task 9 with `kill_tree=process_manager.kill_tree`.
  - `Handlers.on_run_task: Callable[[Project, Task], None]` in Task 6; used by `_handlers()` in Task 9 and by `_project_submenu` action lambdas in Task 6.
  - `build_menu_items(cfg, active, statuses, handlers, running_tasks)` — 5th arg is `running_tasks: set[str]` — added in Task 6, consumed in Task 9.
  - `_TaskRunnerProtocol` in `actions.py` — defined in Task 7 with `.run / .is_running / .kill_all` — used by `on_run_task`, `on_run_script`, `on_exit`, `on_stop_all_and_exit`.
  - `paths.task_log_file(key)` — added in Task 4; consumed in Task 9's `_on_task_complete` error balloon.
- **Scope:** single iteration, single plan. Iter 4a deliberately excludes the other Iter 4 sub-iterations (single-instance, packaging, OS integration, explicit "Update" bundle) — those get their own specs.
- **Ordering:** Tasks 6–8 intentionally leave `tests/test_tray_app.py` transiently broken (same pattern used in Iter 3). Task 9 closes everything.
