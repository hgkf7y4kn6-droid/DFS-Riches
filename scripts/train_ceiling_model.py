"""Fit the ceiling model (app.ceiling_model) on 2023-2025 and test it on 2026.

    python -m scripts.train_ceiling_model [--data DIR]

Rows are Sleeper-projected QB/RB/WR/TE player-weeks (3+ projected DK points, Week 2 on) that played; the
projection includes the role & script model (app.player_model). One linear quantile regression per position at
the 85th percentile (pinball loss, solved as a linear program). Writes data/ceiling_model.json with the 2026
record against two baselines: the projection times a fitted position multiple, and app.ceiling's formula core.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.optimize import linprog

from app import ceiling_model as cm, dk_scoring, player_model as pm
from scripts import train_player_model as tpm
from scripts.train_game_model import REL, fetch

TAU = 0.85
FEATURES = {"QB": ["proj", "sd", "p85", "rush_share", "yds", "implied", "abs_spread"],
            "RB": ["proj", "sd", "p85", "td_share", "yds", "implied", "abs_spread", "ts_l3", "snap_l3"],
            "WR": ["proj", "sd", "p85", "td_share", "yds", "implied", "abs_spread", "ts_l3"],
            "TE": ["proj", "sd", "p85", "td_share", "yds", "implied", "abs_spread", "ts_l3"]}


def _stats(d: Path, year: int) -> list[dict]:
    path = fetch(f"{REL}/stats_player/stats_player_week_{year}.csv", d / f"stats_player_week_{year}.csv")
    return [s for s in csv.DictReader(open(path, newline="")) if s.get("season_type", "REG") == "REG"]


def rows_for(d: Path, year: int, weeks) -> list[dict]:
    """The player trainer's player-weeks (scripts.train_player_model.player_weeks) with the projection the app
    shows (plus the role & script adjustment) and each player's last 12 games before the week."""
    games: dict[str, list] = {}
    for s in _stats(d, year - 1) + _stats(d, year):
        games.setdefault(pm.key(s["player_display_name"], s["position"]), []).append(
            (int(s["season"]), int(s["week"]), dk_scoring.dk_offense_points(s)))
    out = []
    for r in tpm.player_weeks(d, year, [w for w in weeks if w >= 2]):
        past = [g[2] for g in sorted(games.get(r["key"], [])) if (g[0], g[1]) < (year, r["week"])]
        out.append({"season": year, "week": r["week"], "key": r["key"], "pos": r["pos"], "actual": r["actual"],
                    "proj": r["proj"] + (pm.adjustment(r["pos"], r["f"]) or 0.0), "history": past[-12:], "line": r["line"],
                    "implied": r["implied"], "spread": r["spread"], "ts_l3": r["f"]["ts_l3"], "snap_l3": r["f"]["snap_l3"]})
    return out


def typical_cv(rows) -> dict[str, float]:
    out = {}
    for pos in pm.POSITIONS:
        cvs = [statistics.pstdev(r["history"]) / statistics.fmean(r["history"]) for r in rows
               if r["pos"] == pos and len(r["history"]) >= 6 and statistics.fmean(r["history"]) > 3]
        out[pos] = round(statistics.median(cvs), 3)
    return out


def fit_qr(X: np.ndarray, y: np.ndarray, tau: float = TAU) -> dict:
    """Linear quantile regression on standardized inputs: min sum tau*u + (1-tau)*v s.t. y - Zb = u - v."""
    n, p = X.shape
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.hstack([np.ones((n, 1)), (X - mu) / sd])
    k = p + 1
    c = np.concatenate([np.zeros(2 * k), tau * np.ones(n), (1 - tau) * np.ones(n)])
    A = sparse.hstack([sparse.csr_matrix(Z), sparse.csr_matrix(-Z), sparse.identity(n), -sparse.identity(n)]).tocsr()
    res = linprog(c, A_eq=A, b_eq=y, bounds=(0, None), method="highs")
    b = res.x[:k] - res.x[k:2 * k]
    return {"mu": mu.round(5).tolist(), "sd": sd.round(5).tolist(), "b": b.round(5).tolist()}


