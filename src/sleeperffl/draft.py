"""Live draft board and pick recommendations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .league import League
from .pool import Player
from .value import (
    RosterNeed,
    expected_best_available,
    late_round_penalty,
    positional_caps,
    replacement_levels,
    roster_need,
    survival_probability,
    vor,
)

# How the two signals are blended into one ranking. VONA leads because the
# question at the clock is "who won't be here next time", not "who is best".
W_VOR = 0.45
W_VONA = 0.55


def pick_number(round_no: int, slot: int, teams: int) -> int:
    """Overall pick number for a snake draft (1-indexed round and slot)."""
    if round_no % 2 == 1:
        return (round_no - 1) * teams + slot
    return (round_no - 1) * teams + (teams - slot + 1)


def slot_picks(slot: int, teams: int, rounds: int) -> list[int]:
    """Every overall pick number belonging to one draft slot."""
    return [pick_number(r, slot, teams) for r in range(1, rounds + 1)]


def linear_picks(slot: int, teams: int, rounds: int) -> list[int]:
    """Pick numbers for a non-snake (linear) draft."""
    return [(r - 1) * teams + slot for r in range(1, rounds + 1)]


def round_and_slot(pick_no: int, teams: int, snake: bool = True) -> tuple[int, int]:
    """Inverse of :func:`pick_number` — which round and column a pick sits in."""
    round_no = (pick_no - 1) // teams + 1
    index = (pick_no - 1) % teams + 1
    if snake and round_no % 2 == 0:
        index = teams - index + 1
    return round_no, index


def format_pick(pick_no: int, teams: int, snake: bool = True) -> str:
    round_no, slot = round_and_slot(pick_no, teams, snake)
    return f"{round_no}.{slot:02d}"


@dataclass
class DraftState:
    draft_id: str
    teams: int
    rounds: int
    snake: bool
    my_slot: int | None
    picks: list[dict[str, Any]]
    status: str

    @property
    def picks_made(self) -> int:
        return len(self.picks)

    @property
    def on_the_clock(self) -> int:
        """Overall number of the pick currently being made."""
        return self.picks_made + 1

    @property
    def total_picks(self) -> int:
        return self.teams * self.rounds

    @property
    def is_complete(self) -> bool:
        return self.status == "complete" or self.picks_made >= self.total_picks

    def my_picks(self) -> list[int]:
        if self.my_slot is None:
            return []
        if self.snake:
            return slot_picks(self.my_slot, self.teams, self.rounds)
        return linear_picks(self.my_slot, self.teams, self.rounds)

    def my_next_picks(self, count: int = 2) -> list[int]:
        current = self.on_the_clock
        return [p for p in self.my_picks() if p >= current][:count]

    def picks_until_my_turn(self) -> int | None:
        upcoming = self.my_next_picks(1)
        if not upcoming:
            return None
        return upcoming[0] - self.on_the_clock

    def is_my_turn(self) -> bool:
        return self.picks_until_my_turn() == 0

    def drafted_ids(self) -> set[str]:
        return {p["player_id"] for p in self.picks if p.get("player_id")}

    def my_drafted_ids(self) -> list[str]:
        if self.my_slot is None:
            return []
        return [
            p["player_id"]
            for p in self.picks
            if p.get("player_id") and p.get("draft_slot") == self.my_slot
        ]

    def picks_by_slot(self) -> dict[int, list[dict[str, Any]]]:
        by_slot: dict[int, list[dict[str, Any]]] = {}
        for pick in self.picks:
            slot = pick.get("draft_slot")
            if slot is not None:
                by_slot.setdefault(slot, []).append(pick)
        return by_slot


def resolve_my_slot(
    draft: Mapping[str, Any], picks: Sequence[Mapping[str, Any]], user_id: str
) -> int | None:
    """Find your draft column: from the draft order, or from picks already made.

    ``draft_order`` is null until the commissioner sets the order, so during a
    live draft we fall back to whichever column has been making your picks.
    """
    order = draft.get("draft_order") or {}
    slot = order.get(user_id)
    if slot:
        return int(slot)
    for pick in picks:
        if pick.get("picked_by") == user_id and pick.get("draft_slot"):
            return int(pick["draft_slot"])
    return None


def load_draft_state(client, draft_id: str, user_id: str, slot_override: int | None) -> DraftState:
    draft = client.draft(draft_id)
    if not draft:
        raise RuntimeError(f"Draft {draft_id} not found.")
    picks = client.draft_picks(draft_id)
    settings = draft.get("settings") or {}
    return DraftState(
        draft_id=draft_id,
        teams=settings.get("teams", 12),
        rounds=settings.get("rounds", 15),
        snake=draft.get("type", "snake") == "snake",
        my_slot=slot_override or resolve_my_slot(draft, picks, user_id),
        picks=list(picks),
        status=draft.get("status", "unknown"),
    )


@dataclass
class Recommendation:
    player: Player
    vor: float
    vona: float
    score: float
    survival: float
    need_multiplier: float
    reason: str


def recommend(
    league: League,
    pool: Mapping[str, Player],
    state: DraftState,
    limit: int = 5,
) -> list[Recommendation]:
    """Rank the board for the pick you are about to make."""
    levels = replacement_levels(league, pool)
    caps = positional_caps(league)
    drafted = state.drafted_ids()

    available = [p for p in pool.values() if p.player_id not in drafted]

    my_ids = set(state.my_drafted_ids())
    my_players = [pool[pid] for pid in my_ids if pid in pool]
    picks_left = max(len(state.my_picks()) - len(my_ids), 0)
    need = roster_need(league, my_players, picks_left)

    # A position at its cap is not draftable at all. A third quarterback or a
    # second kicker is a wasted bench spot no matter how the numbers look, so
    # filter rather than merely penalise. Fall back if that leaves nothing.
    draftable = [p for p in available if need.filled.get(p.position, 0) < caps.get(p.position, 99)]
    if draftable:
        available = draftable

    values = {p.player_id: vor(p, levels) for p in available}

    following = state.my_next_picks(2)
    next_pick = following[1] if len(following) > 1 else None

    by_position: dict[str, list[tuple[Player, float]]] = {}
    for player in available:
        by_position.setdefault(player.position, []).append((player, values[player.player_id]))
    for rows in by_position.values():
        rows.sort(key=lambda row: row[1], reverse=True)

    recommendations: list[Recommendation] = []
    for player in available:
        value = values[player.player_id]
        position = player.position

        if next_pick is None:
            # Last pick of the draft: nothing survives to compare against.
            baseline = 0.0
            survival = 0.0
        else:
            others = [row for row in by_position[position] if row[0].player_id != player.player_id]
            baseline = expected_best_available(others, next_pick, floor=0.0)
            survival = survival_probability(player, next_pick)

        vona = round(value - baseline, 2)
        multiplier = need.multiplier(position, caps) * late_round_penalty(position, need, league)

        base = W_VOR * value + W_VONA * max(vona, 0.0)
        # Late in a draft every remaining player is below replacement, so base
        # goes negative. Multiplying a negative by a <1 need factor would make
        # a player *more* attractive, so mirror the discount for that case.
        score = base * multiplier if base >= 0 else base * (2.0 - multiplier)

        recommendations.append(
            Recommendation(
                player=player,
                vor=value,
                vona=vona,
                score=round(score, 2),
                survival=survival,
                need_multiplier=round(multiplier, 2),
                reason=_reason(player, need, vona, survival, my_players, state),
            )
        )

    recommendations.sort(key=lambda r: r.score, reverse=True)
    return recommendations[:limit]


def _reason(
    player: Player,
    need: RosterNeed,
    vona: float,
    survival: float,
    my_players: Sequence[Player],
    state: DraftState,
) -> str:
    parts: list[str] = []

    open_here = need.dedicated_open.get(player.position, 0)
    if open_here > 0:
        parts.append(f"{player.position} starter open")
    elif need.flex_open > 0 and player.position in ("RB", "WR", "TE"):
        parts.append("fills FLEX")
    else:
        parts.append("depth")

    following = state.my_next_picks(2)
    if len(following) > 1:
        label = format_pick(following[1], state.teams, state.snake)
        parts.append(f"{survival * 100:.0f}% to last to {label}")

    if vona >= 25:
        parts.append("big drop-off after him")

    if player.injury_status:
        parts.append(f"INJ {player.injury_status}")

    if player.bye_week:
        clash = sum(
            1
            for p in my_players
            if p.bye_week == player.bye_week and p.position == player.position
        )
        if clash >= 1:
            parts.append(f"bye {player.bye_week} clashes with {clash} other {player.position}")

    return " · ".join(parts)
