from datetime import datetime, timezone
from pathlib import Path

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
    # The cheaper of each pair wins within its family, whatever the other family's payout share.
    assert score[1] > score[2] and score[3] > score[4]
    assert score[3] > score[2]                               # a cheap Double Up isn't buried under tournaments


def test_bigger_cash_games_rank_higher_and_tournaments_keep_the_users_field_setting():
    du = {"kind": "Double Up", "rake": 0.13, "paid_pct": 0.435, "top_multiple": 2.0, "prize_pool": 1.0}
    gpp = {"kind": "Tournament", "rake": 0.15, "paid_pct": 0.22, "top_multiple": 100.0, "prize_pool": 1.0}
    rows = [{**du, "id": 1, "field_size": 23}, {**du, "id": 2, "field_size": 2873}, {**du, "id": 3, "field_size": 287},
            {**gpp, "id": 4, "field_size": 100}, {**gpp, "id": 5, "field_size": 50000}]
    order = [r["id"] for r in contests.score_contests(rows) if r["kind"] == "Double Up"]
    assert order == [2, 3, 1]                                        # bigger double ups first, same rake
    small = {r["id"]: r["score"] for r in contests.score_contests(rows, {"rake": 4, "paid": 3, "payout": 3, "field": 5})}
    assert small[4] > small[5]                                       # "small field" still means small for tournaments
    assert small[2] > small[1]


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


# DraftKings' Thursday-night grade sheet: (grade, fee, max entries, field, rake, cashout, first prize / pool).
# Showdown $ names dropped; pool is taken as first prize / (% to 1st).
_SHEET = """B 50 1 681 3000 10.0
B 3180 4 134 100000 24.9
B 50 1 340 1500 10.0
B 200 1 222 10000 25.0
B 75 5 227 3000 20.0
B 150 5 296 7500 18.8
C 100 1 444 10000 25.0
C 5 1 2378 1000 10.0
C 100 1 1111 20000 20.0
C 3 1 3963 1000 10.0
C 20 5 1176 2000 10.0
C 444 5 400 50000 31.3
C 1 1 5945 500 10.0
C 5 1 9512 4000 10.0
D 0.25 20 35671 300 4.0
D 4 5 4458 1500 10.0
D 1 5 5945 500 10.0
D 15 1 1568 5000 25.0
D 333 50 1668 100000 20.0
D 2 20 5945 1000 10.0
D 0.1 20 47562 200 5.0
D 15 1 2745 10000 28.6
F 1 20 59453 2500 5.0
F 3 20 99088 25000 10.0
F 33 105 3533 20000 20.0
F 0.5 150 237812 10000 10.0
F 5 150 71343 50000 16.7
F 20 150 73529 300000 24.0"""


def test_grades_match_the_draftkings_sheet():
    rows, want = [], []
    for i, line in enumerate(_SHEET.splitlines()):
        grade, fee, mec, field, first, pct = line.split()
        rows.append({"id": i, "kind": "Tournament", "slate": "JAX @ BAL", "game_type": "Showdown Captain Mode", "max_entries": int(mec),
                     "field_size": int(field), "top_prize": float(first), "prize_pool": float(first) / (float(pct) / 100)})
        want.append(grade)
    got = [r["grade"] for r in contests.grade_contests(rows)]
    assert sum(g == w for g, w in zip(got, want)) >= 27  # fitted to this sheet: one contest (a D) grades as a C


def test_fifty_fifties_and_triple_ups_are_ungraded_and_slates_graded_apart():
    base = {"max_entries": 1, "field_size": 100, "top_prize": 100.0, "prize_pool": 1000.0, "entry_fee": 12.0, "game_type": "Classic"}
    rows = [{**base, "kind": "50/50", "slate": "Main"}, {**base, "kind": "Triple Up", "slate": "Main"},
            {**base, "kind": "Tournament", "slate": "Main"}, {**base, "kind": "Tournament", "slate": "Early"}]
    got = contests.grade_contests(rows)
    assert got[0]["grade"] is None and got[1]["grade"] is None and got[2]["grade"] == got[3]["grade"] is not None


def _week10_main_sheet():
    rows, want = [], []
    for line in open(Path(__file__).parent / "fixtures" / "dk_gpp_grades_w10_main.txt"):
        grade, _name, fee, mec, field, first, rake, _cash, pct = line.strip().split("|")
        fee, field, first, pct = float(fee), int(field), float(first), float(pct)
        pool = fee * field * (1 - float(rake) / 100)                              # DraftKings' pool, from the sheet's own rake
        assert abs(first / pool * 100 - pct) < 1.0                                # which agrees with its % to 1st
        rows.append({"kind": "Tournament", "slate": "Main", "game_type": "Classic", "max_entries": int(mec), "field_size": field,
                     "top_prize": pct / 100 * pool, "prize_pool": pool, "entry_fee": fee})   # % to 1st as listed (rounded)
        want.append(grade)
    return rows, want


