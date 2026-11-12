"""Back-test: game-environment indicators season by season. Does a relationship found in one season -- whatever teams
it showed up with -- hold in the next season, and does the current player model miss it?

    python -m scripts.test_season_indicators [--data DIR] [--players]

Regular season 2016-2026. Every team profile is built only from that team's earlier games IN THE SAME SEASON (no
carry-over), shrunk toward the league-to-date mean (4 games of weight), from week 4 on. Offense (o_), its defense
(d_, allowed), the opponent's offense (oo_) and the opponent's defense (od_): first- and second-half points and EPA
per play, first-three-drive EPA, Q4 points, EPA per dropback and per rush, explosive-play rate (20+ yard pass, 10+
yard run).

Indicators, from the team's side (products are of league-centred ratings):
  opp_fast_start     the opponent's 1H offense + own 1H defense allowed - own 1H offense - the opponent's 1H defense
  second_half_team   own (2H - 1H) points scored minus own (2H - 1H) points allowed
  comeback_trap      opp_fast_start x own offense's 2H tilt (a second-half offense behind a fast starter)
  leaky_2h           own 2H offense weakness + own 2H defense weakness (gives leads back)
  leaky_2h_x_fav     leaky_2h x the spread (a favourite that gives leads back)
  opp_leaky_2h       the same for the opponent
  2h_exploit         own 2H offense x the opponent's 2H defense allowed
  1h_exploit         own 1H offense x the opponent's 1H defense allowed
  pass_exploit       own EPA/dropback x the opponent's EPA/dropback allowed (what earlier offenses did to it)
  rush_exploit       the same for runs
  pass_match / rush_match / explosive_match   the additive versions (own + opponent defense allowed)
  early_match        first-three-drive EPA: own + opponent defense - opponent offense - own defense
  q4_match           Q4 points, same construction
  opp_explosive      the opponent's explosive offense + own explosive defense allowed

1. Per season: each indicator's coefficient on each outcome beyond the spread and total (one indicator at a time).
   Outcomes: margin vs the spread, points vs the implied total, 1H and 2H margin, pass and rush attempts,
   QB/RB/WR/TE DK points.
2. Carry-over: when an indicator is significant (|t| >= 2) in a season, how often it has the same sign the next
   season, and the out-of-sample error change from applying last season's fit (line + indicator) to this season,
   against last season's line-only fit -- for all seasons and for the seasons where it was significant the year before.
   Also an in-season version: refit on the season's earlier weeks (weeks 4..w-1, from week 8) and apply to week w.
3. --players: the current player model season by season (2023-2026; each of 2023-2025 corrected by a model fit on
   the other two, 2026 by the shipped training seasons) and its misses (actual - corrected) on each indicator, per
   position and season, with the same carry-over check.
Writes data/season_indicator_tests.json.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.test_fast_starts import SEASONS, ols

OUT = Path(__file__).resolve().parent.parent / "data" / "season_indicator_tests.json"
K = 4
MIN_WEEK = 4
T_SIG = 2.0
OUTCOMES = ("margin_vs_spread", "pts_vs_implied", "margin_1h", "margin_2h", "pass_att", "rush_att",
            "dk_QB", "dk_RB", "dk_WR", "dk_TE")
BASE = ["spread", "total_line"]


def half_stats(d: Path) -> pd.DataFrame:
    rows = []
    for s in SEASONS:
        p = pd.read_csv(d / f"play_by_play_{s}.csv.gz", low_memory=False,
                        usecols=["game_id", "season_type", "posteam", "qtr", "play_type", "epa", "qb_dropback",
                                 "yards_gained"])
        p = p[(p.season_type == "REG") & p.play_type.isin(["pass", "run"]) & p.epa.notna() & p.posteam.notna()]
        p["h2"] = p.qtr >= 3
        p["expl"] = ((p.qb_dropback == 1) & (p.yards_gained >= 20)) | ((p.qb_dropback != 1) & (p.yards_gained >= 10))
        g = p.groupby(["game_id", "posteam"])
        r = pd.DataFrame({"epa_1h": p[~p.h2].groupby(["game_id", "posteam"]).epa.mean(),
                          "epa_2h": p[p.h2].groupby(["game_id", "posteam"]).epa.mean(),
                          "expl": g.expl.mean()}).reset_index().rename(columns={"posteam": "team"})
        rows.append(r)
    return pd.concat(rows)


def team_games(d: Path) -> pd.DataFrame:
    tg = pd.read_pickle(d / "scoring_timing_team_games.pkl")
    tg = tg.merge(half_stats(d), on=["game_id", "team"], how="left")
    tg["pts_1h"] = tg.q1_for + tg.q2_for
    tg["pts_2h"] = tg.q3_for + tg.q4_for
    tg["margin_1h"] = tg.pts_1h - (tg.q1_against + tg.q2_against)
    tg["margin_2h"] = tg.pts_2h - (tg.q3_against + tg.q4_against)
    tg["margin_vs_spread"] = tg.pts_for - tg.pts_against - tg.spread
    tg["pts_vs_implied"] = tg.pts_for - (tg.total_line + tg.spread) / 2
    return tg


METRICS = ("pts_1h", "pts_2h", "epa_1h", "epa_2h", "early_epa", "q4_for", "epa_db", "epa_rush", "expl")


def ratings(tg: pd.DataFrame) -> pd.DataFrame:
    """o_/d_/oo_/od_ ratings for each team-game from the same season's earlier weeks."""
    out = []
    for s in SEASONS:
        cur = tg[tg.season == s]
        for w in sorted(cur.week.unique()):
            if w < MIN_WEEK:
                continue
            prior = cur[cur.week < w]
            val = {}
            for m in METRICS:
                lg = prior[m].mean()
                for side, key in (("o", "team"), ("d", "opp")):     # opp==X rows: what X's defense allowed
                    g = prior.groupby(key)[m].agg(["sum", "count"])
                    val[(side, m)] = ((g["sum"] + K * lg) / (g["count"] + K) - lg).to_dict()
            for x in cur[cur.week == w].itertuples():
                rec = {"game_id": x.game_id, "team": x.team}
                for m in METRICS:
                    rec[f"o_{m}"] = val[("o", m)].get(x.team, 0.0)
                    rec[f"d_{m}"] = val[("d", m)].get(x.team, 0.0)
                    rec[f"oo_{m}"] = val[("o", m)].get(x.opp, 0.0)
                    rec[f"od_{m}"] = val[("d", m)].get(x.opp, 0.0)
                out.append(rec)
    p = tg.merge(pd.DataFrame(out), on=["game_id", "team"], how="inner")
    I = pd.DataFrame(index=p.index)
    I["opp_fast_start"] = p.oo_pts_1h + p.d_pts_1h - p.o_pts_1h - p.od_pts_1h
    own_tilt = p.o_pts_2h - p.o_pts_1h
    I["second_half_team"] = own_tilt - (p.d_pts_2h - p.d_pts_1h)
    I["comeback_trap"] = I.opp_fast_start * own_tilt
    I["leaky_2h"] = -p.o_pts_2h + p.d_pts_2h
    I["leaky_2h_x_fav"] = I.leaky_2h * p.spread
    I["opp_leaky_2h"] = -p.oo_pts_2h + p.od_pts_2h
    I["2h_exploit"] = p.o_epa_2h * p.od_epa_2h * 100
    I["1h_exploit"] = p.o_epa_1h * p.od_epa_1h * 100
    I["pass_exploit"] = p.o_epa_db * p.od_epa_db * 100
    I["rush_exploit"] = p.o_epa_rush * p.od_epa_rush * 100
    I["pass_match"] = p.o_epa_db + p.od_epa_db
    I["rush_match"] = p.o_epa_rush + p.od_epa_rush
    I["explosive_match"] = p.o_expl + p.od_expl
    I["opp_explosive"] = p.oo_expl + p.d_expl
    I["early_match"] = p.o_early_epa + p.od_early_epa - p.oo_early_epa - p.d_early_epa
    I["q4_match"] = p.o_q4_for + p.od_q4_for - p.oo_q4_for - p.d_q4_for
    I["2h_epa_match"] = p.o_epa_2h + p.od_epa_2h - p.oo_epa_2h - p.d_epa_2h
    p = pd.concat([p, I.add_prefix("i_")], axis=1)
    return p.dropna(subset=["spread", "total_line", "dk_QB"])


