from __future__ import annotations

import json

import httpx
import pytest
import respx

from sleeperffl.notify import Notifier

SERVER = "https://ntfy.example"
URL = "https://ntfy.example/"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("sleeperffl.notify.time.sleep", lambda _: None)


def _body(route, index=0):
    return json.loads(route.calls[index].request.content)


@respx.mock
def test_send_publishes_json_to_the_server_root():
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    assert Notifier(SERVER, "dbdev-ffl").send("T", "body", priority="high", tags="football,warning")
    body = _body(route)
    assert body == {
        "topic": "dbdev-ffl",
        "title": "T",
        "message": "body",
        "priority": 4,
        "tags": ["football", "warning"],
    }


@respx.mock
def test_non_ascii_title_and_message_are_delivered_intact():
    """Headers are ASCII-only; this is why the payload travels as JSON."""
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    title = "OUT: Breece Hall (RB - NYJ) — your player"
    message = "Swap in Kaʻimi Fairbairn — São Paulo café"
    assert Notifier(SERVER, "dbdev-ffl").send(title, message)
    body = _body(route)
    assert body["title"] == title
    assert body["message"] == message
    assert "Title" not in route.calls[0].request.headers


@respx.mock
def test_click_url_is_included_when_given():
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    Notifier(SERVER, "t").send("T", "b", click="https://sleeper.com/x")
    assert _body(route)["click"] == "https://sleeper.com/x"


@respx.mock
def test_unknown_priority_falls_back_to_default():
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    Notifier(SERVER, "t").send("T", "b", priority="whatever")
    assert _body(route)["priority"] == 3


@respx.mock
def test_token_is_sent_as_bearer():
    """A private server denies anonymous publishes, so the token must go out."""
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    Notifier(SERVER, "dbdev-ffl", token="tk_abc").send("T", "b")
    assert route.calls[0].request.headers["Authorization"] == "Bearer tk_abc"


@respx.mock
def test_no_auth_header_without_token():
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    Notifier(SERVER, "dbdev-ffl").send("T", "b")
    assert "Authorization" not in route.calls[0].request.headers


@respx.mock
def test_trailing_slash_on_server_is_handled():
    route = respx.post(URL).mock(return_value=httpx.Response(200))
    assert Notifier(SERVER + "/", "dbdev-ffl").send("T", "b")
    assert route.call_count == 1


@respx.mock
def test_transient_429_is_retried():
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(429, content=b"slow down"), httpx.Response(200)]
    )
    assert Notifier(SERVER, "dbdev-ffl").send("T", "b")
    assert route.call_count == 2


@respx.mock
def test_quota_429_is_not_retried():
    """A daily quota will not clear by hammering it — report and move on."""
    body = b'{"code":42908,"error":"limit reached: daily message quota reached"}'
    route = respx.post(URL).mock(return_value=httpx.Response(429, content=body))
    assert not Notifier(SERVER, "dbdev-ffl").send("T", "b")
    assert route.call_count == 1


@respx.mock
def test_server_error_is_retried_then_gives_up():
    route = respx.post(URL).mock(return_value=httpx.Response(503))
    assert not Notifier(SERVER, "dbdev-ffl").send("T", "b")
    assert route.call_count == 4


@respx.mock
def test_403_is_not_retried():
    route = respx.post(URL).mock(return_value=httpx.Response(403))
    assert not Notifier(SERVER, "dbdev-ffl").send("T", "b")
    assert route.call_count == 1


@respx.mock
def test_network_error_is_retried():
    route = respx.post(URL).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200)]
    )
    assert Notifier(SERVER, "dbdev-ffl").send("T", "b")
    assert route.call_count == 2


def test_unexpected_error_returns_false_instead_of_raising(monkeypatch):
    """One bad alert must never abort the rest of a watcher run."""
    def explode(*args, **kwargs):
        raise UnicodeEncodeError("ascii", "—", 0, 1, "boom")
    monkeypatch.setattr("sleeperffl.notify.httpx.post", explode)
    assert Notifier(SERVER, "t").send("T", "b") is False


def test_disabled_notifier_never_sends():
    assert not Notifier(SERVER, "t", enabled=False).send("T", "b")
