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
