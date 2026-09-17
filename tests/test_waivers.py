from __future__ import annotations

import time

from sleeperffl.waivers import (
    WatcherState,
    detect_alerts,
    free_agents,
    rank_free_agents,
    update_state,
    waiver_advice,
    weakest_rostered_by_position,
)


def test_free_agents_excludes_everyone_rostered(league, pool):
    available = {p.player_id for p in free_agents(league, pool)}
    for owned in ("rb0", "wr0", "rb1", "wr1"):
        assert owned not in available
    assert "rb2" in available


def test_free_agents_includes_ir_and_taxi_as_owned(league, pool):
    league.rosters[0]["reserve"] = ["rb2"]
    league.rosters[1]["taxi"] = ["wr2"]
    available = {p.player_id for p in free_agents(league, pool)}
    assert "rb2" not in available
    assert "wr2" not in available


def test_rank_free_agents_orders_by_value(league, pool):
    rows = rank_free_agents(league, pool, limit=5)
    values = [value for _, value in rows]
    assert values == sorted(values, reverse=True)
    assert rows[0][0].player_id == "rb2"


def test_first_run_records_a_baseline_without_alerting(league, pool):
    state = WatcherState()
    alerts = detect_alerts(league, pool, state, trending_add=[])
    assert alerts == []
    update_state(state, league, pool, alerts)
    assert state.initialised
    assert "rb0" in state.rostered


def test_dropped_player_is_detected_on_the_next_run(league, pool):
    state = WatcherState()
    update_state(state, league, pool, [])

    # The rival cuts a good running back.
    league.rosters[1]["players"] = []

    alerts = detect_alerts(league, pool, state, trending_add=[])
    dropped = [a for a in alerts if a.kind == "dropped"]
    assert {a.player.player_id for a in dropped} == {"rb1", "wr1"}
    assert dropped[0].priority == "high"
    assert "vs replacement" in dropped[0].detail


def test_a_drop_is_not_re_alerted_within_the_cooldown(league, pool):
    state = WatcherState()
    update_state(state, league, pool, [])
    league.rosters[1]["players"] = []

    first = detect_alerts(league, pool, state, trending_add=[])
    update_state(state, league, pool, first)
    second = detect_alerts(league, pool, state, trending_add=[])
    assert second == []


def test_low_value_drops_are_ignored(league, pool):
    state = WatcherState()
    league.rosters[1]["players"] = ["rb39"]
    update_state(state, league, pool, [])
    league.rosters[1]["players"] = []
    alerts = detect_alerts(league, pool, state, trending_add=[], min_vor=0.0)
    assert alerts == []


def test_injury_to_a_starter_surfaces_the_backup(league, pool):
    state = WatcherState()
    update_state(state, league, pool, [])

    # rb0 is on our roster and goes down; rb2 is the free agent behind him.
    pool["rb0"].injury_status = "IR"
    alerts = detect_alerts(league, pool, state, trending_add=[])
    openings = [a for a in alerts if a.kind == "injury_opening"]
    assert openings
    assert all(a.player.team == "DET" for a in openings)
    assert "IR" in openings[0].detail


def test_trending_surge_flags_an_available_player(league, pool):
    # Give "my" roster a weak back so rb5 is a genuine upgrade.
    league.rosters[0]["players"] = ["rb0", "rb30", "wr0"]
    state = WatcherState()
    update_state(state, league, pool, [])
    trending = [{"player_id": "rb5", "count": 91234}]
    alerts = detect_alerts(league, pool, state, trending_add=trending)
    assert [a.player.player_id for a in alerts if a.kind == "trending"] == ["rb5"]
    assert "91,234" in alerts[0].detail


def test_trending_player_already_rostered_is_not_flagged(league, pool):
    state = WatcherState()
    update_state(state, league, pool, [])
    alerts = detect_alerts(league, pool, state, trending_add=[{"player_id": "rb0", "count": 5000}])
    assert alerts == []


def test_one_alert_per_player_with_the_strongest_reason_winning(league, pool):
    state = WatcherState()
    update_state(state, league, pool, [])
    league.rosters[1]["players"] = []
    trending = [{"player_id": "rb1", "count": 40000}]
    alerts = detect_alerts(league, pool, state, trending_add=trending)
    rb1_alerts = [a for a in alerts if a.player.player_id == "rb1"]
    assert len(rb1_alerts) == 1
    assert rb1_alerts[0].kind == "dropped"


