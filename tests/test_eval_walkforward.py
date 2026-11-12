import random

from scripts import eval_walkforward as ev


def _line(rng, pos):
    return {"pass_td": rng.uniform(0.5, 2.5) if pos == "QB" else 0, "pass_yd": rng.uniform(150, 320) if pos == "QB" else 0,
            "rush_yd": rng.uniform(0, 90), "rush_td": rng.uniform(0, 0.8), "rec_yd": rng.uniform(0, 90), "rec_td": rng.uniform(0, 0.7)}


def _rows(n, seed, implied_shift=0.0, bump=0.0):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        pos = rng.choice(["QB", "RB", "WR", "TE"])
        proj = rng.uniform(5, 22)
        implied = rng.uniform(16, 30) + implied_shift
        out.append({"season": 2025, "week": rng.randint(2, 17), "key": "k", "pos": pos, "proj": proj, "history": [proj * rng.uniform(0.4, 1.6) for _ in range(rng.choice([3, 8, 12]))],
                    "line": _line(rng, pos), "implied": implied, "spread": rng.uniform(-10, 10), "ts_l3": rng.uniform(0.05, 0.35),
                    "snap_l3": rng.uniform(0.3, 0.9), "actual": max(0.0, rng.gauss(proj + bump, 6))})
    return out


def test_implied_edges_come_from_training_rows_only():
    train = _rows(300, 1)
    lo, hi = ev.implied_edges(train)
    assert 16 <= lo < hi <= 30
    assert ev._bucket(lo, (lo, hi)) == "low implied" and ev._bucket(hi + 0.01, (lo, hi)) == "high implied"


def test_spread_buckets_cover_every_margin_once():
    names = {ev._spread_name(m / 2) for m in range(-40, 41)}
    assert names == {n for n, _, _ in ev.SPREAD_BUCKETS}
    assert ev._spread_name(-12) == "big dog (-6.5 or worse)" and ev._spread_name(0) == "close (-2.5 to 2.5)"


def test_slices_partition_and_flag_thin():
    rows = _rows(200, 2)
    sl = ev.slice_rows(rows, (20.0, 25.0))
    for prefix in ("pos:", "env:", "spread:", "history:"):
        assert sum(len(v) for k, v in sl.items() if k.startswith(prefix)) == len(rows)
    m = ev.slice_metrics(rows[:10], lambda r: r["proj"] * 1.5)
    assert m["thin"] and m["n"] == 10


def test_metrics_are_exact_on_a_hand_worked_case():
    rows = [{"actual": 10.0, "proj": 8.0}, {"actual": 30.0, "proj": 12.0}]
    m = ev.slice_metrics(rows, lambda r: 20.0)         # ceilings 20: first under (d=-10), second over (d=+10)
    assert m["beat_ceiling"] == 0.5
    assert m["pinball"] == round((0.15 * 10 + 0.85 * 10) / 2, 3)    # (tau-1)*d = 1.5 ; tau*d = 8.5
    assert m["ceiling_bias"] == 0.0 and m["proj_bias"] == 10.0 and m["proj_mae"] == 10.0


def test_gate_needs_overall_and_low_implied_wins():
    base = {"all": {"pinball": 2.0, "beat_ceiling": 0.15}, "env: low implied": {"pinball": 2.0, "beat_ceiling": 0.10}}
    better = {"all": {"pinball": 1.9, "beat_ceiling": 0.15}, "env: low implied": {"pinball": 1.9, "beat_ceiling": 0.14}}
    assert ev.passes_gate(better, base) == (True, [])
    only_overall = {**better, "env: low implied": {"pinball": 2.1, "beat_ceiling": 0.14}}
    ok, why = ev.passes_gate(only_overall, base)
    assert not ok and any("low implied" in w for w in why)
    worse_calibration = {"all": {"pinball": 1.9, "beat_ceiling": 0.15}, "env: low implied": {"pinball": 1.9, "beat_ceiling": 0.05}}
    assert not ev.passes_gate(worse_calibration, base)[0]


def test_walk_forward_scores_each_fold_with_a_model_trained_before_it():
    seen = []

    def build(train):
        seen.append(len(train))
        mean_actual = sum(r["actual"] for r in train) / len(train)
        return {"flat": lambda r: mean_actual * 2}
    folds = {2025: (_rows(120, 3), _rows(60, 4)), 2026: (_rows(150, 5), _rows(40, 6))}
    out = ev.walk_forward(folds, build)
    assert seen == [120, 150]
    assert out["folds"]["2025"]["test_n"] == 60 and out["pooled"]["flat"]["all"]["n"] == 100
    assert sum(v["n"] for k, v in out["pooled"]["flat"].items() if k.startswith("pos:")) == 100


def test_default_candidates_fit_and_evaluate_on_synthetic_rows():
    train, test = _rows(400, 7), _rows(80, 8)
    out = ev.walk_forward({2025: (train, test)})
    assert set(out["pooled"]) == {"current", "projection_multiple", "formula_core"}
    assert out["pooled"]["current"]["all"]["n"] == 80
