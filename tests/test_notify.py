from __future__ import annotations

import httpx
import pytest
import respx

from sleeperffl.notify import Notifier

URL = "https://ntfy.example/dbdev-ffl"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("sleeperffl.notify.time.sleep", lambda _: None)


@respx.mock
def test_send_posts_title_and_body():
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    assert Notifier("https://ntfy.example", "dbdev-ffl").send("T", "body")
    request = route.calls[0].request
    assert request.headers["Title"] == "T"
    assert request.content == b"body"


@respx.mock
def test_token_is_sent_as_bearer():
    """A private server denies anonymous publishes, so the token must go out."""
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    Notifier("https://ntfy.example", "dbdev-ffl", token="tk_abc").send("T", "b")
    assert route.calls[0].request.headers["Authorization"] == "Bearer tk_abc"


@respx.mock
def test_no_auth_header_without_token():
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    Notifier("https://ntfy.example", "dbdev-ffl").send("T", "b")
    assert "Authorization" not in route.calls[0].request.headers


@respx.mock
def test_trailing_slash_on_server_is_handled():
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    assert Notifier("https://ntfy.example/", "dbdev-ffl").send("T", "b")
    assert route.call_count == 1


@respx.mock
def test_transient_429_is_retried():
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(429, content=b"slow down"), httpx.Response(200)]
    )
    assert Notifier("https://ntfy.example", "dbdev-ffl").send("T", "b")
    assert route.call_count == 2


@respx.mock
def test_quota_429_is_not_retried():
    """A daily quota will not clear by hammering it — report and move on."""
    body = b'{"code":42908,"error":"limit reached: daily message quota reached"}'
    route = respx.post(URL).mock(return_value=httpx.Response(429, content=body))
    assert not Notifier("https://ntfy.example", "dbdev-ffl").send("T", "b")
    assert route.call_count == 1


@respx.mock
def test_server_error_is_retried_then_gives_up():
    route = respx.post(URL).mock(return_value=httpx.Response(503))
    assert not Notifier("https://ntfy.example", "dbdev-ffl").send("T", "b")
    assert route.call_count == 4


@respx.mock
def test_403_is_not_retried():
    route = respx.post(URL).mock(return_value=httpx.Response(403))
    assert not Notifier("https://ntfy.example", "dbdev-ffl").send("T", "b")
    assert route.call_count == 1


@respx.mock
def test_network_error_is_retried():
    route = respx.post(URL).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200)]
    )
    assert Notifier("https://ntfy.example", "dbdev-ffl").send("T", "b")
    assert route.call_count == 2


def test_disabled_notifier_never_sends():
    assert not Notifier("https://ntfy.example", "t", enabled=False).send("T", "b")
