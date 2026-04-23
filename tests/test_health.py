import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from foxtray import health


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def tcp_server():
    port = _free_port()
    server = socket.socket()
    server.bind(("127.0.0.1", port))
    server.listen(1)
    yield port
    server.close()


def test_port_listening_true_when_socket_open(tcp_server: int) -> None:
    assert health.port_listening(tcp_server) is True


def test_port_listening_false_when_nothing_there() -> None:
    assert health.port_listening(_free_port()) is False


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args, **kwargs) -> None:
        pass


@pytest.fixture
def http_server():
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _OkHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


def test_http_ok_true_on_200(http_server: int) -> None:
    assert health.http_ok(f"http://127.0.0.1:{http_server}/") is True


def test_http_ok_false_on_connection_refused() -> None:
    assert health.http_ok(f"http://127.0.0.1:{_free_port()}/") is False


def test_wait_port_free_returns_true_when_already_free() -> None:
    assert health.wait_port_free(_free_port(), timeout=1.0) is True


def test_wait_port_free_returns_false_when_still_listening(tcp_server: int) -> None:
    start = time.monotonic()
    assert health.wait_port_free(tcp_server, timeout=0.3) is False
    assert time.monotonic() - start >= 0.3
