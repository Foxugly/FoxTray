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
