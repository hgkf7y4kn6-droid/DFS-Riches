"""Fit the shootout leverage model (app.shootout_leverage) and backtest it.

    python -m scripts.train_leverage [--data DIR]

1. For every Sunday main-slate game of 2023-2025 (1:00 and 4:00 kickoffs), count how many of the week's top
   DFS scorers it produced (top 3 QBs, 6 RBs, 9 WRs, 3 TEs of the slate by DraftKings points).
2. Fit a Poisson model of that count on the Vegas total and spread; leave one season out to check it beats
   "every game gets an even share".
3. Record how often games in each total band finished 10+ over their total and reached 50+ points.
4. Backtest the rating on this season's slates with saved projected ownership (data/ownership): do games whose
   expected share of top scorers most exceeds their share of the field produce more top scorers per unit of
   ownership?
Writes data/leverage_model.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from app import dk_scoring
from app import shootout_leverage as sl
from app.matching import normalize_name
from scripts.train_game_model import GAMES_URL, REL, fetch

ROOT = Path(__file__).resolve().parent.parent


def main_slate(g: dict) -> bool:
    return g["weekday"] == "Sunday" and "12:00" <= g["gametime"] < "17:00"


def top_counts(stats: list[dict], week: int, team_game: dict[str, str], n_games: int) -> tuple[dict[str, int], int]:
    """{game: top scorers} among the given teams' players; per-position counts scale with the slate's size."""
    pts = [(s["position"], s["team"], dk_scoring.dk_offense_points(s)) for s in stats
           if s.get("season_type") == "REG" and int(s["week"]) == week and s["position"] in sl.TOP and s["team"] in team_game]
    cnt: dict[str, int] = defaultdict(int)
    total = 0
    for pos, n in sl.TOP.items():
        k = max(1, round(n * n_games / 13))
        for _, t, _ in sorted([p for p in pts if p[0] == pos], key=lambda p: -p[2])[:k]:
            cnt[team_game[t]] += 1
            total += 1
    return cnt, total


def build(d: Path, seasons) -> list[dict]:
    games = [g for g in csv.DictReader(open(fetch(GAMES_URL, d / "games.csv"), newline=""))
             if g["game_type"] == "REG" and g["home_score"] and g["total_line"] and g["spread_line"]]
    rows = []
    for y in seasons:
        stats = list(csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{y}.csv", d / f"stats_player_week_{y}.csv"), newline="")))
        for w in sorted({int(g["week"]) for g in games if g["season"] == str(y)}):
            slate = [g for g in games if g["season"] == str(y) and int(g["week"]) == w and main_slate(g)]
            if len(slate) < 6:
                continue
            team_game = {t: g["game_id"] for g in slate for t in (g["away_team"], g["home_team"])}
            cnt, _ = top_counts(stats, w, team_game, len(slate))
            for g in slate:
                rows.append({"season": y, "week": w, "game": g["game_id"], "total_line": float(g["total_line"]),
                             "spread": abs(float(g["spread_line"])), "final": int(g["home_score"]) + int(g["away_score"]),
                             "top": cnt[g["game_id"]]})
    return rows


def fit_poisson(rows, ridge=1.0, iters=40) -> list[float]:
    b = [0.0] * 3
    for _ in range(iters):
        g = [0.0] * 3
        H = [[0.0] * 3 for _ in range(3)]
        for r in rows:
            x = sl.features(r["total_line"], r["spread"])
            mu = math.exp(sum(bi * xi for bi, xi in zip(b, x)))
            for i in range(3):
                g[i] += (r["top"] - mu) * x[i]
                for j in range(3):
                    H[i][j] += mu * x[i] * x[j]
        for i in (1, 2):
            g[i] -= ridge * b[i]
            H[i][i] += ridge
        M = [H[i][:] + [g[i]] for i in range(3)]
        for c in range(3):
            p = max(range(c, 3), key=lambda k: abs(M[k][c]))
            M[c], M[p] = M[p], M[c]
            for k in range(3):
                if k != c:
                    f = M[k][c] / M[c][c]
                    M[k] = [a - f * bb for a, bb in zip(M[k], M[c])]
        b = [bi + M[i][3] / M[i][i] for i, bi in enumerate(b)]
    return b


def log_scores(rows, coef) -> tuple[float, float]:
    ll_m = ll_e = 0.0
    for key in {(r["season"], r["week"]) for r in rows}:
        slate = [r for r in rows if (r["season"], r["week"]) == key]
        shares = sl.expected_shares([(r["total_line"], r["spread"]) for r in slate], coef)
        for r, s in zip(slate, shares):
            ll_m += r["top"] * math.log(s)
            ll_e += r["top"] * math.log(1 / len(slate))
    return round(ll_m, 1), round(ll_e, 1)


def bands(rows) -> list[dict]:
    out = []
    for lo, hi in sl.BANDS:
        xs = [r for r in rows if lo <= r["total_line"] < hi]
        out.append({"lo": lo, "hi": hi, "games": len(xs),
                    "over_by_10": round(sum(r["final"] - r["total_line"] >= 10 for r in xs) / len(xs), 3),
                    "points_50": round(sum(r["final"] >= 50 for r in xs) / len(xs), 3)})
    return out


def ownership_backtest(d: Path, season: int, coef) -> dict:
    """This season's slates with saved projected ownership: games ranked by leverage vs the top scorers they
    produced per unit of ownership."""
    stats = list(csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv",
                                           d / f"stats_player_week_{season}.csv"), newline="")))
    team_of = {(normalize_name(s["player_display_name"]), int(s["week"])): s["team"] for s in stats if s.get("season_type") == "REG"}
    games = [g for g in csv.DictReader(open(d / "games.csv", newline="")) if g["season"] == str(season) and g["game_type"] == "REG"
             and g["home_score"] and g["total_line"]]
    out = []
    for f in sorted((ROOT / "data" / "ownership").glob(f"{season}_w*_classic*.json")):
        own = json.loads(f.read_text())
        w = own["week"]
        hist = [h for h in own.get("history") or [] if not own.get("lock") or h["timestamp"] <= own["lock"]]
        if not hist:
            continue
        gpp = hist[-1]["contests"]["gpp"]
        team_game = {t: g["game_id"] for g in games if int(g["week"]) == w for t in (g["away_team"], g["home_team"])}
        own_g: dict[str, float] = defaultdict(float)
        for name, (a, b) in gpp.items():
            t = team_of.get((normalize_name(name), w))
            if t in team_game:
                own_g[team_game[t]] += a / (a + b)
        slate = [g for g in games if g["game_id"] in own_g]
        if len(slate) < 3:
            continue
        team_game = {t: g["game_id"] for g in slate for t in (g["away_team"], g["home_team"])}
        cnt, n_top = top_counts(stats, w, team_game, len(slate))
        tot_own = sum(own_g.values())
        shares = sl.expected_shares([(float(g["total_line"]), abs(float(g["spread_line"]))) for g in slate], coef)
        for g, s in zip(slate, shares):
            o = own_g[g["game_id"]] / tot_own
            out.append({"week": w, "game": g["game_id"], "total_line": float(g["total_line"]), "own_share": round(o, 4),
                        "expected_share": round(s, 4), "leverage": round(s / o, 3), "top_share": round(cnt[g["game_id"]] / n_top, 4)})
    if not out:
        return {"games": 0}
    out.sort(key=lambda r: -r["leverage"])
    k = max(1, len(out) // 3)
    per = lambda grp: round(sum(r["top_share"] for r in grp) / sum(r["own_share"] for r in grp), 2)  # noqa: E731
    return {"games": len(out), "weeks": sorted({r["week"] for r in out}),
            "top_third": {"top_scorers_per_ownership": per(out[:k]), "avg_total": round(statistics.fmean(r["total_line"] for r in out[:k]), 1)},
            "bottom_third": {"top_scorers_per_ownership": per(out[-k:]), "avg_total": round(statistics.fmean(r["total_line"] for r in out[-k:]), 1)},
            "rows": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()
    d = Path(args.data)
    d.mkdir(parents=True, exist_ok=True)
    train_seasons = [args.season - 3, args.season - 2, args.season - 1]
    rows = build(d, train_seasons)
    cv = {}
    for s in train_seasons:
        coef = fit_poisson([r for r in rows if r["season"] != s])
        m, e = log_scores([r for r in rows if r["season"] == s], coef)
        cv[str(s)] = {"model": m, "even": e}
        print(f"{s}: log score {m} vs even shares {e}")
    coef = fit_poisson(rows)
    bt = ownership_backtest(d, args.season, coef)
    print("coefficients", [round(c, 3) for c in coef])
    print("ownership backtest", {k: v for k, v in bt.items() if k != "rows"})
    sl.MODEL_FILE.write_text(json.dumps({"trained_on": train_seasons, "coef": coef, "bands": bands(rows), "cv_log_score": cv,
                                         "games": len(rows), "ownership_backtest": bt}, indent=1))


if __name__ == "__main__":
    main()