def fit_predict(tr: pd.DataFrame, te: pd.DataFrame, y: str, xs: list[str]) -> np.ndarray:
    X = np.column_stack([np.ones(len(tr)), tr[xs].to_numpy(float)])
    b, *_ = np.linalg.lstsq(X, tr[y].to_numpy(float), rcond=None)
    return np.column_stack([np.ones(len(te)), te[xs].to_numpy(float)]) @ b


def carry(p: pd.DataFrame, y: str, ind: str) -> dict:
    per = {}
    for s, g in p.groupby("season"):
        g = g.dropna(subset=[y, ind])
        f = ols(g, y, BASE + [ind])
        per[int(s)] = (f[ind]["coef"], f[ind]["t"])
    seasons = sorted(per)
    # next-season replication of significant seasons
    sig = [(s, per[s]) for s in seasons[:-1] if abs(per[s][1]) >= T_SIG]
    same = [np.sign(per[s + 1][0]) == np.sign(c) for s, (c, _t) in sig if s + 1 in per]
    # last season's fit applied to this season
    gain_all, gain_sel = [], []
    for s in seasons[1:]:
        tr, te = p[p.season == s - 1].dropna(subset=[y, ind]), p[p.season == s].dropna(subset=[y, ind])
        e0 = ((te[y] - fit_predict(tr, te, y, BASE)) ** 2).mean()
        e1 = ((te[y] - fit_predict(tr, te, y, BASE + [ind])) ** 2).mean()
        gain_all.append((e0, e1, len(te)))
        if abs(per[s - 1][1]) >= T_SIG:
            gain_sel.append((e0, e1, len(te)))
    pct = lambda g: round(100 * (sum(b * n for _, b, n in g) / sum(a * n for a, _, n in g) - 1), 3) if g else None  # noqa: E731
    return {"by_season_t": {s: per[s][1] for s in seasons},
            "seasons_sig": sum(abs(t) >= T_SIG for _, t in per.values()),
            "seasons_sig_pos": sum(t >= T_SIG for _, t in per.values()),
            "seasons_sig_neg": sum(t <= -T_SIG for _, t in per.values()),
            "sig_then_same_sign_next": f"{sum(same)}/{len(same)}" if same else "0/0",
            "last_season_fit_mse_change_pct": pct(gain_all),
            "last_season_fit_when_sig_mse_change_pct": pct(gain_sel), "n_sig_years_applied": len(gain_sel)}


