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
    was_active = state.load().active is not None and state.load().active.name == args.name
    _orchestrator().stop(args.name)
    if was_active:
        print(f"Stopped {args.name}")
    else:
        print(f"{args.name} was not active; nothing to stop")
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
    except process.ExecutableNotFound as exc:
        print(f"Cannot launch subprocess: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Cannot open config: {exc}", file=sys.stderr)
        return 2
    except config.ProjectNotFound as exc:
        print(f"Unknown project: {exc.args[0]}", file=sys.stderr)
        return 2
