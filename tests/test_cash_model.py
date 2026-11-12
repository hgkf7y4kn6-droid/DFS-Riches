import json
from datetime import datetime, timedelta, timezone

import pytest

import app.optimal as optimal
from app import cash_model as cm
from app import salary_log
from app.models import Game, GameContext, Player, Slate

from tests.test_optimizer import _classic_pool, _p

pytestmark = pytest.mark.anyio


def _games(n, dk=12.0, snap=0.8, os=0.2):
    return [{"dk": dk, "snap": snap, "os": os, "car": 3, "att": 30} for _ in range(n)]


def _model():
    flat = {"features": ["mu8", "impl", "snap", "os_mu", "trend"], "median": {f: 0.0 for f in ("mu8", "impl", "snap", "os_mu", "trend")},
            "mean": {f: 0.0 for f in ("mu8", "impl", "snap", "os_mu", "trend")}, "sd": {f: 1.0 for f in ("mu8", "impl", "snap", "os_mu", "trend")},
            "coef": {"c": 1.0, "mu8": 1.0, "impl": 0.0, "snap": 0.0, "os_mu": 0.0, "trend": 0.0}}
    return {"positions": {"RB": flat, "WR": flat, "TE": flat}}


def test_features_need_history_and_a_real_role():
    assert cm.features(_games(3), "WR", 24, 3) is None                       # fewer than 4 games
    assert cm.features(_games(8, dk=3.0), "WR", 24, 3) is None               # trailing average under 5
    assert cm.features(_games(8, dk=8.0), "QB", 24, 3) is None               # a QB needs 10+
    f = cm.features(_games(8, dk=14.0), "WR", 24, 3)
    assert f["mu8"] == 14.0 and f["snap"] == pytest.approx(0.8) and f["os_mu"] == pytest.approx(0.2) and f["trend"] == pytest.approx(1.0)


def test_features_use_only_the_windows_asked_for():
    games = _games(10, dk=2.0) + _games(8, dk=20.0)       # oldest first: a long-ago slump, then a hot stretch
    f = cm.features(games, "RB", 24, 3)
    assert f["mu8"] == 20.0 and f["mu6"] == 20.0


def test_predict_standardizes_and_fills_missing_with_the_median():
    m = _model()
    assert cm.predict(m, "WR", {"mu8": 12.0, "impl": 24, "snap": 0.8, "os_mu": 0.2, "trend": 1.0}) == pytest.approx(13.0)
    assert cm.predict(m, "WR", {"mu8": None}) == pytest.approx(1.0)   # median 0 -> intercept only


def test_eligibility_filters_match_the_tested_lineup():
    assert cm.eligible("QB", 5000, 15, None)
    assert cm.eligible("DST", 2500, 6, None)
    assert not cm.eligible("WR", 6000, 15, 0.55)             # snap share under 60%
    assert not cm.eligible("RB", 6000, 15, None)
    assert not cm.eligible("WR", 3800, 7.5, 0.8)             # cheap and projected under 8
    assert cm.eligible("WR", 3800, 9.0, 0.8)
    assert cm.eligible("WR", 6000, 7.5, 0.8)                 # the projection floor only applies to cheap slots


def test_flag_is_off_by_default_and_reads_the_environment(monkeypatch):
    assert not cm.enabled()
    monkeypatch.setenv("CASH_MODEL", "v2")
    assert cm.enabled()
    monkeypatch.setenv("CASH_MODEL", "off")
    assert not cm.enabled()


def test_shipped_model_file_covers_every_position():
    model = json.loads(cm.MODEL_PATH.read_text())
    assert set(model["positions"]) == set(cm.FEATURES)
    for pos, m in model["positions"].items():
        assert m["features"] == cm.FEATURES[pos] and set(m["coef"]) == {"c", *m["features"]}


def test_build_games_derives_touches_share_and_snap():
    index = {"p|WR": [{"season": 2026, "week": 2, "team": "A", "dk_points": 10.0, "snap_pct": 80.0,
                       "stats": {"receiving": {"tgt": 8, "rec": 5, "yds": 60, "td": 0}}},
                      {"season": 2026, "week": 1, "team": "A", "dk_points": 6.0, "snap_pct": None,
                       "stats": {"receiving": {"tgt": 4, "rec": 2, "yds": 20, "td": 0}}}]}
    out = cm.build_games(index, {(2026, 1, "A"): 50.0, (2026, 2, "A"): 80.0})["p|WR"]
    assert [g["week"] for g in out] == [1, 2]
    assert out[0]["snap"] is None and out[0]["os"] == pytest.approx(0.08)
    assert out[1]["snap"] == pytest.approx(0.8) and out[1]["os"] == pytest.approx(0.1)


