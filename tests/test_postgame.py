from datetime import datetime, timezone

import numpy as np

from app import postgame, trenches
from app.models import Game, GameContext, Player, TopPlayer


def _game(away_score, home_score, home_spread=-3.0, total=44.5):
    ctx = GameContext(home_spread=home_spread, away_spread=-home_spread, total_line=total,
                      away_implied_total=round(total / 2 + home_spread / 2, 1), home_implied_total=round(total / 2 - home_spread / 2, 1),
                      is_final=True, away_score=away_score, home_score=home_score,
                      spread_result=round(home_score - away_score + home_spread, 1), total_result=round(home_score + away_score - total, 1))
    return Game(game_id="g1", season=2026, week=4, away="AAA", home="BBB", kickoff_utc=datetime(2026, 9, 27, 17, tzinfo=timezone.utc),
                kickoff_et="Sun", day_part="SUN_EARLY", context=ctx)


def _tw():
    def unit(pr, rs, ds):
        return {"pressure_rate": pr, "rush_success": rs, "db_success": ds, "sack_rate": pr / 2, "stuff_rate": 0.18,
                "rush_epa": 0.0, "db_epa": 0.05, "explosive_pass": 0.08, "epa_play": 0.0, "success": 0.44}
    teams = {"AAA": {"off": unit(0.10, 0.50, 0.52), "def": unit(0.20, 0.36, 0.40), "cov": {}, "games": 3},
             "BBB": {"off": unit(0.22, 0.36, 0.40), "def": unit(0.10, 0.50, 0.52), "cov": {}, "games": 3},
             "CCC": {"off": unit(0.16, 0.43, 0.46), "def": unit(0.15, 0.43, 0.46), "cov": {}, "games": 3}}
    trenches.grade_units(teams)
    return {"teams": teams, "league": {"off": {"pressure_rate": 0.16, "rush_success": 0.43, "db_success": 0.46}}}


HIST = {"coef": [0.0, 1.0], "games": 1000, "seasons": [2010, 2025],
        "margin_miss": sorted(float(x) for x in range(0, 30)), "total_miss": sorted(float(x) for x in range(0, 30))}


def test_fit_logistic_recovers_a_known_slope():
    rng = np.random.default_rng(0)
    x = rng.normal(size=4000)
    y = (rng.random(4000) < 1 / (1 + np.exp(-(0.3 + 1.5 * x)))).astype(float)
    b = postgame.fit_logistic(np.column_stack([np.ones_like(x), x]), y, ridge=0.0)
    assert abs(b[0] - 0.3) < 0.15 and abs(b[1] - 1.5) < 0.15


def test_share_at_least_and_verdicts():
    assert postgame.share_at_least([1.0, 2.0, 3.0, 4.0], 3.0) == 0.5
    assert postgame.share_at_least([], 3.0) == 0.0
    assert [postgame._verdict(p) for p in (0.8, 0.6, 0.5, 0.4, 0.2, None)] == \
        ["Expected", "Favorite won", "Coin flip", "Mild upset", "Upset", "No line"]


def test_matchup_review_scores_against_pregame_expectation():
    tw = _tw()
    # AAA's strong protection vs BBB's weak rush; AAA got hit a lot anyway -> BBB's rush won, pregame call missed
    comp = {"db": 30, "hit": 12, "rush": 20, "rush_succ": 9, "db_succ": 15}
    rows = {m["key"]: m for m in postgame.matchup_review(tw, comp, "AAA", "BBB")}
    prot = rows["protection"]
    assert prot["verdict"] == "held" and prot["call"] == "miss" and "was sacked or hit" in prot["text"]
    assert rows["run"]["verdict"] in ("held", "to form")
    assert postgame.matchup_review(tw, {"db": 3, "hit": 1}, "AAA", "BBB") == []      # too few attempts
    assert postgame.matchup_review(tw, None, "AAA", "BBB") == []


