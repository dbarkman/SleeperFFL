from __future__ import annotations

import pytest

from sleeperffl.draft import (
    DraftState,
    format_pick,
    linear_picks,
    pick_number,
    resolve_my_slot,
    round_and_slot,
    slot_picks,
)


def test_snake_pick_numbers_reverse_on_even_rounds():
    # 8 teams: slot 1 picks 1st in round 1 and 16th overall in round 2.
    assert pick_number(1, 1, 8) == 1
    assert pick_number(2, 1, 8) == 16
    assert pick_number(3, 1, 8) == 17
    # Slot 8 is the turn: picks 8 and 9 back to back.
    assert pick_number(1, 8, 8) == 8
    assert pick_number(2, 8, 8) == 9


def test_slot_picks_covers_every_round():
    picks = slot_picks(3, 8, 15)
    assert len(picks) == 15
    assert picks[:4] == [3, 14, 19, 30]
    assert picks == sorted(picks)


def test_linear_draft_does_not_reverse():
    assert linear_picks(3, 8, 3) == [3, 11, 19]


@pytest.mark.parametrize("teams", [8, 10, 12, 14])
def test_round_and_slot_inverts_pick_number(teams):
    for round_no in range(1, 16):
        for slot in range(1, teams + 1):
            overall = pick_number(round_no, slot, teams)
            assert round_and_slot(overall, teams) == (round_no, slot)


def test_format_pick_is_human_readable():
    assert format_pick(1, 8) == "1.01"
    assert format_pick(9, 8) == "2.08"
    assert format_pick(16, 8) == "2.01"


def _state(picks, slot=3, teams=8, rounds=15):
    return DraftState(
        draft_id="D1",
        teams=teams,
        rounds=rounds,
        snake=True,
        my_slot=slot,
        picks=picks,
        status="drafting",
    )


def test_picks_until_my_turn_counts_down():
    assert _state([]).picks_until_my_turn() == 2
    assert _state([{"player_id": "a"}]).picks_until_my_turn() == 1
    assert _state([{"player_id": "a"}, {"player_id": "b"}]).picks_until_my_turn() == 0
    assert _state([{"player_id": "a"}, {"player_id": "b"}]).is_my_turn()


def test_my_next_picks_spans_the_snake_turn():
    state = _state([{"player_id": str(i)} for i in range(2)])
    assert state.my_next_picks(2) == [3, 14]


def test_my_drafted_ids_filters_by_slot():
    picks = [
        {"player_id": "a", "draft_slot": 1},
        {"player_id": "b", "draft_slot": 3},
        {"player_id": "c", "draft_slot": 3},
    ]
    assert _state(picks).my_drafted_ids() == ["b", "c"]


def test_resolve_slot_prefers_draft_order():
    draft = {"draft_order": {"u1": 5}}
    assert resolve_my_slot(draft, [], "u1") == 5


def test_resolve_slot_falls_back_to_picks_when_order_is_null():
    # draft_order stays null until the commissioner sets it, which is the
    # normal state for a league that is still filling up.
    draft = {"draft_order": None}
    picks = [{"picked_by": "u1", "draft_slot": 4, "player_id": "a"}]
    assert resolve_my_slot(draft, picks, "u1") == 4
    assert resolve_my_slot(draft, [], "u1") is None


def test_draft_is_complete_when_every_pick_is_in():
    state = _state([{"player_id": str(i)} for i in range(120)])
    assert state.is_complete
