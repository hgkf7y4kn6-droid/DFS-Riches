"""Two usage signals Sleeper's projections might leave on the table, back-tested against its final weekly projection.

    python -m scripts.test_usage_signals [--data DIR]

1. Red-zone usage. For each RB/WR/TE game: his share of his team's red-zone opportunities (carries + targets from the
   opponent's 20, and the inside-10 and inside-5 slices) over his team's previous four games, from play-by-play. Does
   actual minus Sleeper's projection grow with it, holding the projection constant?
2. Role breaks. A player's offensive snap share last week against his own two weeks before (a rise or fall of 25+
   points, such as a rookie going from 24% to 71% of the snaps). After a break the projections rest on a blend of the old
   and new role; does actual minus projection follow the direction of the break?

Seasons 2023-2026 (the years with archived Sleeper projections). Slope t-statistics cluster by team-season. The
leave-one-season-out test fits the correction on three seasons and scores the fourth: does Sleeper + correction beat
Sleeper alone? Writes data/usage_signal_tests.json.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from app import dk_scoring
from app.matching import normalize_name
from scripts.test_vacated_recipients import attach_projections
from scripts.train_game_model import REL, fetch

OUT = Path(__file__).resolve().parent.parent / "data" / "usage_signal_tests.json"
SEASONS = (2023, 2024, 2025, 2026)
SKILL = ("RB", "WR", "TE")
MIN_PROJ = 3.0
BREAK = 25.0          # snap-share points


def f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def team_fix(t: str) -> str:
    return {"JAC": "JAX", "WSH": "WAS", "LA": "LAR", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LAR"}.get(t, t)


def redzone(d: Path, s: int) -> dict:
    """(gsis id, week) -> [rz opps, inside-10 opps, inside-5 opps, rz tds]; (team, week) -> the same for the whole team."""
    path = d / f"play_by_play_{s}.csv.gz"
    cols = ["week", "season_type", "posteam", "yardline_100", "play_type", "rusher_player_id", "receiver_player_id",
            "touchdown", "td_player_id", "two_point_attempt"]
    df = pd.read_csv(path, usecols=cols, low_memory=False)
    df = df[(df["season_type"] == "REG") & df["posteam"].notna() & df["yardline_100"].notna()
            & df["play_type"].isin(["run", "pass"]) & (df["two_point_attempt"].fillna(0) == 0)]
    df = df[df["yardline_100"] <= 20]
    out: dict = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for r in df.itertuples(index=False):
        pid = r.rusher_player_id if r.play_type == "run" else r.receiver_player_id
        if not isinstance(pid, str):
            continue
        week, yl = int(r.week), r.yardline_100
        td = r.touchdown == 1 and r.td_player_id == pid
        for key in ((pid, week), (team_fix(r.posteam), week)):
            v = out[key]
            v[0] += 1
            v[1] += yl <= 10
            v[2] += yl <= 5
            v[3] += td
    return out


def season_rows(d: Path, s: int) -> list[dict]:
    stats = [r for r in csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{s}.csv", d / f"stats_player_week_{s}.csv"),
                                            newline="")) if r.get("season_type", "REG") == "REG" and r.get("week")]
    snap_pct = {}
    for r in csv.DictReader(open(fetch(f"{REL}/snap_counts/snap_counts_{s}.csv", d / f"snap_counts_{s}.csv"), newline="")):
        if r.get("game_type", "REG") == "REG" and r.get("week"):
            snap_pct[(int(r["week"]), team_fix(r["team"]), normalize_name(r["player"]))] = 100 * f(r.get("offense_pct"))
    rz = redzone(d, s)
    weeks_by_team = defaultdict(set)
    for (w, t, _n) in snap_pct:
        weeks_by_team[t].add(w)
    by_player = defaultdict(dict)
    for r in stats:
        if r.get("position") in SKILL:
            by_player[(r["player_id"], team_fix(r["team"]), r["player_display_name"], r["position"])][int(r["week"])] = r
    rows = []
    for (pid, team, name, pos), g in by_player.items():
        nn = normalize_name(name)
        weeks = sorted(weeks_by_team[team])
        for w in g:
            prev = [x for x in weeks if x < w]
            if len(prev) < 3:
                continue
            last4 = prev[-4:]
            pl = [rz.get((pid, x), [0, 0, 0, 0]) for x in last4]
            tm = [rz.get((team, x), [0, 0, 0, 0]) for x in last4]
            share = [sum(p[i] for p in pl) / sum(t[i] for t in tm) if sum(t[i] for t in tm) else 0.0 for i in range(3)]
            td_rate = sum(p[3] for p in pl) / len(last4)
            snaps = [snap_pct.get((x, team, nn)) for x in prev[-3:]]
            last, before = snaps[-1], [x for x in snaps[:-1] if x is not None]
            brk = (last - float(np.mean(before))) if last is not None and before else None
            rows.append({"season": s, "week": w, "team": team, "name": name, "pos": pos, "played": True, "pts": dk_scoring.dk_offense_points(g[w]),
                         "rz": share[0], "rz10": share[1], "rz5": share[2], "rz_tds": td_rate, "rz_games": len(last4),
                         "brk": brk, "last_snap": last})
    return rows


def cluster_slope(X: np.ndarray, y: np.ndarray, groups: np.ndarray, j: int):
    X1 = np.column_stack([np.ones(len(y)), X])
    A = np.linalg.inv(X1.T @ X1)
    beta = A @ X1.T @ y
    e = y - X1 @ beta
    meat = np.zeros((X1.shape[1], X1.shape[1]))
    for g in np.unique(groups):
        m = groups == g
        sg = X1[m].T @ e[m]
        meat += np.outer(sg, sg)
    se = np.sqrt(np.diag(A @ meat @ A))
    return float(beta[j + 1]), float(beta[j + 1] / se[j + 1]), beta


def fit_test(rows: list[dict], cols: list[str], label: str) -> dict:
    X = np.array([[r[c] for c in cols] for r in rows], dtype=float)
    y = np.array([r["pts"] - r["proj"] for r in rows])
    g = np.array([f"{r['team']}{r['season']}" for r in rows])
    seasons = np.array([r["season"] for r in rows])
    out = {"n": len(rows), "terms": {}}
    for j, c in enumerate(cols):
        slope, t, _ = cluster_slope(X, y, g, j)
        by = {}
        for s in SEASONS:
            m = seasons == s
            if m.sum() > 100:
                by[int(s)] = round(float(cluster_slope(X[m], y[m], g[m], j)[0]), 3)
        out["terms"][c] = {"slope": round(slope, 3), "t": round(t, 1), "slope_by_season": by}
    base = corr = 0.0
    for s in SEASONS:
        tr, te = seasons != s, seasons == s
        if te.sum() == 0:
            continue
        X1 = np.column_stack([np.ones(tr.sum()), X[tr]])
        beta = np.linalg.lstsq(X1, y[tr], rcond=None)[0]
        pred = np.column_stack([np.ones(te.sum()), X[te]]) @ beta
        base += float((y[te] ** 2).sum())
        corr += float(((y[te] - pred) ** 2).sum())
    n = len(y)
    out["loso_rmse_sleeper"] = round(float(np.sqrt(base / n)), 3)
    out["loso_rmse_corrected"] = round(float(np.sqrt(corr / n)), 3)
    out["loso_change_pct"] = round(100 * (np.sqrt(corr / base) - 1), 2)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    d = Path(ap.parse_args().data)
    rows = [r for s in SEASONS for r in season_rows(d, s)]
    attach_projections(d, rows)
    rows = [r for r in rows if (r.get("proj") or 0) >= MIN_PROJ]
    res = {"seasons": list(SEASONS), "rows": len(rows), "min_projection": MIN_PROJ, "tests": {}}
    for pos_label, sel in (("RB/WR/TE", SKILL), ("RB", ("RB",)), ("WR", ("WR",)), ("TE", ("TE",))):
        sub = [r for r in rows if r["pos"] in sel]
        res["tests"][f"red zone | {pos_label}"] = fit_test(sub, ["proj", "rz", "rz5"], "rz")
        res["tests"][f"red zone TD rate | {pos_label}"] = fit_test(sub, ["proj", "rz_tds"], "rz_tds")
        brk = [r for r in sub if r["brk"] is not None]
        res["tests"][f"role break (snap change) | {pos_label}"] = fit_test(brk, ["proj", "brk"], "brk")
        for name, cut, grp in (("riser", BREAK, [r for r in brk if r["brk"] >= BREAK]), ("faller", BREAK, [r for r in brk if r["brk"] <= -BREAK]),
                               ("mild riser", 15.0, [r for r in brk if 15 <= r["brk"] < BREAK]),
                               ("mild faller", 15.0, [r for r in brk if -BREAK < r["brk"] <= -15])):
            if len(grp) >= 8:
                resid = np.array([r["pts"] - r["proj"] for r in grp])
                res["tests"][f"{name} (snap change {cut:.0f}+ pts) | {pos_label}"] = {
                    "n": len(grp), "mean_actual_minus_proj": round(float(resid.mean()), 2),
                    "share_beating_projection": round(float((resid > 0).mean()), 3),
                    "se": round(float(resid.std(ddof=1) / len(resid) ** 0.5), 2),
                    "mean_projection": round(float(np.mean([r["proj"] for r in grp])), 2)}
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
