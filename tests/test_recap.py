from datetime import datetime, timezone

from app import recap
from app.models import Game, GameContext


def play(week=7, off="AAA", de="BBB", **kw):
    row = {"week": str(week), "posteam": off, "defteam": de, "play_type": "pass", "qb_dropback": "1", "qb_kneel": "0", "qb_spike": "0",
           "wp": "0.5", "epa": "0.1", "success": "1", "yards_gained": "6", "down": "1", "ydstogo": "10", "sack": "0", "qb_hit": "0",
           "pass_oe": "5", "touchdown": "0", "td_team": "", "yardline_100": "60", "fixed_drive": "1", "fixed_drive_result": "Punt",
           "interception": "0", "fumble": "0", "fumble_lost": "0", "third_down_converted": "0", "fourth_down_converted": "0"}
    row.update({k: str(v) for k, v in kw.items()})
    return row


def counts(rows):
    acc = recap.RecapAccumulator()
    for r in rows:
        acc.add(r)
    return acc.result()


def test_windows_split_neutral_early_down_and_garbage_time():
    c = counts([play(wp=0.5, down=1), play(wp=0.5, down=2, success=0), play(wp=0.15, down=1),   # competitive, neutral only for 0.5
                play(wp=0.05, down=1, yards_gained=40), play(wp=0.85, down=3)])["7|AAA"]
    assert c["plays"] == 5 and c["n"] == 2 and c["ed"] == 3 and c["ed_succ"] == 2         # 0.15 is competitive, not neutral
    assert c["g"] == 1 and c["g_pass_yds"] == 40 and c["n_oe_n"] == 2


def test_red_zone_trips_count_drives_and_touchdowns_once():
    rows = [play(yardline_100=15, fixed_drive=3, fixed_drive_result="Touchdown"), play(yardline_100=4, fixed_drive=3, fixed_drive_result="Touchdown"),
            play(yardline_100=12, fixed_drive=5, fixed_drive_result="Field goal"), play(yardline_100=70, fixed_drive=7)]
    c = counts(rows)["7|AAA"]
    assert c["rz_trips"] == 2 and c["rz_td"] == 1


def test_turnovers_third_and_long_and_non_offensive_touchdowns():
    rows = [play(interception=1), play(fumble=1, fumble_lost=1, play_type="run", qb_dropback=0),
            play(down=3, ydstogo=9, third_down_converted=1), play(down=3, ydstogo=3),
            play(touchdown=1, td_team="BBB", play_type="punt")]            # a punt return touchdown: credited to BBB
    out = counts(rows)
    a = out["7|AAA"]
    assert a["int"] == 1 and a["fum_lost"] == 1 and a["t3"] == 2 and a["t3l"] == 1 and a["t3lc"] == 1
    assert out["7|BBB"]["nonoff_td"] == 1 and "nonoff_td" not in a


def _ctx(a, h):
    return GameContext(is_final=True, away_score=a, home_score=h, home_spread=-3.0, total_line=44.0)


def _game(a, h):
    return Game(game_id="g", season=2026, week=7, away="AAA", home="BBB", kickoff_utc=datetime(2026, 10, 25, 17, tzinfo=timezone.utc),
                kickoff_et="Sun 1:00 PM ET", day_part="SUN_EARLY", context=_ctx(a, h))


def _team(epa, **extra):
    n = 30
    base = {"plays": 60, "n": n, "n_epa": epa * n, "n_succ": n / 2, "ed": 30, "ed_succ": 15, "db": 30, "hit": 4, "sack": 2, "n_oe": 3.0 * n, "n_oe_n": n}
    return {**base, **extra}


def test_out_played_but_won_on_the_bounces_is_fragile():
    # AAA wins 24-20 with worse neutral EPA, 3 takeaways to 0 and a defensive touchdown
    cts = {"7|AAA": _team(-0.15, int=0, fum_lost=0, nonoff_td=1), "7|BBB": _team(0.20, int=2, fum_lost=1)}
    r = recap.game_recap(_game(24, 20), cts, {"pressure": 0.15, "rz_td": 0.6, "third_long": 0.25, "early_success": 0.43})
    assert r["verdict"] == "Won on luck" and r["tone"] == "warn"
    assert r["teams"]["AAA"]["tag"] == "fragile" and r["teams"]["BBB"]["tag"] == "ascending"
    assert any("Turnover margin" in n for n in r["teams"]["AAA"]["noise"])
    assert r["teams"]["BBB"]["reason"].startswith("Lost 20-24 but led")


def test_a_deserved_win_is_earned_and_a_blowout_is_not_called_ascending():
    cts = {"7|AAA": _team(0.30), "7|BBB": _team(0.0, int=3)}                 # AAA out-played BBB and won big
    r = recap.game_recap(_game(31, 10), cts, {"pressure": 0.15})
    assert r["verdict"] == "Earned it" and r["teams"]["AAA"]["tag"] == "steady"      # the noise was on the loser's side
    assert r["teams"]["BBB"]["tag"] == "steady"                                      # lost big: nothing was masked


def test_thin_samples_make_no_claim():
    cts = {"7|AAA": {"plays": 5, "n": 3, "n_epa": 1.0}, "7|BBB": {"plays": 5, "n": 3, "n_epa": -1.0}}
    r = recap.game_recap(_game(10, 3), cts, {})
    assert r["verdict"] == "Result stands (thin sample)" and r["teams"]["AAA"]["tag"] == "steady"
    assert recap.game_recap(_game(10, 3), {}, {}) is None


def test_recap_endpoint_defaults_to_the_previous_week(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    async def current():
        return 2026, 8
    seen = []

    async def fake(season, week):
        seen.append((season, week))
        return {"season": season, "week": week, "available": False, "games": [], "ascending": [], "fragile": [], "unavailable": []}
    monkeypatch.setattr(main, "current_season_week", current)
    monkeypatch.setattr(recap, "week_recap", fake)
    monkeypatch.setenv("REQUIRE_SIGN_IN", "0")
    body = TestClient(main.app).get("/api/recap").json()
    assert seen == [(2026, 7)] and body["week"] == 7
