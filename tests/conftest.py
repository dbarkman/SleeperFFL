from __future__ import annotations

import pytest

from sleeperffl.league import League, Manager
from sleeperffl.pool import Player

ROSTER_POSITIONS = [
    "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF",
    "BN", "BN", "BN", "BN", "BN",
]

PPR_SCORING = {
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -1.0,
    "fum_lost": -2.0,
}


def make_player(pid, name, position, proj, adp=None, team="DET", bye=6, injury=None):
    return Player(
        player_id=pid,
        name=name,
        position=position,
        team=team,
        bye_week=bye,
        injury_status=injury,
        proj_season=proj,
        adp=adp,
    )


@pytest.fixture
def pool():
    """A small but realistically shaped pool for an 8-team league."""
    players = {}
    # Enough bodies at each position to push past replacement level.
    for index in range(40):
        players[f"rb{index}"] = make_player(
            f"rb{index}", f"RB {index}", "RB", 300 - index * 6, adp=1.5 + index * 3
        )
    for index in range(40):
        players[f"wr{index}"] = make_player(
            f"wr{index}", f"WR {index}", "WR", 290 - index * 5, adp=3.0 + index * 3
        )
    for index in range(20):
        players[f"qb{index}"] = make_player(
            f"qb{index}", f"QB {index}", "QB", 360 - index * 8, adp=20.0 + index * 6
        )
    for index in range(20):
        players[f"te{index}"] = make_player(
            f"te{index}", f"TE {index}", "TE", 250 - index * 12, adp=23.0 + index * 8
        )
    for index in range(12):
        players[f"k{index}"] = make_player(
            f"k{index}", f"K {index}", "K", 140 - index * 3, adp=130.0 + index * 2
        )
    for index in range(12):
        players[f"def{index}"] = make_player(
            f"def{index}", f"DEF {index}", "DEF", 130 - index * 4, adp=125.0 + index * 2
        )
    return players


@pytest.fixture
def league():
    return League(
        league_id="L1",
        name="Test League",
        season="2026",
        status="pre_draft",
        total_rosters=8,
        roster_positions=list(ROSTER_POSITIONS),
        scoring=dict(PPR_SCORING),
        settings={"waiver_type": 0, "waiver_budget": 100, "waiver_clear_days": 2},
        draft_id="D1",
        managers=[
            Manager(user_id="u1", display_name="dbdev", team_name=None, roster_id=1, is_commissioner=True),
            Manager(user_id="u2", display_name="rival", team_name="Rivals", roster_id=2, is_commissioner=False),
        ],
        rosters=[
            {"roster_id": 1, "owner_id": "u1", "players": ["rb0", "wr0"], "settings": {"waiver_position": 8}},
            {"roster_id": 2, "owner_id": "u2", "players": ["rb1", "wr1"], "settings": {"waiver_position": 1}},
        ],
        my_user_id="u1",
    )
