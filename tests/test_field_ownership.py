import numpy as np
import pytest

from app import field_ownership as fo
from app import play_rankings as pr


def _table():
    """A small synthetic Classic slate: 4 teams, enough players at every position."""
    rows, pid = [], 0
    teams = [("AAA", "BBB"), ("BBB", "AAA"), ("CCC", "DDD"), ("DDD", "CCC")]
    spec = {"QB": [(7000, 21), (6000, 18)], "RB": [(8000, 19), (6500, 15), (5000, 11), (4000, 7)],
            "WR": [(8000, 18), (6800, 15), (5500, 12), (4200, 9), (3500, 7)], "TE": [(6000, 13), (3500, 7)],
            "DST": [(3500, 8)]}
    for t, opp in teams:
        for pos, players in spec.items():
            for k, (sal, proj) in enumerate(players):
                pid += 1
                rows.append({"id": pid, "name": f"{t} {pos}{k}", "position": pos, "team": t, "opponent": opp,
                             "salary": sal, "final": float(proj) + (pid % 3) * 0.4, "floor": proj * 0.55,
                             "ceiling": proj * 1.75, "injury": "Healthy"})
    games = [{"away": "AAA", "home": "BBB", "away_implied": 24.0, "home_implied": 21.0, "env_score": 0.6},
             {"away": "CCC", "home": "DDD", "away_implied": 20.0, "home_implied": 23.5, "env_score": -0.2}]
    return rows, games


def test_engineered_features_and_backup_injury_start():
    table, games = _table()
    starter = next(p for p in table if p["team"] == "AAA" and p["position"] == "RB" and p["salary"] == 8000)
    starter["injury"] = "OUT"
    rows = fo.engineer(table, games)
    assert all(r["id"] != starter["id"] for r in rows)                      # out players leave the pool
    backup = next(r for r in rows if r["team"] == "AAA" and r["position"] == "RB" and r["salary"] == 6500)
    assert backup["backup"] == 1.0
    r = next(r for r in rows if r["team"] == "AAA" and r["position"] == "QB" and r["salary"] == 7000)
    assert r["value"] == pytest.approx(r["final"] / 7.0)
    assert r["implied"] == 24.0
    qbs = [x for x in rows if x["position"] == "QB"]
    assert sorted(x["pos_value_rank"] for x in qbs) == [float(i) for i in range(1, len(qbs) + 1)]
    assert sum(x["salary_delta_k"] for x in qbs) == pytest.approx(0.0)
    assert all(x["scarcity"] > 0 for x in rows)


def test_field_simulation_fills_every_slot_and_stays_bounded():
    rows = fo.engineer(*_table())
    own, price = fo.simulate_field(rows, "large_gpp", n_sims=2000)
    totals = fo._slot_totals(own, rows)
    assert totals["QB"] == pytest.approx(1.0)
    assert totals["DST"] == pytest.approx(1.0)
    assert totals["RB"] + totals["WR"] + totals["TE"] == pytest.approx(7.0)   # 2 RB + 3 WR + TE + FLEX
    assert totals["TE"] < 1.3                                                  # fields rarely FLEX a TE
    assert ((own >= 0) & (own <= 1)).all()
    assert price > 0


def test_cash_field_is_more_concentrated_than_large_gpp():
    rows = fo.engineer(*_table())
    cash, _ = fo.simulate_field(rows, "cash", n_sims=3000)
    gpp, _ = fo.simulate_field(rows, "large_gpp", n_sims=3000)
    assert cash.max() > gpp.max()


def test_bradley_terry_shares_sum_to_slots_and_pairwise_odds():
    rows = fo.engineer(*_table())
    totals = {"QB": 1.0, "RB": 2.4, "WR": 3.5, "TE": 1.1, "DST": 1.0}
    bt = fo.bradley_terry(rows, "cash", 2.5, totals)
    for pos, total in totals.items():
        assert sum(bt[i] for i, r in enumerate(rows) if r["position"] == pos) == pytest.approx(total)
    assert fo.bt_head_to_head(3.0, 1.0) == pytest.approx(0.75)


