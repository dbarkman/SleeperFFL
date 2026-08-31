"""HTTP client for the Sleeper API.

Two hosts are in play:

* ``https://api.sleeper.app/v1`` — the documented read-only API.
* ``https://api.sleeper.app`` — undocumented ``/projections`` and ``/stats``
  endpoints. They carry the projected points and ADP that make the draft and
  waiver tooling worth anything, but being undocumented they can change or
  disappear without notice, so every caller treats them as best-effort.
"""

from __future__ import annotations

import random
import time
from typing import Any

import httpx

from .cache import Cache

BASE_V1 = "https://api.sleeper.app/v1"
BASE_ROOT = "https://api.sleeper.app"

MAX_ATTEMPTS = 5
BACKOFF_BASE = 1.0
BACKOFF_CAP = 30.0

# Sleeper warns about IP blocks past ~1000 calls/minute. We stay far under that,
# but a minimum spacing keeps a tight draft-poll loop honest.
MIN_INTERVAL = 0.05


class SleeperError(RuntimeError):
    pass


class SleeperClient:
    def __init__(self, cache: Cache, timeout: float = 20.0) -> None:
        self.cache = cache
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "sleeperffl/0.1 (personal league tool)"},
            follow_redirects=True,
        )
        self._last_call = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SleeperClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _sleep_until_allowed(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET with exponential backoff on 429 and 5xx.

        429 is never surfaced to the caller on the first hit — Sleeper throttles
        by IP and the right response is always to back off and retry.
        """
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            self._sleep_until_allowed()
            try:
                response = self._client.get(url, params=params)
                self._last_call = time.monotonic()
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if response.status_code == 200:
                    if not response.content:
                        return None
                    return response.json()
                if response.status_code == 404:
                    return None
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise SleeperError(
                        f"GET {url} failed: {response.status_code} {response.text[:200]}"
                    )
                last_error = SleeperError(f"GET {url} -> {response.status_code}")
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(float(retry_after), BACKOFF_CAP))
                    continue

            delay = min(BACKOFF_BASE * (2**attempt), BACKOFF_CAP)
            time.sleep(delay + random.uniform(0, delay * 0.1))

        raise SleeperError(f"GET {url} failed after {MAX_ATTEMPTS} attempts: {last_error}")

    # --- documented endpoints -------------------------------------------------

    def user(self, username_or_id: str) -> dict[str, Any] | None:
        return self.get(f"{BASE_V1}/user/{username_or_id}")

    def state(self, sport: str = "nfl") -> dict[str, Any]:
        return self.cache.fetch(
            f"state_{sport}", "state", lambda: self.get(f"{BASE_V1}/state/{sport}")
        )

    def leagues(self, user_id: str, season: str, sport: str = "nfl") -> list[dict[str, Any]]:
        return self.get(f"{BASE_V1}/user/{user_id}/leagues/{sport}/{season}") or []

    def league(self, league_id: str) -> dict[str, Any]:
        return self.cache.fetch(
            f"league_{league_id}", "league", lambda: self.get(f"{BASE_V1}/league/{league_id}")
        )

    def rosters(self, league_id: str) -> list[dict[str, Any]]:
        return self.cache.fetch(
            f"rosters_{league_id}",
            "rosters",
            lambda: self.get(f"{BASE_V1}/league/{league_id}/rosters") or [],
        )

    def league_users(self, league_id: str) -> list[dict[str, Any]]:
        return self.cache.fetch(
            f"users_{league_id}",
            "users",
            lambda: self.get(f"{BASE_V1}/league/{league_id}/users") or [],
        )

    def matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        return self.get(f"{BASE_V1}/league/{league_id}/matchups/{week}") or []

    def transactions(self, league_id: str, week: int) -> list[dict[str, Any]]:
        return self.get(f"{BASE_V1}/league/{league_id}/transactions/{week}") or []

    def draft(self, draft_id: str) -> dict[str, Any]:
        return self.get(f"{BASE_V1}/draft/{draft_id}")

    def draft_picks(self, draft_id: str) -> list[dict[str, Any]]:
        """Never cached — this is the live feed during a draft."""
        return self.get(f"{BASE_V1}/draft/{draft_id}/picks") or []

    def players(self, sport: str = "nfl") -> dict[str, Any]:
        """The full ~5MB player map. Sleeper asks for at most one call per day."""
        return self.cache.fetch(
            f"players_{sport}", "players", lambda: self.get(f"{BASE_V1}/players/{sport}") or {}
        )

    def trending(
        self, kind: str, sport: str = "nfl", lookback_hours: int = 24, limit: int = 100
    ) -> list[dict[str, Any]]:
        key = f"trending_{sport}_{kind}_{lookback_hours}_{limit}"
        return self.cache.fetch(
            key,
            "trending",
            lambda: self.get(
                f"{BASE_V1}/players/{sport}/trending/{kind}",
                params={"lookback_hours": lookback_hours, "limit": limit},
            )
            or [],
        )

    # --- undocumented endpoints -----------------------------------------------

    def season_projections(self, season: str, sport: str = "nfl") -> list[dict[str, Any]]:
        """Full-season projections, including redraft ADP (``adp_ppr`` et al)."""
        params = [("season_type", "regular")]
        for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
            params.append(("position[]", pos))
        return self.cache.fetch(
            f"proj_season_{sport}_{season}",
            "projections_season",
            lambda: self.get(f"{BASE_ROOT}/projections/{sport}/{season}", params=params) or [],
        )

    def week_projections(self, season: str, week: int, sport: str = "nfl") -> list[dict[str, Any]]:
        params = [("season_type", "regular")]
        for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
            params.append(("position[]", pos))
        return self.cache.fetch(
            f"proj_week_{sport}_{season}_{week}",
            "projections_week",
            lambda: self.get(f"{BASE_ROOT}/projections/{sport}/{season}/{week}", params=params)
            or [],
        )

    def schedule(self, season: str, sport: str = "nfl") -> list[dict[str, Any]]:
        """Regular-season game list. Bye weeks are derived from what is missing."""
        return self.cache.fetch(
            f"schedule_{sport}_{season}",
            "schedule",
            lambda: self.get(f"{BASE_ROOT}/schedule/{sport}/regular/{season}") or [],
        )

    def week_stats(self, season: str, week: int, sport: str = "nfl") -> list[dict[str, Any]]:
        params = [("season_type", "regular")]
        for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
            params.append(("position[]", pos))
        return self.cache.fetch(
            f"stats_week_{sport}_{season}_{week}",
            "stats_week",
            lambda: self.get(f"{BASE_ROOT}/stats/{sport}/{season}/{week}", params=params) or [],
        )
