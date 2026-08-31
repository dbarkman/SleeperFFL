"""Turning projections into draft decisions.

Three layers, each building on the last:

1. **Replacement level** — what a freely available starter at each position is
   worth in *this* league. An 8-team league has a far higher replacement level
   than a 14-team one, which is why raw projected points rank players badly.
2. **VOR** — projected points above that replacement level.
3. **VONA** — value over the best player likely to *survive* until your next
   pick. This is the number that should actually drive a snake pick: taking the
   guy who will still be there in two rounds is how you leave value on the board.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from .league import League, flex_eligible
from .pool import Player

# Spread of the ADP survival curve, in picks. Larger = managers deviate more
# from consensus, so a player's availability decays more gradually.
ADP_SPREAD = 7.0

# A player this far past their ADP is treated as certain to be gone.
ADP_HORIZON = 40.0


def replacement_levels(league: League, pool: Mapping[str, Player]) -> dict[str, float]:
    """Projected points of the last startable player at each position.

    Dedicated slots are counted directly; flex slots are then handed out
    greedily to whichever position still offers the best remaining player, which
    is what actually happens as a draft unfolds.
    """
    by_position: dict[str, list[float]] = {}
    for player in pool.values():
        by_position.setdefault(player.position, []).append(player.proj_season)
    for values in by_position.values():
        values.sort(reverse=True)

    counts = {pos: league.dedicated_starters(pos) for pos in by_position}

    for slot, slot_count in league.flex_slots().items():
        eligible = [pos for pos in flex_eligible(slot) if pos in by_position]
        for _ in range(slot_count):
            best_pos, best_value = None, float("-inf")
            for pos in eligible:
                index = counts.get(pos, 0)
                values = by_position[pos]
                value = values[index] if index < len(values) else float("-inf")
                if value > best_value:
                    best_pos, best_value = pos, value
            if best_pos is None:
                break
            counts[best_pos] = counts.get(best_pos, 0) + 1

    levels: dict[str, float] = {}
    for pos, values in by_position.items():
        if not values:
            levels[pos] = 0.0
            continue
        # The replacement player is the next one after the last starter.
        index = min(counts.get(pos, 0), len(values) - 1)
        levels[pos] = values[index]
    return levels


def vor(player: Player, levels: Mapping[str, float]) -> float:
    return round(player.proj_season - levels.get(player.position, 0.0), 2)


def survival_probability(player: Player, pick_no: int, spread: float = ADP_SPREAD) -> float:
    """Probability the player is still on the board at ``pick_no``.

    A logistic curve centred on the player's ADP: at their ADP it is a coin
    flip, and it decays either side of that. Players with no ADP at all are
    deep enough that they are almost certainly still available.
    """
    if player.adp is None:
        return 0.95
    delta = pick_no - player.adp
    if delta > ADP_HORIZON:
        return 0.0
    if delta < -ADP_HORIZON:
        return 1.0
    return 1.0 / (1.0 + math.exp(delta / spread))


def expected_best_available(
    candidates: Sequence[tuple[Player, float]],
    pick_no: int,
    floor: float = 0.0,
    spread: float = ADP_SPREAD,
) -> float:
    """Expected value of the best of ``candidates`` still on the board.

    ``candidates`` is (player, value) sorted by value descending. Availability is
    treated as independent per player, which is close enough over the ~14 picks
    of one snake round trip.
    """
    expected = 0.0
    all_gone = 1.0
    for player, value in candidates:
        probability = survival_probability(player, pick_no, spread)
        expected += value * all_gone * probability
        all_gone *= 1.0 - probability
        if all_gone < 1e-4:
            break
    return expected + all_gone * floor


# Positions where carrying a backup is pointless — you stream them instead.
NO_BACKUP_NEEDED = frozenset({"K", "DEF"})


@dataclass
class RosterNeed:
    """How badly the roster still wants each position."""

    filled: dict[str, int]
    dedicated_open: dict[str, int]
    flex_open: int
    bench_open: int
    picks_left: int
    dedicated_slots: dict[str, int] = field(default_factory=dict)

    def needs_insurance(self, position: str) -> bool:
        """True when the roster has starters at this position but no backup.

        A position with mandatory starting slots and no spare body means one
        injury leaves a slot empty, and an empty slot scores zero every week.
        """
        if position in NO_BACKUP_NEEDED:
            return False
        slots = self.dedicated_slots.get(position, 0)
        if slots == 0:
            return False
        return self.filled.get(position, 0) < slots + 1

    @property
    def open_starting_slots(self) -> int:
        return sum(self.dedicated_open.values()) + self.flex_open

    def fills_open_slot(self, position: str) -> bool:
        if self.dedicated_open.get(position, 0) > 0:
            return True
        return self.flex_open > 0 and position in ("RB", "WR", "TE")

    def multiplier(self, position: str, caps: Mapping[str, int]) -> float:
        cap = caps.get(position, 99)
        have = self.filled.get(position, 0)
        if have >= cap:
            return 0.05

        # Once picks left no longer exceed unfilled starting slots, every
        # remaining pick has to fill one. An empty starting slot scores zero
        # every single week, which no amount of bench depth makes up for.
        if self.picks_left <= self.open_starting_slots and not self.fills_open_slot(position):
            return 0.02

        if self.dedicated_open.get(position, 0) > 0:
            return 1.0
        if self.flex_open > 0 and position in ("RB", "WR", "TE"):
            return 0.9
        if self.needs_insurance(position):
            return 0.8
        return 0.65


def positional_caps(league: League) -> dict[str, int]:
    """Sensible maximum roster count per position for this league's shape."""
    slots = league.slot_counts
    total = len(league.roster_positions)
    caps = {
        "QB": slots.get("QB", 1) + 1,
        "TE": slots.get("TE", 1) + 1,
        "K": slots.get("K", 1),
        "DEF": slots.get("DEF", 1),
    }
    # Whatever is left over can go to RB/WR depth.
    spare = max(total - sum(caps.values()) - slots.get("RB", 2) - slots.get("WR", 2), 0)
    caps["RB"] = slots.get("RB", 2) + slots.get("FLEX", 0) + spare
    caps["WR"] = slots.get("WR", 2) + slots.get("FLEX", 0) + spare
    return caps


