"""Does the pregame team lineup adjustment predict player DFS points beyond a baseline?

Baseline (per position QB/RB/WR/TE): actual DK points ~ the player's trailing-8-game average + his team's closing implied
total + expected margin. That already contains the market's view of the team, and roughly what a projection knows about
the player's role. Sleeper's projections are NOT used: api.sleeper.com is unreachable from this environment, so this tests
the idea against a weaker baseline than the app's (the app's Sleeper projection beats a trailing average, MAE 5.83 vs
6.18), and a gain here may be smaller or absent against the real projection. No DK salary history exists for earlier
seasons, so no salary-implied test is run for them either.

Lineup adjustment = scripts.backtest_context_change (modes "active": game-day active list + injury report; "report":
injury report only), in points: own offense lineup effect and the opposing defense's lineup effect. Weeks 5+.
Validation: leave one season out over 2023-2025, plus 2026 weeks 5+ held out (trained on 2023-2025).

    python -m scripts.backtest_lineup_dfs
Needs pandas, plus the files listed in backtest_context_change and data/cache/train/stats_player_week_YYYY.csv (2022-2026).
Writes data/lineup_dfs_backtest.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.dk_scoring import dk_offense_points
from scripts import backtest_context_change as bcc

TRAIN = bcc.TRAIN
OUT = Path(__file__).resolve().parents[1] / "data" / "lineup_dfs_backtest.json"
SEASONS = [2022, 2023, 2024, 2025, 2026]
TRAIN_SEASONS = [2023, 2024, 2025]
TEST_SEASON = 2026
POSITIONS = ("QB", "RB", "WR", "TE")
MIN_WEEK = 5
MIN_TRAIL = 6.0          # trailing average (DK points) needed to count as a real role, like the app's 3-point Sleeper floor
PLAYS = bcc.PLAYS


def team_adjustments(mode: str, hist, lu, outs, actives, games) -> dict:
    """(season, week, team) -> {"own_off": points, "opp_def": points}."""
    out = {}
    for _, g in games.iterrows():
        for team, opp in ((g.away_team, g.home_team), (g.home_team, g.away_team)):
            vals = {}
            for unit, who, col, key in (("off", team, "off_epa", "own_off"), ("def", opp, "def_epa", "opp_def")):
                if mode == "active":
                    tgt = bcc.active_lineup(lu, outs, actives, g.season, g.week, who, unit)
                else:
                    tgt = bcc.pregame_lineup(lu, outs, g.season, g.week, who, unit)
                vals[key] = bcc.adjustment(unit, col, who, g.season, g.week, tgt, hist, lu) * PLAYS
            out[(g.season, g.week, team)] = vals
    return out


def player_table(games: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for s in SEASONS:
        d = pd.read_csv(TRAIN / f"stats_player_week_{s}.csv", low_memory=False)
        d = d[(d.season_type == "REG") & d.position.isin(POSITIONS)]
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    d["pts"] = [dk_offense_points(r) for r in d.to_dict("records")]
    d = d.sort_values(["player_id", "season", "week"])
    d["trail8"] = d.groupby("player_id").pts.transform(lambda x: x.shift(1).rolling(8, min_periods=4).mean())
    g = games.copy()
    g["imp_h"], g["imp_a"] = (g.total_line + g.spread_line) / 2, (g.total_line - g.spread_line) / 2
    home = g[["season", "week", "home_team", "imp_h", "spread_line"]].rename(columns={"home_team": "team", "imp_h": "imp", "spread_line": "spr"})
    away = g[["season", "week", "away_team", "imp_a", "spread_line"]].rename(columns={"away_team": "team", "imp_a": "imp"})
    away["spr"] = -away.pop("spread_line")
    d = d.merge(pd.concat([home, away]), on=["season", "week", "team"], how="inner")
    d = d[(d.week >= MIN_WEEK) & (d.trail8 >= MIN_TRAIL)]
    return d[["player_id", "position", "season", "week", "team", "pts", "trail8", "imp", "spr"]].copy()


def design(d: pd.DataFrame, lineup: bool) -> np.ndarray:
    cols = [np.ones(len(d)), d.trail8.to_numpy(), d.imp.to_numpy(), d.spr.to_numpy()]
    if lineup:
        cols += [d.own_off.to_numpy(), d.opp_def.to_numpy()]
    return np.column_stack(cols)


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def cluster_t(X: np.ndarray, y: np.ndarray, b: np.ndarray, clusters: np.ndarray) -> np.ndarray:
    e = y - X @ b
    bread = np.linalg.inv(X.T @ X)
    meat = np.zeros((X.shape[1], X.shape[1]))
    ids = pd.factorize(clusters)[0]
    for g in np.unique(ids):
        m = ids == g
        s = X[m].T @ e[m]
        meat += np.outer(s, s)
    G, n, k = len(np.unique(ids)), len(y), X.shape[1]
    V = bread @ meat @ bread * (G / (G - 1)) * ((n - 1) / (n - k))
    return b / np.sqrt(np.diag(V))


def evaluate(d: pd.DataFrame) -> dict:
    res = {}
    for pos in POSITIONS:
        p = d[d.position == pos]
        tr, te = p[p.season.isin(TRAIN_SEASONS)], p[p.season == TEST_SEASON]
        loso_b, loso_l = [], []
        for s in TRAIN_SEASONS:
            fit, hold = tr[tr.season != s], tr[tr.season == s]
            bb = ols(design(fit, False), fit.pts.to_numpy())
            bl = ols(design(fit, True), fit.pts.to_numpy())
            loso_b += list(np.abs(hold.pts.to_numpy() - design(hold, False) @ bb))
            loso_l += list(np.abs(hold.pts.to_numpy() - design(hold, True) @ bl))
        Xl = design(tr, True)
        b = ols(Xl, tr.pts.to_numpy())
        t = cluster_t(Xl, tr.pts.to_numpy(), b, (tr.season.astype(str) + "|" + tr.week.astype(str) + "|" + tr.team).to_numpy())
        bb_all, bl_all = ols(design(tr, False), tr.pts.to_numpy()), b
        r = {"n_train": int(len(tr)), "slope_own_off": round(float(b[4]), 3), "t_own_off": round(float(t[4]), 2),
             "slope_opp_def": round(float(b[5]), 3), "t_opp_def": round(float(t[5]), 2),
             "loso_mae_baseline": round(float(np.mean(loso_b)), 3), "loso_mae_with_lineup": round(float(np.mean(loso_l)), 3)}
        if len(te) >= 30:
            r["test_2026"] = {"n": int(len(te)),
                              "mae_baseline": round(float(np.mean(np.abs(te.pts.to_numpy() - design(te, False) @ bb_all))), 3),
                              "mae_with_lineup": round(float(np.mean(np.abs(te.pts.to_numpy() - design(te, True) @ bl_all))), 3)}
        res[pos] = r
    return res


def leverage(d: pd.DataFrame) -> dict:
    """Player-weeks on teams with a large lineup effect: do they beat the baseline in the predicted direction?"""
    out = {}
    base = {}
    for pos in POSITIONS:
        p = d[d.position == pos]
        tr = p[p.season.isin(TRAIN_SEASONS)]
        base[pos] = ols(design(tr, False), tr.pts.to_numpy())
    resid = np.zeros(len(d))
    for pos in POSITIONS:
        m = (d.position == pos).to_numpy()
        resid[m] = d.pts.to_numpy()[m] - design(d[m], False) @ base[pos]
    d = d.assign(resid=resid, adj=d.own_off + d.opp_def)
    for thr in (1.5, 3.0):
        hi, lo = d[d.adj >= thr], d[d.adj <= -thr]
        out[f"adj_ge_{thr}"] = {"players_up": int(len(hi)), "mean_resid_up": round(float(hi.resid.mean()), 2) if len(hi) else None,
                                "players_down": int(len(lo)), "mean_resid_down": round(float(lo.resid.mean()), 2) if len(lo) else None,
                                "beat_baseline_up_pct": round(100 * float((hi.resid > 0).mean()), 1) if len(hi) else None,
                                "beat_baseline_down_pct": round(100 * float((lo.resid > 0).mean()), 1) if len(lo) else None}
    return out


def main() -> None:
    bcc.SEASONS = SEASONS
    hist, lu, outs, actives = bcc.unit_epa(), bcc.lineups(), bcc.reported_out(), bcc.active_lists()
    games = pd.read_csv(TRAIN / "games.csv")
    games = games[(games.game_type == "REG") & games.season.isin(SEASONS[1:]) & (games.week >= MIN_WEEK)].dropna(subset=["total_line", "spread_line"])
    base = player_table(games)
    report = {"baseline": "trailing-8 DK points + closing implied total + expected margin (no Sleeper projection)",
              "rows": int(len(base))}
    for mode in ("active", "report"):
        adj = team_adjustments(mode, hist, lu, outs, actives, games)
        d = base.copy()
        keys = list(zip(d.season, d.week, d.team))
        d["own_off"] = [adj.get(k, {}).get("own_off", 0.0) for k in keys]
        d["opp_def"] = [adj.get(k, {}).get("opp_def", 0.0) for k in keys]
        report[mode] = {"by_position": evaluate(d), "leverage": leverage(d),
                        "sd_adj_pts": {"own_off": round(float(d.own_off.std()), 2), "opp_def": round(float(d.opp_def.std()), 2)}}
    OUT.write_text(json.dumps(report, indent=1, default=float))
    print(json.dumps(report, indent=1, default=float))


if __name__ == "__main__":
    main()
