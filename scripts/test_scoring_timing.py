"""Back-test: can WHEN an offense scores (opening drives vs fourth quarter), against WHEN its opponent's defense gives up
points -- and how offenses like it have fared against that defense -- forecast early leads, close games and the
pass/run script before kickoff, beyond the closing spread and total?

    python -m scripts.test_scoring_timing [--data DIR]

Regular season 2016-2026. Per team-game, from play-by-play: points by quarter (overtime counts as the fourth),
points and EPA per play on its first three offensive drives, margin after Q1 / at the half / entering Q4.

Pre-game profiles (every input from earlier games: this season's, plus last season's at half weight, shrunk toward
the league-to-date mean), offense and defense:
  early_tilt  points on the first three drives minus what the team's overall scoring implies (league share), i.e.
              starting faster or slower than its strength says; also by quarter (q1..q4 tilts)
  late_tilt   fourth-quarter points minus the same expectation (the "Denver" profile)
  script_epa  EPA per play on the first three drives minus its EPA per play overall
  style_match how offenses most like this one (neutral pass rate, EPA per dropback, EPA per rush) did on their first
              three drives against this defense, against their own norm -- similarity-weighted
Matchup = own offense + opponent defense (allowed) - opponent offense - own defense (allowed), per profile.

1. Persistence: weeks 1-9 vs 10+ of the same season and season to next season, per profile, raw and net of strength.
2. The teams named (DEN, CIN, CHI): their profiles in 2025 and 2026 to date, rank among 32.
3. Prediction, each season held out: Q1 margin, first-three-drives margin, trailing by 7+ after Q1, a one-score game
   entering Q4, pass attempts, rush attempts and QB/RB/WR/TE DK points -- the line alone vs the line plus each profile.
Writes data/scoring_timing_tests.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.test_fast_starts import POS, SEASONS, oos, ols

OUT = Path(__file__).resolve().parent.parent / "data" / "scoring_timing_tests.json"
PRIOR_GAMES = 4
PREV_WEIGHT = 0.5
MIN_WEEK = 4
DRIVE_PTS = {"Touchdown": 7.0, "Field goal": 3.0}
STYLE = ("npass", "epa_db", "epa_rush")
NAMED = ("DEN", "CIN", "CHI")


def team_games(d: Path) -> pd.DataFrame:
    rows = []
    for s in SEASONS:
        p = pd.read_csv(d / f"play_by_play_{s}.csv.gz", low_memory=False,
                        usecols=["game_id", "season_type", "week", "posteam", "defteam", "home_team", "qtr", "play_type",
                                 "qb_dropback", "pass_attempt", "rush_attempt", "fixed_drive", "fixed_drive_result", "epa",
                                 "score_differential", "total_home_score", "total_away_score", "half_seconds_remaining"])
        p = p[p.season_type == "REG"]
        p["q"] = p.qtr.clip(upper=4)
        sc = {k: p[p.q <= k].groupby("game_id")[["total_home_score", "total_away_score"]].max() for k in (1, 2, 3, 4)}
        plays = p[p.play_type.isin(["pass", "run"]) & p.posteam.notna() & p.epa.notna()]
        dr = plays.groupby(["game_id", "posteam"]).fixed_drive.unique()
        res = p[p.posteam.notna()].groupby(["game_id", "posteam", "fixed_drive"]).fixed_drive_result.first()
        for (gid, team), g in plays.groupby(["game_id", "posteam"]):
            home = g.home_team.iloc[0] == team
            opp = g.defteam.iloc[0]
            cum = []
            for k in (1, 2, 3, 4):
                v = sc[k].loc[gid] if gid in sc[k].index else None
                cum.append((0.0, 0.0) if v is None else ((v.total_home_score, v.total_away_score) if home else
                                                         (v.total_away_score, v.total_home_score)))
            cum = [(np.nan_to_num(a), np.nan_to_num(b)) for a, b in cum]
            q_for = [cum[0][0]] + [cum[i][0] - cum[i - 1][0] for i in (1, 2, 3)]
            q_ag = [cum[0][1]] + [cum[i][1] - cum[i - 1][1] for i in (1, 2, 3)]
            first3 = sorted(dr.get((gid, team), []))[:3]
            early = g[g.fixed_drive.isin(first3)]
            ofirst3 = sorted(dr.get((gid, opp), []))[:3]
            neutral = g[(g.qtr <= 3) & (g.score_differential.abs() <= 7)]
            db, ru = g[g.qb_dropback == 1], g[(g.qb_dropback != 1) & (g.play_type == "run")]
            rows.append(dict(
                season=s, game_id=gid, week=int(g.week.iloc[0]), team=team, opp=opp,
                **{f"q{i + 1}_for": float(q_for[i]) for i in range(4)}, **{f"q{i + 1}_against": float(q_ag[i]) for i in range(4)},
                pts_for=float(cum[3][0]), pts_against=float(cum[3][1]),
                early_for=sum(DRIVE_PTS.get(res.get((gid, team, x)), 0.0) for x in first3),
                early_against=sum(DRIVE_PTS.get(res.get((gid, opp, x)), 0.0) for x in ofirst3),
                early_epa=float(early.epa.mean()) if len(early) else np.nan, epa=float(g.epa.mean()),
                npass=float(neutral.qb_dropback.mean()) if len(neutral) >= 10 else np.nan,
                epa_db=float(db.epa.mean()) if len(db) else np.nan, epa_rush=float(ru.epa.mean()) if len(ru) else np.nan,
                margin_q1=float(cum[0][0] - cum[0][1]), margin_q3=float(cum[2][0] - cum[2][1]),
                pass_att=float(g.pass_attempt.sum()), rush_att=float(g.rush_attempt.sum())))
        print(s, flush=True)
    tg = pd.DataFrame(rows)
    # the same game from the defense's side: what this team's offense did is what the opponent's defense allowed
    own = tg[["game_id", "team", "early_epa", "epa"]].rename(columns={"team": "opp", "early_epa": "early_epa_allowed",
                                                                      "epa": "epa_allowed"})
    tg = tg.merge(own, on=["game_id", "opp"], how="left")
    gm = pd.read_csv(d / "games.csv")
    gm = gm[gm.game_type == "REG"]
    lines = pd.concat([gm.assign(team=gm.home_team, spread=gm.spread_line)[["game_id", "team", "spread", "total_line"]],
                       gm.assign(team=gm.away_team, spread=-gm.spread_line)[["game_id", "team", "spread", "total_line"]]])
    tg = tg.merge(lines, on=["game_id", "team"], how="left")
    fs = pd.read_pickle(d / "fast_start_team_games.pkl")[["game_id", "team", *[f"dk_{p}" for p in POS]]]
    return tg.merge(fs, on=["game_id", "team"], how="left")


def add_tilts(t: pd.DataFrame, lg: dict) -> pd.DataFrame:
    """Per game: timing points minus what the game's total points imply at league shares."""
    t = t.copy()
    for side, tot in (("for", "pts_for"), ("against", "pts_against")):
        t[f"early_tilt_{side}"] = t[f"early_{side}"] - t[tot] * lg["early_share"]
        for i in range(1, 5):
            t[f"q{i}_tilt_{side}"] = t[f"q{i}_{side}"] - t[tot] * lg[f"q{i}_share"]
    t["script_epa"] = t.early_epa - t.epa
    t["script_epa_allowed"] = t.early_epa_allowed - t.epa_allowed
    return t


