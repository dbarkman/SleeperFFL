"""League context — settings, managers, rosters, and your seat at the table."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .api import SleeperClient

BENCH_SLOTS = frozenset({"BN", "IR", "TAXI"})

# Which positions can fill each flex-style slot.
FLEX_ELIGIBILITY: dict[str, frozenset[str]] = {
    "FLEX": frozenset({"RB", "WR", "TE"}),
    "WRRB_FLEX": frozenset({"RB", "WR"}),
    "REC_FLEX": frozenset({"WR", "TE"}),
    "SUPER_FLEX": frozenset({"QB", "RB", "WR", "TE"}),
    "IDP_FLEX": frozenset({"DL", "LB", "DB"}),
}

WAIVER_TYPES = {0: "rolling waiver priority", 1: "reverse standings", 2: "FAAB"}


@dataclass
class Manager:
    user_id: str
    display_name: str
    team_name: str | None
    roster_id: int | None
    is_commissioner: bool

    @property
    def label(self) -> str:
        return self.team_name or self.display_name


@dataclass
class League:
    league_id: str
    name: str
    season: str
    status: str
    total_rosters: int
    roster_positions: list[str]
    scoring: dict[str, float]
    settings: dict[str, Any]
    draft_id: str | None
    managers: list[Manager]
    rosters: list[dict[str, Any]]
    my_user_id: str

    # --- roster shape ---------------------------------------------------------

    @property
    def starting_slots(self) -> list[str]:
        return [slot for slot in self.roster_positions if slot not in BENCH_SLOTS]

    @property
    def bench_size(self) -> int:
        return sum(1 for slot in self.roster_positions if slot == "BN")

    @property
    def slot_counts(self) -> dict[str, int]:
        return dict(Counter(self.starting_slots))

    def dedicated_starters(self, position: str) -> int:
        """Starting slots that only this position can fill, across the league."""
        return self.slot_counts.get(position, 0) * self.total_rosters

    def flex_slots(self) -> dict[str, int]:
        """Flex-style slot name -> league-wide count."""
        return {
            slot: count * self.total_rosters
            for slot, count in self.slot_counts.items()
            if slot in FLEX_ELIGIBILITY
        }

    # --- waivers --------------------------------------------------------------

    @property
    def waiver_type(self) -> str:
        return WAIVER_TYPES.get(self.settings.get("waiver_type"), "unknown")

    @property
    def uses_faab(self) -> bool:
        return self.settings.get("waiver_type") == 2

    @property
    def waiver_clear_days(self) -> int | None:
        return self.settings.get("waiver_clear_days")

    # --- my team --------------------------------------------------------------

    @property
    def my_roster(self) -> dict[str, Any] | None:
        for roster in self.rosters:
            if roster.get("owner_id") == self.my_user_id:
                return roster
        return None

    @property
    def my_roster_id(self) -> int | None:
        roster = self.my_roster
        return roster.get("roster_id") if roster else None

    def manager_for_roster(self, roster_id: int) -> Manager | None:
        for manager in self.managers:
            if manager.roster_id == roster_id:
                return manager
        return None

    def rostered_player_ids(self) -> set[str]:
        """Every player owned by anyone in the league, including IR and taxi."""
        owned: set[str] = set()
        for roster in self.rosters:
            for key in ("players", "reserve", "taxi"):
                for player_id in roster.get(key) or []:
                    owned.add(player_id)
        return owned

    def waiver_order(self) -> list[tuple[int, int]]:
        """(waiver_position, roster_id) sorted best priority first."""
        rows = [
            (roster.get("settings", {}).get("waiver_position"), roster.get("roster_id"))
            for roster in self.rosters
        ]
        return sorted([r for r in rows if r[0] is not None], key=lambda r: r[0])

    @property
    def my_waiver_position(self) -> int | None:
        roster = self.my_roster
        if not roster:
            return None
        return (roster.get("settings") or {}).get("waiver_position")

    @property
    def my_faab_remaining(self) -> int | None:
        if not self.uses_faab:
            return None
        roster = self.my_roster
        if not roster:
            return None
        budget = self.settings.get("waiver_budget", 100)
        return budget - (roster.get("settings") or {}).get("waiver_budget_used", 0)


def flex_eligible(slot: str) -> frozenset[str]:
    return FLEX_ELIGIBILITY.get(slot, frozenset())


def resolve_league_id(client: SleeperClient, user_id: str, season: str, explicit: str | None) -> str:
    """Use the configured league, or the user's only league for the season."""
    if explicit:
        return explicit
    leagues = client.leagues(user_id, season)
    if not leagues:
        raise RuntimeError(f"No NFL leagues found for user {user_id} in {season}.")
    if len(leagues) > 1:
        names = ", ".join(f"{lg['name']} ({lg['league_id']})" for lg in leagues)
        raise RuntimeError(
            f"User is in {len(leagues)} leagues for {season}; pass --league-id. Found: {names}"
        )
    return leagues[0]["league_id"]


def load_league(client: SleeperClient, user_id: str, season: str, league_id: str | None) -> League:
    league_id = resolve_league_id(client, user_id, season, league_id)
    raw = client.league(league_id)
    users = client.league_users(league_id)
    rosters = client.rosters(league_id)

    roster_by_owner = {r.get("owner_id"): r.get("roster_id") for r in rosters}
    managers = [
        Manager(
            user_id=u["user_id"],
            display_name=u.get("display_name") or u.get("username") or u["user_id"],
            team_name=(u.get("metadata") or {}).get("team_name"),
            roster_id=roster_by_owner.get(u["user_id"]),
            is_commissioner=bool(u.get("is_owner")),
        )
        for u in users
    ]

    return League(
        league_id=league_id,
        name=raw.get("name", "league"),
        season=str(raw.get("season", season)),
        status=raw.get("status", "unknown"),
        total_rosters=raw.get("total_rosters", len(rosters) or 12),
        roster_positions=list(raw.get("roster_positions") or []),
        scoring=dict(raw.get("scoring_settings") or {}),
        settings=dict(raw.get("settings") or {}),
        draft_id=raw.get("draft_id"),
        managers=managers,
        rosters=rosters,
        my_user_id=user_id,
    )