def test_safe_lineup_uses_cash_points_only_when_given_them():
    pool = [Player(**{**p, "opponent": "", "value_per_1k": 0.0}) for p in _classic_pool()]
    plain = optimal.build_lineups(pool, "classic")
    assert "note" not in plain[0] and all("cash_proj" not in r for r in plain[0]["players"])
    # the cash model prefers the cheap QB and covers no one else but a legal lineup's worth of players
    cash = {p.dk_draftable_id: {"proj": p.proj_points * (3.0 if p.name == "QB Cheap" else 1.0), "snap": 0.9} for p in pool}
    out = optimal.build_lineups(pool, "classic", cash=cash)
    safe, tournament = out[0], out[1]
    assert safe["note"] == "Cash model v2 (experimental)" and "cash_proj" in safe
    assert next(r for r in safe["players"] if r["slot"] == "QB")["name"] == "QB Cheap"
    assert tournament["metric"] == "tournament" and "note" not in tournament     # only the Safe lineup changes


def test_uncovered_players_cannot_make_the_safe_lineup():
    pool = [Player(**{**p, "opponent": "", "value_per_1k": 0.0}) for p in _classic_pool()]
    cash = {p.dk_draftable_id: {"proj": p.proj_points, "snap": 0.9} for p in pool if p.name != "QB Star"}
    safe = optimal.build_lineups(pool, "classic", cash=cash)[0]
    assert "QB Star" not in {r["name"] for r in safe["players"]}


def test_salary_log_records_changes_and_leaves_started_slates_alone(tmp_path):
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    players = [Player(**{**p, "opponent": "X", "value_per_1k": 0.0}) for p in _classic_pool()]
    assert salary_log.record(2026, 9, "classic", 155993, "classic", players, now)
    data = salary_log.load(2026, 9)
    assert data["columns"] == salary_log.COLUMNS and data["slates"]["classic"]["draft_group_id"] == 155993
    first = data["slates"]["classic"]["players"][0]
    assert first[6] == 9000 and first[1] == "RB1"                      # sorted by salary, highest first
    assert not salary_log.record(2026, 9, "classic", 155993, "classic", players, now + timedelta(hours=1))   # unchanged: no rewrite
    players[0] = players[0].model_copy(update={"salary": 8100})
    assert salary_log.record(2026, 9, "classic", 155993, "classic", players, now + timedelta(hours=2))
    assert salary_log.record(2026, 9, "classic_sunday", 155994, "classic", players, now)
    assert set(salary_log.load(2026, 9)["slates"]) == {"classic", "classic_sunday"}


def test_salary_log_never_raises(monkeypatch):
    monkeypatch.setattr(salary_log, "SALARY_DIR", salary_log.SALARY_DIR / "a" / "b")
    monkeypatch.setattr(salary_log.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    players = [Player(**{**p, "opponent": "X", "value_per_1k": 0.0}) for p in _classic_pool()]
    assert salary_log.record(2026, 9, "classic", 1, "classic", players, datetime.now(timezone.utc)) is False
    assert salary_log.record(2026, 9, "classic", 1, "classic", [], datetime.now(timezone.utc)) is False


async def test_get_optimal_records_salaries_and_survives_a_cash_model_failure(monkeypatch, tmp_path):
    kickoff = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(optimal, "OPTIMAL_LINEUPS_PATH", tmp_path / "optimal.json")
    game = Game(game_id="g", season=2026, week=9, away="A", home="B", kickoff_utc=kickoff, kickoff_et="", day_part="SUN_EARLY",
                context=GameContext())
    slate = Slate(slate_id="classic", label="C", slate_type="classic", draft_group_id=7, games=[game], available=True, source="live")
    players = [Player(**{**p, "opponent": "", "value_per_1k": 0.0}) for p in _classic_pool()]

    async def fake_list_slates(season, week):
        return None, [slate]

    class _SP:
        pass

    async def fake_players(season, week, slate_id):
        sp = _SP()
        sp.players = players
        return sp

    async def boom(*a, **k):
        raise RuntimeError("nflverse down")

    monkeypatch.setattr(optimal.slates_module, "list_slates", fake_list_slates)
    monkeypatch.setattr(optimal.slates_module, "get_slate_players", fake_players)
    monkeypatch.setattr(optimal.cash_model, "projections", boom)
    monkeypatch.setenv("CASH_MODEL", "v2")

    result = await optimal.get_optimal(2026, 9, "classic", now=kickoff - timedelta(hours=3))
    assert result["status"] == "live" and len(result["lineups"]) == 2
    assert "note" not in result["lineups"][0]                           # fell back to the app's projection
    assert salary_log.load(2026, 9)["slates"]["classic"]["draft_group_id"] == 7

    await optimal.get_optimal(2026, 9, "classic", now=kickoff + timedelta(hours=1))   # started: the snapshot is not touched
    assert salary_log.load(2026, 9)["slates"]["classic"]["saved_at"].startswith("2026-11-08T15:00")
