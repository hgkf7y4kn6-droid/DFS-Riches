import asyncio
import json
from types import SimpleNamespace

import pytest

from app import outside_sources as osrc
from app import ownership_store as store


def _player(name, team, pos, proj, injury="Healthy", slot="FLEX", chance=None):
    return SimpleNamespace(name=name, team=team, position=pos, injury=injury, proj_points=proj, ceiling=proj * 1.6, salary=5000, value_per_1k=0.0,
                           roster_slot=slot, proj_notes=[], play_chance=chance, outside_proj=None, outside_weight=0.0, outside_notes=[])


@pytest.fixture
def outside(tmp_path, monkeypatch):
    (tmp_path / "2026_w11_footballers.json").write_text(json.dumps({"slate": "classic_sunday", "records": [
        {"set": "a", "name": "Dak Prescott", "team": "DAL", "pos": "QB", "own": 23.4, "proj": 24.0},
        {"set": "b", "name": "D. Prescott", "team": "DAL", "pos": "QB", "salary": 6700, "proj": 26.0, "ceil": 36.9, "own": 23.9},
        {"set": "b", "name": "A. St. Brown", "team": "DET", "pos": "WR", "salary": 8200, "proj": 17.5, "ceil": 25.7, "own": 15.1},
        {"set": "b", "name": "Steelers", "team": "PIT", "pos": "DST", "salary": 3300, "proj": 9.0, "ceil": 15.0, "own": 14.0}]}))
    (tmp_path / "2026_w11_sharp.json").write_text(json.dumps({"slate": "classic_sunday", "notes": [
        {"name": "Amon-Ra St. Brown", "team": "DET", "pos": "WR", "view": "core", "note": "Trust."}]}))
    (tmp_path / "blend_weights.json").write_text(json.dumps({"weights": {"QB": 0.3, "WR": 0.0, "DST": 0.3}}))
    monkeypatch.setattr(osrc, "DIR", tmp_path)
    osrc._book.cache_clear()
    yield tmp_path
    osrc._book.cache_clear()


def test_abbreviated_and_full_names_find_the_same_player(outside):
    assert osrc.footballers(2026, 11, "Dak Prescott", "DAL", "QB") == {"proj": 25.0, "ceil": 36.9, "own": 23.4}   # mean of both sets; the notes' ownership wins
    assert osrc.footballers(2026, 11, "Amon-Ra St. Brown", "DET", "WR")["own"] == 15.1                           # 'A. St. Brown' -> 'Amon-Ra St. Brown'
    assert osrc.footballers(2026, 11, "Steelers", "PIT", "DST")["proj"] == 9.0
    assert osrc.footballers(2026, 11, "Dak Prescott", "TEN", "QB") is None                                       # the team has to agree


def test_projection_moves_by_the_evaluated_weight_and_only_where_the_source_earned_it(outside):
    qb, wr, dst = _player("Dak Prescott", "DAL", "QB", 20.0), _player("Amon-Ra St. Brown", "DET", "WR", 16.0), _player("Steelers", "PIT", "DST", 6.0)
    osrc.apply_to_players([qb, wr, dst], 2026, 11, "classic_sunday", play_factor=lambda p: 1.0)
    assert qb.proj_points == round(0.7 * 20.0 + 0.3 * 25.0, 2) and qb.outside_proj == 25.0 and qb.outside_weight == 0.3
    assert qb.ceiling == round(32.0 * qb.proj_points / 20.0, 1) and "30% of the way" in qb.proj_notes[-1]
    assert wr.proj_points == 16.0 and wr.outside_proj == 17.5 and "not blended" in wr.proj_notes[-1]          # the model was better at WR
    assert wr.outside_notes == ["Sharp Football (core play): Trust."]                                          # Sharp: a note, no number moves
    assert dst.proj_points == round(0.7 * 6.0 + 0.3 * 9.0, 2)


def test_questionable_players_get_the_same_chance_to_play_discount_and_other_slates_are_untouched(outside):
    q = _player("Dak Prescott", "DAL", "QB", 18.0, injury="Q", chance=0.8)
    osrc.apply_to_players([q], 2026, 11, "classic_sunday", play_factor=lambda p: p.play_chance * 0.9)
    assert q.outside_proj == round(25.0 * 0.72, 2)
    other, cpt = _player("Dak Prescott", "DAL", "QB", 20.0), _player("Dak Prescott", "DAL", "QB", 30.0, slot="CPT")
    osrc.apply_to_players([other], 2026, 11, "classic_afternoon", play_factor=lambda p: 1.0)
    osrc.apply_to_players([cpt], 2026, 11, "classic_sunday", play_factor=lambda p: 1.0)
    assert other.proj_points == 20.0 and other.outside_proj is None and cpt.proj_points == 30.0


def test_blend_final_and_no_files_is_a_no_op(outside, tmp_path):
    assert osrc.blend_final(20.0, 25.0, 0.3) == (21.5, 1.5)
    assert osrc.blend_final(20.0, None, 0.3) == (20.0, 0.0) and osrc.blend_final(20.0, 25.0, 0.0) == (20.0, 0.0)
    p = _player("Dak Prescott", "DAL", "QB", 20.0)
    osrc.apply_to_players([p], 2026, 12, "classic_sunday", play_factor=lambda q: 1.0)                       # no Week 12 files
    assert p.proj_points == 20.0 and p.outside_proj is None


def test_footballers_ownership_enters_the_store_once(outside, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "OWN_DIR", tmp_path / "own")
    players = [{"key": store.player_key("Dak Prescott", "DAL", "QB"), "name": "Dak Prescott", "team": "DAL", "position": "QB", "roster_slot": "FLEX"},
               {"key": store.player_key("Steelers", "PIT", "DST"), "name": "Steelers", "team": "PIT", "position": "DST", "roster_slot": "FLEX"}]

    async def fake_players(season, week, slate_id):
        return players, {}
    from app import ownership_slate
    monkeypatch.setattr(ownership_slate, "players_for", fake_players)
    assert asyncio.run(osrc.ensure_ownership(2026, 11, "classic_sunday")) == 2
    assert asyncio.run(osrc.ensure_ownership(2026, 11, "classic_sunday")) == 0                              # idempotent
    obs = store.load(2026, 11, "classic_sunday")["observations"]
    assert {o["name"]: o["pct"] for o in obs} == {"Dak Prescott": 23.4, "Steelers": 14.0} and all(o["kind"] == "source" for o in obs)
    assert asyncio.run(osrc.ensure_ownership(2026, 11, "classic_afternoon")) == 0                          # only the slate the files name


def test_shipped_week_11_files_and_weights_are_sane():
    shipped = json.loads((osrc.DIR / "blend_weights.json").read_text())["weights"] if (osrc.DIR / "blend_weights.json").exists() else {}
    assert shipped and max(shipped.values()) <= 0.3                                  # capped: one graded week
    foot = json.loads((osrc.DIR / "2026_w11_footballers.json").read_text())["records"]
    assert len(foot) > 100 and all(r["pos"] in ("QB", "RB", "WR", "TE", "DST") and 0 <= (r.get("own") or 0) <= 100 for r in foot)
