"""Do schedule-adjusted form and the schedule ahead predict what teams (and their players) do next?

Walk-forward on 2016-2025 play-by-play (seasons 2019+ are predicted from coefficients fit on earlier seasons).

  A  Opponent adjustment: a team's next-game EPA/play from its last 6 games raw vs. the same games each measured against
     what that game's opponent usually allowed, with and without the next opponent's own rating. Offence and defence, in
     total and split pass / rush (a rushing offence is judged against rush defences).
  B  Stickiness: with 6+ games played, split the last 3 games' move from the 3 before into the part the schedule explains
     (the opponents were soft / tough) and the part that is the team itself, and ask which carries into the next 3 games.
     Also: the softness of the next 3 opponents.
  C  Market: does the schedule-adjusted rating differ from the closing spread / total in a way that predicts the result?
  D  Players: when a receiver's share of team targets jumps, how much is still there in the next 3 games, and does it
     matter whether the jump came against a soft pass defence?

Needs pandas and data/cache/train (see scripts.backtest_roster_moves). Writes data/schedule_trend_backtest.json.
    python -m scripts.backtest_schedule_trends
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts import backtest_roster_moves as b

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "schedule_trend_backtest.json"
OUTLOOK = ROOT / "data" / "schedule_outlook.json"
N_RATE, K_RATE = 12, 3          # a rating = mean of the last 12 games, shrunk with 3 league-average games
FAMILIES = {                    # name: (own column, opponent-side column it is judged against, weight)
    "off_total": ("off_y", "def_y", "plays"), "off_pass": ("off_pass", "def_pass", "db"), "off_rush": ("off_rush", "def_rush", "rush_n"),
    "def_total": ("def_y", "off_y", "plays"), "def_pass": ("def_pass", "off_pass", "db"), "def_rush": ("def_rush", "off_rush", "rush_n")}


# ------------------------------------------------------------------------------------------------ panel
def panel(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    g["off_y"] = (g.epa_db_s + g.epa_run_s) / g.plays
    g["off_pass"] = g.epa_db_s / g.db
    g["off_rush"] = g.epa_run_s / g.rush_n.replace(0, np.nan)
    o = g[b.KEY + ["posteam", "off_y", "off_pass", "off_rush", "plays", "db", "rush_n"]].rename(columns={
        "posteam": "defteam", "off_y": "def_y", "off_pass": "def_pass", "off_rush": "def_rush", "plays": "dplays", "db": "ddb", "rush_n": "drush_n"})
    g = g.merge(o, on=b.KEY + ["defteam"])
    for c in ("off_y", "off_pass", "off_rush", "def_y", "def_pass", "def_rush"):
        g[c + "_c"] = g[c] - g.groupby("season")[c].transform("mean")
    g = g.rename(columns={"posteam": "team", "defteam": "opp"}).sort_values(["season", "week"]).reset_index(drop=True)
    g["key"] = g.season * 100 + g.week
    return g


class Ratings:
    """rate(team, column, key) = shrunk mean of the team's last N_RATE games of `column` strictly before `key`."""

    def __init__(self, p: pd.DataFrame, cols: list[str]):
        self.s = {}
        for team, d in p.groupby("team"):
            d = d.sort_values("key")
            for c in cols:
                v = d[c].fillna(0).values
                self.s[(team, c)] = (d.key.values, np.concatenate([[0], np.cumsum(v)]))

    def rate(self, team: str, col: str, key: int) -> float:
        ks, cs = self.s[(team, col)]
        i = int(np.searchsorted(ks, key, side="left"))
        lo = max(0, i - N_RATE)
        return float((cs[i] - cs[lo]) / ((i - lo) + K_RATE))


