"""Back-test: early-drive efficiency as an in-season trait. Do teams that have been efficient on their opening drives
THIS season (no carry-over from last season) keep producing a particular game script and player performance in their
next game -- beyond the closing line and beyond Sleeper's projections?

    python -m scripts.test_early_efficiency [--data DIR] [--model]

Built on scripts.test_scoring_timing's team-games (run that first). Ratings for a game in week w use only weeks < w of
the same season, shrunk toward the league-to-date mean (PRIOR_GAMES games of weight), from week 4 on:
  off_early   EPA per play on the team's first three drives          def_early   the same allowed
  off_epa     EPA per play, every snap (the control: is "early" anything more than "good")
  def_epa     the same allowed
Matchups, from the team's side:
  own_early   own off_early + opponent def_early - league       opp_early   opponent off_early + own def_early - league
  own_epa / opp_epa likewise from full-game EPA.

1. Within-season persistence: each rating against the next game's early-drive EPA, early-drive EPA beyond the
   full-game rating, by season and by part of the season.
2. Next-game outcomes, each season fit on its own (is the sign the same year after year?) and each season held out:
   points on the first 3 drives, Q1 margin, trailing 7+ after Q1, points minus the implied team total (beating the
   market), pass and rush attempts, QB/RB/WR/TE DK points -- the line alone vs plus the early ratings vs plus the
   full-game control.
3. --model: own_early / opp_early as player-correction inputs (app.player_model), for passers/receivers and running
   backs separately, 2023-2025 each held out and 2026 weeks 2-9, against the current inputs.
Writes data/early_efficiency_tests.json.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.test_fast_starts import SEASONS, oos, ols

OUT = Path(__file__).resolve().parent.parent / "data" / "early_efficiency_tests.json"
PRIOR_GAMES = 4
MIN_WEEK = 4
RATE = ("off_early", "def_early", "off_epa", "def_epa", "off_first3_pts", "def_first3_pts")
SRC = {"off_early": ("team", "early_epa"), "def_early": ("opp", "early_epa"), "off_epa": ("team", "epa"),
       "def_epa": ("opp", "epa"), "off_first3_pts": ("team", "early_for"), "def_first3_pts": ("opp", "early_for")}


def ratings(tg: pd.DataFrame, k: float = PRIOR_GAMES) -> pd.DataFrame:
    out = []
    for s in SEASONS:
        cur = tg[tg.season == s]
        for w in sorted(cur.week.unique()):
            if w < MIN_WEEK:
                continue
            prior = cur[cur.week < w]
            lg = {r: prior[SRC[r][1]].mean() for r in RATE}
            val = {}
            for r, (key, col) in SRC.items():
                g = prior.groupby(key)[col].agg(["sum", "count"])
                val[r] = ((g["sum"] + k * lg[r]) / (g["count"] + k) - lg[r]).to_dict()
            for x in cur[cur.week == w].itertuples():
                rec = {"game_id": x.game_id, "team": x.team, "week_bin": "4-8" if w <= 8 else "9-13" if w <= 13 else "14+"}
                for r in RATE:
                    rec[r] = val[r].get(x.team, 0.0)
                    rec["opp_" + r] = val[r].get(x.opp, 0.0)
                out.append(rec)
    p = tg.merge(pd.DataFrame(out), on=["game_id", "team"], how="inner")
    p["own_early"] = p.off_early + p.opp_def_early
    p["opp_early"] = p.opp_off_early + p.def_early
    p["own_epa"] = p.off_epa + p.opp_def_epa
    p["opp_epa"] = p.opp_off_epa + p.def_epa
    p["own_first3"] = p.off_first3_pts + p.opp_def_first3_pts
    p["opp_first3"] = p.opp_off_first3_pts + p.def_first3_pts
    p["implied"] = (p.total_line + p.spread) / 2
    p["pts_vs_implied"] = p.pts_for - p.implied
    p["first3_margin"] = p.early_for - p.early_against
    p["trail7_q1"] = (p.margin_q1 <= -7).astype(float)
    return p


def persistence(p: pd.DataFrame) -> dict:
    """Rating going in vs the same thing in the next game (a team-game correlation; within-season only)."""
    p = p.dropna(subset=["early_epa", "epa"])
    out = {}
    for label, sel in [("all", p.index == p.index)] + [(f"weeks {b}", p.week_bin == b) for b in ("4-8", "9-13", "14+")]:
        q = p[sel]
        # early EPA beyond what the full-game rating predicts
        b = np.polyfit(q.off_epa, q.early_epa, 1)
        resid_next = q.early_epa - np.polyval(b, q.off_epa)
        out[label] = {"n": len(q),
                      "off_early_vs_next_early_epa": round(float(q.off_early.corr(q.early_epa)), 3),
                      "off_epa_vs_next_early_epa": round(float(q.off_epa.corr(q.early_epa)), 3),
                      "off_early_vs_next_early_epa_beyond_off_epa": round(float((q.off_early - q.off_epa).corr(resid_next)), 3),
                      "off_epa_vs_next_epa": round(float(q.off_epa.corr(q.epa)), 3),
                      "def_early_vs_next_early_epa_allowed": round(float(q.def_early.corr(q.early_epa_allowed)), 3)}
    out["by_season_off_early_vs_next_early_epa"] = {int(s): round(float(g.off_early.corr(g.early_epa)), 3) for s, g in p.groupby("season")}
    out["by_season_beyond_off_epa"] = {}
    for s, g in p.groupby("season"):
        b = np.polyfit(g.off_epa, g.early_epa, 1)
        out["by_season_beyond_off_epa"][int(s)] = round(float((g.off_early - g.off_epa).corr(g.early_epa - np.polyval(b, g.off_epa))), 3)
    return out


Y = ("first3_margin", "margin_q1", "trail7_q1", "pts_vs_implied", "pass_att", "rush_att", "dk_QB", "dk_RB", "dk_WR", "dk_TE")
BASE = ["spread", "total_line"]
SETS = {"+early": ["own_early", "opp_early"], "+first3_pts": ["own_first3", "opp_first3"], "+full_epa": ["own_epa", "opp_epa"],
        "+early+full_epa": ["own_early", "opp_early", "own_epa", "opp_epa"]}


def outcomes(p: pd.DataFrame) -> dict:
    p = p.dropna(subset=["spread", "total_line", "dk_QB", "pts_vs_implied"])
    out = {"team_games": len(p)}
    for y in Y:
        mse0 = oos(p, y, BASE)
        r = {"loso_mse_line_only": round(mse0, 4)}
        for k, xs in SETS.items():
            r[k] = {"loso_mse_change_pct": round(100 * (oos(p, y, BASE + xs) / mse0 - 1), 3),
                    **{x: ols(p, y, BASE + xs)[x] for x in xs}}
        # each season on its own: own_early and opp_early coefficients beyond the line and full-game EPA
        per = {}
        for s, g in p.groupby("season"):
            f = ols(g, y, BASE + SETS["+early+full_epa"])
            per[int(s)] = {x: f[x]["coef"] for x in ("own_early", "opp_early")} | {"t_own": f["own_early"]["t"], "t_opp": f["opp_early"]["t"]}
        r["by_season (beyond line + full-game EPA)"] = per
        r["seasons_own_early_positive"] = sum(v["own_early"] > 0 for v in per.values())
        r["seasons_opp_early_positive"] = sum(v["opp_early"] > 0 for v in per.values())
        out[y] = r
    # terciles of the early-efficiency matchup edge within spread bins
    p = p.copy()
    p["edge"] = p.own_early - p.opp_early
    p["spread_bin"] = pd.cut(p.spread, [-30, -3.5, 3.5, 30], labels=["dog 4+", "within 3", "fav 4+"])
    p["edge_t"] = p.groupby("spread_bin", observed=True).edge.transform(lambda x: pd.qcut(x, 3, labels=["worse", "even", "better"]))
    tab = p.groupby(["spread_bin", "edge_t"], observed=True).agg(
        n=("edge", "size"), first3_margin=("first3_margin", "mean"), trail7_q1=("trail7_q1", "mean"),
        pts_vs_implied=("pts_vs_implied", "mean"), pass_att=("pass_att", "mean"), rush_att=("rush_att", "mean"),
        dk_QB=("dk_QB", "mean"), dk_RB=("dk_RB", "mean"), dk_WR=("dk_WR", "mean"), dk_TE=("dk_TE", "mean"))
    out["by_spread_and_early_edge"] = [{"spread": str(i[0]), "early_edge": str(i[1]), **{k: round(float(v), 3) for k, v in row.items()}}
                                       for i, row in tab.iterrows()]
    return out


def player_model(d: Path, p: pd.DataFrame, test_weeks: int) -> dict:
    from app import player_model as pm
    from scripts import test_defensive_injuries as tdi
    from scripts import train_player_model as tpm
    from scripts.train_game_model import REL, fetch
    rt = {(int(x.season), int(x.week), x.team): (x.own_early, x.opp_early) for x in p.itertuples()}

    def rows(season, weeks):
        st = csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv", d / f"stats_player_week_{season}.csv"), newline=""))
        team = {(int(s["week"]), pm.key(s["player_display_name"], s["position"])): s["team"].replace("LAR", "LA")
                for s in st if s.get("week") and s.get("season_type", "REG") == "REG"}
        out = []
        for r in tpm.player_weeks(d, season, weeks):
            if r["week"] < 2:
                continue
            own, opp = rt.get((season, r["week"], team.get((r["week"], r["key"]))), (0.0, 0.0))
            pas = r["pos"] in ("QB", "WR", "TE")
            f = {**r["f"], "own_early_x_pass": own if pas else 0.0, "own_early_x_rb": own if r["pos"] == "RB" else 0.0,
                 "opp_early_x_pass": opp if pas else 0.0, "opp_early_x_rb": opp if r["pos"] == "RB" else 0.0}
            out.append({"season": season, "week": r["week"], "key": r["key"], "pos": r["pos"], "f": f, "proj": r["proj"],
                        "actual": r["actual"]})
        return out
    train = [x for s in (2023, 2024, 2025) for x in rows(s, range(1, 19))]
    test = rows(2026, range(1, test_weeks + 1))
    rated = lambda x: x["week"] >= MIN_WEEK  # noqa: E731
    feats = ("own_early_x_pass", "own_early_x_rb", "opp_early_x_pass", "opp_early_x_rb")
    return {"rows": {"train": len(train), "test": len(test)}, "subset": f"weeks {MIN_WEEK}+ (rated)",
            "own+opp": tdi.feature_test(train, test, feats, rated),
            "own only": tdi.feature_test(train, test, feats[:2], rated)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--model", action="store_true")
    ap.add_argument("--test-weeks", type=int, default=9)
    args = ap.parse_args()
    d = Path(args.data)
    tg = pd.read_pickle(d / "scoring_timing_team_games.pkl")
    p = ratings(tg)
    res = {"prior_games": PRIOR_GAMES, "persistence": persistence(p), "outcomes": outcomes(p),
           "shrinkage_sensitivity_first3_margin_loso_mse_change_pct": {
               k: round(100 * (oos(q, "first3_margin", BASE + SETS["+early"]) / oos(q, "first3_margin", BASE) - 1), 3)
               for k in (1, 2, 8) for q in [ratings(tg, k).dropna(subset=["spread", "total_line"])]}}
    if args.model:
        res["player_model"] = player_model(d, p, args.test_weeks)
    OUT.write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: v for k, v in res.items() if k != "outcomes"}, indent=1, default=float)[:5000])


if __name__ == "__main__":
    main()
