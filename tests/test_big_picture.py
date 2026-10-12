import pytest

from app.big_picture import history, odds, quant, store


# ------------------------------------------------------------------ betting math
def test_break_even_and_profit():
    assert quant.implied(-110) == pytest.approx(110 / 210)
    assert quant.implied(150) == pytest.approx(100 / 250)
    assert quant.profit(-110) == pytest.approx(100 / 110)
    assert quant.profit(150) == pytest.approx(1.5)
    assert quant.american("−115") == -115 and quant.american("+120") == 120 and quant.american("EVEN") == 100


def test_no_vig_and_ev_with_push():
    a, b = quant.no_vig(-120, 100)
    assert a + b == pytest.approx(1) and a > 0.5
    # A push returns the stake: it adds nothing, it doesn't count as a loss.
    assert quant.ev(0.5, 0.1, 100) == pytest.approx(0.5 - 0.4)
    assert quant.fair_american(0.5) == -100 and quant.fair_american(0.6) == -150 and quant.fair_american(0.4) == 150


def test_margin_distribution_has_key_numbers_and_pushes():
    m = quant.margin_dist(0.0)
    assert sum(m.values()) == pytest.approx(1)
    assert m[3] > m[2] and m[3] > m[4] and m[7] > m[8]
    assert m[0] < 0.01                      # ties are rare
    win, push = quant.cover(m, -3.0, +1)    # home -3
    assert push == pytest.approx(m[3])
    w2, p2 = quant.cover(m, 3.0, -1)        # away +3: wins when home margin < 3
    assert p2 == pytest.approx(m[3]) and w2 > win


def test_evaluate_and_classify():
    t = quant.total_dist(48.0)
    over = quant.evaluate("total", t, 44.5, +1, -110, -110)
    assert over["model_cond"] > 0.5 and over["ev_model"] > 0 and over["market_novig"] == 0.5
    assert 0.5 < over["blend_cond"] < over["model_cond"]       # the market pulls the model back
    assert over["model_breakeven_line"] >= 44.5
    assert quant.classify(over, "total", 3.5, False) in ("strongest", "price_sensitive")
    assert quant.classify(over, "total", 3.5, True) == "watchlist"            # unresolved injury news
    assert quant.classify(over, "total", 3.5, False, trusted=False) == "watchlist"
    under = quant.evaluate("total", t, 44.5, -1, -110, -110)
    assert quant.classify(under, "total", -3.5, False) == "none"
    no_price = quant.evaluate("total", t, 44.5, +1, None, None)
    assert no_price["price_available"] is False and "ev_model" not in no_price


def test_project_game_home_edge_and_weather():
    lg = {"off": {"epa_play": 0.0}, "def": {"epa_play": 0.0}}
    flat = {"epa_play": 0.0}
    g = quant.project_game(flat, flat, flat, flat, lg, home_plays=62, away_plays=62, league_points=22.5)
    assert g["fair_home_spread"] == pytest.approx(-quant.HOME_EDGE, abs=0.11)
    assert g["fair_total"] == pytest.approx(45.0, abs=0.1)
    wet = quant.project_game(flat, flat, flat, flat, lg, home_plays=62, away_plays=62, league_points=22.5, weather_points=0.9)
    assert wet["fair_total"] < g["fair_total"]
    good = quant.project_game({"epa_play": 0.1}, flat, flat, flat, lg, home_plays=62, away_plays=62, league_points=22.5)
    assert good["home_points"] > g["home_points"] and good["fair_home_spread"] < g["fair_home_spread"]


# ------------------------------------------------------------------ DraftKings parsing
DK_PAYLOAD = {
    "events": [{"id": "1", "startEventDate": "2026-10-18T17:00:00Z",
                "participants": [{"name": "NY Jets", "venueRole": "Away"}, {"name": "NE Patriots", "venueRole": "Home"}]}],
    "markets": [
        {"id": "m1", "eventId": "1", "name": "Spread", "marketType": {"name": "Spread"}},
        {"id": "m2", "eventId": "1", "name": "Total", "marketType": {"name": "Total"}},
        {"id": "m3", "eventId": "1", "name": "Moneyline", "marketType": {"name": "Moneyline"}},
        {"id": "m4", "eventId": "1", "name": "NE Patriots: Team Total Points", "marketType": {"name": "Team Total Points"}},
        {"id": "m5", "eventId": "1", "name": "Alternate Spread", "marketType": {"name": "Alternate Spread"}},
    ],
    "selections": [
        {"marketId": "m1", "outcomeType": "Away", "points": 7.0, "displayOdds": {"american": "−105"}},
        {"marketId": "m1", "outcomeType": "Home", "points": -7.0, "displayOdds": {"american": "−115"}},
        {"marketId": "m2", "outcomeType": "Over", "label": "Over", "points": 43.5, "displayOdds": {"american": "−110"}},
        {"marketId": "m2", "outcomeType": "Under", "label": "Under", "points": 43.5, "displayOdds": {"american": "−110"}},
        {"marketId": "m3", "outcomeType": "Home", "displayOdds": {"american": "−340"}},
        {"marketId": "m3", "outcomeType": "Away", "displayOdds": {"american": "+270"}},
        {"marketId": "m4", "label": "Over", "points": 25.5, "displayOdds": {"american": "−115"}},
        {"marketId": "m4", "label": "Under", "points": 25.5, "displayOdds": {"american": "−105"}},
        {"marketId": "m5", "outcomeType": "Home", "points": -10.0, "displayOdds": {"american": "+150"}},
    ],
}