def add_ratings(p: pd.DataFrame) -> tuple[pd.DataFrame, Ratings]:
    cols = [c + "_c" for c in ("off_y", "off_pass", "off_rush", "def_y", "def_pass", "def_rush")]
    R = Ratings(p, cols)
    for fam, (own, opp, _w) in FAMILIES.items():
        p[f"opp_{opp}"] = [R.rate(o, opp + "_c", k) for o, k in zip(p.opp, p.key)]          # what the opponent usually gives up / produces
        p[f"adj_{own}"] = p[own + "_c"] - p[f"opp_{opp}"]
    return p, R


# ------------------------------------------------------------------------------------------------ A and B
def windows(p: pd.DataFrame, R: Ratings) -> pd.DataFrame:
    rows = []
    for (team, season), d in p.groupby(["team", "season"]):
        d = d.sort_values("week").reset_index(drop=True)
        n = len(d)
        for i in range(6, n):
            rec = {"team": team, "season": season, "week": int(d.week[i]), "i": i}
            for fam, (own, opp, w) in FAMILIES.items():
                a, c = f"adj_{own}", own + "_c"
                o_col = f"opp_{opp}"
                old, new = slice(i - 6, i - 3), slice(i - 3, i)
                rec[f"{fam}_y"] = d[c][i]
                rec[f"{fam}_w"] = d[w][i]
                rec[f"{fam}_raw6"] = d[c][i - 6:i].mean()
                rec[f"{fam}_adj6"] = d[a][i - 6:i].mean()
                rec[f"{fam}_opp"] = d[o_col][i]                                    # the coming opponent's rating
                rec[f"{fam}_adj_old"] = d[a][old].mean()
                rec[f"{fam}_adj_delta"] = d[a][new].mean() - d[a][old].mean()
                rec[f"{fam}_raw_delta"] = d[c][new].mean() - d[c][old].mean()
                rec[f"{fam}_sched_delta"] = d[o_col][new].mean() - d[o_col][old].mean()   # how much softer the last 3 opponents were than the 3 before
                if i + 2 < n:
                    rec[f"{fam}_y3"] = d[c][i:i + 3].mean()
                    rec[f"{fam}_w3"] = d[w][i:i + 3].sum()
                    rec[f"{fam}_next3_opp"] = np.mean([R.rate(o, opp + "_c", int(d.key[i])) for o in d.opp[i:i + 3]])
            rows.append(rec)
    return pd.DataFrame(rows)


def wf(df, y, xs0, xs1, w):
    """Out-of-sample weighted MSE of y on xs0 vs xs1 (fit on earlier seasons)."""
    P0, P1, Y, W = [], [], [], []
    for s in b.TEST_SEASONS:
        tr = df[df.season < s].dropna(subset=[y, *xs1])
        te = df[df.season == s].dropna(subset=[y, *xs1])
        if len(tr) < 300 or len(te) == 0:
            continue
        b0 = b.wols(tr[xs0].values, tr[y].values, tr[w].values)
        b1 = b.wols(tr[xs1].values, tr[y].values, tr[w].values)
        P0.append(b.pred(b0, te[xs0].values)); P1.append(b.pred(b1, te[xs1].values)); Y.append(te[y].values); W.append(te[w].values)
    p0, p1, yy, ww = map(np.concatenate, (P0, P1, Y, W))
    m0, m1 = np.average((yy - p0) ** 2, weights=ww), np.average((yy - p1) ** 2, weights=ww)
    return {"n": int(len(yy)), "mse_change_pct": round(float(100 * (m1 / m0 - 1)), 2), "corr_base": round(float(np.corrcoef(p0, yy)[0, 1]), 3),
            "corr_with": round(float(np.corrcoef(p1, yy)[0, 1]), 3)}


def fit(df, y, xs, w):
    d = df.dropna(subset=[y, *xs])
    beta, t = b.cluster_t(d[xs].values, d[y].values, d[w].values.astype(float), (d.team + d.season.astype(str)).values)
    return {x: [round(float(beta[i + 1]), 3), round(float(t[i + 1]), 1)] for i, x in enumerate(xs)}