def test_summarize_builds_result_flow_matchups_and_predictability():
    g = _game(17, 27)                     # BBB (home, -3) wins by 10
    full = {"4|AAA": {"plays": 60, "epa": -6.0, "succ": 24, "db": 35, "db_epa": -5.0, "rush": 25, "rush_epa": -1.0, "sack": 3, "explosive": 3},
            "4|BBB": {"plays": 65, "epa": 9.0, "succ": 32, "db": 30, "db_epa": 6.0, "rush": 35, "rush_epa": 3.0, "sack": 1, "explosive": 6}}
    comp = {"4|AAA": {"db": 30, "hit": 6, "rush": 20, "rush_succ": 8, "db_succ": 12},
            "4|BBB": {"db": 25, "hit": 5, "rush": 30, "rush_succ": 15, "db_succ": 12}}
    box = {(4, "AAA"): {"giveaways": 2, "yards_per_play": 4.6}, (4, "BBB"): {"giveaways": 0, "yards_per_play": 6.1}}
    actuals = {"teams": ["AAA", "BBB"], "players": {}, "dst": {"BBB": 12.0},
               "by_team": {"BBB": [["Star Back", "RB", 28.4]], "AAA": [["Kicker Guy", "K", 12.0]]}}
    players = [Player(name="Star Back", team="BBB", opponent="AAA", position="RB", roster_slot="", salary=7000, proj_points=18.0,
                      value_per_1k=2.6, game_info="AAA@BBB")]
    targets = {"BBB": [TopPlayer(name="BBB DST", position="DST", salary=3000, proj_points=7.0, ceiling=11.0, role="DST")]}
    out = postgame.summarize(g, tw=_tw(), competitive=comp, full_game=full, box=box, actuals=actuals, players=players,
                             targets=targets, hist=HIST, calib={"coef": 0.0, "games": 200, "logloss_line": 0.6,
                                                                "logloss_with_metrics": 0.6, "vegas_favorite_win_rate": 0.66,
                                                                "metrics_favorite_win_rate": 0.6})
    assert out["headline"] == "BBB beat AAA 27-17."
    assert out["result"][0] == "BBB covered (BBB -3) by 7."
    assert "BBB won the efficiency battle" in out["flow"][1] and "turnovers (AAA 2, BBB 0)" in out["flow"][1]
    pred = out["predictability"]
    assert pred["winner"] == "BBB" and pred["line_win_prob"] > 0.5 and pred["verdict"] in ("Favorite won", "Expected")
    assert pred["margin_miss"] == 7.0 and pred["model_win_prob"] is not None
    assert any("didn't improve" in t for t in pred["text"])
    assert out["pbp_available"] and out["matchups"]
    dfs = out["dfs"]
    assert dfs["top_scorers"][0]["name"] == "Star Back" and dfs["top_scorers"][0]["value"] == round(28.4 / 7, 2)
    assert all(p["position"] != "K" for p in dfs["top_scorers"])
    assert dfs["targets"][0]["result"] == "Hit ceiling"


def test_summarize_handles_unfinished_ties_and_missing_pbp():
    unfinished = _game(0, 0)
    unfinished.context.is_final = False
    kw = dict(tw=None, competitive={}, full_game={}, box={}, actuals=None, players=[], targets={}, hist={}, calib={})
    assert postgame.summarize(unfinished, **kw) is None
    tie = postgame.summarize(_game(20, 20), **kw)
    assert tie["headline"] == "AAA and BBB tied 20-20." and tie["predictability"]["verdict"] == "Tie"
    assert not tie["pbp_available"] and tie["note"] and tie["matchups"] == []
    upset = postgame.summarize(_game(30, 10, home_spread=-10), **{**kw, "hist": HIST})
    assert upset["predictability"]["verdict"] in ("Upset", "Mild upset") and upset["predictability"]["winner"] == "AAA"