def roster_need(league: League, my_players: Iterable[Player], picks_left: int) -> RosterNeed:
    """Work out which starting slots the roster still has open."""
    filled: dict[str, int] = {}
    for player in my_players:
        filled[player.position] = filled.get(player.position, 0) + 1

    remaining = dict(filled)
    dedicated_open: dict[str, int] = {}
    for slot, count in league.slot_counts.items():
        if slot in flex_eligible(slot) or slot in ("FLEX", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX"):
            continue
        have = remaining.get(slot, 0)
        used = min(have, count)
        remaining[slot] = have - used
        dedicated_open[slot] = count - used

    flex_open = 0
    for slot, count in league.slot_counts.items():
        eligible = flex_eligible(slot)
        if not eligible:
            continue
        for _ in range(count):
            source = max(
                (pos for pos in eligible if remaining.get(pos, 0) > 0),
                key=lambda pos: remaining.get(pos, 0),
                default=None,
            )
            if source is None:
                flex_open += 1
            else:
                remaining[source] -= 1

    starters = len(league.starting_slots)
    bench_open = max(len(league.roster_positions) - starters - 0, 0)

    return RosterNeed(
        filled=filled,
        dedicated_open=dedicated_open,
        flex_open=flex_open,
        bench_open=bench_open,
        picks_left=picks_left,
        dedicated_slots={
            slot: count
            for slot, count in league.slot_counts.items()
            if not flex_eligible(slot)
        },
    )


def late_round_penalty(position: str, need: RosterNeed, league: League) -> float:
    """Keep kickers and defenses out of the early rounds.

    Drafting a K or DEF before the last couple of rounds burns a pick on a
    position where the difference between first and last is a point a week.
    """
    if position not in ("K", "DEF"):
        return 1.0
    still_needed = sum(
        league.slot_counts.get(pos, 0) - need.filled.get(pos, 0) for pos in ("K", "DEF")
    )
    if need.picks_left <= max(still_needed, 1) + 1:
        return 1.0
    # Fades in over the final few rounds rather than switching on hard.
    slack = need.picks_left - still_needed
    return max(0.02, 1.0 / (1.0 + slack))
