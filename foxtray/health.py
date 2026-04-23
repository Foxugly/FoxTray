"""Port and HTTP health checks."""
from __future__ import annotations

import socket
import time

import requests


def port_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    with socket.socket() as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except OSError:
            return False
        return True


def http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException:
        return False
    return 200 <= response.status_code < 500


def wait_port_free(port: int, timeout: float = 10.0, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_listening(port):
            return True
        time.sleep(interval)
    return not port_listening(port)
