"""Fit the median-based prop pricer (app.prop_pricer) on 2023-2025 and test it on 2026.

    python -m scripts.fit_prop_pricer [--data DIR]

Rows are the ceiling trainer's player-weeks (scripts.train_ceiling_model.rows_for: Sleeper-projected QB/RB/WR/TE
who played, Week 2 on), each stat projected as Sleeper's stat times the app's points correction (corrected /
Sleeper DK points), graded against nflverse's actual stat.

Per stat and position: the lognormal shift (from a grid) and sigma minimize log loss over standard lines (the
projection x 0.7-1.3, at the half yard / half catch), with the bias set so half the actual results land above the
median; the two-piece normal's widths come from the 15th/50th/85th percentiles of the residuals around the median,
scaled by the projection to a power picked on training; tail_from is the first ladder rung from which the
two-piece normal priced better than the lognormal in training.

The 2026 record compares four ways to price the same projection: a normal around the average (sd of the misses),
a two-piece normal around the average (how the app prices DK-point thresholds), the lognormal around the median,
and the hybrid the app uses. No historical sportsbook prop lines are available, so lines are built around each
projection, plus Sleeper's projected stat as a stand-in market line. Writes data/prop_pricer.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import optimize, special

from app import player_model as pm, prop_pricer as pp, projections
from scripts import train_ceiling_model as tcm
from scripts.train_game_model import REL, fetch

TRAIN, TEST = (2023, 2024, 2025), 2026
ACTUAL = {"pass_yd": "passing_yards", "rush_yd": "rushing_yards", "rec_yd": "receiving_yards", "rec": "receptions"}
MIN_PROJ = {"pass_yd": 120.0, "rush_yd": 8.0, "rec_yd": 8.0, "rec": 1.0}
SHIFTS = {"pass_yd": (25, 50, 100, 200, 400), "rush_yd": (5, 10, 20, 40, 80), "rec_yd": (5, 10, 20, 40, 80), "rec": (0.5, 1, 2, 4, 8)}
K_GRID = (0.7, 0.85, 1.0, 1.15, 1.3)
POWERS = (0.0, 0.5, 1.0)
Z85 = 1.0364


def f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def half(x: float) -> float:
    """The book-style line at or just above x: n.5."""
    return math.floor(x) + 0.5


def standard_lines(proj: float) -> list[float]:
    return sorted({half(proj * k) for k in K_GRID if proj * k >= 0.5})


def brier(ps, ys) -> float:
    return float(np.mean((np.asarray(ps) - np.asarray(ys, float)) ** 2))


def logloss(ps, ys) -> float:
    p = np.clip(np.asarray(ps), 1e-4, 1 - 1e-4)
    y = np.asarray(ys, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


# ------------------------------------------------------------------ rows
def rows(d: Path, season: int, weeks) -> list[dict]:
    actual = {}
    path = fetch(f"{REL}/stats_player/stats_player_week_{season}.csv", d / f"stats_player_week_{season}.csv")
    for s in csv.DictReader(open(path, newline="")):
        if s.get("season_type", "REG") == "REG":
            actual[(int(s["week"]), pm.key(s["player_display_name"], s["position"]))] = s
    out = []
    for r in tcm.rows_for(d, season, weeks):
        a = actual.get((r["week"], r["key"]))
        raw = projections.dk_points_from_line(r["line"], r["pos"])
        if not a or raw <= 0:
            continue
        ratio = r["proj"] / raw
        for stat, (_, positions) in pp.STATS.items():
            proj = f(r["line"].get(stat)) * ratio
            if r["pos"] in positions and proj >= MIN_PROJ[stat]:
                out.append({"season": season, "week": r["week"], "pos": r["pos"], "stat": stat, "proj": proj,
                            "sleeper": f(r["line"].get(stat)), "actual": max(f(a.get(ACTUAL[stat])), 0.0)})
    return out


# ------------------------------------------------------------------ fit
def fit_lognormal(tr: list[dict], stat: str) -> dict:
    best = None
    for shift in SHIFTS[stat]:
        e = [math.log(r["actual"] + shift) - math.log(r["proj"] + shift) for r in tr]
        bias = float(np.median(e))
        pairs = [(L, r) for r in tr for L in standard_lines(r["proj"])]
        ys = np.array([r["actual"] > L for L, r in pairs], float)
        lz = np.array([math.log(L + shift) for L, _ in pairs])
        lm = np.array([math.log(r["proj"] + shift) + bias for _, r in pairs])

        def loss(log_sigma):
            p = 1 - special.ndtr((lz - lm) / math.exp(log_sigma[0]))
            return logloss(p, ys)
        res = optimize.minimize(loss, [math.log(float(np.std(e)) or 0.5)], method="Nelder-Mead")
        cand = {"shift": shift, "bias": round(bias, 4), "sigma": round(math.exp(res.x[0]), 4), "train_logloss": res.fun}
        if best is None or cand["train_logloss"] < best["train_logloss"]:
            best = cand
    return best


def two_piece_widths(tr: list[dict], p: dict, power: float) -> dict:
    scaled = [(r["actual"] - pp.median(r["proj"], p)) / (r["proj"] + p["shift"]) ** power for r in tr]
    q15, q50, q85 = np.quantile(scaled, [0.15, 0.5, 0.85])
    return {"power": power, "offset": round(float(q50), 4), "lo": round(float(q50 - q15) / Z85, 4),
            "hi": round(float(q85 - q50) / Z85, 4)}


def rung_brier(rs: list[dict], stat: str, prob) -> dict[str, float]:
    step = 0.5 if stat == "rec" else 0.01
    out = {}
    for rung in pp.RUNGS[stat]:
        ys = [r["actual"] >= rung for r in rs]
        out[str(rung)] = brier([prob(rung - step, r) for r in rs], ys)
    return out


def fit(train: list[dict]) -> dict:
    params = {}
    for stat, (_, positions) in pp.STATS.items():
        for pos in positions:
            tr = [r for r in train if r["stat"] == stat and r["pos"] == pos]
            if len(tr) < 200:
                continue
            p = fit_lognormal(tr, stat)
            p.pop("train_logloss")
            best = None
            for power in POWERS:
                q = {**p, "two_piece": two_piece_widths(tr, p, power)}
                score = statistics.fmean(rung_brier(tr, stat, lambda L, r: pp.p_two_piece(L, r["proj"], q)).values())
                if best is None or score < best[0]:
                    best = (score, q)
            p = best[1]
            ln = rung_brier(tr, stat, lambda L, r: pp.p_lognormal(L, r["proj"], p))
            tp = rung_brier(tr, stat, lambda L, r: pp.p_two_piece(L, r["proj"], p))
            tail = None
            for rung in pp.RUNGS[stat]:
                if all(tp[str(x)] < ln[str(x)] for x in pp.RUNGS[stat] if x >= rung):
                    tail = rung
                    break
            p["tail_from"] = tail
            p["n_train"] = len(tr)
            params[f"{stat}|{pos}"] = p
            print(stat, pos, p)
    return params


# ------------------------------------------------------------------ the 2026 record
def mean_pricers(train: list[dict]) -> dict:
    """The average-centered comparators, per stat|pos: a normal (sd of the misses) and a two-piece normal (the
    15th/85th percentile misses either side of the average)."""
    out = {}
    for k in {f"{r['stat']}|{r['pos']}" for r in train}:
        res = [r["actual"] - r["proj"] for r in train if f"{r['stat']}|{r['pos']}" == k]
        q15, q85 = np.quantile(res, [0.15, 0.85])
        out[k] = {"sd": float(np.std(res)), "lo": float(-q15) / Z85, "hi": float(q85) / Z85}
    return out


def evaluate(test: list[dict], params: dict, mp: dict) -> dict:
    def pricers(r):
        k = f"{r['stat']}|{r['pos']}"
        p, m = params[k], mp[k]
        return {
            "normal_at_average": lambda L: float(1 - special.ndtr((L - r["proj"]) / m["sd"])),
            "two_piece_at_average": lambda L: float(1 - special.ndtr((L - r["proj"]) / (m["hi"] if L >= r["proj"] else m["lo"]))),
            "lognormal_at_median": lambda L: pp.p_lognormal(L, r["proj"], p),
            "median_pricer": lambda L: pp.p_over(L, r["proj"], p),
        }
    test = [r for r in test if f"{r['stat']}|{r['pos']}" in params]
    names = ("normal_at_average", "two_piece_at_average", "lognormal_at_median", "median_pricer")
    out: dict = {"n": len(test)}

    # Where the actual result lands against the average vs the median (a fair line has half above).
    out["share_above"] = {
        "average": round(statistics.fmean(r["actual"] > r["proj"] for r in test), 3),
        "median": round(statistics.fmean(r["actual"] > pp.median(r["proj"], params[f"{r['stat']}|{r['pos']}"]) for r in test), 3)}
    out["mae"] = {
        "average": round(statistics.fmean(abs(r["actual"] - r["proj"]) for r in test), 2),
        "median": round(statistics.fmean(abs(r["actual"] - pp.median(r["proj"], params[f"{r['stat']}|{r['pos']}"])) for r in test), 2)}

    # Standard lines around each projection
    std = {n: ([], []) for n in names}
    calib = defaultdict(lambda: [0, 0, 0.0])
    for r in test:
        pr = pricers(r)
        for L in standard_lines(r["proj"]):
            y = r["actual"] > L
            for n in names:
                p = pr[n](L)
                std[n][0].append(p)
                std[n][1].append(y)
                if n == "median_pricer":
                    b = min(9, int(p * 10))
                    calib[b][0] += 1
                    calib[b][1] += y
                    calib[b][2] += p
    out["standard_lines"] = {n: {"brier": round(brier(*std[n]), 4), "logloss": round(logloss(*std[n]), 4),
                                 "avg_p_over": round(statistics.fmean(std[n][0]), 3)} for n in names}
    out["standard_lines"]["actual_over_rate"] = round(statistics.fmean(std[names[0]][1]), 3)
    out["calibration_median_pricer"] = [
        {"bin": f"{b / 10:.1f}-{(b + 1) / 10:.1f}", "n": c[0], "predicted": round(c[2] / c[0], 3), "actual": round(c[1] / c[0], 3)}
        for b, c in sorted(calib.items())]

    # Ladder rungs, by stat
    out["ladders"] = {}
    for stat in pp.STATS:
        rs = [r for r in test if r["stat"] == stat]
        if not rs:
            continue
        step = 0.5 if stat == "rec" else 0.01
        lad = {}
        for rung in pp.RUNGS[stat]:
            ys = [r["actual"] >= rung for r in rs]
            lad[str(rung)] = {"base_rate": round(statistics.fmean(ys), 3),
                              **{n: round(brier([pricers(r)[n](rung - step) for r in rs], ys), 4) for n in names}}
        out["ladders"][stat] = lad

    # Sleeper's projected stat as a stand-in market line (n.5): picks at 55%+ either way
    picks = {}
    for n in names:
        o, u = [], []
        for r in test:
            if r["sleeper"] < MIN_PROJ[r["stat"]]:
                continue
            L = half(r["sleeper"])
            p = pricers(r)[n](L)
            if p >= 0.55:
                o.append(r["actual"] > L)
            elif p <= 0.45:
                u.append(r["actual"] < L)
        both = o + u
        picks[n] = {"overs": len(o), "over_hit": round(statistics.fmean(o), 3) if o else None,
                    "unders": len(u), "under_hit": round(statistics.fmean(u), 3) if u else None,
                    "hit": round(statistics.fmean(both), 3) if both else None}
    out["vs_sleeper_line_55pct"] = picks

    out["by_stat"] = {}
    for k in sorted(params):
        rs = [r for r in test if f"{r['stat']}|{r['pos']}" == k]
        if not rs:
            continue
        p = params[k]
        ys, pm_, pa = [], [], []
        for r in rs:
            pr = pricers(r)
            for L in standard_lines(r["proj"]):
                ys.append(r["actual"] > L)
                pm_.append(pr["median_pricer"](L))
                pa.append(pr["two_piece_at_average"](L))
        out["by_stat"][k] = {"n": len(rs),
                             "share_above_average": round(statistics.fmean(r["actual"] > r["proj"] for r in rs), 3),
                             "share_above_median": round(statistics.fmean(r["actual"] > pp.median(r["proj"], p) for r in rs), 3),
                             "brier_median_pricer": round(brier(pm_, ys), 4), "brier_two_piece_at_average": round(brier(pa, ys), 4)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    train = [r for s in TRAIN for r in rows(d, s, range(2, 19))]
    test = rows(d, TEST, range(2, args.test_weeks + 1))
    print(f"train stat-weeks {len(train)}, test {len(test)}")
    params = fit(train)
    mp = mean_pricers(train)
    rec = {"test_2026": evaluate(test, params, mp), "train": evaluate(train, params, mp)}
    print(json.dumps(rec["test_2026"], indent=1))
    pp.PARAMS_FILE.write_text(json.dumps({"trained_on": list(TRAIN), "params": params, "records": rec}, indent=1))


if __name__ == "__main__":
    main()
