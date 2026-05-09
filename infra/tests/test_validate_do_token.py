"""Unit tests for validate_do_token — the only live-validation step."""

from io import BytesIO
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest

from setup import InvalidToken, NetworkError, validate_do_token


def _ok_response():
    """Mimic a successful urllib response context manager."""
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: False
    return resp


def test_200_response_does_not_raise(monkeypatch):
    monkeypatch.setattr("setup.urllib.request.urlopen", lambda *a, **kw: _ok_response())
    validate_do_token("dop_v1_real-looking-token")  # should not raise


def test_401_raises_invalid_token(monkeypatch):
    def fake_urlopen(*a, **kw):
        raise HTTPError(
            url="https://api.digitalocean.com/v2/account",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b""),
        )

    monkeypatch.setattr("setup.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(InvalidToken):
        validate_do_token("bad-token")


def test_other_http_error_is_network_error(monkeypatch):
    """5xx etc. should be treated as ambiguous, not as 'token is bad'."""

    def fake_urlopen(*a, **kw):
        raise HTTPError(
            url="https://api.digitalocean.com/v2/account",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=BytesIO(b""),
        )

    monkeypatch.setattr("setup.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(NetworkError):
        validate_do_token("dop_v1_real-looking-token")


def test_url_error_is_network_error(monkeypatch):
    def fake_urlopen(*a, **kw):
        raise URLError("nodename nor servname provided")

    monkeypatch.setattr("setup.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(NetworkError):
        validate_do_token("dop_v1_real-looking-token")


def test_timeout_is_network_error(monkeypatch):
    def fake_urlopen(*a, **kw):
        raise TimeoutError("timed out")

    monkeypatch.setattr("setup.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(NetworkError):
        validate_do_token("dop_v1_real-looking-token")
