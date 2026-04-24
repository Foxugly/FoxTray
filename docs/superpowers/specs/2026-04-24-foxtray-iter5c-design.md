# FoxTray Iter 5c — Log Retention + Open Log Files Design

## Goal

Two log-ergonomics features:

1. **Configurable rotation retention** — today's rotation keeps only `X.log` + `X.log.1` (2 files total). Add an optional top-level `log_retention: N` (default 2). Keeps current + (N-1) rotated backups named `X.log.1`, `X.log.2`, …, `X.log.{N-1}`.
2. **Open log file menu entries** — per-project submenu entries "Open backend log" and "Open frontend log" that open the respective `.log` file in the user's default `.log`/`.txt` editor (via `os.startfile`).

## Non-goals

- Size-based rotation (only count-based).
- Time-based retention.
- In-tray log viewer UI (tkinter window) — too much complexity for now.
- Task log rotation changes — tasks use `rotate_task` which stays at 2 deep.

## Architecture overview

### Log rotation

Move the hardcoded "1 backup" behavior in `foxtray/logs.py` into a parameter with a default of 2. The rotation algorithm shifts filenames backward: `X.log.{N-2}` → `X.log.{N-1}`, …, `X.log.1` → `X.log.2`, `X.log` → `X.log.1`. The oldest (`X.log.{N-1}`) is unlinked if it exists.

Config: new top-level `log_retention: int = 2` in `Config`. Passed into `ProcessManager` (or read from a module-level variable set by `cmd_*` before spawning — cleaner: pass to `ProcessManager.__init__`).

Actually, cleaner: make `logs.rotate(project, component, keep=2)` accept a `keep` kwarg. `ProcessManager.start` reads it from a field on ProcessManager (or passes it). Least intrusive: pass `keep` from `cmd_list`/`cmd_start`/`cmd_stop`/`cmd_tray` via a `LogConfig` dataclass, OR make `logs.rotate` consult a module-level `get_retention()` helper that reads from `config`.

**Decision:** keep it simple. `logs.rotate(project, component, keep=2)` gains a `keep` parameter defaulting to 2. `ProcessManager.__init__(keep=2)` stores and passes. `Orchestrator.__init__(manager, cfg)` wires `ProcessManager(keep=cfg.log_retention)` via the call sites. Where we already build `ProcessManager()` — `cli._orchestrator(cfg)` and `cli.cmd_tray` — read `cfg.log_retention`.

### Open log files

New menu entries in `_project_submenu`, right after "Open frontend folder":
- "Open backend log"
- "Open frontend log"

Implementation: `actions.on_open_log(log_path, icon)` → `os.startfile(log_path)` with a friendly balloon if the file doesn't exist yet (e.g., project never started).

## File structure

Modified:
- `foxtray/config.py` — `Config.log_retention: int = 2` + parsing/validation.
- `foxtray/logs.py` — `rotate(project, component, keep=2)` takes count.
- `foxtray/process.py` — `ProcessManager(log_retention=2)` stores + passes.
- `foxtray/project.py` — `Orchestrator.__init__` doesn't change (manager is already constructed by caller).
- `foxtray/cli.py` — `_orchestrator(cfg)` and `cmd_tray` build `ProcessManager(log_retention=cfg.log_retention)`.
- `foxtray/ui/actions.py` — `on_open_log(log_path, icon)`.
- `foxtray/ui/tray.py` — `Handlers.on_open_log`; `_project_submenu` adds 2 entries; `TrayApp._handlers` wires.
- `tests/test_config.py` — log_retention parsing.
- `tests/test_logs.py` — multi-level rotation.
- `tests/test_process.py` — ProcessManager passes keep through.
- `tests/test_tray.py` — menu entries present.
- `tests/test_tray_actions.py` — on_open_log behavior.

## Components

### `foxtray/logs.py`