def test_a(W: pd.DataFrame) -> dict:
    out = {}
    for fam in FAMILIES:
        r = {"raw6": wf(W, f"{fam}_y", [f"{fam}_raw6"], [f"{fam}_raw6"], f"{fam}_w")}
        r["adj6_vs_raw6"] = wf(W, f"{fam}_y", [f"{fam}_raw6"], [f"{fam}_adj6"], f"{fam}_w")
        r["raw6_plus_next_opponent"] = wf(W, f"{fam}_y", [f"{fam}_raw6"], [f"{fam}_raw6", f"{fam}_opp"], f"{fam}_w")
        r["adj6_plus_next_opponent_vs_raw6"] = wf(W, f"{fam}_y", [f"{fam}_raw6"], [f"{fam}_adj6", f"{fam}_opp"], f"{fam}_w")
        r["coefs_adj6_next_opponent"] = fit(W, f"{fam}_y", [f"{fam}_adj6", f"{fam}_opp"], f"{fam}_w")
        out[fam] = r
    return out


def test_b(W: pd.DataFrame) -> dict:
    out = {}
    for fam in FAMILIES:
        y, w = f"{fam}_y3", f"{fam}_w3"
        xs = [f"{fam}_adj_old", f"{fam}_adj_delta", f"{fam}_sched_delta", f"{fam}_next3_opp"]
        r = {"coefs": fit(W, y, xs, w)}
        r["add_adjusted_move_and_schedule_ahead"] = wf(W, y, xs[:1], xs, w)
        r["add_only_schedule_ahead"] = wf(W, y, xs[:1], [xs[0], xs[3]], w)
        r["add_only_adjusted_move"] = wf(W, y, xs[:1], xs[:2], w)
        # the raw view: one number for "how much better lately", schedule and all
        r["raw_move_coef"] = fit(W, y, [f"{fam}_adj_old", f"{fam}_raw_delta"], w)[f"{fam}_raw_delta"]
        out[fam] = r
    return out


# ------------------------------------------------------------------------------------------------ C
def test_c(p: pd.DataFrame, R: Ratings) -> dict:
    games = pd.read_csv(b.TRAIN / "games.csv", usecols=["game_id", "season", "week", "game_type", "home_team", "away_team", "result", "total", "spread_line", "total_line"])
    games = games[(games.game_type == "REG") & games.season.between(2016, 2025) & (games.week >= 6)].dropna(subset=["result", "spread_line", "total_line"])
    adj = {"off_y": "adj_off_total", "def_y": "adj_def_total"}
    # adjusted ratings as of each game: a rolling mean of the opponent-adjusted columns
    R2 = Ratings(p.assign(a_off=p["adj_off_y"], a_def=p["adj_def_y"]), ["a_off", "a_def"])
    rows = []
    mean_tl = games.groupby("season").total_line.mean()
    for _, r in games.iterrows():
        k = int(r.season * 100 + r.week)
        try:
            raw_h = R.rate(r.home_team, "off_y_c", k) + R.rate(r.away_team, "def_y_c", k)
            raw_a = R.rate(r.away_team, "off_y_c", k) + R.rate(r.home_team, "def_y_c", k)
            adj_h = R2.rate(r.home_team, "a_off", k) + R2.rate(r.away_team, "a_def", k)
            adj_a = R2.rate(r.away_team, "a_off", k) + R2.rate(r.home_team, "a_def", k)
        except KeyError:
            continue
        rows.append({"season": r.season, "week": r.week, "y_m": r.result - r.spread_line, "y_t": r.total - r.total_line,
                     "x_m_raw": 62 * (raw_h - raw_a) + 1.8 - r.spread_line, "x_m_adj": 62 * (adj_h - adj_a) + 1.8 - r.spread_line,
                     "x_t_raw": 62 * (raw_h + raw_a) - (r.total_line - mean_tl[r.season]), "x_t_adj": 62 * (adj_h + adj_a) - (r.total_line - mean_tl[r.season])})
    m = pd.DataFrame(rows)
    out = {"games": int(len(m))}
    for y, xs in (("y_m", ("x_m_raw", "x_m_adj")), ("y_t", ("x_t_raw", "x_t_adj"))):
        for x in xs:
            beta, t = b.cluster_t(m[[x]].values, m[y].values, np.ones(len(m)), m.season.astype(str).values)
            hi = m[m[x].abs() >= m[x].abs().quantile(0.8)]
            out[f"{y}_on_{x}"] = {"slope": round(float(beta[1]), 3), "t": round(float(t[1]), 2),
                                  "top_quintile_hit_pct": round(float(100 * (np.sign(hi[y]) == np.sign(hi[x])).mean()), 1), "n_top_quintile": int(len(hi)),
                                  "by_season_slope": {int(s): round(float(np.polyfit(d[x], d[y], 1)[0]), 2) for s, d in m.groupby("season")}}
    return out