def in_season(p: pd.DataFrame, y: str, ind: str) -> float:
    """Refit on the season's earlier rated weeks, apply to week w (w >= 8)."""
    e0 = e1 = 0.0
    for s, g in p.groupby("season"):
        g = g.dropna(subset=[y, ind])
        for w in sorted(g.week.unique()):
            if w < 8:
                continue
            tr, te = g[g.week < w], g[g.week == w]
            e0 += ((te[y] - fit_predict(tr, te, y, BASE)) ** 2).sum()
            e1 += ((te[y] - fit_predict(tr, te, y, BASE + [ind])) ** 2).sum()
    return round(100 * (e1 / e0 - 1), 3)


def team_level(p: pd.DataFrame) -> dict:
    inds = [c for c in p.columns if c.startswith("i_")]
    out = {}
    for y in OUTCOMES:
        out[y] = {}
        for ind in inds:
            r = carry(p, y, ind)
            r["in_season_refit_mse_change_pct"] = in_season(p, y, ind)
            out[y][ind[2:]] = r
        print("team", y, flush=True)
    return out


def summary(res: dict, n_seasons: int) -> list[dict]:
    """Indicator-outcome pairs ranked by how often they are significant and carry to the next season."""
    rows = []
    for y, v in res.items():
        for ind, r in v.items():
            k, n = map(int, r["sig_then_same_sign_next"].split("/"))
            rows.append({"outcome": y, "indicator": ind, "seasons_sig": r["seasons_sig"],
                         "pos/neg": f"{r['seasons_sig_pos']}/{r['seasons_sig_neg']}",
                         "carry_same_sign": r["sig_then_same_sign_next"],
                         "last_season_fit": r["last_season_fit_mse_change_pct"],
                         "last_season_fit_when_sig": r["last_season_fit_when_sig_mse_change_pct"],
                         "in_season_refit": r.get("in_season_refit_mse_change_pct")})
    return sorted(rows, key=lambda r: (-r["seasons_sig"], r["last_season_fit"] or 0))


# ---------------------------------------------------------------- player level (current model, 2023-2026)

