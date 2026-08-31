from __future__ import annotations

import httpx
import pytest
import respx

from sleeperffl.api import BASE_V1, SleeperClient, SleeperError
from sleeperffl.cache import Cache


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Never actually sleep during backoff tests.
    monkeypatch.setattr("sleeperffl.api.time.sleep", lambda _: None)
    with SleeperClient(Cache(tmp_path)) as c:
        yield c


@respx.mock
def test_get_returns_parsed_json(client):
    respx.get(f"{BASE_V1}/user/dbdev").mock(
        return_value=httpx.Response(200, json={"user_id": "1"})
    )
    assert client.user("dbdev") == {"user_id": "1"}


@respx.mock
def test_404_returns_none_rather_than_raising(client):
    respx.get(f"{BASE_V1}/user/nobody").mock(return_value=httpx.Response(404))
    assert client.user("nobody") is None


@respx.mock
def test_429_is_retried_with_backoff_not_raised(client):
    """Sleeper throttles by IP; backing off is always the right response."""
    route = respx.get(f"{BASE_V1}/user/dbdev").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(200, json={"user_id": "1"}),
        ]
    )
    assert client.user("dbdev") == {"user_id": "1"}
    assert route.call_count == 3


@respx.mock
def test_429_honours_retry_after_header(client):
    route = respx.get(f"{BASE_V1}/user/dbdev").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    assert client.user("dbdev") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_server_errors_are_retried(client):
    route = respx.get(f"{BASE_V1}/user/dbdev").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    assert client.user("dbdev") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_gives_up_after_the_attempt_limit(client):
    respx.get(f"{BASE_V1}/user/dbdev").mock(return_value=httpx.Response(429))
    with pytest.raises(SleeperError, match="after 5 attempts"):
        client.user("dbdev")


@respx.mock
def test_client_errors_raise_immediately(client):
    route = respx.get(f"{BASE_V1}/user/dbdev").mock(return_value=httpx.Response(400))
    with pytest.raises(SleeperError):
        client.user("dbdev")
    assert route.call_count == 1


@respx.mock
def test_network_errors_are_retried(client):
    route = respx.get(f"{BASE_V1}/user/dbdev").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={"ok": True})]
    )
    assert client.user("dbdev") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_repeated_reads_hit_the_cache_not_the_network(client):
    route = respx.get(f"{BASE_V1}/league/L1").mock(
        return_value=httpx.Response(200, json={"name": "x"})
    )
    client.league("L1")
    client.league("L1")
    assert route.call_count == 1


@respx.mock
def test_draft_picks_are_never_cached(client):
    """The pick feed is the one thing that must be live during a draft."""
    route = respx.get(f"{BASE_V1}/draft/D1/picks").mock(
        return_value=httpx.Response(200, json=[])
    )
    client.draft_picks("D1")
    client.draft_picks("D1")
    assert route.call_count == 2


@respx.mock
def test_stale_cache_is_served_when_sleeper_goes_down(client):
    """A mid-draft outage should degrade, not crash."""
    route = respx.get(f"{BASE_V1}/league/L1").mock(
        return_value=httpx.Response(200, json={"name": "x"})
    )
    assert client.league("L1")["name"] == "x"

    # Expire the entry, then make the network fail.
    client.cache.set("league_L1", {"name": "x"})
    import os, time as _t
    path = client.cache._path("league_L1")
    old = _t.time() - 99999
    os.utime(path, (old, old))
    route.mock(return_value=httpx.Response(500))

    assert client.league("L1")["name"] == "x"