OFF = ("early_tilt_for", "q1_tilt_for", "q2_tilt_for", "q3_tilt_for", "q4_tilt_for", "script_epa", "pts_for",
       "early_for", "q4_for")
DEF = ("early_tilt_against", "q1_tilt_against", "q2_tilt_against", "q3_tilt_against", "q4_tilt_against",
       "script_epa_allowed", "pts_against", "early_against", "q4_against")


def league(t: pd.DataFrame) -> dict:
    tot = t.pts_for.sum()
    return {"early_share": t.early_for.sum() / tot, **{f"q{i}_share": t[f"q{i}_for"].sum() / tot for i in range(1, 5)}}


def profiles(tg: pd.DataFrame) -> pd.DataFrame:
    lg = league(tg)
    tg = add_tilts(tg, lg)
    out = []
    for s in SEASONS:
        cur, prev = tg[tg.season == s], tg[tg.season == s - 1]
        for w in sorted(cur.week.unique()):
            if w < MIN_WEEK:
                continue
            prior = cur[cur.week < w]
            pool = pd.concat([prior.assign(wt=1.0), prev.assign(wt=PREV_WEIGHT)])
            lgm = {c: np.average(pool[c].dropna(), weights=pool.loc[pool[c].notna(), "wt"]) for c in OFF + DEF + STYLE}

            def prof(team: str, cols, key="team") -> dict:
                g = pool[pool[key] == team]
                r = {}
                for c in cols:
                    v = g[[c, "wt"]].dropna()
                    r[c] = ((v[c] * v.wt).sum() + PRIOR_GAMES * lgm[c]) / (v.wt.sum() + PRIOR_GAMES) - lgm[c]
                return r
            teams = set(cur[cur.week == w].team)
            o = {t: prof(t, OFF + STYLE) for t in teams}
            df = {t: prof(t, DEF) for t in teams}
            # style match: offenses like this one, first three drives against this defense, vs their own norm
            sty = pd.DataFrame({t: {k: o[t][k] for k in STYLE} for t in o}).T
            sd = sty.std().replace(0, 1)
            for r in cur[cur.week == w].itertuples():
                rec = {"game_id": r.game_id, "team": r.team}
                for k in OFF:
                    rec[f"o_{k}"] = o[r.team][k]
                    rec[f"oo_{k}"] = o[r.opp][k]
                for k in DEF:
                    rec[f"d_{k}"] = df[r.team][k]
                    rec[f"od_{k}"] = df[r.opp][k]
                for side, off, de in (("own", r.team, r.opp), ("opp", r.opp, r.team)):
                    games = prior[prior.opp == de]          # this defense's earlier games this season
                    if len(games) == 0:
                        rec[f"style_{side}"] = 0.0
                        continue
                    me = np.array([o[off][k] for k in STYLE]) / sd.to_numpy()
                    wts, vals = [], []
                    for gg in games.itertuples():
                        if gg.team not in o:
                            # an offense not on this week's slate: use its season-to-date profile
                            o[gg.team] = prof(gg.team, OFF + STYLE)
                        them = np.array([o[gg.team][k] for k in STYLE]) / sd.to_numpy()
                        wts.append(np.exp(-0.5 * np.sum((me - them) ** 2)))
                        vals.append(gg.early_for - (o[gg.team]["early_for"] + lgm["early_for"]))
                    wts = np.array(wts)
                    rec[f"style_{side}"] = float((wts * vals).sum() / (wts.sum() + 1.0))   # shrunk: +1 game of zero
                out.append(rec)
        print("profiles", s, flush=True)
    p = tg.merge(pd.DataFrame(out), on=["game_id", "team"], how="inner")
    m = lambda k_off, k_def: p[f"o_{k_off}"] + p[f"od_{k_def}"] - p[f"oo_{k_off}"] - p[f"d_{k_def}"]  # noqa: E731
    p["m_early_tilt"] = m("early_tilt_for", "early_tilt_against")
    p["m_q1_tilt"] = m("q1_tilt_for", "q1_tilt_against")
    p["m_q4_tilt"] = m("q4_tilt_for", "q4_tilt_against")
    p["m_script_epa"] = m("script_epa", "script_epa_allowed")
    p["m_style"] = p.style_own - p.style_opp
    # late-scoring for both sides (a "stays close" game): both offenses' and both defenses' Q4 tilts
    p["both_q4_tilt"] = p.o_q4_tilt_for + p.oo_q4_tilt_for + p.d_q4_tilt_against + p.od_q4_tilt_against
    p["both_early_tilt"] = p.o_early_tilt_for + p.oo_early_tilt_for + p.d_early_tilt_against + p.od_early_tilt_against
    return p, tg


