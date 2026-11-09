"""Tests for scripts/fetch_tles.py's retrying GET (no network: urlopen is faked)."""

import http.client
import io
import sys
import urllib.error

import pytest

from paths import REPO

sys.path.insert(0, str(REPO / "scripts"))
import fetch_tles as ft  # noqa: E402


def fake_urlopen(monkeypatch, outcomes):
    """Make urlopen raise or return each outcome in turn; returns the call log."""
    calls = []

    def urlopen(request, timeout):
        calls.append(request.full_url)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return io.BytesIO(outcome.encode())

    monkeypatch.setattr(ft.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ft.time, "sleep", lambda seconds: None)
    return calls


@pytest.mark.parametrize("error", [
    TimeoutError("The read operation timed out"),     # 2026-11-09 refresh failure
    ConnectionResetError("reset by peer"),
    http.client.IncompleteRead(b"[{"),
    urllib.error.URLError("connect timed out"),
    urllib.error.HTTPError("u", 503, "busy", {}, None),
])
def test_transient_failures_are_retried(monkeypatch, error):
    calls = fake_urlopen(monkeypatch, [error, "[]"])
    assert ft.get("https://example.test/x") == "[]"
    assert len(calls) == 2


def test_client_errors_are_not_retried(monkeypatch):
    calls = fake_urlopen(monkeypatch, [urllib.error.HTTPError("u", 404, "missing", {}, None)])
    with pytest.raises(urllib.error.HTTPError):
        ft.get("https://example.test/x")
    assert len(calls) == 1


def test_gives_up_after_the_last_try(monkeypatch):
    calls = fake_urlopen(monkeypatch, [TimeoutError()] * 4)
    with pytest.raises(TimeoutError):
        ft.get("https://example.test/x", tries=4)
    assert len(calls) == 4
