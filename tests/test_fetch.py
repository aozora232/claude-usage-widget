from unittest import mock

import pytest
import requests

import claude_usage_widget as w


def _resp(status: int, payload: dict | None = None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = payload or {}
    return r


def test_fetch_usage_success():
    with mock.patch.object(w.requests, "get", return_value=_resp(200, {"five_hour": {}})) as g:
        data = w.fetch_usage("tok")
    assert data == {"five_hour": {}}
    _, kwargs = g.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["headers"]["anthropic-beta"] == "oauth-2025-04-20"


def test_fetch_usage_401_raises_token_expired():
    with mock.patch.object(w.requests, "get", return_value=_resp(401)):
        with pytest.raises(w.TokenExpiredError):
            w.fetch_usage("tok")


def test_fetch_usage_429_raises_rate_limit_error():
    with mock.patch.object(w.requests, "get", return_value=_resp(429)):
        with pytest.raises(w.RateLimitError):
            w.fetch_usage("tok")


def test_rate_limit_error_is_fetch_error_subclass():
    # 既存の except FetchError で漏れなく捕捉できること(専用exceptを先に書く前提)
    assert issubclass(w.RateLimitError, w.FetchError)


def test_fetch_usage_500_raises_fetch_error():
    with mock.patch.object(w.requests, "get", return_value=_resp(500)):
        with pytest.raises(w.FetchError):
            w.fetch_usage("tok")


def test_fetch_usage_network_error_raises_fetch_error():
    with mock.patch.object(w.requests, "get", side_effect=requests.ConnectionError("boom")):
        with pytest.raises(w.FetchError):
            w.fetch_usage("tok")


def test_fetch_usage_invalid_json_raises_fetch_error():
    r = _resp(200)
    r.json.side_effect = ValueError("no json")
    with mock.patch.object(w.requests, "get", return_value=r):
        with pytest.raises(w.FetchError):
            w.fetch_usage("tok")