def persistence(tg: pd.DataFrame) -> dict:
    cols = {"early_tilt_for (offense, first 3 drives vs its strength)": "early_tilt_for",
            "q4_tilt_for (offense, 4th quarter vs its strength)": "q4_tilt_for",
            "q1_tilt_for": "q1_tilt_for", "script_epa (offense)": "script_epa",
            "early_tilt_against (defense)": "early_tilt_against", "q4_tilt_against (defense)": "q4_tilt_against",
            "script_epa_allowed (defense)": "script_epa_allowed",
            "control: pts_for": "pts_for", "control: epa": "epa"}
    g = tg.groupby(["season", "team"])
    half = {}
    for label, c in cols.items():
        a = tg[tg.week <= 9].groupby(["season", "team"])[c].mean()
        b = tg[tg.week > 9].groupby(["season", "team"])[c].mean()
        j = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
        yr = g[c].mean().unstack("season")
        yoy = [yr[s].corr(yr[s + 1]) for s in SEASONS[:-1] if s + 1 in yr]
        half[label] = {"weeks_1_9_vs_10_plus": round(float(j.a.corr(j.b)), 3), "n_team_seasons": len(j),
                       "season_to_next": round(float(np.nanmean(yoy)), 3)}
    return half


def named(p: pd.DataFrame, tg: pd.DataFrame) -> dict:
    out = {}
    for s in (2025, 2026):
        t = tg[tg.season == s]
        agg = t.groupby("team").agg(games=("week", "size"), pts=("pts_for", "mean"),
                                    **{f"q{i}_pts": (f"q{i}_for", "mean") for i in range(1, 5)},
                                    first3_pts=("early_for", "mean"), early_tilt=("early_tilt_for", "mean"),
                                    q4_tilt=("q4_tilt_for", "mean"), script_epa=("script_epa", "mean"),
                                    first3_allowed=("early_against", "mean"), q4_allowed=("q4_against", "mean"),
                                    margin_q1=("margin_q1", "mean"), close_into_q4=("margin_q3", lambda x: (x.abs() <= 8).mean()))
        agg["second_half_share"] = (agg.q3_pts + agg.q4_pts) / agg.pts
        rank = agg.rank(ascending=False, method="min")
        out[s] = {tm: {k: f"{agg.loc[tm, k]:.2f} (#{int(rank.loc[tm, k])})" for k in agg.columns if k != "games"} | {"games": int(agg.loc[tm, "games"])}
                  for tm in NAMED if tm in agg.index}
        out[s]["league_avg"] = {k: round(float(agg[k].mean()), 2) for k in agg.columns if k != "games"}
    return out


