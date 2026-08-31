"""Small TTL disk cache so we stay well under Sleeper's rate limit.

The player map alone is ~5MB and Sleeper explicitly asks that it be fetched at
most once a day, so anything that is expensive or slow-moving lands here.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

# Seconds. Keyed by logical resource name, not URL.
TTL = {
    "players": 24 * 60 * 60,
    "projections_season": 6 * 60 * 60,
    "projections_week": 60 * 60,
    "stats_week": 30 * 60,
    "league": 5 * 60,
    "rosters": 5 * 60,
    "users": 60 * 60,
    "trending": 30 * 60,
    "state": 15 * 60,
    "schedule": 7 * 24 * 60 * 60,
}

DEFAULT_TTL = 5 * 60


class Cache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.replace("/", "_").replace(":", "_")
        return self.root / f"{safe}.json"

    def age(self, key: str) -> float | None:
        """Seconds since this key was written, or None if it is not cached."""
        path = self._path(key)
        if not path.exists():
            return None
        return time.time() - path.stat().st_mtime

    def get(self, key: str, ttl: float) -> Any | None:
        age = self.age(key)
        if age is None or age > ttl:
            return None
        try:
            return json.loads(self._path(key).read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def set(self, key: str, value: Any) -> None:
        path = self._path(key)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(value))
        tmp.replace(path)

    def fetch(self, key: str, kind: str, loader: Callable[[], Any]) -> Any:
        """Return the cached value for `key`, calling `loader` on a miss.

        Falls back to stale cached data if the loader raises, so a transient
        Sleeper outage during a live draft degrades instead of crashing.
        """
        ttl = TTL.get(kind, DEFAULT_TTL)
        hit = self.get(key, ttl)
        if hit is not None:
            return hit
        try:
            value = loader()
        except Exception:
            stale = self.get(key, float("inf"))
            if stale is not None:
                return stale
            raise
        self.set(key, value)
        return value
