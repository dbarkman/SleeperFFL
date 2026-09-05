"""Runtime configuration, read from the environment with sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SLEEPER_USERNAME = "dbdev"
SPORT = "nfl"


def _cache_root() -> Path:
    override = os.environ.get("SLEEPERFFL_CACHE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "sleeperffl"


def _state_root() -> Path:
    override = os.environ.get("SLEEPERFFL_STATE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "state" / "sleeperffl"


@dataclass(frozen=True)
class Config:
    username: str
    season: str | None
    league_id: str | None
    cache_dir: Path
    state_dir: Path
    ntfy_topic: str
    ntfy_server: str
    ntfy_token: str | None

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            username=os.environ.get("SLEEPERFFL_USERNAME", SLEEPER_USERNAME),
            season=os.environ.get("SLEEPERFFL_SEASON") or None,
            league_id=os.environ.get("SLEEPERFFL_LEAGUE_ID") or None,
            cache_dir=_cache_root(),
            state_dir=_state_root(),
            ntfy_topic=os.environ.get("SLEEPERFFL_NTFY_TOPIC", "dbdev-ffl"),
            ntfy_server=os.environ.get("SLEEPERFFL_NTFY_SERVER", "https://ntfy.cla.ms"),
            ntfy_token=os.environ.get("SLEEPERFFL_NTFY_TOKEN") or None,
        )
