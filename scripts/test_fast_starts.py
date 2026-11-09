"""Back-test: when a team falls behind early, how much does it change its passing and its players' DK points -- beyond
what the closing spread already says -- and can the early deficit be seen coming before kickoff?

    python -m scripts.test_fast_starts [--data DIR] [--model]

Regular season 2016-2026 (nflverse play-by-play, closing lines from games.csv, DK points from stats_player_week).
Every rate is from the team's own perspective; "spread" is its expected margin (positive = favored).

1. Script effect (in game, not knowable pre-game): each team-game's score after the first quarter, and whether the
   opponent scored on each of its first three drives (the Bengals-in-Madrid case). Ordinary least squares of the
   team's passing (dropback rate after the first quarter, pass attempts, rush attempts) and its QB / RB / WR / TE DK
   points on the spread, the total and the early score -- the early-score coefficients are what the line does not
   already carry.
2. Predictability: each team's first-quarter points scored and allowed in its earlier games this season (shrunk
   toward the league-to-date mean), combined into an expected first-quarter margin for the matchup. Does it predict
   the actual first-quarter margin, and the team's pass attempts and position DK points, beyond the spread and total?
   Each season tested on a fit to the other seasons; a full-game version of the same rating is the control (if the
   first-quarter rating adds nothing the full-game one does not, "fast starters" are just good teams, already in
   the spread).
3. --model: the expected first-quarter margin as player-correction inputs (app.player_model), passers/receivers and
   running backs separately: each of 2023-2025 held out, and 2026, against the current inputs.
Writes data/fast_start_tests.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from app import dk_scoring

OUT = Path(__file__).resolve().parent.parent / "data" / "fast_start_tests.json"
SEASONS = list(range(2016, 2027))
PRIOR_GAMES = 4            # shrinkage weight (games) toward the league-to-date mean
MIN_WEEK = 4               # predictability rows need three-plus earlier games
SCORE = ("Touchdown", "Field goal")
POS = ("QB", "RB", "WR", "TE")


def team_games(d: Path) -> pd.DataFrame:
    """One row per (game, team): the early score, its passing volume, and its position DK points."""
    rows = []
    for s in SEASONS:
        p = pd.read_csv(d / f"play_by_play_{s}.csv.gz", low_memory=False,
                        usecols=["game_id", "season_type", "week", "posteam", "defteam", "home_team", "away_team", "qtr",
                                 "play_type", "qb_dropback", "pass_attempt", "rush_attempt", "fixed_drive",
                                 "fixed_drive_result", "total_home_score", "total_away_score", "game_seconds_remaining"])
        p = p[p.season_type == "REG"]
        q1 = p[p.qtr == 1].groupby("game_id").agg(h=("total_home_score", "max"), a=("total_away_score", "max"))
        fin = p.groupby("game_id").agg(h=("total_home_score", "max"), a=("total_away_score", "max"))
        # each team's first three offensive drives: how many ended in points
        dr = p[p.posteam.notna() & p.fixed_drive.notna()].groupby(["game_id", "posteam", "fixed_drive"]).fixed_drive_result.first()
        dr = dr.reset_index().sort_values(["game_id", "posteam", "fixed_drive"])
        first3 = dr.groupby(["game_id", "posteam"]).head(3).groupby(["game_id", "posteam"]).fixed_drive_result.apply(
            lambda x: int(x.isin(SCORE).sum()))
        plays = p[p.play_type.isin(["pass", "run"]) & p.posteam.notna()]
        for (gid, team), g in plays.groupby(["game_id", "posteam"]):
            home = g.home_team.iloc[0] == team
            opp = g.defteam.iloc[0]
            q = q1.loc[gid] if gid in q1.index else None
            own_q1 = (q.h if home else q.a) if q is not None else 0
            opp_q1 = (q.a if home else q.h) if q is not None else 0
            f = fin.loc[gid]
            late = g[g.qtr >= 2]
            rows.append(dict(season=s, game_id=gid, week=int(g.week.iloc[0]), team=team, opp=opp,
                             q1_for=float(own_q1), q1_against=float(opp_q1), q1_margin=float(own_q1 - opp_q1),
                             final_for=float(f.h if home else f.a), final_against=float(f.a if home else f.h),
                             opp_first3=int(first3.get((gid, opp), 0)), own_first3=int(first3.get((gid, team), 0)),
                             db_rate_after_q1=float(late.qb_dropback.mean()) if len(late) else np.nan,
                             pass_att=float(g.pass_attempt.sum()), rush_att=float(g.rush_attempt.sum()),
                             plays=float(len(g))))
        print(s, "team-games", sum(1 for r in rows if r["season"] == s), flush=True)
    tg = pd.DataFrame(rows)
    tg["final_margin"] = tg.final_for - tg.final_against
    tg["q1_for"] = tg.q1_for.fillna(0)
    # closing lines
    gm = pd.read_csv(d / "games.csv")
    gm = gm[gm.game_type == "REG"]
    lines = pd.concat([gm.assign(team=gm.home_team, spread=gm.spread_line)[["game_id", "team", "spread", "total_line"]],
                       gm.assign(team=gm.away_team, spread=-gm.spread_line)[["game_id", "team", "spread", "total_line"]]])
    tg = tg.merge(lines, on=["game_id", "team"], how="left")
    # position DK points per team-game
    pts = []
    for s in SEASONS:
        st = pd.read_csv(d / f"stats_player_week_{s}.csv", low_memory=False)
        st = st[(st.season_type == "REG") & st.position.isin(POS)]
        st["dk"] = [dk_scoring.dk_offense_points(r) for r in st.to_dict("records")]
        g = st.groupby(["season", "week", "team", "position"]).dk.sum().unstack("position").fillna(0).reset_index()
        pts.append(g)
    pts = pd.concat(pts).rename(columns={k: f"dk_{k}" for k in POS})
    pts["team"] = pts.team.replace({"LAR": "LA"})
    return tg.merge(pts, on=["season", "week", "team"], how="left")


def ols(df: pd.DataFrame, y: str, xs: list[str]) -> dict:
    d = df[[y, *xs]].dropna()
    X = np.column_stack([np.ones(len(d)), d[xs].to_numpy(float)])
    Y = d[y].to_numpy(float)
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    resid = Y - X @ beta
    sigma2 = resid @ resid / (len(d) - X.shape[1])
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))
    return {"n": len(d), **{x: {"coef": round(float(b), 3), "se": round(float(e), 3), "t": round(float(b / e), 1)}
                            for x, b, e in zip(xs, beta[1:], se[1:])},
            "r2": round(float(1 - resid.var() / Y.var()), 4)}


OUTCOMES = ("db_rate_after_q1", "pass_att", "rush_att", "dk_QB", "dk_RB", "dk_WR", "dk_TE")


def script_effect(tg: pd.DataFrame) -> dict:
    t = tg.dropna(subset=["spread", "total_line"]).copy()
    t["trail7_q1"] = (t.q1_margin <= -7).astype(float)
    t["lead7_q1"] = (t.q1_margin >= 7).astype(float)
    t["opp_scored_first3"] = (t.opp_first3 == 3).astype(float)
    t["own_scored_first3"] = (t.own_first3 == 3).astype(float)
    t["opp_first3_pts_drives"] = t.opp_first3.astype(float)
    out = {"team_games": len(t),
           "how_often": {"trail_7plus_after_q1": round(float(t.trail7_q1.mean()), 3),
                         "opp_scored_on_first_3_drives": round(float(t.opp_scored_first3.mean()), 3)},
           "means": {k: round(float(t[k].mean()), 2) for k in OUTCOMES}}
    for label, xs in (("q1_margin (per point)", ["spread", "total_line", "q1_margin"]),
                      ("trail/lead 7+ after Q1", ["spread", "total_line", "trail7_q1", "lead7_q1"]),
                      ("opponent scored on its first 3 drives", ["spread", "total_line", "opp_scored_first3", "own_scored_first3"]),
                      ("opponent's scoring drives of its first 3 (0-3)", ["spread", "total_line", "opp_first3_pts_drives", "own_first3"])):
        out[label] = {y: ols(t, y, xs) for y in OUTCOMES}
    # the line alone, for reference
    out["line_only"] = {y: ols(t, y, ["spread", "total_line"]) for y in OUTCOMES}
    return out


def ratings(tg: pd.DataFrame) -> pd.DataFrame:
    """Pre-game, per team-game: expected first-quarter margin from Q1 points for/against in earlier games this season,
    and the same built from full-game points (the control), each shrunk toward the league-to-date mean."""
    out = []
    for s in SEASONS:
        t = tg[tg.season == s]
        for w in sorted(t.week.unique()):
            if w < MIN_WEEK:
                continue
            prior, now = t[t.week < w], t[t.week == w]
            lg = {c: prior[c].mean() for c in ("q1_for", "final_for")}
            def sh(team, col, against=False):  # noqa: E306
                v = prior[prior.opp == team][col.replace("against", "for")] if against else prior[prior.team == team][col]
                return (v.sum() + PRIOR_GAMES * lg[col.replace("against", "for")]) / (len(v) + PRIOR_GAMES)
            for r in now.itertuples():
                rec = {"game_id": r.game_id, "team": r.team}
                for kind, col in (("q1", "q1_for"), ("full", "final_for")):
                    own_off, own_def = sh(r.team, col), sh(r.team, col, against=True)
                    opp_off, opp_def = sh(r.opp, col), sh(r.opp, col, against=True)
                    # team's expected points: its offense + the opponent's defense allowed - league; same for the opponent
                    lgv = lg[col]
                    exp_for = own_off + opp_def - lgv
                    exp_against = opp_off + own_def - lgv
                    rec[f"{kind}_exp_margin"] = exp_for - exp_against
                    rec[f"{kind}_exp_against"] = exp_against - lgv
                out.append(rec)
    return tg.merge(pd.DataFrame(out), on=["game_id", "team"], how="inner")


def oos(df: pd.DataFrame, y: str, xs: list[str]) -> float:
    """Leave-one-season-out mean squared error."""
    err = []
    for s in df.season.unique():
        tr, te = df[df.season != s], df[df.season == s]
        X = np.column_stack([np.ones(len(tr)), tr[xs].to_numpy(float)])
        b, *_ = np.linalg.lstsq(X, tr[y].to_numpy(float), rcond=None)
        p = np.column_stack([np.ones(len(te)), te[xs].to_numpy(float)]) @ b
        err.append((te[y].to_numpy(float) - p) ** 2)
    return float(np.concatenate(err).mean())


def predictability(tg: pd.DataFrame) -> dict:
    r = ratings(tg).dropna(subset=["spread", "total_line", "db_rate_after_q1"])
    r["trail7_q1"] = (r.q1_margin <= -7).astype(float)
    # persistence: first-half-season vs second-half-season Q1 margin per team, raw and net of full-game margin
    pers = []
    for (s, t), g in tg.groupby(["season", "team"]):
        a, b = g[g.week <= 9], g[g.week > 9]
        if len(a) >= 4 and len(b) >= 4:
            pers.append(dict(q1_a=a.q1_margin.mean(), q1_b=b.q1_margin.mean(),
                             share_a=a.q1_margin.mean() - a.final_margin.mean() / 4,
                             share_b=b.q1_margin.mean() - b.final_margin.mean() / 4,
                             q1for_a=a.q1_for.mean(), q1for_b=b.q1_for.mean()))
    pers = pd.DataFrame(pers)
    out = {"team_games": len(r),
           "split_half_persistence (team-seasons, weeks 1-9 vs 10+)": {
               "n": len(pers),
               "q1_margin_corr": round(float(pers.q1_a.corr(pers.q1_b)), 3),
               "q1_points_scored_corr": round(float(pers.q1for_a.corr(pers.q1for_b)), 3),
               "q1_margin_beyond_full_game_corr": round(float(pers.share_a.corr(pers.share_b)), 3)}}
    base = ["spread", "total_line"]
    out["fits"] = {}
    for y in ("q1_margin", "trail7_q1", "pass_att", "db_rate_after_q1", "dk_QB", "dk_RB", "dk_WR", "dk_TE"):
        mse0 = oos(r, y, base)
        res = {"n": len(r), "loso_mse_line_only": round(mse0, 4)}
        for label, xs in (("+q1_exp_margin", base + ["q1_exp_margin"]), ("+full_exp_margin", base + ["full_exp_margin"]),
                          ("+both", base + ["q1_exp_margin", "full_exp_margin"])):
            res[label] = {"loso_mse": round(oos(r, y, xs), 4), "mse_change_pct": round(100 * (oos(r, y, xs) / mse0 - 1), 3),
                          "fit": ols(r, y, xs)}
        out["fits"][y] = res
    # buckets of the pre-game rating, among games with a similar spread: how often they trail by 7+ after Q1
    r["spread_bin"] = pd.cut(r.spread, [-30, -6.5, -2.5, 2.5, 6.5, 30])
    r["q1_bin"] = r.groupby("spread_bin", observed=True).q1_exp_margin.transform(lambda x: pd.qcut(x, 3, labels=["slow", "mid", "fast"]))
    tab = r.groupby(["spread_bin", "q1_bin"], observed=True).agg(n=("trail7_q1", "size"), trail7_q1=("trail7_q1", "mean"),
                                                                 q1_margin=("q1_margin", "mean"), pass_att=("pass_att", "mean"))
    out["trail7_by_spread_and_q1_rating"] = [{"spread": str(i[0]), "q1_rating_tercile": str(i[1]),
                                              **{k: round(float(v), 3) for k, v in row.items()}} for i, row in tab.iterrows()]
    return out, r


def case_study(tg: pd.DataFrame, r: pd.DataFrame, game_id: str, fit: dict) -> dict:
    g = tg[tg.game_id == game_id]
    out = {}
    for row in g.itertuples():
        rr = r[(r.game_id == game_id) & (r.team == row.team)]
        out[row.team] = {"spread": row.spread, "total": row.total_line, "q1_score": f"{row.q1_for:.0f}-{row.q1_against:.0f}",
                         "opp_scoring_drives_of_first_3": row.opp_first3, "pass_att": row.pass_att, "rush_att": row.rush_att,
                         "db_rate_after_q1": round(row.db_rate_after_q1, 3),
                         "dk": {p: round(getattr(row, f"dk_{p}"), 1) for p in POS},
                         "pre_game_q1_exp_margin": round(float(rr.q1_exp_margin.iloc[0]), 2) if len(rr) else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--model", action="store_true", help="also test the rating as player-correction inputs")
    ap.add_argument("--test-weeks", type=int, default=9)
    args = ap.parse_args()
    d = Path(args.data)
    cache = d / "fast_start_team_games.pkl"
    tg = pd.read_pickle(cache) if cache.exists() else team_games(d)
    tg.to_pickle(cache)
    res = {"seasons": [SEASONS[0], SEASONS[-1]], "script_effect": script_effect(tg)}
    pred, r = predictability(tg)
    res["predictability"] = pred
    res["case_2026_09_CIN_ATL"] = case_study(tg, r, "2026_09_CIN_ATL", res["script_effect"])
    if args.model:
        from scripts import fast_start_model
        res["player_model"] = fast_start_model.run(d, r, args.test_weeks)
    OUT.write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res, indent=1, default=float)[:20000])


if __name__ == "__main__":
    main()
