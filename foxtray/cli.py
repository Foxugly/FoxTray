"""CLI command implementations for FoxTray."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from foxtray import config, paths, process, project, singleton, state
from foxtray.ui import tray as tray_module

log = logging.getLogger(__name__)

def _default_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config.yaml"
    return Path(__file__).resolve().parent.parent / "config.yaml"


CONFIG_PATH = _default_config_path()


def _bootstrap_file_handler() -> logging.Handler:
    last_exc: OSError | None = None
    for path in paths.bootstrap_log_candidates():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return logging.FileHandler(path, encoding="utf-8")
        except OSError as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("No bootstrap log path candidates available")


def _configure_logging() -> None:
    paths.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            _bootstrap_file_handler(),
        ],
        force=True,
    )


def _orchestrator(cfg: config.Config) -> project.Orchestrator:
    return project.Orchestrator(manager=process.ProcessManager(log_retention=cfg.log_retention), cfg=cfg)


def cmd_list(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    orchestrator = _orchestrator(cfg)
    for proj in cfg.projects:
        status = orchestrator.status(proj)
        label = "RUNNING" if status.running else "stopped"
        print(f"{proj.name:<20} {label}")
    return 0


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


def cmd_stop(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    cfg.get(args.name)  # validates name exists
    was_active = state.load().active is not None and state.load().active.name == args.name
    _orchestrator(cfg).stop(args.name)
    if was_active:
        print(f"Stopped {args.name}")
    else:
        print(f"{args.name} was not active; nothing to stop")
    return 0


def cmd_stop_all(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    _orchestrator(cfg).stop_all()
    print("Stopped all")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    proj = cfg.get(args.name)
    status = _orchestrator(cfg).status(proj)
    print(f"name:               {status.name}")
    print(f"running:            {status.running}")
    print(f"backend alive:      {status.backend_alive}")
    print(f"frontend alive:     {status.frontend_alive}")
    print(f"backend port open:  {status.backend_port_listening}")
    print(f"frontend port open: {status.frontend_port_listening}")
    print(f"url responds:       {status.url_ok}")
    return 0


def cmd_tray(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    try:
        singleton.acquire_lock()
    except singleton.LockHeldError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    try:
        manager = process.ProcessManager(log_retention=cfg.log_retention)
        orchestrator = project.Orchestrator(manager=manager, cfg=cfg)
        tray_module.TrayApp(cfg, orchestrator, manager, args.config).run()
    finally:
        singleton.release_lock()
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        cfg = config.load(args.config)
    except config.ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    issues: list[str] = []
    for proj in cfg.projects:
        if not proj.backend.path.exists():
            issues.append(f"{proj.name}: backend.path does not exist: {proj.backend.path}")
        elif not proj.backend.python_executable.exists():
            issues.append(
                f"{proj.name}: backend venv python missing: {proj.backend.python_executable}"
            )
        if proj.frontend is not None and not proj.frontend.path.exists():
            issues.append(f"{proj.name}: frontend.path does not exist: {proj.frontend.path}")
        if proj.path_root is not None and not proj.path_root.exists():
            issues.append(f"{proj.name}: path_root does not exist: {proj.path_root}")
    for script in cfg.scripts:
        if not script.path.exists():
            issues.append(f"script {script.name!r}: path does not exist: {script.path}")

    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 2
    print(f"Config OK: {len(cfg.projects)} project(s), {len(cfg.scripts)} script(s)")
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

    sub.add_parser(
        "tray", help="Run FoxTray as a Windows tray icon"
    ).set_defaults(func=cmd_tray)

    sub.add_parser(
        "validate",
        help="Validate config.yaml — paths, venvs, script targets",
    ).set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None and getattr(sys, "frozen", False) and len(sys.argv) == 1:
        argv = ["tray"]
    _configure_logging()
    args = build_parser().parse_args(argv)
    log.info("FoxTray starting command=%s config=%s frozen=%s", args.command, args.config, getattr(sys, "frozen", False))
    state.clear_if_orphaned()
    try:
        rc = args.func(args)
        if rc != 0:
            log.error("FoxTray command failed command=%s exit_code=%s", args.command, rc)
        return rc
    except config.ConfigError as exc:
        log.exception("Config error during startup")
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except process.PortInUse as exc:
        log.exception("Port in use during startup")
        print(f"Port in use: {exc}", file=sys.stderr)
        return 2
    except process.ExecutableNotFound as exc:
        log.exception("Executable not found during startup")
        print(f"Cannot launch subprocess: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        log.exception("OS error during startup")
        print(f"Cannot open config: {exc}", file=sys.stderr)
        return 2
    except config.ProjectNotFound as exc:
        log.exception("Unknown project during startup")
        print(f"Unknown project: {exc.args[0]}", file=sys.stderr)
        return 2
