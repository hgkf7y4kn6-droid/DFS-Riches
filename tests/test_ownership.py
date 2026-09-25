import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app import ownership_field as of
from app import ownership_learning as ol
from app import ownership_model as om
from app import ownership_store as store

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
LOCK = NOW + timedelta(hours=5)


def _obs(key, pct, kind="source", source="S1", contest="gpp", hours_ago=1.0, user="", conf=3):
    return {"kind": kind, "key": key, "pct": pct, "source": source, "contest": contest, "user_id": user, "confidence": conf,
            "timestamp": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_beta_effective_n_and_decay_phases():
    # 20% with N=100 -> Beta(20, 80): sigma = sqrt(.2*.8/101) ~ 3.98 pts
    assert om.n_from_sigma(math.sqrt(0.2 * 0.8 / 101), 0.2) == pytest.approx(100, rel=0.01)
    assert om.half_life_hours(30) == 12 and om.half_life_hours(10) == 6 and om.half_life_hours(2) == 2
    assert om.half_life_hours(0.2) == pytest.approx(0.375)
    assert om.decay(6, 10) == pytest.approx(0.5)


def test_source_bias_correction_matches_the_spec_example():
    learning = {"sources": {"A": {"n": 50, "bias": 0.021, "mae": 0.03, "sd": 0.035}}}
    m = om.model_a("p", "gpp", [_obs("p", 24.0, source="A", hours_ago=0)], learning, NOW, 5)
    assert m["parts"][0]["bias_adjusted"] == pytest.approx(21.9)
    assert m["mu"] == pytest.approx(0.219, abs=1e-6)


def test_correlated_sources_are_not_counted_as_independent():
    obs = [_obs("p", 20.0, source=s, hours_ago=0) for s in ("A", "B", "C")]
    corr = {"source_corr": {"A|B": {"rho": 0.9, "n": 50}, "A|C": {"rho": 0.9, "n": 50}, "B|C": {"rho": 0.9, "n": 50}}}
    dependent = om.model_a("p", "gpp", obs, corr, NOW, 5)
    independent = om.model_a("p", "gpp", obs, {"source_corr": {k: {"rho": 0.0, "n": 50} for k in corr["source_corr"]}}, NOW, 5)
    raw = sum(p["n"] for p in dependent["parts"])
    assert independent["n"] == pytest.approx(raw)
    assert dependent["n"] == pytest.approx(raw / (1 + 2 * 0.9))


def test_accurate_crowd_contributors_carry_more_weight():
    learning = {"users": {"sharp": {"n": 500, "mae": 0.015}, "new": {"n": 0}}}
    crowd = [_obs("p", 30.0, kind="crowd", user="sharp"), _obs("p", 10.0, kind="crowd", user="new")]
    m = om.model_b("gpp", crowd, learning, NOW, 5)
    assert m["mu"] > 0.2 and m["users"] == 2
    assert m["mean"] == pytest.approx(0.2)


def _players():
    ps = []
    for pos, n in (("QB", 4), ("RB", 6), ("WR", 8), ("TE", 4), ("DST", 4)):
        for i in range(n):
            ps.append({"key": f"{pos}{i}", "position": pos, "salary": 7000 - 800 * i, "final": 20 - 3 * i, "value": 3 - 0.2 * i,
                       "ceiling": 30 - 3 * i, "implied": 24, "injury": "Healthy", "team": f"T{i % 4}", "opponent": f"T{(i + 1) % 4}"})
    return ps


def test_posterior_respects_slots_news_and_updates_toward_sources():
    ps = _players()
    ps[5]["injury"] = "O"          # RB1 ruled out
    ps[6]["injury"] = "Q"
    slots = om.classic_slots({})
    post = om.posterior(ps, [_obs("WR0", 40.0, hours_ago=0.5)], {}, now=NOW, lock=LOCK,
                        contests=("gpp", "cash"), group_of=lambda p: p["position"], slots=slots)
    g = post["by_contest"]["gpp"]
    mean = lambda k: g[k]["alpha"] / (g[k]["alpha"] + g[k]["beta"])  # noqa: E731
    healthy = [dict(p, injury="Healthy") if p["key"] == "RB2" else p for p in ps]
    prior_only = om.posterior(healthy, [], {}, now=NOW, lock=LOCK, contests=("gpp",), group_of=lambda p: p["position"], slots=slots)
    pg = prior_only["by_contest"]["gpp"]
    assert mean("RB1") < 0.01 and g["RB1"]["news"].startswith("Confirmed news")
    prior_wr0 = pg["WR0"]["alpha"] / (pg["WR0"]["alpha"] + pg["WR0"]["beta"])
    assert abs(mean("WR0") - 0.40) < abs(prior_wr0 - 0.40)     # the source pulls the posterior toward 40%
    assert g["RB2"]["alpha"] + g["RB2"]["beta"] < pg["RB2"]["alpha"] + pg["RB2"]["beta"]   # Q widens
    qb_total = sum(pg[p["key"]]["alpha"] / (pg[p["key"]]["alpha"] + pg[p["key"]]["beta"]) for p in ps if p["position"] == "QB")
    assert qb_total == pytest.approx(1.0, abs=0.01)
    # nothing after lock counts
    late = om.posterior(ps, [_obs("WR0", 90.0, hours_ago=-6)], {}, now=NOW + timedelta(hours=7), lock=LOCK,
                        contests=("gpp",), group_of=lambda p: p["position"], slots=slots)
    assert late["by_contest"]["gpp"]["WR0"]["models"]["A"] is None


def test_monte_carlo_summaries_are_consistent():
    det = {"a": {"alpha": 20, "beta": 80}, "b": {"alpha": 5, "beta": 95}, "c": {"alpha": 40, "beta": 60}}
    sim = om.simulate(det, ["a", "b", "c"])
    a = sim["stats"]["a"]
    assert a["mean"] == pytest.approx(0.2, abs=0.005)
    assert a["ci95"][0] < a["ci80"][0] < a["ci50"][0] < a["median"] < a["ci50"][1] < a["ci80"][1] < a["ci95"][1]
    assert sum(sim["stats"]["c"]["rank_probs"].values()) == pytest.approx(1.0)
    assert sim["stats"]["c"]["rank_probs"]["1"] > 0.99
    assert a["p_over"]["10"] > a["p_over"]["20"] > a["p_over"]["30"]


def test_parsers():
    rows = store.parse_lines("Ja'Marr Chase, 22.5%\nA.J. Brown\tPHI\t14\nBUF, 8, cheap DST\nnope")
    assert [(r["name"], r["team"], r["pct"]) for r in rows] == [("Ja'Marr Chase", "", 22.5), ("A.J. Brown", "PHI", 14.0), ("BUF", "", 8.0)]
    csv_text = ("Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n"
                "1,1,a,0,150,QB Josh Allen RB Derrick Henry RB James Cook WR A WR B WR C TE D FLEX E DST Bills ,,Josh Allen,QB,21.5%,30\n"
                "2,2,b,0,140,QB Lamar Jackson RB X RB Y WR A WR B WR C TE D FLEX E DST Ravens ,,Bills,DST,8.10%,7\n")
    parsed = store.parse_dk_standings(csv_text)
    assert parsed["entries"] == 2 and parsed["ownership"][("Josh Allen", "QB")] == 21.5
    assert parsed["lineups"][0][0] == ("QB", "Josh Allen") and parsed["lineups"][0][-1] == ("DST", "Bills")


def _field_players():
    ps, sal = [], {"QB": 7000, "RB": 6000, "WR": 5500, "TE": 4000, "DST": 3000}
    for pos, n in (("QB", 2), ("RB", 3), ("WR", 4), ("TE", 2), ("DST", 2)):
        for i in range(n):
            ps.append({"key": f"{pos}{i}", "position": pos, "team": "A" if i % 2 == 0 else "B",
                       "opponent": "B" if i % 2 == 0 else "A", "salary": sal[pos] - 200 * i})
    return ps


def test_exact_lineup_probability_matches_simulated_frequency():
    ps = _field_players()
    theta = {"QB": [0.7, 0.3], "RB": [1.2, 0.8, 0.4], "WR": [1.2, 1.0, 0.8, 0.5], "TE": [0.7, 0.4], "DST": [0.6, 0.4]}
    a, b = [], []
    for p in ps:
        t = theta[p["position"]][int(p["key"][-1])] / 4
        a.append(t * 100000)
        b.append((1 - t) * 100000)
    fm = of.FieldModel(ps, np.array(a), np.array(b), {"RB": 0.4, "WR": 0.5, "TE": 0.1}, {"min_salary": 0}, seed=9)
    acc, p_valid, _ = fm.sample(60000, max_rounds=3)
    freq = Counter(acc)
    lineup, count = freq.most_common(1)[0]
    exact = fm.expected_prob(list(lineup)) / p_valid
    assert count / len(acc) == pytest.approx(exact, rel=0.1)


def test_duplication_scales_with_contest_size():
    ps = _field_players()
    a = np.full(len(ps), 30.0)
    b = np.full(len(ps), 70.0)
    fm = of.FieldModel(ps, a, b, {"RB": 0.4, "WR": 0.5, "TE": 0.1}, {"min_salary": 0}, seed=2)
    lu = ["QB0", "RB0", "RB1", "WR0", "WR1", "WR2", "TE0", "WR3", "DST1"]
    small = of.duplication(fm, {"L": lu}, 100, sims=3000)["lineups"]["L"]
    big = of.duplication(fm, {"L": lu}, 10000, sims=3000)["lineups"]["L"]
    assert big["expected_duplicates"] == pytest.approx(small["expected_duplicates"] * 9999 / 99, rel=0.05)
    assert 0 <= big["p_duplicated"] <= 1


def test_isotonic_is_monotone():
    xs, ys = ol.isotonic([0.1, 0.2, 0.3, 0.4, 0.5], [0.12, 0.30, 0.25, 0.45, 0.44])
    assert all(y2 >= y1 for y1, y2 in zip(ys, ys[1:]))


def test_relearn_grades_sources_against_actual(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "OWN_DIR", tmp_path)
    monkeypatch.setattr(store, "LEARNING_PATH", tmp_path / "learning.json")
    lock = "2026-09-27T17:00:00+00:00"
    obs, snap = [], {}
    rng = np.random.default_rng(0)
    for i in range(40):
        actual = float(rng.uniform(1, 30))
        key = f"p{i}"
        obs.append({"kind": "actual", "key": key, "pct": actual, "contest": "gpp", "source": "dk_standings", "timestamp": "2026-09-28T12:00:00+00:00"})
        obs.append({"kind": "source", "key": key, "pct": actual + 3.0, "contest": "gpp", "source": "HighBias", "timestamp": "2026-09-27T15:00:00+00:00"})
        obs.append({"kind": "source", "key": key, "pct": actual + 3.0, "contest": "gpp", "source": "AfterLock", "timestamp": "2026-09-27T18:00:00+00:00"})
        snap[key] = [actual / 100 * 50, (1 - actual / 100) * 50]
    data = {"season": 2026, "week": 3, "slate_id": "classic_sunday", "lock": lock, "observations": obs, "field_lineups": {},
            "history": [{"timestamp": "2026-09-27T16:00:00+00:00", "contests": {"gpp": snap}}], "features": {}}
    (tmp_path / "2026_w3_classic_sunday.json").write_text(json.dumps(data))
    learning = ol.relearn()
    assert learning["sources"]["HighBias"]["bias"] == pytest.approx(0.03, abs=1e-6)
    assert "AfterLock" not in learning["sources"]           # post-lock numbers are never graded
    assert learning["model"]["by_contest"]["gpp"]["n"] == 40
    assert learning["slates_with_actuals"] == 1
