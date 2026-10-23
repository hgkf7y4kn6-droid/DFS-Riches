"""Who actually plays when listed Questionable or Doubtful, and how do they score?

    python -m scripts.test_injury_trends [--data DIR] [--sites FILE]

1. Play rates, 2019-2026 (nflverse's copy of the official report: the game status and the last practice of the week),
   every position and QB/RB/WR/TE: a player "played" with any snap in the game.
2. The week's trend, 2026 weeks 1-6 (the club sites' Wednesday-Friday practice log: --sites is a JSON file of
   {"TEAM|week": app.big_picture.rosters.team_report(...)} for every team and week; the sites keep only the current
   season): does the direction of the week (DNP -> LP, LP -> DNP, ...) say more than the last day alone?
3. Scoring, 2023-2026: QB/RB/WR/TE projected 3+ DK points by Sleeper. Of those who played, actual minus projection by
   status and last practice, against everyone else who played (healthy or not listed).
4. The play-chance model app.injury_news uses: a logistic regression on Questionable QB/RB/WR/TE with 2+ games and a
   5+ DK point average before the week -- last practice (DNP / LP / FP), quarterback, and a 10+ point average --
   with and without the practice day (for when the club's report can't be read); checked by holding out each season,
   and how much a Questionable player who plays scores against his projection.
Writes data/injury_trend_tests.json and data/injury_model.json.
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

from app import dk_scoring, injury_news, player_model as pm, projections
from app.matching import normalize_name
from scripts.train_game_model import REL, fetch
from scripts.train_player_model import sleeper_week

OUT = Path(__file__).resolve().parent.parent / "data" / "injury_trend_tests.json"
MODEL = Path(__file__).resolve().parent.parent / "data" / "injury_model.json"
SEASONS = tuple(range(2019, 2027))
PROJ_SEASONS = (2023, 2024, 2025, 2026)
SKILL = ("QB", "RB", "WR", "TE")
PRACTICE = {"Did Not Participate In Practice": "DNP", "Limited Participation in Practice": "LP",
            "Full Participation in Practice": "FP"}
TEAM_FIX = {"LAR": "LA"}


def mean(xs, default=None):
    xs = list(xs)
    return statistics.fmean(xs) if xs else default


def rate(rows) -> dict:
    n = len(rows)
    p = mean((r["played"] for r in rows), 0.0)
    return {"n": n, "played": round(p, 3), "se": round((p * (1 - p) / n) ** 0.5, 3) if n else None}


def snaps_played(d: Path, season: int) -> dict[tuple[int, str, str], bool]:
    out = {}
    with open(fetch(f"{REL}/snap_counts/snap_counts_{season}.csv", d / f"snap_counts_{season}.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("game_type", "REG") != "REG" or not r.get("week"):
                continue
            n = sum(float(r.get(k) or 0) for k in ("offense_snaps", "defense_snaps", "st_snaps"))
            out[(int(r["week"]), r["team"], normalize_name(r["player"]))] = n > 0
    return out


def report_rows(d: Path, inj_dir: Path) -> list[dict]:
    rows = []
    for s in SEASONS:
        played = snaps_played(d, s)
        weeks_with_snaps = {w for (w, _t, _n) in played}
        teams_weeks = {(w, t) for (w, t, _n) in played}
        path = fetch(f"{REL}/injuries/injuries_{s}.csv", inj_dir / f"injuries_{s}.csv")
        for r in csv.DictReader(open(path, newline="")):
            if r.get("game_type") != "REG" or not r.get("week"):
                continue
            w, team = int(r["week"]), r["team"]
            if w not in weeks_with_snaps or (w, team) not in teams_weeks:
                continue
            status = r.get("report_status") or "None"
            rows.append({"season": s, "week": w, "team": team, "name": r["full_name"], "pos": r.get("position"),
                         "status": status, "practice": PRACTICE.get(r.get("practice_status") or "", "?"),
                         "played": played.get((w, team, normalize_name(r["full_name"])), False)})
    return rows


def trend_rows(sites: dict, played: dict) -> list[dict]:
    rows = []
    for key, rep in sites.items():
        team, w = key.split("|")
        w = int(w)
        if not isinstance(rep, dict):
            continue
        team = TEAM_FIX.get(team, team)
        for p in rep.values():
            t = injury_news.practice_trend(p.get("practice") or {})
            if t is None:
                continue
            rows.append({"week": w, "team": team, "pos": p.get("position"), "status": p.get("game_status") or "None",
                         **t, "played": played.get((w, team, normalize_name(p["name"])), False)})
    return rows


def season_avgs(d: Path, season: int) -> dict[tuple[int, str, str], float]:
    """{(week, team, name): DK points per game over his earlier games this season}, with 2+ earlier games."""
    games = defaultdict(dict)
    for r in csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv",
                                       d / f"stats_player_week_{season}.csv"), newline="")):
        if r.get("season_type", "REG") == "REG" and r.get("week") and r.get("position") in SKILL:
            games[(r["team"], normalize_name(r["player_display_name"]))][int(r["week"])] = dk_scoring.dk_offense_points(r)
    out = {}
    for (team, name), wk in games.items():
        for w in range(1, 19):
            prior = [v for x, v in wk.items() if x < w]
            if len(prior) >= 2:
                out[(w, team, name)] = statistics.fmean(prior)
    return out


def fit_logit(X: np.ndarray, y: np.ndarray, l2: float = 1.0) -> np.ndarray:
    """Ridge-penalized logistic regression by Newton steps; X's first column is the intercept (not penalized)."""
    w = np.zeros(X.shape[1])
    pen = np.full(X.shape[1], l2)
    pen[0] = 0.0
    for _ in range(50):
        p = 1 / (1 + np.exp(-X @ w))
        g = X.T @ (p - y) + pen * w
        h = X.T @ (X * (p * (1 - p))[:, None]) + np.diag(pen)
        step = np.linalg.solve(h, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def design(rows, feats) -> tuple[np.ndarray, np.ndarray]:
    X = np.array([[1.0] + [injury_news.chance_features(r["pos"], r["practice"], r["avg"])[f] for f in feats] for r in rows])
    return X, np.array([float(r["played"]) for r in rows])


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def chance_model(d: Path, report: list[dict]) -> tuple[dict, dict]:
    """(data/injury_model.json's play-chance fits, their held-out-season checks)."""
    avgs = {s: season_avgs(d, s) for s in SEASONS}
    rows = []
    for r in report:
        if r["pos"] in SKILL and r["status"] == "Questionable":
            a = avgs[r["season"]].get((r["week"], r["team"], normalize_name(r["name"])))
            if a is not None and a >= 5:
                rows.append({**r, "avg": a, "practice": r["practice"] if r["practice"] in injury_news.PRACTICE_LEVEL else None})
    model, check = {"n": len(rows), "star_avg": injury_news.STAR_AVG}, {}
    for label, feats in (("with_practice", injury_news.PRACTICE_FEATURES), ("without_practice", injury_news.NO_PRACTICE_FEATURES)):
        use = [r for r in rows if r["practice"]] if label == "with_practice" else rows
        X, y = design(use, feats)
        w = fit_logit(X, y)
        model[label] = {"intercept": round(float(w[0]), 4), "coef": {f: round(float(v), 4) for f, v in zip(feats, w[1:])}}
        held, base, flat = [], [], []
        for s in SEASONS:
            tr = [r for r in use if r["season"] != s]
            te = [r for r in use if r["season"] == s]
            if not te:
                continue
            Xt, yt = design(tr, feats)
            Xe, ye = design(te, feats)
            p = 1 / (1 + np.exp(-Xe @ fit_logit(Xt, yt)))
            held.append((log_loss(p, ye), len(te)))
            base.append((log_loss(np.full(len(te), yt.mean()), ye), len(te)))
            flat.append((log_loss(np.ones(len(te)) * 0.999, ye), len(te)))
        wavg = lambda xs: round(sum(a * n for a, n in xs) / sum(n for _a, n in xs), 4)  # noqa: E731
        check[label] = {"n": len(use), "held_out_log_loss": wavg(held), "one_rate_log_loss": wavg(base),
                        "assume_he_plays_log_loss": wavg(flat)}
        cells = {}
        for pos in ("QB", "RB/WR/TE"):
            for star in (False, True):
                for pr in (("DNP", "LP", "FP") if label == "with_practice" else (None,)):
                    sub = [r for r in use if (r["pos"] == "QB") == (pos == "QB") and (r["avg"] >= injury_news.STAR_AVG) == star
                           and (pr is None or r["practice"] == pr)]
                    if sub:
                        p = injury_news.play_chance(model, "QB" if pos == "QB" else "WR", pr, 20.0 if star else 6.0)
                        cells[f"{pos} {'10+' if star else '5-10'} avg {pr or 'any'}"] = {
                            "n": len(sub), "played": round(mean((r["played"] for r in sub), 0.0), 3), "model": round(p, 3)}
        check[label]["cells"] = cells
    return model, check


def scoring(d: Path, report: list[dict]) -> dict:
    listed = {(r["season"], r["week"], normalize_name(r["name"])): r for r in report if r["pos"] in SKILL}
    groups = defaultdict(list)
    for s in PROJ_SEASONS:
        stats = [r for r in csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{s}.csv",
                                                      d / f"stats_player_week_{s}.csv"), newline=""))
                 if r.get("season_type", "REG") == "REG" and r.get("week")]
        pts = {(int(r["week"]), pm.key(r["player_display_name"], r["position"])): dk_scoring.dk_offense_points(r)
               for r in stats if r.get("position") in SKILL}
        played = snaps_played(d, s)
        weeks = sorted({w for (w, _t, _n) in played})
        for w in weeks:
            for e in sleeper_week(d, s, w):
                pl = e.get("player") or {}
                pos = pl.get("position")
                if pos not in SKILL or not e.get("team"):
                    continue
                name = f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip()
                proj = projections.dk_points_from_line(e.get("stats") or {}, pos)
                team = TEAM_FIX.get(e["team"], e["team"])
                if proj < 3:
                    continue
                rep = listed.get((s, w, normalize_name(name)))
                did = played.get((w, team, normalize_name(name)), (w, pm.key(name, pos)) in pts)
                label = f"{rep['status']} / {rep['practice']}" if rep and rep["status"] in ("Questionable", "Doubtful", "Out") else (
                    "listed, no status" if rep else "not listed")
                actual = pts.get((w, pm.key(name, pos)), 0.0)
                groups[label].append({"season": s, "proj": proj, "actual": actual, "played": did})
    groups["Questionable (all)"] = [r for k, rs in list(groups.items()) if k.startswith("Questionable /") for r in rs]
    base = [r for k in ("not listed", "listed, no status") for r in groups[k] if r["played"]]
    base_miss = mean(r["actual"] - r["proj"] for r in base)
    base_ratio = mean(r["actual"] for r in base) / mean(r["proj"] for r in base)
    out = {}
    for label, rs in sorted(groups.items()):
        pl = [r for r in rs if r["played"]]
        if len(rs) < 15:
            continue
        miss = [r["actual"] - r["proj"] for r in pl]
        out[label] = {"n": len(rs), "played": round(mean((r["played"] for r in rs), 0.0), 3),
                      "avg_proj": round(mean(r["proj"] for r in rs), 2),
                      "avg_proj_if_sat": round(mean((r["proj"] for r in rs if not r["played"]), 0.0), 2),
                      "n_played": len(pl),
                      "miss_if_played": round(mean(miss, 0.0), 2),
                      "miss_vs_baseline": round(mean(miss, 0.0) - base_miss, 2) if pl else None,
                      "se": round(statistics.pstdev(miss) / len(miss) ** 0.5, 2) if len(miss) > 1 else None,
                      "actual_over_proj_if_played": round(mean(r["actual"] for r in pl) / mean(r["proj"] for r in pl) / base_ratio, 3) if pl else None,
                      "by_season_miss_vs_baseline": {s: round(mean(r["actual"] - r["proj"] for r in pl if r["season"] == s) - base_miss, 2)
                                                     for s in PROJ_SEASONS if any(r["season"] == s for r in pl)}}
    return {"baseline_miss_if_played": round(base_miss, 2), "groups": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--sites", default=None, help="saved club-site practice logs, {'TEAM|week': report}")
    args = ap.parse_args()
    d = Path(args.data)
    report = report_rows(d, d)
    res: dict = {"definition": "played = any offensive, defensive or special-teams snap in the game"}
    for label, sel in (("all_positions", lambda r: True), ("qb_rb_wr_te", lambda r: r["pos"] in SKILL)):
        tab = {}
        for st in ("Out", "Doubtful", "Questionable", "None"):
            sub = [r for r in report if r["status"] == st and sel(r)]
            tab[st] = {"all": rate(sub), **{pr: rate([r for r in sub if r["practice"] == pr]) for pr in ("DNP", "LP", "FP")}}
            tab[st]["by_season"] = {s: rate([r for r in sub if r["season"] == s])["played"] for s in SEASONS if any(r["season"] == s for r in sub)}
        res[f"play_rates_2019_2026_{label}"] = tab
    if args.sites:
        sites = json.loads(Path(args.sites).read_text())
        played = snaps_played(d, 2026)
        rows = [r for r in trend_rows(sites, played) if r["week"] <= max(w for (w, _t, _n) in played)]
        tab = {}
        for st in ("Doubtful", "Questionable"):
            sub = [r for r in rows if r["status"] == st]
            tab[st] = {"all": rate(sub),
                       "by_trend": {t: rate([r for r in sub if r["trend"] == t]) for t in ("up", "flat", "down")},
                       "by_last_and_trend": {f"{last} {t}": rate([r for r in sub if r["last"] == last and r["trend"] == t])
                                             for last in ("DNP", "LP", "FP") for t in ("up", "flat", "down")
                                             if any(r["last"] == last and r["trend"] == t for r in sub)},
                       "by_days_practiced": {str(k): rate([r for r in sub if r["days_practiced"] == k]) for k in range(0, 4)
                                             if any(r["days_practiced"] == k for r in sub)}}
        res["trend_2026_weeks_1_6"] = tab
    res["scoring_2023_2026_qb_rb_wr_te"] = sc = scoring(d, report)
    model, res["play_chance_model"] = chance_model(d, report)
    # A Questionable player who plays: his projection moves only when the shortfall holds up (2+ standard errors).
    q = sc["groups"]["Questionable (all)"]
    model["if_played"] = {"factor": q["actual_over_proj_if_played"] if q["se"] and abs(q["miss_vs_baseline"]) >= 2 * q["se"] else 1.0,
                          "n": q["n_played"], "miss_vs_baseline": q["miss_vs_baseline"], "se": q["se"]}
    res["play_chance_model"]["fit"] = model
    MODEL.write_text(json.dumps(model, indent=1))
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