def test_fractional_logit_recovers_a_bounded_relationship():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(400, len(fo.FEATURES)))
    true = fo.special.expit(-2.0 + 1.2 * X[:, 1] + 0.8 * X[:, 2])
    y = np.clip(true + rng.normal(scale=0.02, size=400), 0, 1)
    model = fo.fit_fractional_logit(X, y)
    pred = fo.predict_fractional_logit(model, X)
    assert ((pred > 0) & (pred < 1)).all()
    assert np.corrcoef(pred, true)[0, 1] > 0.95


def test_gbm_trains_when_lightgbm_is_available():
    pytest.importorskip("lightgbm")
    rng = np.random.default_rng(1)
    X = rng.normal(size=(400, len(fo.FEATURES)))
    y = fo.special.expit(-2 + X[:, 1])
    model = fo.fit_gbm(X, y)
    assert model is not None
    assert np.corrcoef(model.predict(X), fo.special.logit(y))[0, 1] > 0.9


def test_contest_ownership_untrained_uses_sim_and_bradley_terry(monkeypatch):
    monkeypatch.setattr(fo, "trained_models", lambda c: {"slates": 0, "rows": 0, "frac_logit": None, "gbm": None})
    rows = fo.engineer(*_table())
    res = fo.contest_ownership(rows, "small_gpp", n_sims=1500)
    assert set(res["weights"]) == {"sim", "bt"}
    assert sum(res["weights"].values()) == pytest.approx(1.0)
    assert sum(res["own"][i] for i, r in enumerate(rows) if r["position"] == "QB") == pytest.approx(1.0)


def test_play_rankings_counts_tags_and_ownership(monkeypatch):
    monkeypatch.setattr(fo, "trained_models", lambda c: {"slates": 0, "rows": 0, "frac_logit": None, "gbm": None})
    monkeypatch.setattr(fo, "save_features", lambda *a, **k: None)
    monkeypatch.setattr(fo, "N_SIMS", 1500)
    table, games = _table()
    cash = pr.build(table, games, "cash", 2026, 1, "classic")
    assert {p: len(v) for p, v in cash["rankings"].items()} == {"QB": 5, "RB": 10, "WR": 10, "TE": 5}
    assert [p["rank"] for p in cash["rankings"]["RB"]] == list(range(1, 11))
    assert all(set(p["ownership"]) == {"cash"} for p in cash["players"])
    assert {p["tag"] for p in cash["players"]} <= {"prioritize", "neutral", "fade"}
    gpp = pr.build(table, games, "gpp", 2026, 1, "classic")
    assert all(set(p["ownership"]) == {"small_gpp", "large_gpp"} for p in gpp["players"])
    top_rb = gpp["rankings"]["RB"][0]
    assert top_rb["score"] >= gpp["rankings"]["RB"][-1]["score"]
    assert "leverage" in top_rb["parts"]
    assert "chalk" not in cash and len(gpp["chalk"]) == len(gpp["leverage"]) == pr.CROSS_N
    chalk_own = [p["ownership"]["large_gpp"] for p in gpp["chalk"]]
    assert chalk_own == sorted(chalk_own, reverse=True)
    ratios = [p["leverage_ratio"] for p in gpp["leverage"]]
    assert ratios == sorted(ratios, reverse=True)
    assert all(p["p_hit"] >= pr.LEVERAGE_MIN_CEILING for p in gpp["leverage"])


def test_models_train_on_stored_features_and_actual_ownership(tmp_path, monkeypatch):
    from app import ownership_store as store

    monkeypatch.setattr(store, "OWN_DIR", tmp_path)
    fo._TRAINED.clear()
    rng = np.random.default_rng(3)
    table, games = _table()
    rows = fo.engineer(table, games)
    for week in (1, 2, 3):
        fo.save_features(2026, week, "classic", rows)
        data = store.load(2026, week, "classic")
        for r in rows:
            own = float(fo.special.expit(-3 + 0.25 * r["final"] + rng.normal(scale=0.2)))
            data["observations"].append({"kind": "actual", "contest": "cash", "key": store.player_key(r["name"], r["team"], r["position"]),
                                         "pct": round(own * 100, 2)})
        store.save(data)
    trained = fo.trained_models("cash")
    assert trained["slates"] == 3 and trained["rows"] == 3 * len(rows)
    assert trained["frac_logit"] is not None
    assert fo.trained_models("small_gpp")["frac_logit"] is None    # no small-field actuals stored
    fo._TRAINED.clear()