def test_parse_draftkings_game_lines_and_team_totals():
    q = {(r["market"], r["side"]): r for r in odds.parse(DK_PAYLOAD)}
    assert {r["game"] for r in q.values()} == {"NYJ@NE"}
    assert q[("spread", "home")]["line"] == -7.0 and q[("spread", "home")]["price"] == -115
    assert q[("spread", "away")]["line"] == 7.0
    assert q[("total", "over")]["line"] == 43.5
    assert q[("moneyline", "away")]["price"] == 270 and q[("moneyline", "home")]["line"] is None
    assert q[("team_total_home", "over")]["line"] == 25.5
    assert len(q) == 8                      # the alternate spread is ignored


def test_team_names():
    assert [odds.team_abbr(n) for n in ("KC Chiefs", "LA Rams", "LA Chargers", "SF 49ers", "Washington Commanders", "JAC")] == \
        ["KC", "LAR", "LAC", "SF", "WAS", "JAX"]


# ------------------------------------------------------------------ storage + history
@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(store, "LOCAL_DIR", tmp_path)
    return tmp_path


def _row(line, price, at):
    return {"captured_at": at, "season": 2026, "week": 6, "game": "NYJ@NE", "market": "spread", "side": "home",
            "line": line, "price": price, "source": odds.SOURCE}


def test_odds_snapshots_only_store_changes(local_store):
    assert store.add_odds([_row(-7.0, -110, "2026-10-12T01:00:00+00:00")]) == 1
    assert store.add_odds([_row(-7.0, -110, "2026-10-12T02:00:00+00:00")]) == 0          # unchanged
    assert store.add_odds([_row(-7.5, -110, "2026-10-12T03:00:00+00:00")]) == 1
    s = odds.summarize(store.odds_history(2026, 6))["NYJ@NE"]["spread"]["home"]
    assert s["opening"]["line"] == -7.0 and s["current"]["line"] == -7.5 and len(s["moves"]) == 2


def test_reports_are_append_only(local_store):
    a = store.add_report(2026, 6, "agents", {"title": "one"}, {"meta": {"generated_at": "a"}, "games": []}, {"sections": []})
    b = store.add_report(2026, 6, "agents", {"title": "two"}, {"meta": {"generated_at": "b"}, "games": []}, {"sections": []})
    assert b["id"] == a["id"] + 1
    assert store.get_report()["summary"]["title"] == "two"
    assert store.get_report(a["id"])["summary"]["title"] == "one"
    assert [r["id"] for r in store.list_reports()] == [b["id"], a["id"]]


def _game(spread, fair, cls, status):
    return {"game": "NYJ@NE", "home": "NE", "away": "NYJ",
            "market_summary": {"home_spread": spread, "total": 43.5},
            "model": {"fair_home_spread": fair, "fair_total": 44.0, "p_shootout": 0.1, "inputs": {}},
            "candidates": [{"market": "spread", "side": "home", "kind": "spread", "line": spread, "class": cls, "ev_blend": 0.03}],
            "injuries": {"home": [{"name": "QB One", "status": status}], "away": []}}


def test_changes_log():
    prev = {"meta": {"generated_et": "Mon"}, "games": [_game(-7.0, -9.0, "strongest", "Questionable")], "dfs": {"chalk": []}}
    cur = {"games": [_game(-8.0, -9.0, "none", "Out")], "dfs": {"chalk": []}}
    rows = history.changes(cur, prev)["rows"]
    items = {r["item"]: r for r in rows}
    assert "NYJ@NE spread (home)" in items and items["NYJ@NE spread (home)"]["current"] == "-8"
    assert any(r["action"].startswith("removed") for r in rows)
    assert items["QB One (NE)"]["current"] == "Out"
    same = history.changes(prev, prev)
    assert same["rows"] == [] and same["note"] == "No material change since the last report."
    assert history.changes(cur, None)["first_report"] is True


def test_backtest_summary():
    rows = [{"week": 2, "game": "A@B", "margin": 10, "total": 50, "close_spread": -3.0, "close_total": 44.0,
             "fair_spread": -6.0, "fair_total": 48.0},
            {"week": 2, "game": "C@D", "margin": -7, "total": 30, "close_spread": -2.0, "close_total": 41.0,
             "fair_spread": -1.0, "fair_total": 40.0}]
    s = history.summarize_backtest(rows)
    assert s["games"] == 2 and s["spread_mae_model"] == pytest.approx((4 + 8) / 2)
    assert s["ats_gap_1.5"] == {"w": 1, "l": 0, "p": 0, "n": 1, "win_pct": 1.0}
    assert s["totals_gap_2"]["w"] == 1


def test_grading_results():
    fin = {"home_score": 24, "away_score": 17}
    assert history._result({"market": "spread", "side": "home", "line": -7.0}, fin) == "push"
    assert history._result({"market": "spread", "side": "away", "line": 7.5}, fin) == "win"
    assert history._result({"market": "total", "side": "over", "line": 40.5}, fin) == "win"
    assert history._result({"market": "team_total_away", "side": "under", "line": 20.5}, fin) == "win"


def test_clean_database_url():
    from app.big_picture.run import clean_database_url
    url = "postgresql://u:p@host/db?sslmode=require"
    for raw in (url, f"'{url}'", f'"{url}"', f"  {url}\n", f"psql '{url}'", f"DATABASE_URL={url}", f"DATABASE_URL='{url}'"):
        assert clean_database_url(raw) == url
