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
