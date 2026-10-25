from datetime import datetime, timezone

import pytest

import app.contests as contests

pytestmark = pytest.mark.anyio


def _contest(cid, fee, size, pool, mec=1, tmpl=None, game_type="Classic", attr=None, dg=1, sd=1792342800000):
    return {"id": cid, "n": f"Contest {cid}", "a": fee, "m": size, "po": pool, "mec": mec, "nt": 3,
            "tmpl": tmpl or cid, "gameType": game_type, "attr": attr or {"IsGuaranteed": "true"},
            "sd": f"/Date({sd})/", "sdstring": "Sun 1:00PM", "dg": dg}


def _payouts(paid, top=100.0):
    return {"contestDetail": {"payoutSummary": [
        {"minPosition": 1, "maxPosition": 1, "payoutDescriptions": [{"value": top}]},
        {"minPosition": 2, "maxPosition": paid, "payoutDescriptions": [{"value": 5}]}]}}


@pytest.fixture
def lobby(monkeypatch):
    """Serves a fake lobby and per-contest payout tables ({id: (paid places, first prize)})."""
    state = {"lobby": {}, "payouts": {}}

    async def fake_get_json(url):
        if "lobby" in url:
            return state["lobby"]
        paid, top = state["payouts"][int(url.rsplit("/", 1)[1].split("?")[0])]
        return _payouts(paid, top)

    async def no_cache(key, ttl, fetch, **kwargs):
        return await fetch()

    monkeypatch.setattr(contests, "_get_json", fake_get_json)
    monkeypatch.setattr(contests, "cached_fetch", no_cache)
    monkeypatch.setattr(contests, "_PAYOUTS", {})
    monkeypatch.setattr(contests, "_now", lambda: datetime(2026, 10, 18, 12, tzinfo=timezone.utc))
    return state


def test_gpp_filter_keeps_boosters_leagues_qualifiers_but_drops_cash_h2h_and_other_game_types():
    assert contests.is_gpp(_contest(1, 5, 100, 450))
    assert contests.is_gpp(_contest(1, 5, 100, 450, game_type="Showdown Captain Mode"))
    assert not contests.is_gpp(_contest(1, 5, 100, 450, attr={"IsDoubleUp": "true"}))
    assert not contests.is_gpp(_contest(1, 5, 100, 450, attr={"IsFiftyfifty": "true", "League": "true"}))
    assert contests.is_gpp(_contest(1, 5, 100, 450, attr={"League": "true"}))
    assert contests.is_gpp(_contest(1, 5, 100, 450, attr={"IsQualifier": "true"}))
    assert contests.is_gpp(_contest(1, 5, 100, 450, attr={"Multiplier": "true"}))
    assert not contests.is_gpp(_contest(1, 5, 2, 9))
    assert not contests.is_gpp(_contest(1, 0, 100, 50))
    assert not contests.is_gpp(_contest(1, 5, 100, 450, game_type="Snake"))
    assert not contests.is_gpp(_contest(1, 5, 100, 450, attr={"IsBeginner": "true", "League": "true"}))
    assert not contests.is_gpp(_contest(1, 5, 100, 450, attr={"IsCasual": "true"}))


def test_cash_games_are_listed_and_named_by_kind():
    fifty = {**_contest(1, 5, 100, 450, attr={"IsDoubleUp": "true", "IsFiftyfifty": "true"}), "n": "NFL $5 50-50 [50 Entry Max]"}
    double = {**_contest(2, 5, 100, 450, attr={"IsDoubleUp": "true", "IsFiftyfifty": "true"}), "n": "NFL Single Entry $5 Double Up"}
    triple = {**_contest(3, 10, 31, 270, attr={"Multiplier": "true"}), "n": "NFL Showdown $10 Triple Up [Top 9 Win $30] (PIT vs NO)"}
    booster = {**_contest(4, 5, 100, 450, attr={"Multiplier": "true"}), "n": "NFL 10x Booster"}
    h2h = {**_contest(5, 5, 2, 9, attr={"IsDoubleUp": "true", "IsFiftyfifty": "true"}), "n": "NFL $5 Double Up"}
    beginner = {**_contest(6, 5, 100, 450, attr={"IsDoubleUp": "true", "IsBeginner": "true"}), "n": "Beginner NFL $5 Double Up"}
    assert [contests.is_cash(c) for c in (fifty, double, triple, booster, h2h, beginner)] == [True, True, True, False, False, False]
    assert not contests.is_gpp(triple) and contests.is_gpp(booster)
    assert [contests._row(c)["kind"] for c in (fifty, double, triple, booster)] == ["50/50", "Double Up", "Triple Up", "Booster"]