# ------------------------------------------------------------------------------------------------ D
def test_d(p: pd.DataFrame, t: pd.DataFrame, pl: pd.DataFrame) -> dict:
    pos = pl.drop_duplicates("gsis_id").set_index("gsis_id").position
    t = t.copy()
    t["pos"] = t.receiver_player_id.map(pos)
    t = t[t.pos.isin(["WR", "TE", "RB"])]
    team_t = t.groupby(b.KEY + ["posteam"]).tgt.sum().rename("team_tgt").reset_index()
    t = t.merge(team_t, on=b.KEY + ["posteam"])
    t["share"] = t.tgt / t.team_tgt
    opp = p[b.KEY + ["team", "opp", "opp_def_pass", "key"]].rename(columns={"team": "posteam"})
    t = t.merge(opp, on=b.KEY + ["posteam"], how="inner")
    rows = []
    games = p[["team", "season", "week", "game_id"]].sort_values(["team", "season", "week"])
    for (team, season), gm in games.groupby(["team", "season"]):
        ids = gm.game_id.tolist()
        tt = t[(t.posteam == team) & (t.season == season)]
        piv = tt.pivot_table(index="receiver_player_id", columns="game_id", values="share", aggfunc="sum").reindex(columns=ids).fillna(0)
        opp_soft = tt.drop_duplicates("game_id").set_index("game_id").opp_def_pass.reindex(ids)
        for pid, sh in piv.iterrows():
            s = sh.values
            for i in range(5, len(ids) - 3):
                base = s[i - 5:i - 1].mean()          # the four games before the jump game
                last = s[i - 1]
                if base < 0.06 or s[i - 5:i].min() == 0:
                    continue                          # a regular, not a player who just appeared
                rows.append({"team": team, "season": season, "base": base, "jump": last - base, "next3": s[i:i + 3].mean() - base,
                             "soft": opp_soft.iloc[i - 1]})
    d = pd.DataFrame(rows)
    out = {"player_windows": int(len(d))}
    def lam(x):
        beta, tt = b.cluster_t(x[["jump"]].values, x.next3.values, np.ones(len(x)), (x.team + x.season.astype(str)).values)
        return {"n": int(len(x)), "persistence": round(float(beta[1]), 3), "t": round(float(tt[1]), 1)}
    out["all"] = lam(d)
    up = d[d.jump >= 0.08]
    out["jump_up_8pts_plus"] = {**lam(up), "mean_jump": round(float(up.jump.mean()), 3), "mean_next3_change": round(float(up.next3.mean()), 3),
                                "share_of_jump_kept": round(float(up.next3.mean() / up.jump.mean()), 2)}
    q = d.soft.quantile([1 / 3, 2 / 3]).values
    for name, m in (("jump_against_soft_pass_defense", d.soft >= q[1]), ("jump_against_average", (d.soft < q[1]) & (d.soft >= q[0])), ("jump_against_tough", d.soft < q[0])):
        x = d[m & (d.jump >= 0.08)]
        out[name] = {"n": int(len(x)), "mean_jump": round(float(x.jump.mean()), 3), "mean_next3_change": round(float(x.next3.mean()), 3),
                     "share_of_jump_kept": round(float(x.next3.mean() / x.jump.mean()), 2)}
    return out


