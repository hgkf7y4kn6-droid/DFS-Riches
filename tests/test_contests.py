import pytest

import app.contests as contests

pytestmark = pytest.mark.anyio


def _contest(cid, fee, size, pool, mec=1, tmpl=None, game_type="Classic", attr=None):
    return {"id": cid, "n": f"Contest {cid}", "a": fee, "m": size, "po": pool, "mec": mec, "nt": 3,
            "tmpl": tmpl or cid, "gameType": game_type, "attr": attr or {"IsGuaranteed": "true"},
            "sd": "/Date(1792342800000)/", "sdstring": "Sun 1:00PM", "dg": 1}


def _payouts(paid):
    return {"contestDetail": {"payoutSummary": [{"minPosition": 1, "maxPosition": 1}, {"minPosition": 2, "maxPosition": paid}]}}


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


def test_groups_cover_every_fee_and_entry_limit():
    assert [contests.entry_group(n) for n in (1, 2, 10, 11, 20, 21, 150, 151)] == \
        ["se", "2-10", "2-10", "20", "20", "150", "150", None]
    assert [contests.fee_group(f) for f in (0.1, 1, 3, 4, 5, 9, 10, 25, 27)] == \
        ["under1", "1-4", "1-4", "1-4", "5-9", "5-9", "10-25", "10-25", "over25"]


async def test_ranks_by_rake_then_share_paid(monkeypatch):
    lobby = {"Contests": [
        _contest(1, 3, 100, 255),             # 15% rake
        _contest(2, 3, 100, 270, tmpl=20),    # 10% rake, 20% paid
        _contest(3, 3, 100, 270, tmpl=30),    # 10% rake, 25% paid
        _contest(4, 3, 100, 270, attr={"IsFiftyfifty": "true"}),
        _contest(5, 50, 100, 4500, mec=150, attr={"Multiplier": "true"}),
    ], "DraftGroups": [{"DraftGroupId": 1, "ContestStartTimeSuffix": " (Thu-Mon)"}]}
    paid = {2: 20, 3: 25, 1: 22, 5: 20}

    async def fake_get_json(url):
        if "lobby" in url:
            return lobby
        return _payouts(paid[int(url.rsplit("/", 1)[1].split("?")[0])])

    async def no_cache(key, ttl, fetch):
        return await fetch()

    monkeypatch.setattr(contests, "_get_json", fake_get_json)
    monkeypatch.setattr(contests, "cached_fetch", no_cache)
    result = await contests.best_contests()

    se = result["contests"]["se"]["1-4"]
    assert [c["id"] for c in se] == [3, 2, 1]
    assert se[0]["rake"] == 0.1 and se[0]["paid_pct"] == 0.25 and se[0]["paid_places"] == 25
    assert se[0]["slate"] == "Thu-Mon" and se[0]["kind"] == "Tournament"
    assert [(c["id"], c["kind"]) for c in result["contests"]["150"]["over25"]] == [(5, "Booster")]
    assert result["contests"]["2-10"]["1-4"] == []