def test_cash_games_are_scored_against_cash_games():
    gpp = {"kind": "Tournament", "rake": 0.15, "paid_pct": 0.22, "top_multiple": 1000.0, "field_size": 50000, "prize_pool": 1.0}
    cash = {"kind": "Double Up", "rake": 0.12, "paid_pct": 0.45, "top_multiple": 1.8, "field_size": 100, "prize_pool": 1.0}
    rows = contests.score_contests([{**gpp, "id": 1}, {**gpp, "id": 2, "rake": 0.20},
                                    {**cash, "id": 3}, {**cash, "id": 4, "rake": 0.16}])
    score = {r["id"]: r["score"] for r in rows}
    # The cheaper of each pair is best of its family, whatever the other family's payout share.
    assert score[1] == score[3] > score[2] == score[4]


def test_groups_cover_every_fee_and_entry_limit():
    assert [contests.entry_group(n) for n in (1, 2, 10, 11, 20, 21, 150, 151)] == \
        ["se", "2-10", "2-10", "20", "20", "150", "150", None]
    assert [contests.fee_group(f) for f in (0.1, 0.5, 1, 4, 5, 5.5, 6, 10, 11, 12, 25, 27)] == \
        ["under1", "under1", "1-5", "1-5", "1-5", "6-10", "6-10", "6-10", "11-25", "11-25", "11-25", "over25"]


async def test_score_weighs_rake_share_paid_and_top_prize(lobby):
    lobby["lobby"] = {"Contests": [
        _contest(1, 3, 100, 255),             # 15% rake
        _contest(2, 3, 100, 270, tmpl=20),    # 10% rake
        _contest(3, 3, 100, 270, tmpl=30),    # 10% rake (tied with 2), pays more of the field and more to first
        _contest(4, 3, 100, 270, attr={"IsFiftyfifty": "true"}),
        _contest(5, 50, 100, 4500, mec=150, attr={"Multiplier": "true"}),
    ], "DraftGroups": [{"DraftGroupId": 1, "ContestStartTimeSuffix": " (Thu-Mon)"}]}
    lobby["payouts"] = {1: (22, 60.0), 2: (20, 60.0), 3: (25, 90.0), 5: (20, 500.0)}

    result = await contests.best_contests(frozenset({"se"}), frozenset({"1-5"}), frozenset(contests.CASH_KINDS))
    rows = result["contests"]
    assert [c["id"] for c in rows] == [3, 2, 1]
    assert rows[0]["score"] == 90.0 and rows[0]["paid_pct"] == 0.25 and rows[0]["top_multiple"] == 30.0
    assert rows[0]["slate"] == "Thu-Mon" and rows[0]["kind"] == "Tournament"
    assert result["matching"] == 3

    everything = await contests.best_contests()
    assert {c["id"] for c in everything["contests"]} == {1, 2, 3, 4, 5}      # the 50/50-flagged one too
    both = await contests.best_contests(frozenset({"se", "150"}), frozenset({"1-5", "over25"}))
    assert {(c["id"], c["kind"]) for c in both["contests"]} >= {(5, "Booster")}


def test_percentile_ranks_share_ties():
    assert contests._pct_ranks([1, 2, 2, 3]) == [0.0, 0.5, 0.5, 1.0]
    assert contests._pct_ranks([7]) == [1.0]


async def test_free_contests_keep_only_cash_prizes(lobby):
    cash = {**_contest(7, 0, 999999999, 2000), "pd": {"Cash": "$2,000"}}
    no_prize = {**_contest(8, 0, 200, 0), "pd": {}}
    ticket = {**_contest(9, 0, 100, 20), "pd": {"Ticket": "1 Ticket"}}
    paid = {**_contest(10, 5, 100, 450), "pd": {"Cash": "$450"}}
    beginner = {**_contest(11, 0, 100, 50, attr={"IsBeginner": "true"}), "pd": {"Cash": "$50"}}
    lobby["lobby"] = {"Contests": [ticket, cash, no_prize, paid, beginner], "DraftGroups": []}
    rows = (await contests.free_contests())["contests"]
    assert [(r["id"], r["cash"]) for r in rows] == [(7, "$2,000")]


async def test_excluded_kinds_are_left_out(lobby):
    lobby["lobby"] = {"Contests": [
        _contest(1, 3, 100, 270, attr={"IsQualifier": "true"}),
        _contest(2, 3, 100, 255),
    ], "DraftGroups": []}
    lobby["payouts"] = {1: (20, 100.0), 2: (20, 100.0)}
    assert [c["id"] for c in (await contests.best_contests())["contests"]] == [1, 2]
    result = await contests.best_contests(exclude=frozenset({"Qualifier"}))
    assert [c["id"] for c in result["contests"]] == [2]
    assert result["selected"]["excluded"] == ["Qualifier"]


