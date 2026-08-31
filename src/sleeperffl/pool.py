"""The player pool: every fantasy-relevant player, scored for one league.

Merges three sources into a single ``Player`` record — the full player map (for
names, injury status, team), the season projections (for projected stat lines
and redraft ADP), and the schedule (for bye weeks).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .api import SleeperClient
from .scoring import score_line

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# ADP fields Sleeper exposes on the season projection line, best match first for
# a given league format.
ADP_FIELDS = {
    "ppr": ("adp_ppr", "adp_half_ppr", "adp_std"),
    "half_ppr": ("adp_half_ppr", "adp_ppr", "adp_std"),
    "std": ("adp_std", "adp_half_ppr", "adp_ppr"),
    "2qb": ("adp_2qb", "adp_ppr", "adp_half_ppr"),
}


@dataclass
class Player:
    player_id: str
    name: str
    position: str
    team: str | None
    bye_week: int | None = None
    injury_status: str | None = None
    status: str | None = None
    age: int | None = None
    years_exp: int | None = None
    adp: float | None = None
    proj_season: float = 0.0
    proj_stats: dict[str, Any] = field(default_factory=dict)
    search_rank: int | None = None

    @property
    def is_injured(self) -> bool:
        return bool(self.injury_status) and self.injury_status not in ("Questionable", "")

    @property
    def label(self) -> str:
        return f"{self.name} ({self.position} - {self.team or 'FA'})"

    def sort_adp(self) -> float:
        """ADP with undrafted players pushed to the back."""
        return self.adp if self.adp is not None else 9999.0


def bye_weeks(schedule: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Map team abbreviation -> bye week, derived from missing schedule rows."""
    playing: dict[str, set[int]] = {}
    weeks: set[int] = set()
    for game in schedule:
        week = game.get("week")
        if not isinstance(week, int):
            continue
        weeks.add(week)
        for side in ("home", "away"):
            team = game.get(side)
            if team:
                playing.setdefault(team, set()).add(week)
    if not weeks:
        return {}
    all_weeks = set(range(1, max(weeks) + 1))
    byes: dict[str, int] = {}
    for team, played in playing.items():
        missing = sorted(all_weeks - played)
        if len(missing) == 1:
            byes[team] = missing[0]
    return byes


def adp_field_for(scoring: Mapping[str, float], roster_positions: Iterable[str]) -> str:
    """Pick the ADP variant that matches this league's format."""
    if sum(1 for slot in roster_positions if slot in ("QB", "SUPER_FLEX")) > 1:
        fmt = "2qb"
    else:
        rec = scoring.get("rec", 0.0)
        fmt = "ppr" if rec >= 0.75 else "half_ppr" if rec >= 0.25 else "std"
    return ADP_FIELDS[fmt][0]


def build_pool(
    client: SleeperClient,
    season: str,
    scoring: Mapping[str, float],
    roster_positions: Iterable[str],
) -> dict[str, Player]:
    """Return player_id -> Player for everyone with a season projection."""
    roster_positions = list(roster_positions)
    players_map = client.players()
    projections = client.season_projections(season)
    byes = bye_weeks(client.schedule(season))
    adp_key = adp_field_for(scoring, roster_positions)

    pool: dict[str, Player] = {}
    for row in projections:
        player_id = row.get("player_id")
        if not player_id:
            continue
        meta = players_map.get(player_id) or {}
        raw = row.get("player") or {}
        position = meta.get("position") or raw.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        team = row.get("team") or meta.get("team")
        stats = row.get("stats") or {}
        adp = stats.get(adp_key)

        name = meta.get("full_name")
        if not name:
            first = raw.get("first_name") or meta.get("first_name") or ""
            last = raw.get("last_name") or meta.get("last_name") or ""
            name = f"{first} {last}".strip() or player_id

        pool[player_id] = Player(
            player_id=player_id,
            name=name,
            position=position,
            team=team,
            bye_week=byes.get(team) if team else None,
            injury_status=meta.get("injury_status") or raw.get("injury_status"),
            status=meta.get("status"),
            age=meta.get("age"),
            years_exp=meta.get("years_exp") if meta.get("years_exp") is not None else raw.get("years_exp"),
            adp=float(adp) if isinstance(adp, (int, float)) else None,
            proj_season=score_line(stats, scoring),
            proj_stats=stats,
            search_rank=meta.get("search_rank"),
        )
    return pool
