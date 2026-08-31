from __future__ import annotations

from sleeperffl.scoring import is_standard_ppr, score_line
from tests.conftest import PPR_SCORING


def test_score_line_is_a_dot_product_over_shared_keys():
    stats = {"rec": 100, "rec_yd": 1200, "rec_td": 10, "off_snp": 900}
    # off_snp has no scoring multiplier, so it must not contribute.
    assert score_line(stats, PPR_SCORING) == 100 + 120 + 60


def test_score_line_handles_negative_scoring():
    stats = {"pass_yd": 4000, "pass_td": 30, "pass_int": 12, "fum_lost": 3}
    expected = 4000 * 0.04 + 30 * 4 - 12 - 6
    assert score_line(stats, PPR_SCORING) == round(expected, 2)


def test_score_line_ignores_non_numeric_and_missing():
    assert score_line({"rec": None, "rec_yd": "x"}, PPR_SCORING) == 0.0
    assert score_line(None, PPR_SCORING) == 0.0
    assert score_line({}, PPR_SCORING) == 0.0


def test_zero_multipliers_are_skipped():
    scoring = {"rec": 0.0, "rec_yd": 0.1}
    assert score_line({"rec": 100, "rec_yd": 1000}, scoring) == 100.0


def test_defense_points_allowed_buckets_score():
    # Sleeper sets exactly one pts_allow_* flag per defensive game.
    scoring = {"pts_allow_1_6": 7.0, "pts_allow_7_13": 4.0, "sack": 1.0}
    stats = {"pts_allow_1_6": 3, "sack": 40}
    assert score_line(stats, scoring) == 21 + 40


def test_is_standard_ppr_detects_bonuses():
    assert is_standard_ppr(PPR_SCORING)
    assert not is_standard_ppr({**PPR_SCORING, "rec": 0.5})
    assert not is_standard_ppr({**PPR_SCORING, "bonus_rec_te": 0.5})
