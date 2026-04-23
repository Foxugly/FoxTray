"""Port and HTTP health checks."""
from __future__ import annotations

import socket
import time

import requests


def port_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    """Return True if the given port is bound/listening on *host*.

    Uses a bind-based probe so that the check is reliable on Windows loopback
    even when the server's accept-backlog is full (a TCP-connect probe would
    time out rather than succeed in that case, giving a false negative).
    The *timeout* parameter is accepted for API compatibility but is unused
    by the bind probe itself, which is instantaneous.
    """
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return False  # bind succeeded → nothing is using that port
        except OSError:
            return True   # bind failed → port is already in use


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