def player_rows(d: Path, p: pd.DataFrame, test_weeks: int) -> pd.DataFrame:
    cache = d / "season_indicator_players.pkl"
    if cache.exists():
        return pd.read_pickle(cache)
    from app import player_model as pm
    from scripts import train_player_model as tpm
    from scripts.train_game_model import REL, fetch
    rows = []
    for season, weeks in ((2023, range(1, 19)), (2024, range(1, 19)), (2025, range(1, 19)), (2026, range(1, test_weeks + 1))):
        st = csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv", d / f"stats_player_week_{season}.csv"), newline=""))
        team = {(int(s["week"]), pm.key(s["player_display_name"], s["position"])): s["team"].replace("LAR", "LA")
                for s in st if s.get("week") and s.get("season_type", "REG") == "REG"}
        for r in tpm.player_weeks(d, season, weeks):
            if r["week"] >= 2:
                rows.append({"season": season, "week": r["week"], "key": r["key"], "pos": r["pos"], "f": r["f"],
                             "proj": r["proj"], "actual": r["actual"], "team": team.get((r["week"], r["key"]))})
    # corrected: each of 2023-2025 by a fit on the other two; 2026 by the fit on all three
    for s in (2023, 2024, 2025, 2026):
        tr = [r for r in rows if r["season"] in (2023, 2024, 2025) and r["season"] != s]
        with contextlib.redirect_stdout(io.StringIO()):
            models = tpm.fit_all(tr, pm.FEATURES, sorted({r["season"] for r in tr}))
        for r in rows:
            if r["season"] == s:
                r["corrected"] = r["proj"] + (pm.adjustment(r["pos"], r["f"], {"positions": models}) or 0.0)
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "f"} for r in rows])
    df.to_pickle(cache)
    return df


def player_level(d: Path, p: pd.DataFrame, test_weeks: int) -> dict:
    df = player_rows(d, p, test_weeks)
    inds = [c for c in p.columns if c.startswith("i_")]
    df = df.merge(p[["season", "week", "team", *inds]], on=["season", "week", "team"], how="inner")
    df["miss"] = df.actual - df.corrected
    df["miss_sleeper"] = df.actual - df.proj
    out = {"model_by_season": {}}
    for s, g in df.groupby("season"):
        out["model_by_season"][int(s)] = {"n": len(g), "mae_sleeper": round(float(g.miss_sleeper.abs().mean()), 3),
                                          "mae_corrected": round(float(g.miss.abs().mean()), 3),
                                          **{pos: round(float(h.miss.abs().mean()), 3) for pos, h in g.groupby("pos")}}
    res = {}
    for pos in ("QB", "RB", "WR", "TE"):
        g = df[df.pos == pos]
        res[pos] = {}
        for ind in inds:
            per = {}
            for s, h in g.groupby("season"):
                f = ols(h, "miss", ["corrected", ind])
                per[int(s)] = (f[ind]["coef"], f[ind]["t"])
            ss = sorted(per)
            sig = [s for s in ss[:-1] if abs(per[s][1]) >= T_SIG]
            same = [np.sign(per[s + 1][0]) == np.sign(per[s][0]) for s in sig]
            # last season's coefficient applied to this season's misses
            e0 = e1 = 0.0
            for s in ss[1:]:
                tr, te = g[g.season == s - 1], g[g.season == s]
                e0 += ((te.miss - fit_predict(tr, te, "miss", ["corrected"])) ** 2).sum()
                e1 += ((te.miss - fit_predict(tr, te, "miss", ["corrected", ind])) ** 2).sum()
            res[pos][ind[2:]] = {"by_season_t": {s: per[s][1] for s in ss},
                                 "seasons_sig": sum(abs(per[s][1]) >= T_SIG for s in ss),
                                 "sig_then_same_sign_next": f"{sum(same)}/{len(same)}",
                                 "last_season_fit_mse_change_pct": round(100 * (e1 / e0 - 1), 3)}
    out["misses"] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--players", action="store_true")
    ap.add_argument("--test-weeks", type=int, default=9)
    args = ap.parse_args()
    d = Path(args.data)
    p = ratings(team_games(d))
    tl = team_level(p)
    n_ind = sum(1 for c in p.columns if c.startswith("i_"))
    res = {"team_games": len(p), "seasons": len(SEASONS),
           "chance": {"p_sig_per_season": 0.046, "expected_sig_seasons_per_pair": round(0.046 * len(SEASONS), 2),
                      "pairs_tested": n_ind * len(OUTCOMES)},
           "ranked": summary(tl, len(SEASONS)), "team_level": tl}
    if args.players:
        res["players"] = player_level(d, p, args.test_weeks)
    OUT.write_text(json.dumps(res, indent=1, default=float))
    for r in res["ranked"][:40]:
        print(r)


if __name__ == "__main__":
    main()
