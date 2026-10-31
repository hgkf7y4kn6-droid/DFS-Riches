"""Walk-forward evaluation gate for the 85th-percentile ceiling (and the projections under it).

    python -m scripts.eval_walkforward [--data DIR] [--folds 2025 2026] [--test-weeks 8] [--out FILE]

For each fold season S the models train on the three seasons before S only and are scored on S (for the current
season, Weeks 2 through --test-weeks), so no row is ever scored by a model that saw its own season. Rows come from
scripts.train_ceiling_model.rows_for (Sleeper-projected QB/RB/WR/TE player-weeks that played, 3+ projected DK
points, inputs from earlier games only), which needs nflverse downloads and Sleeper's historical projections.

Every metric is reported overall and split where the model's known weak spots show up: position, implied-total
tercile (edges taken from the *training* rows), spread bucket (the team's expected margin), history length, and
the high-target-share pass catcher on a low-total team. A change ships only if `passes_gate` says it beats the
current model out of sample overall and in the low-implied tercile; record that in the model JSON.

Metrics: pinball loss at tau 0.85, beat rate (target 0.15), mean actual-minus-ceiling and actual-minus-projection
(positive = under-forecast), and MAE of the projection.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Callable

import numpy as np

from app import ceiling_model as cm, player_model as pm
from scripts import train_ceiling_model as tcm

TAU = tcm.TAU
THIN = 30                        # slices smaller than this are flagged, not trusted
TS_ALPHA, LOW_IMPLIED = 0.25, 20.0
SPREAD_BUCKETS = (("big dog (-6.5 or worse)", None, -6.5), ("dog (-6.5 to -2.5)", -6.5, -2.5), ("close (-2.5 to 2.5)", -2.5, 2.5),
                  ("favorite (2.5 to 6.5)", 2.5, 6.5), ("big favorite (6.5+)", 6.5, None))

Ceil = Callable[[dict], float]


def implied_edges(train: list[dict]) -> tuple[float, float]:
    """Tercile edges of the implied team total, from training rows only."""
    xs = sorted(r["implied"] for r in train)
    return xs[len(xs) // 3], xs[2 * len(xs) // 3]


def _bucket(x: float, edges: tuple[float, float]) -> str:
    return "low implied" if x <= edges[0] else "mid implied" if x <= edges[1] else "high implied"


def _spread_name(margin: float) -> str:
    for name, lo, hi in SPREAD_BUCKETS:
        if (lo is None or margin > lo) and (hi is None or margin <= hi):
            return name
    return SPREAD_BUCKETS[-1][0]


def slice_rows(rows: list[dict], edges: tuple[float, float]) -> dict[str, list[dict]]:
    """name -> rows, for the overall set and each split."""
    out: dict[str, list[dict]] = {"all": list(rows)}

    def add(name, r):
        out.setdefault(name, []).append(r)
    for r in rows:
        add(f"pos: {r['pos']}", r)
        add(f"env: {_bucket(r['implied'], edges)}", r)
        add(f"spread: {_spread_name(r['spread'])}", r)
        n = len(r["history"])
        add("history: <6 games" if n < 6 else "history: 6-11 games" if n < 12 else "history: 12 games", r)
        if r["pos"] in ("WR", "TE") and r["ts_l3"] >= TS_ALPHA and r["implied"] <= LOW_IMPLIED:
            add("alpha pass catcher (ts>=25%) on implied<=20", r)
    return out


def slice_metrics(rows: list[dict], ceil: Ceil) -> dict:
    y = np.array([r["actual"] for r in rows])
    q = np.array([ceil(r) for r in rows])
    p = np.array([r["proj"] for r in rows])
    d = y - q
    return {"n": len(rows), "thin": len(rows) < THIN,
            "pinball": round(float(np.mean(np.maximum(TAU * d, (TAU - 1) * d))), 3),
            "beat_ceiling": round(float(np.mean(d > 0)), 3),
            "ceiling_bias": round(float(np.mean(d)), 2),
            "proj_bias": round(float(np.mean(y - p)), 2),
            "proj_mae": round(float(np.mean(np.abs(y - p))), 2)}


def evaluate_slices(rows: list[dict], ceil: Ceil, edges: tuple[float, float]) -> dict[str, dict]:
    return {name: slice_metrics(rs, ceil) for name, rs in slice_rows(rows, edges).items()}


def passes_gate(candidate: dict[str, dict], baseline: dict[str, dict]) -> tuple[bool, list[str]]:
    """Whether a candidate may replace the baseline: lower pinball loss overall AND in the low-implied tercile (the
    environment the current model under-serves), without a worse beat rate than the baseline's in the low tercile.
    Returns (ok, reasons it failed)."""
    why = []
    for name in ("all", "env: low implied"):
        if name not in candidate or name not in baseline:
            why.append(f"{name}: missing")
        elif candidate[name]["pinball"] >= baseline[name]["pinball"]:
            why.append(f"{name}: pinball {candidate[name]['pinball']} is not below {baseline[name]['pinball']}")
    low_c, low_b = candidate.get("env: low implied"), baseline.get("env: low implied")
    if low_c and low_b and abs(low_c["beat_ceiling"] - (1 - TAU)) > abs(low_b["beat_ceiling"] - (1 - TAU)) + 1e-9:
        why.append(f"env: low implied: beat rate {low_c['beat_ceiling']} is further from {1 - TAU:.2f} than {low_b['beat_ceiling']}")
    return not why, why


def candidates(train: list[dict]) -> dict[str, Ceil]:
    """The models compared on one fold, each fit to `train` only. Add new candidates here (WS5 adds ceiling v3)."""
    model = tcm.fit_model(train)
    cv = model["cv_pos"]
    mult = {p: float(np.quantile([r["actual"] / r["proj"] for r in train if r["pos"] == p], TAU)) for p in pm.POSITIONS}

    def current(r):
        return cm.ceiling(r["pos"], cm.inputs(r["pos"], r["proj"], r["history"], r["line"], r["implied"], r["spread"],
                                              r["ts_l3"], r["snap_l3"], model), model)
    return {"current": current,
            "projection_multiple": lambda r: r["proj"] * mult[r["pos"]],
            "formula_core": lambda r: tcm.formula_core(r, cv)}


def walk_forward(folds: dict[int, tuple[list[dict], list[dict]]], build: Callable[[list[dict]], dict[str, Ceil]] = candidates) -> dict:
    """folds: season -> (train rows, test rows). Returns per-fold and pooled slice metrics for every candidate."""
    result: dict = {"folds": {}, "pooled": {}}
    pooled: dict[str, list[tuple[dict, float]]] = {}
    pooled_edges: list[tuple[float, float]] = []
    for season, (train, test) in sorted(folds.items()):
        edges = implied_edges(train)
        pooled_edges.append(edges)
        models = build(train)
        result["folds"][str(season)] = {"train_n": len(train), "test_n": len(test), "implied_edges": [round(e, 2) for e in edges],
                                       "models": {name: evaluate_slices(test, fn, edges) for name, fn in models.items()}}
        for name, fn in models.items():
            pooled.setdefault(name, []).extend((r, fn(r)) for r in test)
    if pooled_edges:
        edges = (statistics.fmean(e[0] for e in pooled_edges), statistics.fmean(e[1] for e in pooled_edges))
        for name, pairs in pooled.items():
            cache = {id(r): c for r, c in pairs}
            result["pooled"][name] = evaluate_slices([r for r, _ in pairs], lambda r, cache=cache: cache[id(r)], edges)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--folds", type=int, nargs="+", default=[2025, 2026])
    ap.add_argument("--test-weeks", type=int, default=8, help="last week scored in a fold's season (earlier folds score every week)")
    ap.add_argument("--current-season", type=int, default=2026, help="the in-progress season, scored only through --test-weeks")
    ap.add_argument("--out", default="data/eval_walkforward.json")
    args = ap.parse_args()
    d = Path(args.data)
    d.mkdir(parents=True, exist_ok=True)
    folds = {}
    for season in args.folds:
        train = [r for s in (season - 3, season - 2, season - 1) for r in tcm.rows_for(d, s, range(2, 19))]
        last = args.test_weeks if season >= args.current_season else 18
        folds[season] = (train, tcm.rows_for(d, season, range(2, last + 1)))
        print(f"fold {season}: train {len(train)}, test {len(folds[season][1])}")
    result = walk_forward(folds)
    ok, why = passes_gate(result["pooled"].get("current", {}), result["pooled"].get("formula_core", {}))
    result["note"] = ("Out-of-sample, trained on the three prior seasons per fold. 'current' vs 'formula_core' gate check is "
                      f"informational here: {'passes' if ok else 'fails: ' + '; '.join(why)}")
    Path(args.out).write_text(json.dumps(result, indent=1))
    for name, sl in result["pooled"].items():
        print(f"\n{name}")
        for s, m in sl.items():
            print(f"  {s:48s} n={m['n']:5d}{'*' if m['thin'] else ' '} pinball={m['pinball']:.3f} beat={m['beat_ceiling']:.3f} "
                  f"ceil_bias={m['ceiling_bias']:+.2f} proj_bias={m['proj_bias']:+.2f}")
    print("\n* thin slice (n < 30)")


if __name__ == "__main__":
    main()
