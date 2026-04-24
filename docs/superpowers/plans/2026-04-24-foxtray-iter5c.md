# FoxTray Iter 5c (Log Retention + Open Log Files) Implementation Plan

**Goal:** Configurable log rotation depth + per-project-component "Open backend/frontend log" menu entries.

**Spec:** `docs/superpowers/specs/2026-04-24-foxtray-iter5c-design.md`.

---

## Task 1: `logs.rotate` accepts `keep` parameter + `Config.log_retention`

**Files:** `foxtray/logs.py`, `foxtray/config.py`, `foxtray/process.py`, `foxtray/cli.py`, `tests/test_logs.py`, `tests/test_config.py`, `tests/test_process.py`.

- [ ] **Step 1: Append tests to `tests/test_logs.py`**

```python
def test_rotate_with_keep_3_rotates_two_levels(tmp_appdata: Path) -> None:
    # Write some "current" content, rotate, repeat — verify X.log.1 and X.log.2
    first = logs.open_writer("X", "b")
    first.write("first\n")
    first.close()
    logs.rotate("X", "b", keep=3)
    second = logs.open_writer("X", "b")
    second.write("second\n")
    second.close()
    logs.rotate("X", "b", keep=3)
    third = logs.open_writer("X", "b")
    third.write("third\n")
    third.close()
    # Now X.log = "third", X.log.1 = "second", X.log.2 = "first"
    root = paths.appdata_root() / "logs"
    assert "first" in (root / "X_b.log.2").read_text(encoding="utf-8")
    assert "second" in (root / "X_b.log.1").read_text(encoding="utf-8")
    assert "third" in (root / "X_b.log").read_text(encoding="utf-8")


def test_rotate_with_keep_2_preserves_old_behavior(tmp_appdata: Path) -> None:
    first = logs.open_writer("X", "b")
    first.write("first\n")
    first.close()
    logs.rotate("X", "b", keep=2)
    second = logs.open_writer("X", "b")
    second.write("second\n")
    second.close()
    logs.rotate("X", "b", keep=2)
    # X.log.1 has "second", X.log.2 should NOT exist
    root = paths.appdata_root() / "logs"
    assert (root / "X_b.log.1").exists()
    assert "second" in (root / "X_b.log.1").read_text(encoding="utf-8")
    assert not (root / "X_b.log.2").exists()


def test_rotate_with_keep_1_is_noop(tmp_appdata: Path) -> None:
    fh = logs.open_writer("X", "b")
    fh.write("content\n")
    fh.close()
    logs.rotate("X", "b", keep=1)
    root = paths.appdata_root() / "logs"
    assert (root / "X_b.log").exists()
    assert not (root / "X_b.log.1").exists()
```

- [ ] **Step 2: Append tests to `tests/test_config.py`**

```python
def test_config_log_retention_defaults_to_2(tmp_path: Path) -> None:
    cfg = config.load(write_config(tmp_path, SAMPLE_YAML))
    assert cfg.log_retention == 2


def test_config_log_retention_accepts_positive_int(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n\nlog_retention: 5\n"
    cfg = config.load(write_config(tmp_path, yaml_body))
    assert cfg.log_retention == 5


def test_config_log_retention_rejects_zero(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n\nlog_retention: 0\n"
    with pytest.raises(config.ConfigError, match="log_retention"):
        config.load(write_config(tmp_path, yaml_body))


def test_config_log_retention_rejects_bool(tmp_path: Path) -> None:
    yaml_body = SAMPLE_YAML.rstrip() + "\n\nlog_retention: true\n"
    with pytest.raises(config.ConfigError, match="log_retention"):
        config.load(write_config(tmp_path, yaml_body))
```

- [ ] **Step 3: Append test to `tests/test_process.py`**

```python
def test_process_manager_passes_log_retention_to_rotate(
    tmp_appdata: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from foxtray import logs, process
    rotate_calls: list[tuple[str, str, int]] = []
    def _fake_rotate(project: str, component: str, keep: int = 2) -> None:
        rotate_calls.append((project, component, keep))
    monkeypatch.setattr(logs, "rotate", _fake_rotate)
    # Still need a valid log file writer
    monkeypatch.setattr(logs, "open_writer", lambda p, c: (tmp_path / "x.log").open("w"))
    # Spawn fails because command is bogus — but that's AFTER rotate is called
    def _fake_spawn(*args, **kwargs):
        raise RuntimeError("stop here")
    monkeypatch.setattr(process, "spawn_with_log", _fake_spawn)
    mgr = process.ProcessManager(log_retention=5)
    try:
        mgr.start(project="X", component="b", command=["x"], cwd=tmp_path)
    except RuntimeError:
        pass
    assert rotate_calls == [("X", "b", 5)]
```

