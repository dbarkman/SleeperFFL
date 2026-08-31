from __future__ import annotations

from sleeperffl.draft import DraftState, recommend


def _state(picks, slot=3, teams=8, rounds=15):
    return DraftState(
        draft_id="D1", teams=teams, rounds=rounds, snake=True,
        my_slot=slot, picks=picks, status="drafting",
    )


def _pick(player_id, pick_no, slot):
    return {"player_id": player_id, "pick_no": pick_no, "draft_slot": slot, "round": 1}


def test_recommends_the_best_available_at_the_top_of_the_draft(league, pool):
    recs = recommend(league, pool, _state([], slot=1), limit=3)
    assert recs[0].player.player_id == "rb0"
    assert recs[0].vor > 0


def test_never_recommends_a_player_already_drafted(league, pool):
    taken = [_pick(f"rb{i}", i + 1, i + 1) for i in range(3)]
    recs = recommend(league, pool, _state(taken, slot=4), limit=10)
    assert {"rb0", "rb1", "rb2"}.isdisjoint({r.player.player_id for r in recs})


def test_vona_demotes_a_player_whose_position_is_deep(league, pool):
    """The whole point of the tool: prefer the position that dries up first.

    TEs fall off a cliff after the top few; the WR pool is flat. So even when a
    WR projects higher, a top TE can carry more value-over-next-available.
    """
    recs = recommend(league, pool, _state([], slot=1), limit=60)
    by_id = {r.player.player_id: r for r in recs}
    te = by_id["te0"]
    wr = by_id["wr3"]
    assert te.player.proj_season < wr.player.proj_season
    assert te.vona > wr.vona


def test_kickers_and_defenses_are_kept_out_of_the_early_rounds(league, pool):
    recs = recommend(league, pool, _state([], slot=1), limit=30)
    assert all(r.player.position not in ("K", "DEF") for r in recs)


def test_kicker_surfaces_once_the_roster_is_otherwise_full(league, pool):
    """With one pick left and every skill slot filled, take the kicker."""
    my_slot = 1
    picks = []
    mine = ["rb0", "rb1", "wr0", "wr1", "qb0", "te0", "rb2", "wr2", "rb3", "wr3",
            "rb4", "wr4", "qb1", "te1"]
    pick_no = 0
    for index, player_id in enumerate(mine):
        pick_no += 1
        picks.append(_pick(player_id, pick_no, my_slot))
        # Fill the rest of the round with other teams' picks.
        for other in range(2, 9):
            pick_no += 1
            picks.append(_pick(f"filler{index}_{other}", pick_no, other))

    state = _state(picks, slot=my_slot)
    recs = recommend(league, pool, state, limit=5)
    assert recs[0].player.position in ("K", "DEF")


def test_positional_cap_stops_a_third_quarterback(league, pool):
    my_slot = 1
    picks = [_pick("qb0", 1, my_slot), _pick("qb1", 16, my_slot)]
    recs = recommend(league, pool, _state(picks, slot=my_slot), limit=10)
    assert all(r.player.position != "QB" for r in recs)


def test_reason_explains_the_pick(league, pool):
    recs = recommend(league, pool, _state([], slot=1), limit=1)
    reason = recs[0].reason
    assert "starter open" in reason
    assert "%" in reason


def test_last_pick_of_the_draft_still_returns_a_recommendation(league, pool):
    """No following pick means no VONA baseline — must not divide by zero."""
    my_slot = 1
    picks = [_pick(f"x{i}", i + 1, (i % 8) + 1) for i in range(119)]
    state = _state(picks, slot=my_slot)
    assert state.my_next_picks(2) == [120] or state.my_next_picks(2) == []
    recs = recommend(league, pool, state, limit=3)
    assert recs
