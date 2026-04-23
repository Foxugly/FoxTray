"""Test helper: spawn a grandchild then sleep, so kill_tree has a real tree to reap."""
from __future__ import annotations

import subprocess
import sys
import time

if __name__ == "__main__":
    grandchild = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
    )
    print(grandchild.pid, flush=True)
    time.sleep(120)
