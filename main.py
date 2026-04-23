"""Entry point: ``python main.py <command>``."""
from __future__ import annotations

import sys

from foxtray import cli


if __name__ == "__main__":
    sys.exit(cli.main())