def prediction(p: pd.DataFrame) -> dict:
    p = p.dropna(subset=["spread", "total_line", "dk_QB"]).copy()
    p["first3_margin"] = p.early_for - p.early_against
    p["trail7_q1"] = (p.margin_q1 <= -7).astype(float)
    p["close_into_q4"] = (p.margin_q3.abs() <= 8).astype(float)
    base = ["spread", "total_line"]
    sets = {"+early_tilt": ["m_early_tilt"], "+q1_tilt": ["m_q1_tilt"], "+q4_tilt": ["m_q4_tilt"],
            "+script_epa": ["m_script_epa"], "+style_match": ["m_style"],
            "+all_matchup": ["m_early_tilt", "m_q1_tilt", "m_q4_tilt", "m_script_epa", "m_style"],
            "+both_q4_tilt/both_early_tilt": ["both_q4_tilt", "both_early_tilt"]}
    out = {"team_games": len(p)}
    for y in ("margin_q1", "first3_margin", "trail7_q1", "close_into_q4", "pass_att", "rush_att", "dk_QB", "dk_RB", "dk_WR", "dk_TE"):
        mse0 = oos(p, y, base)
        r = {"loso_mse_line_only": round(mse0, 4)}
        for k, xs in sets.items():
            mse = oos(p, y, base + xs)
            f = ols(p, y, base + xs)
            r[k] = {"mse_change_pct": round(100 * (mse / mse0 - 1), 3), **{x: f[x] for x in xs}}
        out[y] = r
    # the named cases: one-score games entering Q4, by both teams' Q4 tilt tercile within the spread
    p["abs_spread_bin"] = pd.cut(p.spread.abs(), [-0.1, 3, 6.5, 30])
    p["q4_tercile"] = p.groupby("abs_spread_bin", observed=True).both_q4_tilt.transform(lambda x: pd.qcut(x, 3, labels=["low", "mid", "high"]))
    p["early_tercile"] = p.groupby("abs_spread_bin", observed=True).m_early_tilt.transform(lambda x: pd.qcut(x, 3, labels=["slow", "mid", "fast"]))
    out["close_into_q4_by_spread_and_both_q4_tilt"] = [
        {"abs_spread": str(i[0]), "q4_tilt": str(i[1]), "n": int(v.n), "close_into_q4": round(float(v.c), 3)}
        for i, v in p.groupby(["abs_spread_bin", "q4_tercile"], observed=True).agg(n=("close_into_q4", "size"), c=("close_into_q4", "mean")).iterrows()]
    out["trail7_and_pass_att_by_spread_and_early_matchup"] = [
        {"abs_spread": str(i[0]), "early_matchup": str(i[1]), "n": int(v.n), "trail7_q1": round(float(v.t), 3),
         "lead7_q1": round(float(v.l), 3), "pass_att": round(float(v.pa), 1)}
        for i, v in p.assign(lead7=(p.margin_q1 >= 7).astype(float)).groupby(["abs_spread_bin", "early_tercile"], observed=True).agg(
            n=("trail7_q1", "size"), t=("trail7_q1", "mean"), l=("lead7", "mean"), pa=("pass_att", "mean")).iterrows()]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    args = ap.parse_args()
    d = Path(args.data)
    cache = d / "scoring_timing_team_games.pkl"
    tg = pd.read_pickle(cache) if cache.exists() else team_games(d)
    tg.to_pickle(cache)
    p, tgt = profiles(tg)
    p.to_pickle(d / "scoring_timing_profiles.pkl")
    res = {"persistence": persistence(tgt), "named_teams": named(p, tgt), "prediction": prediction(p),
           "league_shares": {k: round(float(v), 3) for k, v in league(tg).items()}}
    OUT.write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps(res, indent=1, default=float)[:6000])


if __name__ == "__main__":
    main()
