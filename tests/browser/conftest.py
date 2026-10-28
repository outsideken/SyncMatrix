"""Serve web/ on a local port for the browser tests, and fail on console errors."""

import functools
import http.server
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="browser tests need pytest-playwright (requirements-dev.txt)")

WEB = Path(__file__).resolve().parents[2] / "web"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def base_url():
    """The page's address; overrides pytest-playwright's own base_url fixture."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                             functools.partial(QuietHandler, directory=str(WEB)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


@pytest.fixture
def errors(page):
    """Console errors and uncaught exceptions; tests assert this stays empty."""
    found = []
    page.on("console", lambda msg: found.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: found.append(str(exc)))
    return found