```python
def rotate(project: str, component: str, keep: int = 2) -> None:
    """Rotate X.log → X.log.1 → X.log.2 → … → X.log.{keep-1}.
    
    Oldest rotated file is unlinked. If keep <= 1 or the current file does not
    exist, this is a no-op."""
    if keep <= 1:
        return
    paths.ensure_dirs()
    current = paths.log_file(project, component)
    if not current.exists():
        return
    stem_dir = current.parent
    base = current.stem
    # Remove the oldest (beyond keep-1)
    oldest = stem_dir / f"{base}.log.{keep - 1}"
    if oldest.exists():
        oldest.unlink()
    # Shift backward: X.log.{keep-2} → X.log.{keep-1}, …, X.log.1 → X.log.2
    for i in range(keep - 2, 0, -1):
        src = stem_dir / f"{base}.log.{i}"
        dst = stem_dir / f"{base}.log.{i + 1}"
        if src.exists():
            src.rename(dst)
    # X.log → X.log.1
    current.rename(stem_dir / f"{base}.log.1")
```

`rotate_task` stays as-is (no retention config).

### `foxtray/process.py`

```python
class ProcessManager:
    def __init__(self, log_retention: int = 2) -> None:
        self._log_retention = log_retention

    def start(
        self, *, project: str, component: str, command: list[str], cwd: Path
    ) -> subprocess.Popen[bytes]:
        logs.rotate(project, component, keep=self._log_retention)
        return spawn_with_log(command, cwd, logs.open_writer(project, component))
```

### `foxtray/config.py`

```python
@dataclass(frozen=True)
class Config:
    projects: list[Project] = field(default_factory=list)
    scripts: tuple[Script, ...] = ()
    auto_start: str | None = None
    log_retention: int = 2
```

In `load()`:
```python
log_retention_raw = raw.get("log_retention", 2)
if not isinstance(log_retention_raw, int) or isinstance(log_retention_raw, bool) or log_retention_raw < 1:
    raise ConfigError(
        f"log_retention must be a positive integer, got {log_retention_raw!r}"
    )
```

Add to `Config(...)` constructor.

### `foxtray/cli.py`

```python
def _orchestrator(cfg: config.Config) -> project.Orchestrator:
    return project.Orchestrator(
        manager=process.ProcessManager(log_retention=cfg.log_retention),
        cfg=cfg,
    )
```

`cmd_tray`:
```python
manager = process.ProcessManager(log_retention=cfg.log_retention)
```

### `foxtray/ui/actions.py`

```python
def on_open_log(log_path: Path, icon: Notifier) -> None:
    try:
        if not log_path.exists():
            icon.notify(f"No log yet: {log_path.name}", title="FoxTray")
            return
        _open_folder_native(log_path)  # os.startfile works on files too
    except Exception as exc:  # noqa: BLE001
        _notify_error(icon, exc)
```

### `foxtray/ui/tray.py`

`Handlers` gains:
```python
on_open_log: Callable[[Path], None]
```

`_project_submenu` adds these after "Open frontend folder":
```python
MenuItemSpec(
    text="Open backend log",
    action=lambda path=paths.log_file(project.name, "backend"): handlers.on_open_log(path),
),
MenuItemSpec(
    text="Open frontend log",
    action=lambda path=paths.log_file(project.name, "frontend"): handlers.on_open_log(path),
),
```

Wire in `TrayApp._handlers`:
```python
on_open_log=lambda path: actions.on_open_log(path, icon),
```

## Testing

Unit tests cover:
- `test_config.py` — `log_retention` defaults 2; accepts positive int; rejects 0, -1, bool, non-int.
- `test_logs.py` — 3-deep rotation: first rotate moves X.log → X.log.1; second moves X.log.1 → X.log.2, X.log → X.log.1; third (with keep=3) unlinks X.log.2.
- `test_process.py` — `ProcessManager(log_retention=5).start(...)` calls `logs.rotate` with `keep=5` (monkeypatch).
- `test_tray_actions.py` — `on_open_log` on existing file calls `_open_folder_native`; on missing file fires "No log yet" balloon.
- `test_tray.py` — project submenu has "Open backend log" and "Open frontend log" entries.

## Self-review

- Placeholder scan: clean.
- `keep=2` as default preserves existing behavior (one backup + current = 2 files).
- `rotate_task` stays unchanged — task logs are short-lived and don't need rotation tuning.
- `on_open_log` works on existing files and gives a friendly message when the file doesn't exist (e.g., never started).