- [ ] **Step 4: Run, confirm failures**

```
./.venv/Scripts/python.exe -m pytest tests/test_logs.py tests/test_config.py tests/test_process.py -v
```

- [ ] **Step 5: Update `foxtray/logs.py` `rotate()`**

Replace the existing `rotate` function body:

```python
def rotate(project: str, component: str, keep: int = 2) -> None:
    """Rotate X.log → X.log.1 → … → X.log.{keep-1}. Oldest is unlinked.

    keep <= 1 is a no-op (no rotation). keep == 2 = current + 1 backup
    (existing default behavior)."""
    if keep <= 1:
        return
    paths.ensure_dirs()
    current = paths.log_file(project, component)
    if not current.exists():
        return
    stem_dir = current.parent
    base = current.stem
    oldest = stem_dir / f"{base}.log.{keep - 1}"
    if oldest.exists():
        oldest.unlink()
    for i in range(keep - 2, 0, -1):
        src = stem_dir / f"{base}.log.{i}"
        dst = stem_dir / f"{base}.log.{i + 1}"
        if src.exists():
            src.rename(dst)
    current.rename(stem_dir / f"{base}.log.1")
```

Remove the old `_previous_path` helper if it's now unused, OR keep it (harmless).

- [ ] **Step 6: Update `foxtray/process.py`**

```python
class ProcessManager:
    def __init__(self, log_retention: int = 2) -> None:
        self._log_retention = log_retention

    def start(
        self, *, project: str, component: str, command: list[str], cwd: Path
    ) -> subprocess.Popen[bytes]:
        logs.rotate(project, component, keep=self._log_retention)
        return spawn_with_log(command, cwd, logs.open_writer(project, component))

    # kill_tree unchanged
```

- [ ] **Step 7: Extend `Config` dataclass and `load()` in `foxtray/config.py`**

```python
@dataclass(frozen=True)
class Config:
    projects: list[Project] = field(default_factory=list)
    scripts: tuple[Script, ...] = ()
    auto_start: str | None = None
    log_retention: int = 2
```

In `load()`, before the final `return Config(...)`:

```python
log_retention_raw = raw.get("log_retention", 2)
if not isinstance(log_retention_raw, int) or isinstance(log_retention_raw, bool) or log_retention_raw < 1:
    raise ConfigError(
        f"log_retention must be a positive integer, got {log_retention_raw!r}"
    )
```

Add `log_retention=log_retention_raw,` to the `Config(...)` constructor.

- [ ] **Step 8: Wire `log_retention` from CLI in `foxtray/cli.py`**

Update `_orchestrator`:
```python
def _orchestrator(cfg: config.Config) -> project.Orchestrator:
    return project.Orchestrator(
        manager=process.ProcessManager(log_retention=cfg.log_retention),
        cfg=cfg,
    )
```

Update `cmd_tray`:
```python
manager = process.ProcessManager(log_retention=cfg.log_retention)
```

- [ ] **Step 9: Run full suite — expect all green**

Note: existing tests instantiating `ProcessManager()` with no args still work (default 2).

- [ ] **Step 10: Commit**

```bash
git add foxtray/logs.py foxtray/process.py foxtray/config.py foxtray/cli.py tests/test_logs.py tests/test_config.py tests/test_process.py
git commit -m "feat(logs): configurable log_retention (default 2, unchanged behavior)"
```

Full message with Co-Authored-By.

---

## Task 2: `on_open_log` + menu entries

**Files:** `foxtray/ui/actions.py`, `foxtray/ui/tray.py`, `tests/test_tray_actions.py`, `tests/test_tray.py`.

- [ ] **Step 1: Append failing tests to `tests/test_tray_actions.py`**

```python
def test_on_open_log_opens_existing_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "some.log"
    log_path.write_text("content\n", encoding="utf-8")
    captured: list[Path] = []
    monkeypatch.setattr(actions, "_open_folder_native", captured.append)
    icon = _FakeIcon()
    actions.on_open_log(log_path, icon)
    assert captured == [log_path]
    assert icon.notifications == []


def test_on_open_log_notifies_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "missing.log"
    monkeypatch.setattr(actions, "_open_folder_native", lambda p: None)
    icon = _FakeIcon()
    actions.on_open_log(log_path, icon)
    assert any("No log yet" in message for _title, message in icon.notifications)
```

