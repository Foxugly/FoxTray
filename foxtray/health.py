"""Port and HTTP health checks."""
from __future__ import annotations

import socket
import time

import requests


def port_listening(port: int, host: str | None = None, timeout: float = 0.3) -> bool:
    """Check whether the given port is bound on localhost.

    When host is None (default), try IPv4 127.0.0.1 and IPv6 ::1 in order and
    return True if EITHER responds. Some dev servers (recent Angular, Vite)
    bind IPv6-only even when the URL says "localhost", so a 127.0.0.1-only
    probe incorrectly reports "not listening" while the HTTP URL works.

    When host is set explicitly (e.g., to check a remote or a specific
    family), only that host is probed.
    """
    if host is not None:
        return _probe(host, port, timeout)
    # Default: IPv4 first (the common case), then IPv6.
    return _probe("127.0.0.1", port, timeout) or _probe("::1", port, timeout)


def _probe(host: str, port: int, timeout: float) -> bool:
    # socket.AF_INET6 is required for "::1", AF_INET for "127.0.0.1".
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
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