def test_state_round_trips_through_disk(tmp_path, league, pool):
    path = tmp_path / "watch.json"
    state = WatcherState()
    update_state(state, league, pool, [])
    state.save(path)

    reloaded = WatcherState.load(path)
    assert reloaded.rostered == state.rostered
    assert reloaded.initialised


def test_corrupt_state_file_falls_back_to_a_fresh_baseline(tmp_path):
    path = tmp_path / "watch.json"
    path.write_text("{not json")
    state = WatcherState.load(path)
    assert not state.initialised
    assert state.rostered == set()


def test_stale_alerts_are_forgotten_after_a_week(league, pool):
    state = WatcherState()
    state.alerted = {"old": time.time() - 8 * 24 * 3600, "fresh": time.time()}
    update_state(state, league, pool, [])
    assert "old" not in state.alerted
    assert "fresh" in state.alerted


def test_waiver_advice_matches_a_rolling_priority_league(league):
    """Never use bidding language in a league that does not bid."""
    assert not league.uses_faab
    advice = waiver_advice(league, value=40.0, rank_among_fa=1)
    assert "waiver #8 of 8" in advice
    assert "$" not in advice
    assert "bid" not in advice.lower()


def test_back_of_the_queue_claims_are_described_as_cheap(league):
    # Roster 1 holds priority 8 of 8 — already last, so a claim costs nothing.
    advice = waiver_advice(league, value=40.0, rank_among_fa=1)
    assert "costs you nothing" in advice


def test_good_priority_is_described_as_worth_protecting(league):
    league.rosters[0]["settings"]["waiver_position"] = 2
    top = waiver_advice(league, value=40.0, rank_among_fa=1)
    assert "Worth spending waiver #2 of 8" in top

    marginal = waiver_advice(league, value=2.0, rank_among_fa=9)
    assert "wait the 2 days" in marginal


def test_waiver_advice_switches_to_bids_in_a_faab_league(league):
    league.settings["waiver_type"] = 2
    assert league.uses_faab
    advice = waiver_advice(league, value=50.0, rank_among_fa=1)
    assert "$" in advice


def test_trending_kickers_and_defenses_are_never_flagged(league, pool):
    """Every league streams them; the whole position is worth a few points."""
    state = WatcherState()
    update_state(state, league, pool, [])
    trending = [{"player_id": "k0", "count": 80000}, {"player_id": "def0", "count": 70000}]
    assert detect_alerts(league, pool, state, trending_add=trending, min_vor=-999) == []


def test_dropped_kicker_is_still_reported(league, pool):
    """The skip only applies to national hype, not to real league movement."""
    league.rosters[1]["players"] = ["k0"]
    state = WatcherState()
    update_state(state, league, pool, [])
    league.rosters[1]["players"] = []
    alerts = detect_alerts(league, pool, state, trending_add=[], min_vor=-999)
    assert [a.player.player_id for a in alerts] == ["k0"]


def test_trending_player_worse_than_my_weakest_is_not_flagged(league, pool):
    # My only RB projects 300; rb5 at 270 would not improve the roster.
    state = WatcherState()
    update_state(state, league, pool, [])
    alerts = detect_alerts(league, pool, state, trending_add=[{"player_id": "rb5", "count": 50000}])
    assert alerts == []


def test_trending_at_a_position_i_do_not_roster_is_flagged(league, pool):
    # No quarterback on my roster, so there is no floor to beat.
    state = WatcherState()
    update_state(state, league, pool, [])
    alerts = detect_alerts(league, pool, state, trending_add=[{"player_id": "qb1", "count": 40000}])
    assert [a.player.player_id for a in alerts] == ["qb1"]


def test_weakest_rostered_by_position(league, pool):
    league.rosters[0]["players"] = ["rb0", "rb30", "wr0", "not-in-pool"]
    weakest = weakest_rostered_by_position(league, pool)
    assert weakest == {"RB": pool["rb30"].proj_season, "WR": pool["wr0"].proj_season}