- [ ] **Step 2: Append failing tests to `tests/test_tray.py`**

```python
def test_menu_project_has_open_backend_log_entry() -> None:
    cfg = config.Config(projects=[_project("A")])
    items = tray.build_menu_items(
        cfg, None, {"A": _status()}, _noop_handlers(),
        running_tasks=set(),
    )
    submenu_texts = [s.text for s in items[0].submenu]
    assert "Open backend log" in submenu_texts
    assert "Open frontend log" in submenu_texts
```

Also update `_noop_handlers()` and `_noop_handlers_with_tasks()` in the file to include `on_open_log=lambda path: None`.

- [ ] **Step 3: Run, confirm failures**

- [ ] **Step 4: Add `on_open_log` to `foxtray/ui/actions.py`**

Append at end of file:

```python
def on_open_log(log_path: Path, icon: Notifier) -> None:
    try:
        if not log_path.exists():
            icon.notify(f"No log yet: {log_path.name}", title="FoxTray")
            return
        _open_folder_native(log_path)
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)
```

- [ ] **Step 5: Update `Handlers`, `_project_submenu`, `TrayApp._handlers` in `foxtray/ui/tray.py`**

Add field to `Handlers`:
```python
on_open_log: Callable[[Path], None]
```

In `_project_submenu`, add 2 entries between "Open frontend folder" and the existing Restart/Copy URL block. Specifically, update the list like this (insert after the 2nd and 3rd entries):

```python
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
    MenuItemSpec(
        text="Open backend log",
        action=lambda p=paths.log_file(project.name, "backend"): handlers.on_open_log(p),
    ),
    MenuItemSpec(
        text="Open frontend log",
        action=lambda p=paths.log_file(project.name, "frontend"): handlers.on_open_log(p),
    ),
]
```

(Then the existing conditional "Restart", "Copy URL", "Open project folder", "Tasks" entries stay after.)

Add `from foxtray import paths` to the imports near the top of `foxtray/ui/tray.py` if not already present.

Wire in `TrayApp._handlers`:
```python
on_open_log=lambda path: actions.on_open_log(path, icon),
```

- [ ] **Step 6: Run full suite — expect all green**

- [ ] **Step 7: Commit**

```bash
git add foxtray/ui/actions.py foxtray/ui/tray.py tests/test_tray_actions.py tests/test_tray.py
git commit -m "feat(ui/tray): Open backend/frontend log menu entries"
```

Full message with Co-Authored-By.

---

## Task 3: Manual smoke doc

**Files:** `docs/manual-tests/iter5c.md`.

Content:

```markdown
# FoxTray Iter 5c — Manual Test Log

Prerequisite: Iter 5b passed.

## Environment
- Date: <fill>
- HEAD: <commit sha>

## log_retention

- [ ] Add `log_retention: 3` at the top level of config.yaml.
- [ ] `python main.py start FoxRunner` then `stop`, then `start` again, then `stop`, then `start` once more. Each `start` rotates logs.
- [ ] Check `%APPDATA%\foxtray\logs\`: should have `FoxRunner_backend.log`, `FoxRunner_backend.log.1`, `FoxRunner_backend.log.2` (and similar for frontend).
- [ ] Set `log_retention: 1` and start a project: rotation is a no-op, old `.log.1` / `.log.2` linger on disk.

## Open backend log / Open frontend log

- [ ] Start FoxRunner, wait for a few seconds of log accumulation.
- [ ] Right-click → FoxRunner ▸ Open backend log. Notepad (or default .log editor) opens with Django runserver output.
- [ ] Same for Open frontend log.
- [ ] Stop FoxRunner. Delete the log file manually. Click Open backend log → balloon "No log yet: FoxRunner_backend.log".

## Observed issues
_None yet._
```

Commit:
```
docs(iter5c): manual smoke checklist
```

---

## Self-review

- Task 1 changes 7 files but all changes are orthogonal — tests pass as a unit.
- Task 2 adds 2 more `Handlers` fields (via 1 field `on_open_log`). Same update pattern as earlier iterations.
- No transient failures expected. All existing tests that construct `ProcessManager()` use default args and stay valid.