def evaluate(rows, ceil) -> dict:
    """Pinball loss, how often the actual beat the ceiling (target 15%), within position-week rank correlation,
    and the share of each position-week's top 10% scorers whose ceiling ranked in its top 20%."""
    y = np.array([r["actual"] for r in rows])
    q = np.array([ceil(r) for r in rows])
    d = y - q
    groups: dict[tuple, list] = {}
    for r, c in zip(rows, q):
        groups.setdefault((r["season"], r["week"], r["pos"]), []).append((c, r["actual"]))
    rho = statistics.fmean(tpm.spearman([a for a, _ in v], [b for _, b in v]) for v in groups.values() if len(v) >= 8)
    cap = []
    for v in groups.values():
        if len(v) >= 10:
            k = max(1, len(v) // 10)
            top_ceil = set(sorted(range(len(v)), key=lambda i: -v[i][0])[:2 * k])
            cap.append(sum(i in top_ceil for i in sorted(range(len(v)), key=lambda i: -v[i][1])[:k]) / k)
    return {"n": len(rows), "pinball": round(float(np.mean(np.maximum(TAU * d, (TAU - 1) * d))), 3),
            "beat_ceiling": round(float(np.mean(d > 0)), 3), "rank_rho": round(rho, 3),
            "top10_in_top20": round(statistics.fmean(cap), 3)}


def formula_core(r, cv) -> float:
    """app.ceiling's history core (mean + 1.04 x spread shrunk toward the position's), blended with the projection."""
    pts = r["history"]
    n = len(pts)
    mean = statistics.fmean(pts) if pts else r["proj"]
    sd = statistics.pstdev(pts) if n >= 2 else cv[r["pos"]] * r["proj"]
    sd = (n * sd + 4 * cv[r["pos"]] * r["proj"]) / (n + 4)
    return max(r["proj"], 0.5 * mean + 0.5 * r["proj"] + 1.04 * sd)


def live_ceilings(season: int) -> dict[tuple[int, str], float]:
    """{(week, player key): ceiling} the app showed before lock, from the saved ownership snapshots (data/ownership)."""
    out = {}
    for path in sorted(Path("data/ownership").glob(f"{season}_w*_classic_sunday.json")):
        snap = json.loads(path.read_text())
        week, roster = snap.get("week"), (snap.get("features") or {}).get("roster") or {}
        for name, v in (snap.get("engineered_features") or {}).items():
            pos = (roster.get(name) or [None])[0]
            if pos in pm.POSITIONS and v.get("ceiling") is not None:
                out[(week, pm.key(name, pos))] = v["ceiling"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-season", type=int, default=2026)
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    d.mkdir(parents=True, exist_ok=True)
    seasons = [args.test_season - 3, args.test_season - 2, args.test_season - 1]
    train = [r for s in seasons for r in rows_for(d, s, range(2, 19))]
    test = rows_for(d, args.test_season, range(2, args.test_weeks + 1))
    print(f"train player-weeks {len(train)} ({seasons}), test {len(test)}")
    cv = typical_cv(train)
    model = {"cv_pos": cv, "positions": {}}
    for pos in pm.POSITIONS:
        tr = [r for r in train if r["pos"] == pos]
        xs = [cm.inputs(pos, r["proj"], r["history"], r["line"], r["implied"], r["spread"], r["ts_l3"], r["snap_l3"], model)
              for r in tr]
        X = np.array([[x[f] for f in FEATURES[pos]] for x in xs])
        model["positions"][pos] = {"features": FEATURES[pos], **fit_qr(X, np.array([r["actual"] for r in tr]))}
        print(pos, dict(zip(["const"] + FEATURES[pos], model["positions"][pos]["b"])))
    mult = {p: float(np.quantile([r["actual"] / r["proj"] for r in train if r["pos"] == p], TAU)) for p in pm.POSITIONS}

    def new(r):
        return cm.ceiling(r["pos"], cm.inputs(r["pos"], r["proj"], r["history"], r["line"], r["implied"], r["spread"],
                                              r["ts_l3"], r["snap_l3"], model), model)

    rec = {"test": evaluate(test, new), "test_projection_multiple": evaluate(test, lambda r: r["proj"] * mult[r["pos"]]),
           "test_formula_core": evaluate(test, lambda r: formula_core(r, cv)), "train": evaluate(train, new)}
    live = live_ceilings(args.test_season)
    sub = [r for r in test if (r["week"], r["key"]) in live]
    if sub:
        rec["test_live_weeks"] = {"weeks": sorted({r["week"] for r in sub}), "model": evaluate(sub, new),
                                  "app_ceiling_live": evaluate(sub, lambda r: live[(r["week"], r["key"])])}
    for k, v in rec.items():
        print(k, v)
    model["records"] = rec
    model["trained_on"] = seasons
    cm.MODEL_FILE.write_text(json.dumps(model, indent=1))


if __name__ == "__main__":
    main()
