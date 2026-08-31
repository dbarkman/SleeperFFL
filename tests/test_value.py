from __future__ import annotations

from sleeperffl.pool import Player
from sleeperffl.value import (
    expected_best_available,
    late_round_penalty,
    positional_caps,
    replacement_levels,
    roster_need,
    survival_probability,
    vor,
)
from tests.conftest import make_player


def test_replacement_level_reflects_league_size(league, pool):
    levels = replacement_levels(league, pool)
    # 8 teams x 1 QB = 8 dedicated QB starters, so replacement is roughly QB9.
    assert levels["QB"] == pool["qb8"].proj_season
    # 8 teams x 1 TE, but FLEX can absorb tight ends too, so it sits at or past TE9.
    assert levels["TE"] <= pool["te8"].proj_season


def test_flex_slots_push_replacement_deeper_at_rb_and_wr(league, pool):
    levels = replacement_levels(league, pool)
    # RB/WR have 16 dedicated starters plus a share of the 16 flex slots, so
    # replacement must be worse than the 16th best at the position.
    assert levels["RB"] < pool["rb15"].proj_season
    assert levels["WR"] < pool["wr15"].proj_season


def test_vor_is_projection_minus_replacement(league, pool):
    levels = replacement_levels(league, pool)
    player = pool["rb0"]
    assert vor(player, levels) == round(player.proj_season - levels["RB"], 2)


def test_survival_probability_is_a_coin_flip_at_adp():
    player = make_player("p", "P", "RB", 200, adp=20.0)
    assert survival_probability(player, 20) == 0.5
    # 15 picks early he is very likely there; 20 picks late he is very likely gone.
    assert survival_probability(player, 5) > 0.85
    assert survival_probability(player, 40) < 0.1
    # Monotonically decreasing as the draft moves past him.
    curve = [survival_probability(player, pick) for pick in range(1, 60)]
    assert curve == sorted(curve, reverse=True)


def test_survival_probability_saturates_beyond_the_horizon():
    player = make_player("p", "P", "RB", 200, adp=60.0)
    # Past the horizon the curve is clamped rather than left asymptotic.
    assert survival_probability(player, 200) == 0.0
    assert survival_probability(player, 1) == 1.0


def test_player_without_adp_is_assumed_available():
    player = make_player("p", "P", "RB", 50, adp=None)
    assert survival_probability(player, 100) == 0.95


def test_expected_best_available_sits_between_the_candidates():
    early = make_player("a", "A", "RB", 300, adp=1.0)   # certainly gone by pick 30
    late = make_player("b", "B", "RB", 200, adp=90.0)   # certainly still there
    result = expected_best_available([(early, 100.0), (late, 40.0)], pick_no=30)
    assert 39.0 < result < 45.0


def test_expected_best_available_falls_back_to_floor_when_board_is_empty():
    assert expected_best_available([], pick_no=30, floor=7.5) == 7.5


def test_roster_need_tracks_open_starting_slots(league, pool):
    need = roster_need(league, [], picks_left=15)
    assert need.dedicated_open["RB"] == 2
    assert need.dedicated_open["QB"] == 1
    assert need.flex_open == 2

    filled = [pool["rb0"], pool["rb1"], pool["qb0"]]
    need = roster_need(league, filled, picks_left=12)
    assert need.dedicated_open["RB"] == 0
    assert need.dedicated_open["QB"] == 0
    assert need.flex_open == 2


def test_flex_absorbs_surplus_running_backs(league, pool):
    filled = [pool[f"rb{i}"] for i in range(4)]
    need = roster_need(league, filled, picks_left=11)
    assert need.dedicated_open["RB"] == 0
    # Two surplus RBs slot into the two FLEX spots.
    assert need.flex_open == 0


def test_need_multiplier_prefers_open_starting_slots(league, pool):
    caps = positional_caps(league)
    empty = roster_need(league, [], picks_left=15)
    assert empty.multiplier("RB", caps) == 1.0

    stacked = roster_need(league, [pool[f"rb{i}"] for i in range(4)], picks_left=11)
    assert stacked.multiplier("RB", caps) < 1.0


def test_positional_caps_limit_kickers_and_defenses(league):
    caps = positional_caps(league)
    assert caps["K"] == 1
    assert caps["DEF"] == 1
    assert caps["QB"] == 2
    assert caps["RB"] > 2


def test_kickers_are_suppressed_until_the_final_rounds(league):
    early = roster_need(league, [], picks_left=15)
    late = roster_need(league, [], picks_left=2)
    assert late_round_penalty("K", early, league) < 0.2
    assert late_round_penalty("K", late, league) == 1.0
    # Skill positions are never penalised.
    assert late_round_penalty("RB", early, league) == 1.0


def test_must_fill_starters_when_picks_run_out(league, pool):
    """With as many picks left as empty starting slots, depth is worthless."""
    caps = positional_caps(league)
    # Every skill slot filled, K and DEF still empty, one pick left.
    filled = [pool[p] for p in ("qb0", "rb0", "rb1", "wr0", "wr1", "te0", "rb2", "wr2")]
    need = roster_need(league, filled, picks_left=1)
    assert need.open_starting_slots == 2
    assert need.multiplier("K", caps) == 1.0
    assert need.multiplier("RB", caps) == 0.02


def test_depth_is_still_allowed_when_picks_are_spare(league, pool):
    caps = positional_caps(league)
    filled = [pool[p] for p in ("qb0", "rb0", "rb1", "wr0", "wr1", "te0", "rb2", "wr2")]
    need = roster_need(league, filled, picks_left=7)
    assert need.multiplier("RB", caps) > 0.5


def test_insurance_is_wanted_for_positions_with_mandatory_slots(league, pool):
    caps = positional_caps(league)
    # Two RB slots filled by exactly two RBs: one injury leaves a slot empty.
    filled = [pool[p] for p in ("qb0", "rb0", "rb1", "wr0", "wr1", "wr2", "wr3", "te0")]
    need = roster_need(league, filled, picks_left=7)
    assert need.needs_insurance("RB")
    assert not need.needs_insurance("WR")  # four WRs for two slots already
    assert need.multiplier("RB", caps) > need.multiplier("WR", caps)


def test_no_insurance_wanted_for_kickers_or_defenses(league, pool):
    filled = [pool["k0"], pool["def0"]]
    need = roster_need(league, filled, picks_left=10)
    assert not need.needs_insurance("K")
    assert not need.needs_insurance("DEF")