def test_d2(p_raw: pd.DataFrame, P: pd.DataFrame, t: pd.DataFrame, pl: pd.DataFrame, R: Ratings) -> dict:
    """Sustained role changes (two games in a row up) vs one-game spikes, and whether the soft pass defences AHEAD predict a
    receiver's next 3 games of receiving EPA beyond his own recent output."""
    pos = pl.drop_duplicates("gsis_id").set_index("gsis_id").position
    q = p_raw[(p_raw.qb_dropback == 1) & p_raw.receiver_player_id.notna() & p_raw.epa.notna() & (p_raw.play_type == "pass")]
    e = q.groupby(b.KEY + ["posteam", "receiver_player_id"]).agg(epa=("epa", "sum"), tg=("epa", "size")).reset_index()
    e["pos"] = e.receiver_player_id.map(pos)
    e = e[e.pos.isin(["WR", "TE", "RB"])]
    team_tg = e.groupby(b.KEY + ["posteam"]).tg.sum().rename("team_tg").reset_index()
    e = e.merge(team_tg, on=b.KEY + ["posteam"])
    e["share"] = e.tg / e.team_tg
    rows_sp, rows_ep = [], []
    for (team, season), gm in P[["team", "season", "week", "game_id", "opp", "key"]].sort_values(["season", "week"]).groupby(["team", "season"]):
        ids = gm.game_id.tolist()
        keys, opps = gm.key.tolist(), gm.opp.tolist()
        ee = e[(e.posteam == team) & (e.season == season)]
        sh = ee.pivot_table(index="receiver_player_id", columns="game_id", values="share", aggfunc="sum").reindex(columns=ids).fillna(0)
        ep = ee.pivot_table(index="receiver_player_id", columns="game_id", values="epa", aggfunc="sum").reindex(columns=ids).fillna(0)
        tg = ee.pivot_table(index="receiver_player_id", columns="game_id", values="tg", aggfunc="sum").reindex(columns=ids).fillna(0)
        for pid in sh.index:
            s, x, n = sh.loc[pid].values, ep.loc[pid].values, tg.loc[pid].values
            for i in range(5, len(ids) - 3):
                base = s[i - 5:i - 1].mean()
                if base < 0.06 or s[i - 5:i].min() == 0:
                    continue
                last2 = s[i - 2:i].mean()
                rows_sp.append({"team": team, "season": season, "base": base, "last1": s[i - 1] - base, "last2": last2 - base,
                                "both_up": float(min(s[i - 2], s[i - 1]) >= base + 0.03), "next3": s[i:i + 3].mean() - base})
                if base >= 0.10 and n[i:i + 3].sum() > 0:
                    soft = np.mean([R.rate(o, "def_pass_c", keys[i]) for o in opps[i:i + 3]])
                    rows_ep.append({"team": team, "season": season, "base_epa": x[i - 4:i].mean(), "soft_ahead": soft, "y": x[i:i + 3].mean()})
    sp = pd.DataFrame(rows_sp)
    sp = sp[sp.season <= 2025]
    out = {}
    one = sp[(sp.last1 >= 0.08) & (sp.both_up == 0)]
    two = sp[(sp.last2 >= 0.06) & (sp.both_up == 1)]
    for name, d in (("one_game_spike_8pts_plus", one), ("two_games_up_sustained", two)):
        out[name] = {"n": int(len(d)), "mean_shift_in_last_game_or_two": round(float(d.last1.mean() if "one" in name else d.last2.mean()), 3),
                     "mean_next3_change": round(float(d.next3.mean()), 3),
                     "share_kept": round(float(d.next3.mean() / (d.last1.mean() if "one" in name else d.last2.mean())), 2)}
    ep = pd.DataFrame(rows_ep)
    ep = ep[ep.season <= 2025]
    beta, tt = b.cluster_t(ep[["base_epa", "soft_ahead"]].values, ep.y.values, np.ones(len(ep)), (ep.team + ep.season.astype(str)).values)
    out["receiver_epa_next3"] = {"n": int(len(ep)), "coef_own_recent_epa": [round(float(beta[1]), 3), round(float(tt[1]), 1)],
                                 "coef_softness_of_next_3_pass_defenses": [round(float(beta[2]), 2), round(float(tt[2]), 1)],
                                 "sd_of_softness": round(float(ep.soft_ahead.std()), 3), "epa_per_game_per_sd_softer": round(float(beta[2] * ep.soft_ahead.std()), 3),
                                 "mean_epa_per_game": round(float(ep.y.mean()), 3)}
    return out


