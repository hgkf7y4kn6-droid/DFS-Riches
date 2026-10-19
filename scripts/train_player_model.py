"""Fit the player projection correction (app.player_model) on 2025 and test it on 2026.

    python -m scripts.train_player_model [--data DIR]

Sleeper's weekly projections (2025 and this season) are scored with DraftKings rules and compared to actual DK
points from nflverse weekly stats; features use only earlier games. Writes data/player_model.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import urllib.request
from pathlib import Path

from app import dk_scoring, game_model as gm, player_model as pm, projections
from app.matching import normalize_name
from scripts.train_game_model import GAMES_URL, REL, fetch

SLEEPER = "https://api.sleeper.com/projections/nfl/{season}/{week}?season_type=regular" + "".join(
    f"&position[]={p}" for p in pm.POSITIONS)
TEAM_FIX = {"LAR": "LA"}            # Sleeper -> nflverse
ALPHAS = (10, 30, 100, 300, 1000, 3000)


def sleeper_week(d: Path, season: int, week: int) -> list[dict]:
    path = d / f"sleeper_{season}_{week}.json"
    if not path.exists():
        print(f"sleeper {season} week {week}", file=sys.stderr)
        req = urllib.request.Request(SLEEPER.format(season=season, week=week), headers={"User-Agent": "Mozilla/5.0 DFSRiches"})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.write_bytes(r.read())
    return json.loads(path.read_text())


def lines(d: Path, season: int) -> dict[tuple[int, str], tuple[float, float]]:
    """{(week, team): (implied total, expected margin)} from the closing lines."""
    out = {}
    for g in csv.DictReader(open(fetch(GAMES_URL, d / "games.csv"), newline="")):
        if g["season"] != str(season) or g["game_type"] != "REG" or not g["total_line"] or not g["spread_line"]:
            continue
        t, s = float(g["total_line"]), float(g["spread_line"])     # s: home expected margin
        out[(int(g["week"]), g["home_team"])] = ((t + s) / 2, s)
        out[(int(g["week"]), g["away_team"])] = ((t - s) / 2, -s)
    return out


def rows_for(d: Path, season: int, weeks) -> list[dict]:
    stats = list(csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv",
                                           d / f"stats_player_week_{season}.csv"), newline="")))
    snaps = list(csv.DictReader(open(fetch(f"{REL}/snap_counts/snap_counts_{season}.csv", d / f"snap_counts_{season}.csv"), newline="")))
    hist = pm.history(stats, snaps, points=dk_scoring.dk_offense_points)
    ln = lines(d, season)
    proj_by_week: dict[int, dict[str, float]] = {}
    out = []
    for w in weeks:
        proj_by_week[w] = {}
        for e in sleeper_week(d, season, w):
            pl, pos = e.get("player") or {}, (e.get("player") or {}).get("position")
            if pos not in pm.POSITIONS or not e.get("team"):
                continue
            p = projections.dk_points_from_line(e.get("stats") or {}, pos)
            name = f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip()
            proj_by_week[w][pm.key(name, pos)] = p
            if p < 3:
                continue
            k = pm.key(name, pos)
            h = hist.get(k, {})
            team = TEAM_FIX.get(e["team"], e["team"])
            imp, spr = ln.get((w, team), (None, None))
            if w not in h or imp is None:
                continue            # didn't play (no stat row) or no line: not a projection miss we can learn from
            ph = {x: proj_by_week[x][k] for x in proj_by_week if x < w and k in proj_by_week[x]}
            f = pm.features(h, w, p, pos, imp, spr, ph)
            out.append({"season": season, "week": w, "key": k, "pos": pos, "f": f, "proj": p, "actual": h[w]["pts"]})
    return out


def fit(rows, alpha):
    X = [[r["f"][k] for k in pm.FEATURES] for r in rows]
    w, m, s, b = gm.fit_ridge(X, [r["actual"] - r["proj"] for r in rows], alpha)
    return {"features": list(pm.FEATURES), "weights": w, "means": m, "sds": s, "intercept": b, "alpha": alpha}


def spearman(x, y):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v)
        for k, i in enumerate(o):
            r[i] = k
        return r
    rx, ry = rank(x), rank(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return num / math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))


def evaluate(rows, models) -> dict:
    """MAE of Sleeper vs corrected projections, and within position-week ranking (Spearman) of each vs actual."""
    adj = [pm.adjustment(r["pos"], r["f"], {"positions": models}) or 0.0 for r in rows]
    mae0 = statistics.fmean(abs(r["actual"] - r["proj"]) for r in rows)
    mae1 = statistics.fmean(abs(r["actual"] - r["proj"] - a) for r, a in zip(rows, adj))
    groups: dict[tuple, list] = {}
    for r, a in zip(rows, adj):
        groups.setdefault((r["season"], r["week"], r["pos"]), []).append((r["proj"], r["proj"] + a, r["actual"]))
    rho0 = statistics.fmean(spearman([g[0] for g in v], [g[2] for g in v]) for v in groups.values() if len(v) >= 8)
    rho1 = statistics.fmean(spearman([g[1] for g in v], [g[2] for g in v]) for v in groups.values() if len(v) >= 8)
    resid = [r["actual"] - r["proj"] for r in rows]
    k = len(rows) // 3
    order = sorted(range(len(rows)), key=lambda i: adj[i])
    top, bot = order[-k:], order[:k]
    boom = lambda idx: sum(rows[i]["actual"] >= 1.5 * rows[i]["proj"] for i in idx) / len(idx)  # noqa: E731
    bust = lambda idx: sum(rows[i]["actual"] < 0.5 * rows[i]["proj"] for i in idx) / len(idx)  # noqa: E731
    return {"n": len(rows), "mae_sleeper": round(mae0, 3), "mae_corrected": round(mae1, 3),
            "rank_rho_sleeper": round(rho0, 3), "rank_rho_corrected": round(rho1, 3),
            "adj_vs_miss_rho": round(spearman(adj, resid), 3),
            "top_third_boom": round(boom(top), 3), "top_third_bust": round(bust(top), 3),
            "bottom_third_boom": round(boom(bot), 3), "bottom_third_bust": round(bust(bot), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-season", type=int, default=2026)
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    d.mkdir(parents=True, exist_ok=True)
    train = [r for r in rows_for(d, args.test_season - 1, range(1, 19)) if r["week"] >= 2]
    test = [r for r in rows_for(d, args.test_season, range(1, args.test_weeks + 1)) if r["week"] >= 2]
    print(f"train player-weeks {len(train)}, test {len(test)}")
    models = {}
    for pos in pm.POSITIONS:
        tr = [r for r in train if r["pos"] == pos]
        # choose the penalty on the second half of 2025 (fit on the first half)
        first, second = [r for r in tr if r["week"] <= 9], [r for r in tr if r["week"] > 9]
        best = min(ALPHAS, key=lambda a: statistics.fmean(
            abs(r["actual"] - r["proj"] - (pm.adjustment(pos, r["f"], {"positions": {pos: fit(first, a)}}) or 0)) for r in second))
        models[pos] = fit(tr, best)
        print(pos, "alpha", best, [(f, round(w, 2)) for f, w in zip(pm.FEATURES, models[pos]["weights"])])
    rec_train = evaluate(train, models)
    rec_test = evaluate(test, models)
    print("2025 (in sample):", rec_train)
    print(f"{args.test_season} weeks 2-{args.test_weeks} (out of sample):", rec_test)
    pm.MODEL_FILE.write_text(json.dumps({"trained_on": [args.test_season - 1], "positions": models,
                                         "records": {"train": rec_train, "test": rec_test}}, indent=1))


if __name__ == "__main__":
    main()