def test_grades_match_the_week_10_main_slate_sheet():
    rows, want = _week10_main_sheet()
    got = [r["grade"] for r in contests.grade_contests(rows)]
    order = "ABCDF"
    assert len(rows) == 56
    assert sum(g == w for g, w in zip(got, want)) >= 51                    # 53 of 56 (the old three-factor grade matched 37)
    assert all(abs(order.index(g) - order.index(w)) <= 1 for g, w in zip(got, want))     # and none is off by more than one grade


def _double_up(field, ratio, fee=5.0):
    return {"kind": "Double Up", "slate": "Main", "game_type": "Classic", "max_entries": 1, "field_size": field, "entry_fee": fee,
            "prize_pool": ratio * fee * field, "top_prize": 2 * fee}


def test_bigger_double_ups_grade_higher_and_a_big_high_payout_one_is_a_b():
    order = "ABCDF"
    grades = [contests.grade_contests([_double_up(f, 0.905)])[0]["grade"] for f in (11, 50, 300, 1500, 6000)]
    assert [order.index(g) for g in grades] == sorted((order.index(g) for g in grades), reverse=True)    # never better as it shrinks
    assert grades[0] != grades[-1] and grades[-1] == "B"
    assert contests.grade_contests([_double_up(100000, 0.912)])[0]["grade"] == "B"                       # the top grade a Double Up gets


def test_lower_double_up_payout_ratio_grades_lower_at_any_size_and_size_does_not_move_it():
    score = lambda f, r: contests.grade_contests([_double_up(f, r)])[0]["grade_score"]     # noqa: E731
    for field in (23, 500, 5000):
        assert score(field, 0.912) > score(field, 0.89) > score(field, 0.870)
    # the same ratio at a different fee or field is the same payout ratio: only the size factor moves the score
    assert contests.grade_contests([_double_up(500, 0.89, fee=1.0)])[0]["grade_score"] == score(500, 0.89)


async def test_guaranteed_status_filter(lobby):
    lobby["lobby"] = {"Contests": [
        _contest(1, 3, 100, 270, attr={"IsGuaranteed": "true"}),
        _contest(2, 3, 100, 255, attr={"IsGuaranteed": "false"}),
        _contest(3, 3, 100, 240, attr={"IsFeatured": "true"}),
    ], "DraftGroups": []}
    lobby["payouts"] = {1: (20, 100.0), 2: (20, 100.0), 3: (20, 100.0)}
    ids = lambda r: sorted(c["id"] for c in r["contests"])          # noqa: E731
    assert ids(await contests.best_contests()) == [1, 2, 3]
    yes = await contests.best_contests(guaranteed="yes")
    assert ids(yes) == [1] and yes["selected"]["guaranteed"] == "yes" and yes["matching"] == 1
    no = await contests.best_contests(guaranteed="no")
    assert ids(no) == [2, 3] and all(not c["guaranteed"] for c in no["contests"])


def _graded_rows():
    """Four tournaments on one slate that grade A..F-ish by field size and entry limit, plus a cash game (ungraded)."""
    def row(i, kind, field, mec, score):
        return {"id": i, "kind": kind, "slate": "Main", "max_entries": mec, "field_size": field, "top_prize": 100.0,
                "prize_pool": 1000.0, "guaranteed": True, "score": score, "entry_fee": 3.0}
    rows = [row(1, "Tournament", 5000, 150, 90), row(2, "Tournament", 50, 1, 10), row(3, "Tournament", 500, 20, 50),
            row(4, "50/50", 100, 1, 99)]
    return contests.grade_contests(rows)


def test_min_grade_keeps_that_grade_or_better_and_drops_ungraded_cash():
    rows = _graded_rows()
    grade = {r["id"]: r["grade"] for r in rows}
    assert grade[2] in ("A", "B") and grade[4] is None
    ids = lambda g: [r["id"] for r in contests.select(rows, frozenset(), frozenset(), frozenset(), min_grade=g)]    # noqa: E731
    assert sorted(ids("any")) == [1, 2, 3, 4]
    assert 4 not in ids("D") and 2 in ids("D")
    better = contests.select(rows, frozenset(), frozenset(), frozenset(), min_grade=grade[2])
    assert all(contests._GRADE_ORDER[r["grade"]] <= contests._GRADE_ORDER[grade[2]] for r in better)


def test_sort_by_grade_puts_the_best_grade_first_and_ungraded_last():
    rows = _graded_rows()
    order = [r["id"] for r in contests.by_grade(rows)]
    assert order[0] == 2 and order[-1] == 4                  # smallest field, single entry = best grade; cash games last
    assert [r["id"] for r in sorted(rows, key=lambda r: -r["score"])][0] == 4    # by score it would be the cash game


def test_the_biggest_double_ups_at_a_high_payout_ratio_grade_b_but_the_lowest_ratio_one_does_not():
    grade = lambda f, r: contests.grade_contests([_double_up(f, r)])[0]["grade"]      # noqa: E731
    assert grade(444, 0.901) == "B" and grade(333, 0.901) == "B"        # as listed on DraftKings: big, high ratio
    assert grade(6896, 0.870) == "C"                                    # the biggest, but at the lowest ratio listed
    assert grade(23, 0.870) == "F"
