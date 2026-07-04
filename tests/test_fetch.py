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


def test_fetch_usage_500_raises_fetch_error():
    with mock.patch.object(w.requests, "get", return_value=_resp(500)):
        with pytest.raises(w.FetchError):
            w.fetch_usage("tok")


def test_fetch_usage_network_error_raises_fetch_error():
    with mock.patch.object(w.requests, "get", side_effect=requests.ConnectionError("boom")):
        with pytest.raises(w.FetchError):
            w.fetch_usage("tok")
