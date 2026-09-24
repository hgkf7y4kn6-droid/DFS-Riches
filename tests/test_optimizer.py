from datetime import datetime, timedelta, timezone

import pytest

import app.optimal as optimal
from app.models import Game, Player, Slate
from app.optimizer import optimize

pytestmark = pytest.mark.anyio


def _p(pid, name, pos, team, salary, proj, *, game="A@B", slot="", injury="Healthy", ceiling=None):
    return dict(dk_draftable_id=pid, name=name, position=pos, team=team, salary=salary, proj_points=proj,
                ceiling=ceiling if ceiling is not None else proj * 1.5, roster_slot=slot, game_info=game, injury=injury)


def _classic_pool():
    pool = [
        _p(1, "QB Star", "QB", "A", 8000, 25), _p(2, "QB Cheap", "QB", "C", 5000, 18, game="C@D"),
        _p(3, "RB1", "RB", "A", 9000, 24), _p(4, "RB2", "RB", "C", 6000, 16, game="C@D"),
        _p(5, "RB3", "RB", "B", 4500, 12), _p(6, "RB Out", "RB", "D", 3000, 30, game="C@D", injury="OUT"),
        _p(7, "WR1", "WR", "A", 8500, 22), _p(8, "WR2", "WR", "C", 6500, 17, game="C@D"),
        _p(9, "WR3", "WR", "B", 5000, 13), _p(10, "WR4", "WR", "D", 4000, 11, game="C@D"),
        _p(11, "WR5", "WR", "B", 3000, 7),
        _p(12, "TE1", "TE", "A", 6000, 14), _p(13, "TE2", "TE", "D", 3500, 9, game="C@D"),
        _p(14, "DST A", "DST", "A", 3500, 8), _p(15, "DST C", "DST", "C", 2500, 6, game="C@D"),
    ]
    return pool


def test_classic_lineup_respects_roster_cap_and_injuries():
    lineup = optimize(_classic_pool(), "classic", "proj_points")
    assert len(lineup) == 9
    assert [p["position"] for p in lineup][:7] == ["QB", "RB", "RB", "WR", "WR", "WR", "TE"]
    assert lineup[7]["position"] in ("RB", "WR", "TE") and lineup[8]["position"] == "DST"
    assert sum(p["salary"] for p in lineup) <= 50000
    assert "RB Out" not in {p["name"] for p in lineup}
    assert len({p["dk_draftable_id"] for p in lineup}) == 9


def test_classic_lineup_is_optimal_against_brute_force():
    from itertools import combinations

    pool = [p for p in _classic_pool() if p["injury"] == "Healthy"]
    best = 0
    for combo in combinations(pool, 9):
        pos = [p["position"] for p in combo]
        counts = {k: pos.count(k) for k in ("QB", "RB", "WR", "TE", "DST")}
        if (counts["QB"] == 1 and counts["DST"] == 1 and 2 <= counts["RB"] <= 3 and 3 <= counts["WR"] <= 4
                and 1 <= counts["TE"] <= 2 and sum(p["salary"] for p in combo) <= 50000
                and len({p["game_info"] for p in combo}) >= 2):
            best = max(best, sum(p["proj_points"] for p in combo))
    lineup = optimize(pool, "classic", "proj_points")
    assert sum(p["proj_points"] for p in lineup) == pytest.approx(best)


def test_showdown_lineup_never_uses_one_player_twice_and_uses_both_teams():
    pool = []
    for i, (name, team, sal, proj) in enumerate([
        ("Stud", "A", 12000, 30), ("QB A", "A", 10000, 20), ("WR A", "A", 8000, 15), ("RB A", "A", 7000, 12),
        ("TE A", "A", 5000, 9), ("K A", "A", 4000, 8), ("WR2 A", "A", 3000, 7), ("Backup B", "B", 1000, 1),
    ]):
        pool.append(_p(100 + i, name, "WR", team, int(sal * 1.5), proj * 1.5, slot="CPT"))
        pool.append(_p(200 + i, name, "WR", team, sal, proj, slot="FLEX"))
    lineup = optimize(pool, "showdown", "proj_points")
    assert lineup[0]["roster_slot"] == "CPT" and all(p["roster_slot"] == "FLEX" for p in lineup[1:])
    assert len({p["name"] for p in lineup}) == 6
    assert {p["team"] for p in lineup} == {"A", "B"}
    assert sum(p["salary"] for p in lineup) <= 50000


def test_players_without_a_game_this_season_are_never_optimal():
    pool = _classic_pool()
    pool.append(_p(99, "Backup QB", "QB", "C", 4000, 0, game="C@D", ceiling=60))
    lineup = optimize(pool, "classic", "ceiling")
    assert "Backup QB" not in {p["name"] for p in lineup}


def test_optimize_returns_none_when_no_valid_lineup():
    assert optimize([_p(1, "QB", "QB", "A", 8000, 20)], "classic", "proj_points") is None


def _slate(kickoff):
    game = Game(game_id="g", season=2026, week=3, away="A", home="B", kickoff_utc=kickoff, kickoff_et="", day_part="SUN_EARLY")
    return Slate(slate_id="classic", label="C", slate_type="classic", draft_group_id=1, games=[game], available=True, source="live")


async def test_get_optimal_saves_before_kickoff_and_serves_frozen_copy_after(monkeypatch, tmp_path):
    kickoff = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(optimal, "OPTIMAL_LINEUPS_PATH", tmp_path / "optimal.json")

    async def fake_list_slates(season, week):
        return None, [_slate(kickoff)]

    players = [Player(**{**p, "opponent": "", "value_per_1k": 0.0}) for p in _classic_pool()]

    class _SP:
        pass

    async def fake_players(season, week, slate_id):
        sp = _SP()
        sp.players = players
        return sp

    monkeypatch.setattr(optimal.slates_module, "list_slates", fake_list_slates)
    monkeypatch.setattr(optimal.slates_module, "get_slate_players", fake_players)

    before = await optimal.get_optimal(2026, 3, "classic", now=kickoff - timedelta(hours=2))
    assert before["status"] == "live"
    assert [lu["metric"] for lu in before["lineups"]] == ["proj_points", "ceiling"]
    saved = optimal.load_saved(2026, 3, "classic")
    assert saved["lineups"] == before["lineups"]

    players[0] = players[0].model_copy(update={"proj_points": 999.0})  # post-kickoff data must not leak in
    after = await optimal.get_optimal(2026, 3, "classic", now=kickoff + timedelta(hours=1))
    assert after["status"] == "saved"
    assert after["lineups"] == before["lineups"]
    assert after["saved_at"] == saved["saved_at"]


async def test_get_optimal_after_kickoff_without_a_record_returns_none(monkeypatch, tmp_path):
    kickoff = datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(optimal, "OPTIMAL_LINEUPS_PATH", tmp_path / "missing.json")

    async def fake_list_slates(season, week):
        return None, [_slate(kickoff)]

    monkeypatch.setattr(optimal.slates_module, "list_slates", fake_list_slates)
    result = await optimal.get_optimal(2026, 3, "classic", now=kickoff + timedelta(hours=1))
    assert result == {"status": "none", "saved_at": None, "lineups": []}