def test_copies_on_other_slates_collapse_into_one_contest():
    def row(cid, name, slate, entries, start="2026-10-18T17:00:00+00:00", tmpl=7, paid=1):
        return {"id": cid, "name": name, "slate": slate, "entries": entries, "start_utc": start, "template_id": tmpl,
                "entry_fee": 2.0, "field_size": 11, "prize_pool": 20.0, "paid_places": paid, "top_prize": 20.0}

    rows = contests.collapse_copies([
        row(1, "NFL Showdown Sat (SEA @ DEN)", "SEA @ DEN", 3, start="2026-10-16T00:15:00+00:00"),
        row(2, "NFL Showdown Sat (SEA @ DEN)", "SEA @ DEN", 5, start="2026-10-16T00:15:00+00:00"),
        row(3, "NFL Showdown Sat (CHI @ ATL)", "CHI @ ATL", 9, tmpl=9),   # another template, same payouts
        row(4, "NFL Sat", "Main", 1),
        row(5, "NFL Sat (Early Only)", "Early Only", 2),
        row(6, "NFL Sat", "Main", 4, paid=2),           # different payouts: its own contest
    ])
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {3, 5, 6}
    assert by_id[3]["copies"] == 3 and by_id[3]["slates"] == ["SEA @ DEN", "CHI @ ATL"]
    assert by_id[3]["title"] == "NFL Showdown Sat" and by_id[6]["title"] == "NFL Sat"
    assert by_id[5]["copies"] == 2 and by_id[5]["slates"] == ["Early Only", "Main"]
    assert by_id[6]["copies"] == 1 and by_id[6]["slates"] == ["Main"]


def test_weights_change_the_order():
    rows = [
        {"id": 1, "rake": 0.05, "paid_pct": 0.20, "top_multiple": 100.0, "field_size": 5000, "prize_pool": 1.0},
        {"id": 2, "rake": 0.15, "paid_pct": 0.40, "top_multiple": 3.0, "field_size": 5, "prize_pool": 1.0},
    ]
    assert [r["id"] for r in contests.score_contests(rows)] == [1, 2]
    assert [r["id"] for r in contests.score_contests(rows, {"field": 5})] == [2, 1]
    assert [r["id"] for r in contests.score_contests(rows, {"rake": 1, "paid": 9})] == [2, 1]
    assert contests.score_contests(rows, {"rake": 10})[0]["score"] == 100.0


def test_weights_normalize_and_fall_back_to_defaults():
    assert contests.normalize_weights({"rake": 2, "field": 2}) == {"rake": 0.5, "paid": 0.0, "payout": 0.0, "field": 0.5}
    assert contests.normalize_weights({"rake": 0}) == contests.normalize_weights(None)
    assert contests.normalize_weights(None)["rake"] == 0.4


async def test_selected_slate_first_and_started_slates_dropped(lobby):
    sunday_night = 1792372800000                                   # 2026-10-19 01:20 UTC
    lobby["lobby"] = {"Contests": [
        _contest(1, 3, 100, 270, tmpl=10),                         # Main, 10% rake: the best overall
        _contest(2, 3, 100, 255, tmpl=20, dg=2, sd=sunday_night),  # Sunday night, 15% rake
        _contest(3, 3, 100, 240, tmpl=30, dg=2, sd=sunday_night),  # Sunday night, 20% rake
        _contest(4, 3, 100, 285, tmpl=40, dg=3, sd=1792256400000), # 2026-10-17: already started
    ], "DraftGroups": []}
    lobby["payouts"] = {1: (20, 100.0), 2: (20, 100.0), 3: (20, 100.0), 4: (20, 100.0)}

    plain = await contests.best_contests()
    assert [c["id"] for c in plain["contests"]] == [1, 2, 3] and plain["selected_slate"] is None
    picked = await contests.best_contests(draft_group_id=2)
    assert [c["id"] for c in picked["contests"]] == [2, 3, 1]
    assert [c["on_selected_slate"] for c in picked["contests"]] == [True, True, False]
    assert picked["selected_slate"] == {"draft_group_id": 2, "matching": 2}


def test_collapsed_contest_opens_the_selected_slates_copy():
    def row(cid, dg, entries):
        return {"id": cid, "name": "NFL Sat", "slate": f"S{dg}", "entries": entries, "start_utc": None, "template_id": 7,
                "entry_fee": 2.0, "field_size": 11, "prize_pool": 20.0, "paid_places": 1, "top_prize": 20.0,
                "draft_group_id": dg}
    [r] = contests.collapse_copies([row(1, 1, 9), row(2, 2, 3)], draft_group_id=2)
    assert r["id"] == 2 and r["on_selected_slate"] and r["copies"] == 2