def outlook(P: pd.DataFrame, R: Ratings, season: int, week: int, coefs: dict) -> dict:
    """Every team's schedule behind and ahead, in EPA per play above/below an average opponent (x100), and the expected move
    from the fitted next-3-game coefficients. Past = the last 6 games' opponents at the time; ahead = the next 3 opponents now."""
    import asyncio
    from app import nflverse_client as nc
    games = asyncio.run(nc.get_games_raw(season))
    key = season * 100 + week
    ahead: dict[str, list[str]] = {}
    for r in sorted(games, key=lambda r: int(r["week"])):
        if r.get("game_type") == "REG" and int(r["week"]) >= week:
            ahead.setdefault(r["home_team"], []).append(r["away_team"])
            ahead.setdefault(r["away_team"], []).append(r["home_team"])
    out = {}
    for team, d in P[P.season == season].groupby("team"):
        d = d.sort_values("week")
        past6 = d.tail(6)
        nxt = ahead.get(team, [])[:3]
        if len(nxt) < 2:
            continue
        row = {"opponents_ahead": nxt}
        for fam in ("off_total", "off_pass", "off_rush", "def_total", "def_pass", "def_rush"):
            own, opp, _w = FAMILIES[fam]
            past = float(past6[f"opp_{opp}"].mean())
            fut = float(np.mean([R.rate(o, opp + "_c", key) for o in nxt]))
            row[fam] = {"schedule_past6": round(100 * past, 1), "schedule_ahead": round(100 * fut, 1), "change": round(100 * (fut - past), 1),
                        "expected_move": round(100 * coefs[fam] * (fut - past), 2),
                        "adj_form_6": round(100 * float(past6[f"adj_{own}"].mean()), 1)}
        out[team] = row
    return out


def main():
    p = b.load_pbp(range(2016, 2027))
    g, pb, t = b.team_games(p)
    pl = b.load_ids()
    P = panel(g)
    P, R = add_ratings(P)
    W = windows(P, R)
    Wt = W[W.season <= 2025]
    P25 = P[P.season <= 2025]
    res = {"seasons": [2016, 2025], "windows": int(len(Wt)),
           "A_opponent_adjustment": test_a(Wt), "B_stickiness": test_b(Wt), "C_market": test_c(P25, R), "D_players": test_d(P25, t, pl)}
    res["D2_roles_and_matchups_ahead"] = test_d2(p, P, t, pl, R)
    coefs = {fam: res["B_stickiness"][fam]["coefs"][f"{fam}_next3_opp"][0] for fam in FAMILIES}
    res["outlook_2026_week10"] = outlook(P, R, 2026, 10, coefs)
    OUTLOOK.write_text(json.dumps({
        "_about": "Schedule behind (last 6 opponents, as rated then) vs ahead (next 3, rated now), in EPA per play x100 above/below an "
                  "average opponent, and the move the next-3-game coefficients imply (scripts/backtest_schedule_trends.py).",
        "season": 2026, "week": 10,
        "coefficients": {f: res["B_stickiness"][f]["coefs"][f"{f}_next3_opp"] for f in FAMILIES},    # [coef, t]
        "teams": res["outlook_2026_week10"]}, indent=1) + "\n")
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
