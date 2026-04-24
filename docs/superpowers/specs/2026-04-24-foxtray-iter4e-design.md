# FoxTray Iter 4e — "Update" Bundled Action Design (Skeleton)

> **Status:** design outline only. Also marked as potentially **redundant** with Iter 4a (per-project tasks + scripts) — the user can already compose an "Update" sequence via `tasks:` + `scripts:` manually. Revisit whether a built-in is worth the complexity before writing the plan.

## Goal

A single menu click on a project runs the standard "pull latest + install deps + migrate" sequence in order, with progress balloons and stop-on-first-failure semantics. Typical sequence:

1. `git pull --rebase` (in project root, or backend / frontend paths).
2. `pip install -r requirements.txt` (backend venv).
3. `npm install` (frontend).
4. `python manage.py migrate` (backend).

## Non-goals (for Iter 4e)

- Dry-run / preview mode — it just runs.
- Rollback on failure — if step 3 fails, user must diagnose manually.
- Update for individual components (backend only, frontend only) — one atomic "Update" per project. A user wanting granular control uses Iter 4a tasks.
- Scheduled/background updates — always user-initiated.
- Cross-project dependency updates (e.g., "Update All") — could be trivial follow-up, not in this spec.

## Alternatives and the case for **not** doing this

Iter 4a's `tasks:` + `scripts:` already let the user wire:

```yaml
- name: FoxRunner
  tasks:
    - name: "Update: git pull"
      cwd: backend
      command: git pull --rebase
    - name: "Update: pip install"
      cwd: backend
      command: python -m pip install -r requirements.txt
    - name: "Update: npm install"
      cwd: frontend
      command: npm install
    - name: "Update: migrate"
      cwd: backend
      command: python manage.py migrate
```

And click them in order. This works today. Iter 4e's only added value is:
- **Sequencing**: run 1-4 in order, stop on failure. User-as-orchestrator is manual.
- **Single click**: reduces cognitive load for "I just want to update everything".

If you want **neither** sequencing-auto nor single-click-convenience, Iter 4a covers it. This spec is only worth implementing if the user confirms they want the sequencing + single-click.

## Architecture overview (if we proceed)

Reuse `TaskManager` from Iter 4a for the actual process execution, and layer sequencing on top.

### `UpdateSequence` class

New `foxtray/update.py`:

```python
@dataclass(frozen=True)
class UpdateStep:
    name: str  # "git pull", "pip install", …
    cwd: Path
    command: list[str]

@dataclass(frozen=True)
class UpdateSequence:
    project_name: str
    steps: tuple[UpdateStep, ...]


def plan_update(project: config.Project) -> UpdateSequence:
    """Build the default 4-step sequence for a project."""
    return UpdateSequence(
        project_name=project.name,
        steps=(
            UpdateStep("git pull (backend)", project.backend.path, ["git", "pull", "--rebase"]),
            UpdateStep(
                "pip install",
                project.backend.path,
                [str(project.backend.python_executable), "-m", "pip", "install", "-r", "requirements.txt"],
            ),
            UpdateStep("npm install", project.frontend.path, ["npm", "install"]),
            UpdateStep(
                "migrate",
                project.backend.path,
                [str(project.backend.python_executable), "manage.py", "migrate"],
            ),
        ),
    )
```

Optional YAML override later (e.g., `project.update: []` with custom steps).

### Sequencer state machine

`UpdateRunner`:
- Holds a `TaskManager` reference + a queue of steps for one project.
- `start(sequence)`: validates no running update for this project; kicks off step 1 via `task_manager.run`.
- `_on_step_complete(key, exit_code)`: if exit_code 0, spawn next step; if non-zero, stop and fire final balloon "⚠ Update <project>: failed at <step>".
- Callback pipes through an `on_update_complete(project_name, ok, failed_step: str | None)` hook back to TrayApp.

Key format: `update:{project}:{step_name}` so `TaskManager` treats them as distinct keys (no collision with regular tasks).

### Menu integration

Each project submenu gets an `Update ▸` entry (or a single `Update` action that confirms "Update FoxRunner?" via MessageBox first).

Proposed UX: single `Update` entry per project that runs the sequence silently, with balloons at each step:
- "FoxRunner update: git pull done"
- "FoxRunner update: pip install done"
- "FoxRunner update: npm install done"
- "FoxRunner update: migrate done"
- "✓ FoxRunner update complete"

On failure:
- "⚠ FoxRunner update: failed at npm install — see logs"
- Subsequent steps NOT run.

### Concurrency

One update per project at a time. Two projects can update in parallel (independent Popens).

`UpdateRunner` tracks `_active: dict[project_name, UpdateSequence]`. Clicking Update on a project with an active update → balloon "FoxRunner update already running".

### Failure handling

- Step's Popen exits non-zero: sequence stops, balloon fires, `_active` entry removed.
- Step's spawn raises (e.g., `ExecutableNotFound`): same as non-zero exit — balloon + stop.
- User clicks `Stop all and exit` mid-update: `TaskManager.kill_all()` terminates the current step. No restart logic.

## Open questions (for brainstorming, if we proceed)

1. **Is this actually worth building given Iter 4a covers 90% of it?** If yes, main value is sequencing + single-click.
2. **Per-project step customization?** If FoxRunner needs `poetry install` instead of `pip install`, how do we express that? Options: YAML `update:` override, or ditch the built-in entirely and let the user compose via tasks.
3. **Confirmation dialog before update?** MessageBox "About to update FoxRunner. Continue?" — safer, but one more click.
4. **Progress balloons at each step vs single final balloon?** Leaning per-step for visibility.
5. **Log files: one per step or combined?** One per step reuses `TaskManager`'s existing per-key log. Combined would need a new log rotation helper.
6. **What about stop-active-project-before-update?** Updating Django deps while Django is running might cause issues. Option A: refuse to update if project is active. Option B: auto-stop, update, auto-restart. Option C: let the user decide (don't touch project state).
7. **`git pull` with uncommitted changes?** Fails. Accept and surface to user. Or pre-check `git status` and refuse with a friendly message.

## File structure (anticipated)

New files:
- `foxtray/update.py` — `UpdateStep`, `UpdateSequence`, `UpdateRunner`.
- `tests/test_update.py`.
- `docs/manual-tests/iter4e.md`.

Modified files:
- `foxtray/config.py` — optional `project.update: []` to override default steps.
- `foxtray/ui/tray.py` — per-project `Update` menu entry; `Handlers.on_update`.
- `foxtray/ui/actions.py` — `on_update`.

## Recommendation

**Defer until Iter 4a has been used in anger for a few weeks.** If the user finds themselves manually clicking Update-git-pull → Update-pip-install → Update-npm-install → Update-migrate regularly, come back and build Iter 4e. If the manual sequence is tolerable, skip this iteration entirely.

## Next step

Before a plan, confirm with the user:
- Yes, worth building.
- Answer questions 2-7 above (step customization, confirmation, logs, project-state interaction).

Then write the plan.
