"""Fit the DST projection (app.dst_model) on 2023-2025 and test it on 2026.

    python -m scripts.train_dst_model [--data DIR]

Rows are every team-week with a Sleeper defense projection and a closing line; the target is actual DK DST points
(nflverse team stats: sacks, takeaways, safeties, blocked kicks, defensive and return TDs, and the points-allowed
tiers). Ridge regression, the penalty chosen by leaving one training season out (mean absolute error). Writes
data/dst_model.json with the 2026 record against Sleeper's line as is.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import urllib.request
from pathlib import Path

from app import dk_scoring, dst_model as dm, game_model as gm, projections
from scripts import train_game_model as tgm, train_player_model as tpm
from scripts.train_game_model import GAMES_URL, REL, fetch

SLEEPER_DEF = "https://api.sleeper.com/projections/nfl/{season}/{week}?season_type=regular&position[]=DEF"
ALPHAS = (1, 3, 10, 30, 100, 300, 1000)


def sleeper_def(d: Path, season: int, week: int) -> list[dict]:
    path = d / f"sleeper_def_{season}_{week}.json"
    if not path.exists():
        print(f"sleeper DEF {season} week {week}", file=sys.stderr)
        req = urllib.request.Request(SLEEPER_DEF.format(season=season, week=week), headers={"User-Agent": "Mozilla/5.0 DFSRiches"})
        with urllib.request.urlopen(req, timeout=120) as r:
            path.write_bytes(r.read())
    return json.loads(path.read_text())


def team_rows(d: Path, year: int) -> list[dict]:
    path = fetch(f"{REL}/stats_team/stats_team_week_{year}.csv", d / f"stats_team_week_{year}.csv")
    return [r for r in csv.DictReader(open(path, newline="")) if r.get("season_type") == "REG"]


def pa_sd(d: Path, seasons) -> float:
    """Spread of team scores around their implied totals (closing lines)."""
    xs = []
    for g in csv.DictReader(open(fetch(GAMES_URL, d / "games.csv"), newline="")):
        if g["game_type"] == "REG" and int(g["season"]) in seasons and g["home_score"] and g["total_line"]:
            t, s = float(g["total_line"]), float(g["spread_line"])
            xs += [int(g["home_score"]) - (t + s) / 2, int(g["away_score"]) - (t - s) / 2]
    return round(statistics.pstdev(xs), 2)


def rows_for(d: Path, year: int, weeks, sd: float) -> list[dict]:
    games = [g for g in csv.DictReader(open(fetch(GAMES_URL, d / "games.csv"), newline=""))
             if g["game_type"] == "REG" and g["season"] == str(year) and g["home_score"] != "" and g["total_line"]]
    cur, prev = team_rows(d, year), team_rows(d, year - 1)
    by_team = {(int(r["week"]), r["team"]): r for r in cur}
    agg, agg_prev = tgm.season_agg(d, year), tgm.season_agg(d, year - 1)
    lg_pass = gm.priors_from_season(gm.season_totals(agg_prev))["league"]["pass_epa"]
    out = []
    for w in weeks:
        line = {}
        for e in sleeper_def(d, year, w):
            t = tpm.TEAM_FIX.get(e.get("team") or "", e.get("team"))
            if t:
                line[t] = projections.dk_points_from_line(e.get("stats") or {}, "DEF")
        rates = dm.team_rates(cur, prev, w)
        qh = gm.qb_history(agg_prev, agg, before_week=w)
        for g in games:
            if int(g["week"]) != w:
                continue
            total, spread = float(g["total_line"]), float(g["spread_line"])
            for side, team, opp in (("home", g["home_team"], g["away_team"]), ("away", g["away_team"], g["home_team"])):
                r = by_team.get((w, team))
                if r is None or team not in line:
                    continue
                opp_score = int(g["away_score"] if side == "home" else g["home_score"])
                margin = spread if side == "home" else -spread
                q_epa, q_n = gm.qb_estimate(qh, g.get(f"{'away' if side == 'home' else 'home'}_qb_id"), lg_pass)
                f = dm.features(line[team], (total - margin) / 2, margin, q_epa, q_n, rates.get(team), rates.get(opp), sd)
                actual = dk_scoring.dk_dst_points(r, opp_score)
                out.append({"season": year, "week": w, "team": team, "f": f, "actual": actual})
    return out


def fit(rows, alpha):
    X = [[r["f"][k] for k in dm.FEATURES] for r in rows]
    w, m, s, b = gm.fit_ridge(X, [r["actual"] for r in rows], alpha)
    return {"features": list(dm.FEATURES), "weights": w, "means": m, "sds": s, "intercept": b, "alpha": alpha}


def evaluate(rows, pred) -> dict:
    """Average miss, within-week rank correlation, and the average actual points of each week's top three."""
    weeks: dict[tuple, list] = {}
    for r in rows:
        weeks.setdefault((r["season"], r["week"]), []).append(r)
    top3 = statistics.fmean(statistics.fmean(r["actual"] for r in sorted(v, key=lambda r: -pred(r))[:3]) for v in weeks.values())
    return {"n": len(rows), "mae": round(statistics.fmean(abs(r["actual"] - pred(r)) for r in rows), 3),
            "rank_rho": round(statistics.fmean(tpm.spearman([pred(r) for r in v], [r["actual"] for r in v]) for v in weeks.values()), 3),
            "top3_avg_actual": round(top3, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-season", type=int, default=2026)
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    d.mkdir(parents=True, exist_ok=True)
    seasons = [args.test_season - 3, args.test_season - 2, args.test_season - 1]
    sd = pa_sd(d, seasons)
    train = [r for s in seasons for r in rows_for(d, s, range(1, 19), sd)]
    test = rows_for(d, args.test_season, range(1, args.test_weeks + 1), sd)
    print(f"train team-weeks {len(train)} ({seasons}), test {len(test)}; opponent-score sd {sd}")

    def cv(a):
        held = []
        for s in seasons:
            m = fit([r for r in train if r["season"] != s], a)
            held += [abs(r["actual"] - gm.apply(m, r["f"])) for r in train if r["season"] == s]
        return statistics.fmean(held)
    alpha = min(ALPHAS, key=cv)
    model = fit(train, alpha)
    held = {}
    for s in seasons:
        m = fit([r for r in train if r["season"] != s], alpha)
        held.update({id(r): gm.apply(m, r["f"]) for r in train if r["season"] == s})
    rec = {"test": evaluate(test, lambda r: gm.apply(model, r["f"])), "test_sleeper": evaluate(test, lambda r: r["f"]["sleeper"]),
           "held_out_seasons": evaluate(train, lambda r: held[id(r)]), "held_out_sleeper": evaluate(train, lambda r: r["f"]["sleeper"])}
    print("alpha", alpha, {k: round(w / s, 3) for k, w, s in zip(dm.FEATURES, model["weights"], model["sds"])})
    for k, v in rec.items():
        print(k, v)
    dm.MODEL_FILE.write_text(json.dumps({"trained_on": seasons, "pa_sd": sd, "model": model, "records": rec}, indent=1))


if __name__ == "__main__":
    main()
