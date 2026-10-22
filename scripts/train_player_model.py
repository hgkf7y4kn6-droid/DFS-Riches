"""Fit the player projection correction (app.player_model) on 2023-2025 and test it on 2026.

    python -m scripts.train_player_model [--data DIR]

Sleeper's weekly projections (2023-2025 and this season) are scored with DraftKings rules and compared to actual DK
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
from scripts import train_game_model as tgm
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


def player_weeks(d: Path, season: int, weeks):
    """The model inputs shared by the player and ceiling trainers, one dict per Sleeper-projected QB/RB/WR/TE
    player-week that played, had 3+ projected DK points and a closing line: {week, key, pos, proj (Sleeper),
    f (app.player_model.features), actual, line (Sleeper's stat line), implied, spread, opp_cb_out}. Inputs use only
    earlier games."""
    stats = list(csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv",
                                           d / f"stats_player_week_{season}.csv"), newline="")))
    snaps = list(csv.DictReader(open(fetch(f"{REL}/snap_counts/snap_counts_{season}.csv", d / f"snap_counts_{season}.csv"), newline="")))
    hist = pm.history(stats, snaps, points=dk_scoring.dk_offense_points)
    ln = lines(d, season)
    agg, prev = tgm.season_agg(d, season), tgm.season_agg(d, season - 1)
    priors = gm.priors_from_season(gm.season_totals(prev))
    ol, dsnaps = tgm.snap_ol(d, season), tgm.snap_def(d, season)
    pressure: dict[int, dict[str, float]] = {}
    explosive: dict[int, dict[str, float]] = {}

    def opp_pressure(week: int, team: str) -> float:
        if week not in pressure:
            est = gm.team_estimates(gm.season_totals(agg, before_week=week), priors)
            pressure[week] = {t: e["d_pressure4"] - priors["league"]["d_pressure4"] for t, e in est.items()}
            explosive[week] = {t: e["d_explosive"] - priors["league"]["d_explosive"] for t, e in est.items()}
        return pressure[week].get(team, 0.0)

    def opp_explosive(week: int, team: str) -> float:
        opp_pressure(week, team)
        return explosive[week].get(team, 0.0)

    weeks = set(weeks)
    proj_by_week: dict[int, dict[str, float]] = {}
    for w in range(1, max(weeks) + 1):
        proj_by_week[w] = {}
        entries = sleeper_week(d, season, w)
        for e in entries:     # every projected line, team or not -- as app.player_model.context reads them live
            pl, pos = e.get("player") or {}, (e.get("player") or {}).get("position")
            if pos in pm.POSITIONS:
                name = f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip()
                proj_by_week[w][pm.key(name, pos)] = projections.dk_points_from_line(e.get("stats") or {}, pos)
        if w not in weeks:
            continue
        for e in entries:
            pl, pos = e.get("player") or {}, (e.get("player") or {}).get("position")
            if pos not in pm.POSITIONS or not e.get("team"):
                continue
            k = pm.key(f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip(), pos)
            p = proj_by_week[w][k]
            h = hist.get(k, {})
            team = TEAM_FIX.get(e["team"], e["team"])
            imp, spr = ln.get((w, team), (None, None))
            if p < 3 or w not in h or imp is None:
                continue            # no real role, didn't play (no stat row), or no line: not a miss we can learn from
            ph = {x: proj_by_week[x][k] for x in proj_by_week if x < w and k in proj_by_week[x]}
            opp = TEAM_FIX.get(e.get("opponent") or "", e.get("opponent") or "")
            f = pm.features(h, w, p, pos, imp, spr, ph, opp_pressure=opp_pressure(w, opp), ol_out=tgm.ol_out(ol, team, w),
                            front7_out=sum(n for u, n in gm.def_out_played(dsnaps, opp, w).items() if u in gm.FRONT7),
                            line=e.get("stats") or {}, opp_explosive=opp_explosive(w, opp),
                            opp_cb_out=gm.cb_out_played(dsnaps, opp, w))
            yield {"week": w, "key": k, "pos": pos, "proj": p, "f": f, "actual": h[w]["pts"], "line": e.get("stats") or {},
                   "implied": imp, "spread": spr, "opp_cb_out": gm.cb_out_played(dsnaps, opp, w)}


def rows_for(d: Path, season: int, weeks) -> list[dict]:
    return [{"season": season, "week": r["week"], "key": r["key"], "pos": r["pos"], "f": r["f"], "proj": r["proj"],
             "actual": r["actual"]} for r in player_weeks(d, season, weeks)]


def fit(rows, alpha, features=pm.FEATURES):
    X = [[r["f"][k] for k in features] for r in rows]
    w, m, s, b = gm.fit_ridge(X, [r["actual"] - r["proj"] for r in rows], alpha)
    return {"features": list(features), "weights": w, "means": m, "sds": s, "intercept": b, "alpha": alpha}


def _ranks(v):
    """Average ranks (ties share their mean rank)."""
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(x, y):
    rx, ry = _ranks(x), _ranks(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


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


def center(model, rows):
    """Shift the intercept so the training adjustments average zero: the model re-ranks players against Sleeper's
    projection rather than moving every projection toward the (right-skewed) mean, which raises absolute error."""
    adj = [gm.apply(model, r["f"]) for r in rows]
    return {**model, "intercept": model["intercept"] - statistics.fmean(adj)}


def fit_all(rows, features=pm.FEATURES, seasons=None):
    """One model per position, the penalty chosen by leaving one training season out (mean absolute error)."""
    models = {}
    for pos in pm.POSITIONS:
        tr = [r for r in rows if r["pos"] == pos]
        def cv(a):
            errs = []
            for s in seasons:
                rest = [r for r in tr if r["season"] != s]
                m = center(fit(rest, a, features), rest)
                errs += [abs(r["actual"] - r["proj"] - (pm.adjustment(pos, r["f"], {"positions": {pos: m}}) or 0))
                         for r in tr if r["season"] == s]
            return statistics.fmean(errs)
        best = min(ALPHAS, key=cv)
        models[pos] = center(fit(tr, best, features), tr)
        print(pos, "alpha", best, [(f, round(w, 2)) for f, w in zip(features, models[pos]["weights"])])
    return models


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-season", type=int, default=2026)
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    d.mkdir(parents=True, exist_ok=True)
    seasons = [args.test_season - 3, args.test_season - 2, args.test_season - 1]
    train = [r for s in seasons for r in rows_for(d, s, range(1, 19)) if r["week"] >= 2]
    test = [r for r in rows_for(d, args.test_season, range(1, args.test_weeks + 1)) if r["week"] >= 2]
    print(f"train player-weeks {len(train)} ({seasons}), test {len(test)}")
    base_feats = tuple(f for f in pm.FEATURES if f not in ("opp_pressure", "ol_out", "front7_out", "spread_x_wpc",
                                                           "adot_x_opp_explosive", "cb_out_x_wr"))
    print("-- role & script only")
    base = fit_all(train, base_feats, seasons)
    print("-- plus opponent pressure and offensive-line starters out")
    no_f7 = fit_all(train, tuple(f for f in pm.FEATURES if f not in ("front7_out", "spread_x_wpc", "adot_x_opp_explosive",
                                                                   "cb_out_x_wr")), seasons)
    print("-- plus the opponent's front-seven starters out (running backs)")
    no_wpc = fit_all(train, tuple(f for f in pm.FEATURES if f not in ("spread_x_wpc", "adot_x_opp_explosive", "cb_out_x_wr")), seasons)
    print("-- plus the spread for workhorse pass-catching backs")
    no_adot = fit_all(train, tuple(f for f in pm.FEATURES if f not in ("adot_x_opp_explosive", "cb_out_x_wr")), seasons)
    print("-- plus receivers' depth of target x the opponent's explosive plays allowed")
    no_cb = fit_all(train, tuple(f for f in pm.FEATURES if f != "cb_out_x_wr"), seasons)
    print("-- plus the opponent's starting corners out")
    models = fit_all(train, pm.FEATURES, seasons)
    rb = [r for r in test if r["pos"] == "RB"]
    rec = {"train": evaluate(train, models), "test": evaluate(test, models),
           "test_role_script_only": evaluate(test, base), "test_without_front7_out": evaluate(test, no_f7),
           "test_rb": evaluate(rb, models), "test_rb_without_front7_out": evaluate(rb, no_f7),
           "test_without_spread_x_wpc": evaluate(test, no_wpc), "test_rb_without_spread_x_wpc": evaluate(rb, no_wpc),
           "test_without_adot_x_opp_explosive": evaluate(test, no_adot),
           "test_wr_te": evaluate([r for r in test if r["pos"] in ("WR", "TE")], models),
           "test_wr_te_without_adot_x_opp_explosive": evaluate([r for r in test if r["pos"] in ("WR", "TE")], no_adot),
           "test_without_cb_out": evaluate(test, no_cb),
           "test_wr_rb": evaluate([r for r in test if r["pos"] in ("WR", "RB")], models),
           "test_wr_rb_without_cb_out": evaluate([r for r in test if r["pos"] in ("WR", "RB")], no_cb)}
    previous = json.loads(pm.MODEL_FILE.read_text()).get("records") if pm.MODEL_FILE.exists() else None
    if previous:
        rec["test_previous_model"] = previous.get("test")
    for k, v in rec.items():
        print(k, v)
    pm.MODEL_FILE.write_text(json.dumps({"trained_on": seasons, "positions": models, "records": rec}, indent=1))


if __name__ == "__main__":
    main()
