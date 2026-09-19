"""Free-agent tracking and the waiver-wire watcher.

The Sleeper API has no "free agents" endpoint, so the pool is derived: every
player with a projection, minus everyone rostered across all teams in the
league. Running that on a schedule and diffing against the previous run is what
turns it into a drop alert.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .league import League
from .pool import Player
from .value import replacement_levels, vor

# Injury designations that actually take a player off the field.
OUT_STATUSES = frozenset({"Out", "IR", "PUP", "Doubtful", "Sus", "NA", "DNR"})

# Don't shout about the 400th-best wide receiver getting cut.
DEFAULT_MIN_VOR = -20.0
DEFAULT_TRENDING_RANK = 50

# National add surges at these positions are near-universal (every league is
# streaming them) and the whole position is worth a few points a season, so a
# trending kicker or defense is never worth a claim. Drops and injury openings
# at these positions are still reported.
TRENDING_SKIP_POSITIONS = frozenset({"K", "DEF"})


@dataclass
class WatcherState:
    rostered: set[str] = field(default_factory=set)
    alerted: dict[str, float] = field(default_factory=dict)
    injuries: dict[str, str] = field(default_factory=dict)
    last_run: float = 0.0
    initialised: bool = False

    @classmethod
    def load(cls, path: Path) -> "WatcherState":
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls(
            rostered=set(raw.get("rostered") or []),
            alerted=dict(raw.get("alerted") or {}),
            injuries=dict(raw.get("injuries") or {}),
            last_run=float(raw.get("last_run") or 0.0),
            initialised=bool(raw.get("initialised")),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "rostered": sorted(self.rostered),
                    "alerted": self.alerted,
                    "injuries": self.injuries,
                    "last_run": self.last_run,
                    "initialised": self.initialised,
                }
            )
        )
        tmp.replace(path)

    def recently_alerted(self, player_id: str, cooldown: float) -> bool:
        seen = self.alerted.get(player_id)
        return seen is not None and (time.time() - seen) < cooldown


@dataclass
class Alert:
    kind: str
    player: Player
    value: float
    headline: str
    detail: str
    priority: str = "default"

    def sort_key(self) -> tuple[int, float]:
        rank = {"my_injury": 0, "dropped": 1, "injury_opening": 2, "trending": 3}.get(
            self.kind, 4
        )
        return (rank, -self.value)


def free_agents(league: League, pool: Mapping[str, Player]) -> list[Player]:
    """Everyone in the player pool that nobody in the league owns."""
    owned = league.rostered_player_ids()
    return [
        player
        for player in pool.values()
        if player.player_id not in owned and player.team and player.status != "Inactive"
    ]


def rank_free_agents(
    league: League, pool: Mapping[str, Player], limit: int = 25
) -> list[tuple[Player, float]]:
    """Free agents ranked by value over replacement in this league."""
    levels = replacement_levels(league, pool)
    rows = [(player, vor(player, levels)) for player in free_agents(league, pool)]
    rows.sort(key=lambda row: row[1], reverse=True)
    return rows[:limit]


def waiver_advice(league: League, value: float, rank_among_fa: int) -> str:
    """Whether a target is worth the cost of claiming him, in league terms."""
    if league.uses_faab:
        remaining = league.my_faab_remaining
        budget = league.settings.get("waiver_budget", 100)
        if remaining is None:
            return "FAAB league — bid to taste."
        share = 0.25 if value > 40 else 0.12 if value > 15 else 0.04
        bid = max(1, int(round(budget * share)))
        return f"Suggested bid ~${bid} of your ${remaining} remaining."

    position = league.my_waiver_position
    if position is None:
        return "Rolling waivers — claim if he beats your worst bench player."

    teams = league.total_rosters
    # Claiming drops you to the back of the queue, so priority is only really
    # spent when you hold a good one. Near the back it costs you almost nothing.
    if position > teams * 2 / 3:
        return (
            f"You hold waiver #{position} of {teams}, so a contested claim likely "
            "goes to someone ahead of you. Put it in regardless — you are already "
            "near the back of the queue, so it costs you nothing."
        )
    if rank_among_fa <= 2 and value > 15:
        return (
            f"Worth spending waiver #{position} of {teams} — clear top-of-wire "
            "talent, and priority is only worth holding for a player like this."
        )
    return (
        f"You hold waiver #{position} of {teams}. Only spend it here if he beats "
        "one of your current starters; otherwise wait the "
        f"{league.waiver_clear_days or 2} days and take him as a free agent."
    )


def weakest_rostered_by_position(league: League, pool: Mapping[str, Player]) -> dict[str, float]:
    """Your lowest-projected player at each position you roster."""
    roster = league.my_roster or {}
    weakest: dict[str, float] = {}
    for player_id in roster.get("players") or []:
        player = pool.get(player_id)
        if player is None:
            continue
        current = weakest.get(player.position)
        if current is None or player.proj_season < current:
            weakest[player.position] = player.proj_season
    return weakest


def _best_bench_sub(
    player: Player, roster: Iterable[Player], starters: set[str]
) -> Player | None:
    """Highest-projected healthy bench player at the same position."""
    candidates = [
        p
        for p in roster
        if p.player_id not in starters
        and p.player_id != player.player_id
        and p.position == player.position
        and p.injury_status not in OUT_STATUSES
    ]
    return max(candidates, key=lambda p: p.proj_season, default=None)


def my_injury_alerts(
    league: League, pool: Mapping[str, Player], state: WatcherState
) -> list[Alert]:
    """Any change in injury designation for a player on your own roster.

    Covers getting hurt, getting worse, and getting cleared. For a starter who
    is now unlikely to play, the alert names the bench player to swap in.
    """
    roster = league.my_roster or {}
    starters = set(roster.get("starters") or [])
    mine = [pool[pid] for pid in roster.get("players") or [] if pid in pool]

    alerts: list[Alert] = []
    for player in mine:
        before = state.injuries.get(player.player_id) or None
        now = player.injury_status or None
        if before == now:
            continue

        role = "starter" if player.player_id in starters else "bench player"
        if now is None:
            alerts.append(
                Alert(
                    kind="my_injury",
                    player=player,
                    value=0.0,
                    headline=f"CLEARED: {player.label}",
                    detail=f"Your {role} {player.name} no longer has an injury designation (was {before}).",
                )
            )
            continue

        was = f" (was {before})" if before else ""
        detail = f"Your {role} {player.name} is now {now}{was}."
        if player.player_id in starters and now in OUT_STATUSES:
            sub = _best_bench_sub(player, mine, starters)
            if sub:
                detail += f" Swap in {sub.name} ({sub.proj_season:.0f} proj) before his game locks."
            else:
                detail += f" No healthy {player.position} on your bench — check the wire."
        alerts.append(
            Alert(
                kind="my_injury",
                player=player,
                value=0.0,
                headline=f"{now.upper()}: {player.label} — your player",
                detail=detail,
                priority="high" if now in OUT_STATUSES else "default",
            )
        )
    return alerts


def detect_alerts(
    league: League,
    pool: Mapping[str, Player],
    state: WatcherState,
    trending_add: Iterable[Mapping[str, Any]],
    min_vor: float = DEFAULT_MIN_VOR,
    trending_rank: int = DEFAULT_TRENDING_RANK,
    cooldown: float = 12 * 60 * 60,
) -> list[Alert]:
    """Compare this run against the previous one and decide what is worth a push."""
    levels = replacement_levels(league, pool)
    owned_now = league.rostered_player_ids()
    available = {p.player_id: p for p in free_agents(league, pool)}
    ranked = {
        player.player_id: index + 1
        for index, (player, _) in enumerate(rank_free_agents(league, pool, limit=200))
    }

    alerts: list[Alert] = []

    # 1. Players who were rostered on the last run and have since been cut.
    if state.initialised:
        for player_id in state.rostered - owned_now:
            player = available.get(player_id)
            if player is None:
                continue
            value = vor(player, levels)
            if value < min_vor or state.recently_alerted(player_id, cooldown):
                continue
            alerts.append(
                Alert(
                    kind="dropped",
                    player=player,
                    value=value,
                    headline=f"DROPPED: {player.label}",
                    detail=(
                        f"{player.proj_season:.0f} proj pts ({value:+.0f} vs replacement). "
                        + waiver_advice(league, value, ranked.get(player_id, 99))
                    ),
                    priority="high" if value > 10 else "default",
                )
            )

    # 2. Your own players changing injury status.
    if state.initialised:
        alerts.extend(my_injury_alerts(league, pool, state))

    # 3. Backups promoted by an injury to the starter ahead of them.
    # Needs a previous run to compare against, or every existing injury would
    # look new.
    newly_out = (
        {
            player_id: status
            for player_id, status in _current_injuries(pool).items()
            if status in OUT_STATUSES and state.injuries.get(player_id) not in OUT_STATUSES
        }
        if state.initialised
        else {}
    )
    for hurt_id in newly_out:
        hurt = pool.get(hurt_id)
        if hurt is None or hurt_id not in owned_now:
            continue
        for player in available.values():
            if player.team != hurt.team or player.position != hurt.position:
                continue
            value = vor(player, levels)
            if state.recently_alerted(player.player_id, cooldown):
                continue
            alerts.append(
                Alert(
                    kind="injury_opening",
                    player=player,
                    value=value,
                    headline=f"OPENING: {player.label}",
                    detail=(
                        f"{hurt.name} is {hurt.injury_status}. {player.name} is the "
                        f"free-agent {player.position} behind him. "
                        + waiver_advice(league, value, ranked.get(player.player_id, 99))
                    ),
                    priority="high",
                )
            )

    # 4. Leaguewide add surges on someone still available here.
    weakest = weakest_rostered_by_position(league, pool)
    for index, row in enumerate(trending_add):
        if index >= trending_rank:
            break
        player_id = row.get("player_id")
        player = available.get(player_id)
        if player is None or state.recently_alerted(player_id, cooldown):
            continue
        if player.position in TRENDING_SKIP_POSITIONS:
            continue
        # Hype alone is not a reason to act: only flag someone who would be an
        # upgrade on the weakest player you already roster at his position.
        floor = weakest.get(player.position)
        if floor is not None and player.proj_season <= floor:
            continue
        value = vor(player, levels)
        if value < min_vor:
            continue
        alerts.append(
            Alert(
                kind="trending",
                player=player,
                value=value,
                headline=f"TRENDING: {player.label}",
                detail=(
                    f"Added in {row.get('count', 0):,} leagues in 24h and still free here. "
                    + waiver_advice(league, value, ranked.get(player_id, 99))
                ),
            )
        )

    # De-duplicate: one alert per player, strongest kind wins.
    best: dict[str, Alert] = {}
    for alert in sorted(alerts, key=lambda a: a.sort_key()):
        best.setdefault(alert.player.player_id, alert)
    return sorted(best.values(), key=lambda a: a.sort_key())


def _current_injuries(pool: Mapping[str, Player]) -> dict[str, str]:
    return {
        player_id: player.injury_status
        for player_id, player in pool.items()
        if player.injury_status
    }


def update_state(state: WatcherState, league: League, pool: Mapping[str, Player], alerts: Iterable[Alert]) -> None:
    now = time.time()
    state.rostered = league.rostered_player_ids()
    state.injuries = _current_injuries(pool)
    state.last_run = now
    state.initialised = True
    for alert in alerts:
        state.alerted[alert.player.player_id] = now
    # Forget alerts older than a week so a player can re-trigger later.
    cutoff = now - 7 * 24 * 60 * 60
    state.alerted = {pid: ts for pid, ts in state.alerted.items() if ts > cutoff}
