import asyncio
from types import SimpleNamespace

import pytest

from app import slate_leverage as sl


def _row(pid, name, slot, salary, final, ceiling, own, pos="WR", team="SF", opp="MIN", actual=False):
    return {"id": pid, "name": name, "team": team, "opponent": opp, "position": pos, "salary": salary, "slot": slot,
            "final": final, "floor": None, "ceiling": ceiling, "own": own, "own_is_actual": actual}


ROWS = [
    # Captain ids (scored x1.5) and Flex ids for the same three players
    _row(101, "Star", "CPT", 15000, 30.0, 48.0, 0.45), _row(102, "Value", "CPT", 9000, 15.0, 30.0, 0.05),
    _row(103, "Dud", "CPT", 7500, 6.0, 12.0, 0.50),
    _row(201, "Star", "FLEX", 10000, 20.0, 32.0, 0.90), _row(202, "Value", "FLEX", 6000, 10.0, 20.0, 0.30),
    _row(203, "Dud", "FLEX", 5000, 4.0, 8.0, 0.80),
]


def test_each_player_gets_a_number_on_both_his_captain_and_flex_id():
    out = sl.showdown(ROWS, None)
    assert set(out) == {101, 102, 103, 201, 202, 203}
    assert {out[i]["slot"] for i in (101, 102, 103)} == {"CPT"} and {out[i]["slot"] for i in (201, 202, 203)} == {"FLEX"}
    assert out[101]["leverage_detail"]["slot"] == "CPT" and out[201]["name"] == "Star"


def test_captain_and_flex_redistribute_their_own_ownership_separately():
    out = sl.showdown(ROWS, None)
    for ids, pool in (((101, 102, 103), 1.0), ((201, 202, 203), 2.0)):
        assert abs(sum(out[i]["leverage_detail"]["fair_own"] for i in ids) - pool * 100) < 0.3     # fair keeps the slot's pool
        assert abs(sum(out[i]["leverage"] for i in ids)) < 0.3                                      # so leverage nets to zero in each slot


def test_a_player_with_real_upside_beats_the_dud_the_field_loves():
    out = sl.showdown(ROWS, None)
    assert out[102]["leverage"] > 0 > out[103]["leverage"]          # cheap Captain with odds vs the 50%-owned dud
    assert out[202]["leverage"] > 0 > out[203]["leverage"]


def test_hit_odds_use_each_slots_own_scoring_bar():
    assert sl.showdown_target("QB", "FLEX") > sl.showdown_target("TE", "FLEX")
    assert sl.showdown_target("QB", "CPT") == sl.showdown_target("RB", "CPT") == sl.CPT_TARGET > sl.showdown_target("QB", "FLEX")
    out = sl.showdown(ROWS, None)
    # the Captain's x1.5 line clears the Captain bar less often than the Flex line clears its own: not the same odds
    assert out[101]["leverage_detail"]["p"] != out[201]["leverage_detail"]["p"]


def test_players_without_ownership_or_a_slot_are_left_out():
    rows = ROWS + [_row(301, "No Own", "FLEX", 4000, 5.0, 9.0, None), _row(302, "No Slot", "", 4000, 5.0, 9.0, 0.1)]
    assert not {301, 302} & set(sl.showdown(rows, None))


def test_actual_ownership_replaces_the_projection_and_is_flagged():
    out = sl.showdown([_row(1, "A", "FLEX", 6000, 10.0, 20.0, 0.12, actual=True), _row(2, "B", "FLEX", 6000, 10.0, 20.0, 0.12)], None)
    assert out[1]["leverage_detail"]["own_is_actual"] is True and out[2]["leverage_detail"]["own_is_actual"] is False


def test_pool_rows_take_ownership_as_percent_and_prefer_uploaded_actuals():
    players = [SimpleNamespace(dk_draftable_id=1, name="A", team="SF", opponent="MIN", position="WR", salary=6000, roster_slot="FLEX",
                               proj_points=10.0, ceiling=20.0),
               SimpleNamespace(dk_draftable_id=2, name="A", team="SF", opponent="MIN", position="WR", salary=9000, roster_slot="CPT",
                               proj_points=15.0, ceiling=30.0),
               SimpleNamespace(dk_draftable_id=3, name="Gone", team="SF", opponent="MIN", position="WR", salary=4000, roster_slot="FLEX",
                               proj_points=3.0, ceiling=6.0)]
    own = {1: {"own": 22.0, "actual": 30.0}, 2: {"own": 8.0, "actual": None}}
    rows = {r["id"]: r for r in sl.showdown_rows(players, own)}
    assert set(rows) == {1, 2}                                              # id 3 has no ownership
    assert rows[1]["own"] == pytest.approx(0.30) and rows[1]["own_is_actual"] is True
    assert rows[2]["own"] == pytest.approx(0.08) and rows[2]["own_is_actual"] is False


def test_classic_leverage_is_the_plays_pages_by_id():
    plays = {"players": [{"id": 5, "name": "A", "team": "BUF", "leverage": 2.4, "leverage_detail": {"fair_own": 9.0}},
                         {"id": 6, "name": "B", "team": "BUF", "leverage": None}]}
    assert sl.classic(plays) == {5: {"name": "A", "team": "BUF", "leverage": 2.4, "leverage_detail": {"fair_own": 9.0}, "slot": None}}
