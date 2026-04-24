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
