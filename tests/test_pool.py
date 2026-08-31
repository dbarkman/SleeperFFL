from __future__ import annotations

from sleeperffl.pool import adp_field_for, bye_weeks


def test_bye_weeks_finds_each_teams_missing_week():
    """Four teams over four weeks, each sitting out exactly one."""
    schedule = [
        {"week": 1, "home": "A", "away": "B"},
        {"week": 2, "home": "A", "away": "C"},
        {"week": 2, "home": "B", "away": "D"},
        {"week": 3, "home": "A", "away": "D"},
        {"week": 3, "home": "B", "away": "C"},
        {"week": 4, "home": "C", "away": "D"},
    ]
    # A plays 1,2,3 -> bye 4.  B plays 1,2,3 -> bye 4.
    # C plays 2,3,4 -> bye 1.  D plays 2,3,4 -> bye 1.
    assert bye_weeks(schedule) == {"A": 4, "B": 4, "C": 1, "D": 1}


def test_bye_weeks_ignores_teams_with_multiple_gaps():
    schedule = [
        {"week": 1, "home": "A", "away": "B"},
        {"week": 4, "home": "A", "away": "B"},
    ]
    # A and B are missing weeks 2 and 3, which is not a bye — it is bad data.
    assert bye_weeks(schedule) == {}


def test_bye_weeks_exactly_one_gap():
    schedule = [
        {"week": 1, "home": "A", "away": "B"},
        {"week": 3, "home": "A", "away": "B"},
    ]
    assert bye_weeks(schedule) == {"A": 2, "B": 2}


def test_bye_weeks_empty_schedule():
    assert bye_weeks([]) == {}


def test_adp_field_matches_league_format():
    ppr = {"rec": 1.0}
    half = {"rec": 0.5}
    std = {"rec": 0.0}
    one_qb = ["QB", "RB", "WR", "TE", "FLEX"]
    assert adp_field_for(ppr, one_qb) == "adp_ppr"
    assert adp_field_for(half, one_qb) == "adp_half_ppr"
    assert adp_field_for(std, one_qb) == "adp_std"
    assert adp_field_for(ppr, ["QB", "SUPER_FLEX", "RB"]) == "adp_2qb"
