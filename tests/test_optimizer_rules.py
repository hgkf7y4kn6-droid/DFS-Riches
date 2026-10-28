"""Independent rule check of every lineup app.optimizer returns: a validator written from the DraftKings
roster rules (not from the optimizer's constraints), run over seeded random pools for both formats."""
import random

import pytest

from app.optimizer import SALARY_CAP, build_many, optimize

CLASSIC_LIMITS = {"QB": (1, 1), "RB": (2, 3), "WR": (3, 4), "TE": (1, 2), "DST": (1, 1)}


def classic_violations(lineup: list[dict]) -> list[str]:
    bad = []
    if len(lineup) != 9:
        bad.append(f"{len(lineup)} players, need 9")
    if len({p["dk_draftable_id"] for p in lineup}) != len(lineup):
        bad.append("duplicate draftable id")
    if len({p["name"] for p in lineup}) != len(lineup):
        bad.append("same person twice")
    if sum(p["salary"] for p in lineup) > SALARY_CAP:
        bad.append("over the salary cap")
    for pos, (lo, hi) in CLASSIC_LIMITS.items():
        n = sum(p["position"] == pos for p in lineup)
        if not lo <= n <= hi:
            bad.append(f"{n} {pos}")
    if len({p["game_info"] for p in lineup}) < 2:
        bad.append("fewer than 2 games")
    return bad


def showdown_violations(lineup: list[dict]) -> list[str]:
    bad = []
    cpt = [p for p in lineup if p["roster_slot"] == "CPT"]
    flex = [p for p in lineup if p["roster_slot"] == "FLEX"]
    if len(cpt) != 1 or len(flex) != 5 or len(lineup) != 6:
        bad.append(f"{len(cpt)} CPT / {len(flex)} FLEX")
    if sum(p["salary"] for p in lineup) > SALARY_CAP:
        bad.append("over the salary cap")
    if len({p["name"] for p in lineup}) != len(lineup):
        bad.append("a player in both CPT and FLEX, or twice")
    if len({p["team"] for p in lineup}) < 2:
        bad.append("only one team")
    return bad


def _classic_pool(rng: random.Random) -> list[dict]:
    games = [("A", "B"), ("C", "D"), ("E", "F"), ("G", "H")]
    pool, pid = [], 0
    for away, home in games:
        for team in (away, home):
            for pos, count in (("QB", 2), ("RB", 4), ("WR", 5), ("TE", 3), ("DST", 1)):
                for k in range(count):
                    pid += 1
                    salary = 100 * rng.randint(25, 95) if pos != "DST" else 100 * rng.randint(20, 40)
                    proj = round(rng.uniform(3, 30) * salary / 6000, 2)
                    pool.append(dict(dk_draftable_id=pid, name=f"{team}{pos}{k}", position=pos, team=team, salary=salary,
                                     proj_points=proj, ceiling=proj * 1.4, dk_fppg=proj, roster_slot="", game_info=f"{away}@{home}",
                                     injury="Healthy"))
    return pool


def _showdown_pool(rng: random.Random) -> list[dict]:
    pool, pid = [], 0
    for team in ("A", "B"):
        for pos, count in (("QB", 2), ("RB", 3), ("WR", 4), ("TE", 2), ("K", 1), ("DST", 1)):
            for k in range(count):
                salary = 100 * rng.randint(20, 90)
                proj = round(rng.uniform(2, 28) * salary / 6000, 2)
                for slot, mult in (("CPT", 1.5), ("FLEX", 1.0)):
                    pid += 1
                    pool.append(dict(dk_draftable_id=pid, name=f"{team}{pos}{k}", position=pos, team=team, salary=int(salary * mult),
                                     proj_points=round(proj * mult, 2), ceiling=proj * mult * 1.4, dk_fppg=proj, roster_slot=slot,
                                     game_info="A@B", injury="Healthy"))
    return pool


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("metric", ["proj_points", "ceiling"])
def test_classic_lineups_obey_every_roster_rule(seed, metric):
    pool = _classic_pool(random.Random(seed))
    lineup = optimize(pool, "classic", metric)
    assert lineup and classic_violations(lineup) == []
    assert optimize(pool, "classic", metric) == lineup                    # deterministic for the same input


@pytest.mark.parametrize("seed", range(8))
def test_showdown_lineups_obey_every_roster_rule(seed):
    pool = _showdown_pool(random.Random(seed))
    lineup = optimize(pool, "showdown", "proj_points")
    assert lineup and showdown_violations(lineup) == []
    cpt = lineup[0]
    assert cpt["roster_slot"] == "CPT"
    assert cpt["proj_points"] == pytest.approx(1.5 * next(p["proj_points"] for p in pool if p["name"] == cpt["name"] and p["roster_slot"] == "FLEX"), abs=0.02)


def test_showdown_captain_multiplier_is_counted_once():
    # CPT rows already carry 1.5x salary and points; the objective is their plain sum, nothing re-multiplied
    pool = _showdown_pool(random.Random(3))
    lineup = optimize(pool, "showdown", "proj_points")
    assert sum(p["proj_points"] for p in lineup) == pytest.approx(
        sum(p["proj_points"] for p in lineup if p["roster_slot"] == "CPT") + sum(p["proj_points"] for p in lineup if p["roster_slot"] == "FLEX"))
    assert lineup[0]["salary"] == pytest.approx(1.5 * next(p["salary"] for p in pool if p["name"] == lineup[0]["name"] and p["roster_slot"] == "FLEX"), abs=1)


def test_classic_is_infeasible_when_a_position_is_missing_or_one_game_only():
    pool = _classic_pool(random.Random(1))
    assert optimize([p for p in pool if p["position"] != "TE"], "classic", "proj_points") is None
    assert optimize([p for p in pool if p["game_info"] == "A@B"], "classic", "proj_points") is None     # DK needs 2+ games


def test_nobody_over_the_cap_when_every_salary_is_expensive():
    pool = _classic_pool(random.Random(2))
    for p in pool:
        p["salary"] += 6000
    assert optimize(pool, "classic", "proj_points") is None


def test_injured_and_zero_salary_players_never_appear():
    pool = _classic_pool(random.Random(4))
    for p in pool[:40]:
        p["injury"] = "OUT"
    pool[40]["salary"] = 0
    lineup = optimize(pool, "classic", "proj_points")
    assert {p["dk_draftable_id"] for p in lineup}.isdisjoint({p["dk_draftable_id"] for p in pool[:40]} | {pool[40]["dk_draftable_id"]})


def test_build_many_lineups_are_each_valid_and_distinct():
    pool = _classic_pool(random.Random(5))
    lineups = build_many(pool, "classic", "proj_points", 5, min_unique=2)
    assert len(lineups) == 5
    for lu in lineups:
        assert classic_violations(lu) == []
    ids = [frozenset(p["dk_draftable_id"] for p in lu) for lu in lineups]
    assert len(set(ids)) == 5 and all(len(a & b) <= 7 for i, a in enumerate(ids) for b in ids[i + 1:])
