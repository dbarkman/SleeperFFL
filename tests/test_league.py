from __future__ import annotations

import pytest

from sleeperffl.league import load_league, resolve_league_id


def test_starting_slots_exclude_the_bench(league):
    assert "BN" not in league.starting_slots
    assert len(league.starting_slots) == 10
    assert league.bench_size == 5


def test_dedicated_starters_scale_with_league_size(league):
    assert league.dedicated_starters("RB") == 16   # 2 per team x 8
    assert league.dedicated_starters("QB") == 8
    assert league.dedicated_starters("DEF") == 8


def test_flex_slots_are_counted_leaguewide(league):
    assert league.flex_slots() == {"FLEX": 16}


def test_waiver_type_is_read_from_settings(league):
    assert league.waiver_type == "rolling waiver priority"
    assert not league.uses_faab
    assert league.my_faab_remaining is None

    league.settings["waiver_type"] = 2
    assert league.uses_faab
    # 100 budget, nothing used yet.
    assert league.my_faab_remaining == 100


def test_my_roster_is_found_by_owner_id(league):
    assert league.my_roster_id == 1
    assert league.my_waiver_position == 8


def test_waiver_order_is_sorted_by_priority(league):
    assert league.waiver_order() == [(1, 2), (8, 1)]


def test_rostered_player_ids_spans_every_team(league):
    assert league.rostered_player_ids() == {"rb0", "wr0", "rb1", "wr1"}


def test_manager_lookup_by_roster(league):
    assert league.manager_for_roster(2).label == "Rivals"
    assert league.manager_for_roster(99) is None


class _FakeClient:
    def __init__(self, leagues):
        self._leagues = leagues

    def leagues(self, user_id, season, sport="nfl"):
        return self._leagues


def test_resolve_league_id_uses_the_only_league():
    client = _FakeClient([{"league_id": "L9", "name": "Only"}])
    assert resolve_league_id(client, "u1", "2026", None) == "L9"


def test_resolve_league_id_prefers_an_explicit_id():
    client = _FakeClient([{"league_id": "L9", "name": "Only"}])
    assert resolve_league_id(client, "u1", "2026", "L1") == "L1"


def test_resolve_league_id_asks_when_ambiguous():
    client = _FakeClient([
        {"league_id": "L1", "name": "A"},
        {"league_id": "L2", "name": "B"},
    ])
    with pytest.raises(RuntimeError, match="pass --league-id"):
        resolve_league_id(client, "u1", "2026", None)


def test_resolve_league_id_reports_when_there_are_none():
    with pytest.raises(RuntimeError, match="No NFL leagues"):
        resolve_league_id(_FakeClient([]), "u1", "2026", None)
