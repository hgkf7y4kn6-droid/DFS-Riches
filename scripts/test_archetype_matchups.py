"""Back-test: offense, defense and team archetypes, assigned fresh each season from that season's earlier games -- do
archetype-vs-archetype matchups play out the same way from one season to the next, whatever teams fill them?

    python -m scripts.test_archetype_matchups [--data DIR]

Profiles from scripts.test_season_indicators (same-season earlier weeks only, shrunk, from week 4). Each week every
team is placed against the other teams that week (z-scores, so a high- or low-scoring season is its own scale):
  offense style     pass-first / run-first (neutral-situation dropback rate) x efficient / inefficient (EPA per play)
  offense timing    fast-start / even / second-half (2H minus 1H points, terciles)
  defense style     stout / porous (EPA allowed) x pass-funnel / run-funnel (pass minus rush EPA allowed)
  defense timing    strong-late / even / fades-late (2H minus 1H points allowed)
  team              complete / offense-led / defense-led / weak (offense and defense EPA)
  team timing       front-runner / even / closer (own 2H-1H tilt minus its defense's)
Matchup families (own archetype x the opponent's): offense style x defense style, offense timing x defense timing,
offense timing x the opponent's offense timing, team x team, team timing x team timing.

For each family and outcome (margin vs the spread, points vs the implied total, 1H and 2H margin, pass and rush
attempts, QB/RB/WR/TE DK points; and the current player model's misses by position, 2023-2026): each cell's effect
beyond the spread and total, shrunk (LAMBDA games of zero), fit on
  - last season, applied to this season
  - every earlier season, applied to this season
  - this season's earlier weeks (from week 8), applied to week w
against the line alone fit the same way; and how well cell effects correlate from one season to the next.
Writes data/archetype_matchup_tests.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts import test_season_indicators as tsi

OUT = Path(__file__).resolve().parent.parent / "data" / "archetype_matchup_tests.json"
LAMBDA = 30.0
OUTCOMES = tsi.OUTCOMES
BASE = tsi.BASE


def z(s: pd.Series, by) -> pd.Series:
    return s.groupby(by).transform(lambda x: (x - x.mean()) / (x.std() or 1.0))


def tercile(s: pd.Series, by, labels) -> pd.Series:
    return s.groupby(by).transform(lambda x: pd.qcut(x.rank(method="first"), 3, labels=labels).astype(str))


def archetypes(p: pd.DataFrame) -> pd.DataFrame:
    by = [p.season, p.week]
    a = pd.DataFrame({"game_id": p.game_id, "team": p.team})
    eff = z(p.o_epa_1h + p.o_epa_2h, by)
    lean = z(p.o_npass, by)
    a["off_style"] = np.where(lean >= 0, "pass-first", "run-first") + np.where(eff >= 0, " efficient", " inefficient")
    a["off_timing"] = tercile(p.o_pts_2h - p.o_pts_1h, by, ["fast-start", "even", "second-half"])
    dq = -(z(p.d_epa_db, by) + z(p.d_epa_rush, by))
    funnel = z(p.d_epa_db, by) - z(p.d_epa_rush, by)
    a["def_style"] = np.where(dq >= 0, "stout", "porous") + np.where(funnel >= 0, " pass-funnel", " run-funnel")
    a["def_timing"] = tercile(p.d_pts_2h - p.d_pts_1h, by, ["strong-late", "even", "fades-late"])
    deff = -z(p.d_epa_1h + p.d_epa_2h, by)
    a["team_timing"] = tercile((p.o_pts_2h - p.o_pts_1h) - (p.d_pts_2h - p.d_pts_1h), by, ["front-runner", "even", "closer"])
    a["team_arch"] = np.select([(eff >= 0) & (deff >= 0), eff >= 0, deff >= 0], ["complete", "offense-led", "defense-led"], "weak")
    a = a.drop(columns=["team"]).assign(team=p.team.to_numpy())
    cols = [c for c in a.columns if c not in ("game_id", "team")]
    # the opponent's archetypes: its own row in the same game
    o = a.rename(columns={"team": "opp", **{c: "opp_" + c for c in cols}})
    return p.merge(a, on=["game_id", "team"]).merge(o, on=["game_id", "opp"], how="left")


FAMILIES = {"offense style x defense style": ("off_style", "opp_def_style"),
            "offense timing x defense timing": ("off_timing", "opp_def_timing"),
            "offense timing x opp offense timing": ("off_timing", "opp_off_timing"),
            "team x team": ("team_arch", "opp_team_arch"),
            "team timing x team timing": ("team_timing", "opp_team_timing")}


def line_fit(tr: pd.DataFrame, y: str):
    X = np.column_stack([np.ones(len(tr)), tr[BASE].to_numpy(float)])
    b, *_ = np.linalg.lstsq(X, tr[y].to_numpy(float), rcond=None)
    return lambda d: np.column_stack([np.ones(len(d)), d[BASE].to_numpy(float)]) @ b


def cell_effects(tr: pd.DataFrame, y: str, cell: str, base=None) -> tuple:
    f = base or line_fit(tr, y)
    r = tr[y] - f(tr)
    g = r.groupby(tr[cell]).agg(["sum", "count"])
    return f, (g["sum"] / (g["count"] + LAMBDA)).to_dict()


def evaluate(p: pd.DataFrame, y: str, cell: str, base_cols=None) -> dict:
    p = p.dropna(subset=[y, cell])
    seasons = sorted(p.season.unique())
    acc = {"last_season": [0.0, 0.0], "all_prior": [0.0, 0.0], "in_season": [0.0, 0.0]}
    eff_by_season = {}
    for s in seasons:
        _, eff_by_season[s] = cell_effects(p[p.season == s], y, cell)
    for s in seasons[1:]:
        te = p[p.season == s]
        for key, tr in (("last_season", p[p.season == s - 1]), ("all_prior", p[p.season < s])):
            if len(tr) == 0:
                continue
            f, eff = cell_effects(tr, y, cell)
            pred = f(te)
            acc[key][0] += ((te[y] - pred) ** 2).sum()
            acc[key][1] += ((te[y] - pred - te[cell].map(eff).fillna(0)) ** 2).sum()
    for s in seasons:
        g = p[p.season == s]
        for w in sorted(g.week.unique()):
            if w < 8:
                continue
            tr, te = g[g.week < w], g[g.week == w]
            f, eff = cell_effects(tr, y, cell)
            pred = f(te)
            acc["in_season"][0] += ((te[y] - pred) ** 2).sum()
            acc["in_season"][1] += ((te[y] - pred - te[cell].map(eff).fillna(0)) ** 2).sum()
    # year-to-year correlation of cell effects
    cors = []
    for s in seasons[1:]:
        a, b = pd.Series(eff_by_season[s - 1]), pd.Series(eff_by_season[s])
        j = pd.concat([a, b], axis=1).dropna()
        if len(j) >= 4:
            cors.append(j.iloc[:, 0].corr(j.iloc[:, 1]))
    return {k: round(100 * (v[1] / v[0] - 1), 3) if v[0] else None for k, v in acc.items()} | {
        "cell_effect_corr_next_season": round(float(np.nanmean(cors)), 3) if cors else None,
        "seasons_positive_corr": f"{sum(c > 0 for c in cors)}/{len(cors)}"}


def cell_table(p: pd.DataFrame, y: str, cell: str) -> list[dict]:
    p = p.dropna(subset=[y, cell]).copy()
    out = []
    for s, g in p.groupby("season"):
        f = line_fit(g, y)
        p.loc[g.index, "_r"] = g[y] - f(g)
    for c, g in p.groupby(cell):
        per = g.groupby("season")._r.mean()
        n = len(g)
        out.append({"cell": c, "n": n, "avg_vs_line": round(float(g._r.mean()), 2),
                    "z": round(float(g._r.mean() / (p._r.std() / np.sqrt(n))), 2),
                    "seasons_same_sign": f"{int((np.sign(per) == np.sign(g._r.mean())).sum())}/{len(per)}"})
    return sorted(out, key=lambda r: -abs(r["z"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    args = ap.parse_args()
    d = Path(args.data)
    tsi.METRICS = tsi.METRICS + ("npass",)
    p = tsi.ratings(tsi.team_games(d))
    p = archetypes(p)
    for fam, (a, b) in FAMILIES.items():
        p[fam] = p[a] + " vs " + p[b]
    res = {"team_games": len(p), "lambda": LAMBDA,
           "archetype_counts": {c: p[c].value_counts().to_dict() for c in ("off_style", "off_timing", "def_style", "def_timing", "team_arch", "team_timing")},
           "team_level": {}, "cells": {}}
    for fam in FAMILIES:
        res["team_level"][fam] = {y: evaluate(p, y, fam) for y in OUTCOMES}
        res["cells"][fam] = {y: cell_table(p, y, fam)[:6] for y in OUTCOMES}
        print(fam, {y: (v["last_season"], v["all_prior"], v["in_season"], v["cell_effect_corr_next_season"])
                    for y, v in res["team_level"][fam].items()}, flush=True)
    # current player model's misses
    pl = pd.read_pickle(d / "season_indicator_players.pkl")
    pl["miss"] = pl.actual - pl.corrected
    pl = pl.merge(p[["season", "week", "team", *FAMILIES]], on=["season", "week", "team"], how="inner")
    res["player_misses"] = {}
    for fam in FAMILIES:
        res["player_misses"][fam] = {}
        for pos in ("QB", "RB", "WR", "TE"):
            g = pl[pl.pos == pos].copy()
            g["spread"], g["total_line"] = 0.0, 0.0          # misses are already net of the projection
            res["player_misses"][fam][pos] = {**evaluate(g, "miss", fam), "top_cells": cell_table(g, "miss", fam)[:4]}
        print("players", fam, {pos: (v["last_season"], v["all_prior"], v["in_season"]) for pos, v in res["player_misses"][fam].items()}, flush=True)
    OUT.write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
