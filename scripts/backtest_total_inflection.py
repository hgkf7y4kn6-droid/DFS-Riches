"""Back-test: do games where BOTH offenses' matchup-adjusted early-down success
rate (SR) and neutral-situation EPA are high go over the closing total?

Walk-forward, 2016-2025 regular season, weeks 5+. Every rate is built only
from the team's PRIOR games that season (shrunk toward the league-to-date mean).
Excluded: wind > 15 mph, rain/snow, and games where either starting QB is not
the team's season-to-date primary starter. Cold alone is NOT excluded.

Matchup value for an offense = league + (its own rate - league) + (the opposing
defense's rate allowed - league), so a soft defense lifts the expectation.

Needs pandas (analysis-only, not a runtime dependency):
    python -m scripts.backtest_total_inflection
Reads PBP and games.csv from data/cache/train/ (see scripts/train_game_model.py
fetch) and writes data/total_inflection.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

TRAIN = Path(__file__).resolve().parents[1] / "data" / "cache" / "train"
OUT = Path(__file__).resolve().parents[1] / "data" / "total_inflection.json"
SEASONS = list(range(2016, 2026))
MIN_WEEK = 5
PRIOR_GAMES = 4          # shrinkage weight (games) toward league-to-date mean
WIND_MAX = 15
BREAKEVEN = 0.524        # -110 pricing
PRECIP = re.compile(r"rain|snow|shower|flurr|drizzle|storm|sleet", re.I)
NEUTRAL = lambda d: (d.qtr <= 3) & (d.score_differential.abs() <= 14) & (d.half_seconds_remaining > 120)  # noqa: E731


def team_games() -> pd.DataFrame:
    rows = []
    for s in SEASONS:
        p = pd.read_csv(TRAIN / f"play_by_play_{s}.csv.gz", low_memory=False,
                        usecols=["game_id", "season_type", "week", "posteam", "defteam", "play_type", "epa",
                                 "success", "down", "qtr", "score_differential", "half_seconds_remaining",
                                 "weather", "wind"])
        p = p[(p.season_type == "REG") & p.play_type.isin(["pass", "run"]) & p.epa.notna()]
        wx = p.groupby("game_id").agg(weather=("weather", "first"), pwind=("wind", "first"))
        for (gid, team), d in p.groupby(["game_id", "posteam"]):
            e, n = d[d.down.isin([1, 2])], d[NEUTRAL(d)]
            rows.append(dict(season=s, game_id=gid, week=int(d.week.iloc[0]), team=team,
                             opp=d.defteam.iloc[0], sr=e.success.mean(), nepa=n.epa.mean(),
                             nn=len(n), en=len(e)))
        wx["season"] = s
        rows.append(dict(_wx=wx.reset_index()))
    wxs = pd.concat([r["_wx"] for r in rows if "_wx" in r])
    tg = pd.DataFrame([r for r in rows if "_wx" not in r])
    return tg, wxs


def build() -> pd.DataFrame:
    tg, wx = team_games()
    games = pd.read_csv(TRAIN / "games.csv")
    games = games[(games.game_type == "REG") & games.season.isin(SEASONS)].copy()
    games = games.merge(wx[["game_id", "weather", "pwind"]], on="game_id", how="left")
    games["wind_mph"] = games.wind.fillna(games.pwind).fillna(0)
    games["precip"] = games.weather.fillna("").str.contains(PRECIP)
    out = []
    for s in SEASONS:
        t = tg[tg.season == s].sort_values("week")
        for _, g in games[games.season == s].iterrows():
            if g.week < MIN_WEEK or pd.isna(g.total_line):
                continue
            rec = dict(game_id=g.game_id, season=s, week=g.week, total=g.total, line=g.total_line,
                       wind=g.wind_mph, precip=bool(g.precip), roof=g.roof)
            ok = True
            for side, team, opp, qb in (("a", g.away_team, g.home_team, g.away_qb_id), ("h", g.home_team, g.away_team, g.home_qb_id)):
                pri = games[(games.season == s) & (games.week < g.week) &
                            ((games.away_team == team) | (games.home_team == team))]
                starters = pd.concat([pri[pri.away_team == team].away_qb_id, pri[pri.home_team == team].home_qb_id])
                rec[f"{side}_qb_change"] = bool(len(starters) and starters.mode().iloc[0] != qb)
                prior = t[t.week < g.week]
                lg_sr, lg_ep = prior.sr.mean(), prior.nepa.mean()
                def shrunk(df, col, lg):  # noqa: E306
                    v = df[col].dropna()
                    return (v.sum() + PRIOR_GAMES * lg) / (len(v) + PRIOR_GAMES)
                own, allowed = prior[prior.team == team], prior[prior.opp == team]   # opp==team -> offense faced this defense
                opp_def = prior[prior.opp == opp]
                rec[f"{side}_sr"] = lg_sr + (shrunk(own, "sr", lg_sr) - lg_sr) + (shrunk(opp_def, "sr", lg_sr) - lg_sr)
                rec[f"{side}_ne"] = lg_ep + (shrunk(own, "nepa", lg_ep) - lg_ep) + (shrunk(opp_def, "nepa", lg_ep) - lg_ep)
                rec[f"{side}_sr_raw"] = shrunk(own, "sr", lg_sr)
                rec[f"{side}_ne_raw"] = shrunk(own, "nepa", lg_ep)
            out.append(rec)
    df = pd.DataFrame(out)
    df["diff"] = df.total - df.line
    df["over"] = np.where(df["diff"] > 0, 1.0, np.where(df["diff"] < 0, 0.0, np.nan))
    return df


def rate(d: pd.DataFrame) -> dict:
    x = d.over.dropna()
    n = len(x)
    if n == 0:
        return dict(n=0)
    k = int(x.sum())
    p = k / n
    z = (p - 0.5) / np.sqrt(0.25 / n)
    return dict(n=n, over_pct=round(p * 100, 1), avg_total=round(d.total.mean(), 1), avg_line=round(d.line.mean(), 1),
                avg_diff=round(d["diff"].mean(), 2), z_vs_50=round(float(z), 2))


def main() -> None:
    df = build()
    df["clean"] = (df.wind <= WIND_MAX) & ~df.precip & ~df.a_qb_change & ~df.h_qb_change
    c = df[df.clean].copy()
    for pre in ("adj", "raw"):
        sfx = "" if pre == "adj" else "_raw"
        c[f"min_sr_{pre}"] = c[["a_sr" + sfx, "h_sr" + sfx]].min(axis=1)
        c[f"min_ne_{pre}"] = c[["a_ne" + sfx, "h_ne" + sfx]].min(axis=1)
    report = dict(all_games=rate(df), clean_games=rate(c), excluded=dict(wind=int((df.wind > WIND_MAX).sum()), precip=int(df.precip.sum()),
                  qb_change=int((df.a_qb_change | df.h_qb_change).sum())))
    grid = {}
    for pre in ("adj", "raw"):
        sr_cuts = np.quantile(c[f"min_sr_{pre}"], [0.2, 0.4, 0.6, 0.8])
        ne_cuts = np.quantile(c[f"min_ne_{pre}"], [0.2, 0.4, 0.6, 0.8])
        rows = []
        for i, sc in enumerate([-9, *sr_cuts]):
            for j, nc in enumerate([-9, *ne_cuts]):
                m = c[(c[f"min_sr_{pre}"] >= sc) & (c[f"min_ne_{pre}"] >= nc)]
                rows.append(dict(sr_min=round(float(sc), 3), neutral_epa_min=round(float(nc), 3), **rate(m)))
        grid[pre] = rows
    report["grid"] = grid
    # walk-forward: pick the (sr, epa) cell with best over% (n>=60) on prior seasons, test on the next season
    report["walk_forward"], report["walk_forward_pooled"] = {}, {}
    for pre in ("adj", "raw"):
        sr_c, ne_c = f"min_sr_{pre}", f"min_ne_{pre}"
        wf = []
        for test in SEASONS[3:]:
            tr, te = c[c.season < test], c[c.season == test]
            best = None
            for q1 in (0.4, 0.5, 0.6, 0.7, 0.8):
                for q2 in (0.4, 0.5, 0.6, 0.7, 0.8):
                    a, b = tr[sr_c].quantile(q1), tr[ne_c].quantile(q2)
                    r = rate(tr[(tr[sr_c] >= a) & (tr[ne_c] >= b)])
                    if r["n"] >= 60 and (best is None or r["over_pct"] > best[0]["over_pct"]):
                        best = (r, a, b)
            if best:
                _, a, b = best
                t = te[(te[sr_c] >= a) & (te[ne_c] >= b)]
                wf.append(dict(test_season=test, sr_min=round(float(a), 3), neutral_epa_min=round(float(b), 3), train=best[0], test=rate(t)))
        report["walk_forward"][pre] = wf
        tot = pd.DataFrame([w["test"] for w in wf if w["test"]["n"]])
        if len(tot):
            k = round((tot.over_pct * tot.n / 100).sum())
            n = int(tot.n.sum())
            report["walk_forward_pooled"][pre] = dict(n=n, over=int(k), over_pct=round(100 * k / n, 1), breakeven_pct=BREAKEVEN * 100)
    OUT.write_text(json.dumps(report, indent=1, default=float))
    print(json.dumps({k: v for k, v in report.items() if k != "grid"}, indent=1, default=float))


if __name__ == "__main__":
    main()
