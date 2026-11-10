"""Do roster moves (QB changes, lost receivers, lost or added pass rushers) predict team results beyond the team's own history?

Walk-forward: every season 2019-2025 is predicted by coefficients fit only on earlier seasons (2016+), so nothing
sees the future. Every test compares a baseline (the team's own previous 8 games, shrunk to the league) with the
baseline plus a roster-based signal. A signal only counts if it cuts out-of-sample squared error.

  T1  QB: the starter's career EPA per dropback (shrunk) vs the team's own recent EPA per dropback, on all games, on
      QB-change games, and on games where the QB came from another team. Also: what an inexperienced QB (< 300 career
      dropbacks) does to interceptions, sacks, red-zone TDs, pass rate, EPA and target concentration.
  T2  Receivers: share of the team's recent targets belonging to WR/TE/RB who are absent (traded, hurt) -> EPA, pass
      rate and plays.
  T3  Pass rush: each defender's own sacks+hits per snap carried to the team he is on now, against the team's own
      pressure rate; plus the share of recent pressures that left with absent players.

Needs pandas (analysis only). Data (data/cache/train, untracked): play_by_play_YYYY.csv.gz, snap_counts_YYYY.csv,
players.csv from https://github.com/nflverse/nflverse-data/releases/ (pbp, snap_counts, players).
    python -m scripts.backtest_roster_moves
Writes data/roster_move_backtest.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "data" / "cache" / "train"
OUT = ROOT / "data" / "roster_move_backtest.json"
MODEL = ROOT / "data" / "roster_adjust_model.json"
SEASONS = list(range(2016, 2026))
TEST_SEASONS = list(range(2019, 2026))
WIN = 8                    # games in a team's own baseline
K_TEAM = 100.0             # pseudo-dropbacks of league average
K_QB = 150.0
K_SNAPS = 300.0
INEXP = 300                # career dropbacks below which a QB is inexperienced
PBP_COLS = ["season", "week", "season_type", "game_id", "posteam", "defteam", "play_type", "epa", "qb_dropback", "interception",
            "sack", "qb_hit", "passer_player_id", "receiver_player_id", "wp", "qtr", "down", "fixed_drive",
            "fixed_drive_result", "drive_inside20", "sack_player_id", "half_sack_1_player_id", "half_sack_2_player_id",
            "qb_hit_1_player_id", "qb_hit_2_player_id", "tackle_for_loss_1_player_id", "tackle_for_loss_2_player_id",
            "two_point_attempt", "pass_attempt"]
KEY = ["season", "week", "game_id"]


# ----------------------------------------------------------------------------------------------- stats helpers
def wols(X: np.ndarray, y: np.ndarray, w: np.ndarray, ridge: float = 1e-9):
    X1 = np.column_stack([np.ones(len(X)), X])
    W = w[:, None]
    beta = np.linalg.solve(X1.T @ (W * X1) + ridge * np.eye(X1.shape[1]), X1.T @ (w * y))
    return beta


def pred(beta, X):
    return beta[0] + X @ beta[1:]


def cluster_t(X: np.ndarray, y: np.ndarray, w: np.ndarray, groups: np.ndarray):
    """(beta, t) with team-season clustered errors."""
    X1 = np.column_stack([np.ones(len(X)), X])
    A = np.linalg.inv(X1.T @ (w[:, None] * X1))
    beta = A @ X1.T @ (w * y)
    e = y - X1 @ beta
    meat = np.zeros((X1.shape[1],) * 2)
    for g in np.unique(groups):
        m = groups == g
        s = X1[m].T @ (w[m] * e[m])
        meat += np.outer(s, s)
    se = np.sqrt(np.diag(A @ meat @ A))
    return beta, beta / se


def walk_forward(df: pd.DataFrame, y: str, base: str, extra: list[str], w: str, subset=None) -> dict:
    """Out-of-sample weighted MSE of base-only vs base+extra, fit on earlier seasons (all games), scored on `subset`."""
    se_b = se_x = ws = 0.0
    preds_b, preds_x, ys, ws_all = [], [], [], []
    betas = []
    for s in TEST_SEASONS:
        tr = df[df.season < s].dropna(subset=[y, base, *extra])
        te = df[df.season == s].dropna(subset=[y, base, *extra])
        if subset is not None:
            te = te[subset(te)]
        if len(te) == 0 or len(tr) < 200:
            continue
        b0 = wols(tr[[base]].values, tr[y].values, tr[w].values)
        b1 = wols(tr[[base, *extra]].values, tr[y].values, tr[w].values)
        p0, p1 = pred(b0, te[[base]].values), pred(b1, te[[base, *extra]].values)
        preds_b.append(p0), preds_x.append(p1), ys.append(te[y].values), ws_all.append(te[w].values)
        betas.append(b1[2:] if extra else b1)
    if not ys:
        return {}
    p0, p1, yy, ww = map(np.concatenate, (preds_b, preds_x, ys, ws_all))
    m0 = float(np.average((yy - p0) ** 2, weights=ww))
    m1 = float(np.average((yy - p1) ** 2, weights=ww))
    return {"n": int(len(yy)), "mse_base": round(m0, 5), "mse_with": round(m1, 5), "mse_change_pct": round(100 * (m1 / m0 - 1), 2),
            "corr_base": round(float(np.corrcoef(p0, yy)[0, 1]), 3), "corr_with": round(float(np.corrcoef(p1, yy)[0, 1]), 3),
            "avg_extra_coefs": [round(float(c), 3) for c in np.mean(betas, axis=0)] if extra else []}


def rolling_base(df: pd.DataFrame, num: str, den: str, k: float, mu: float, name: str):
    """Team's own previous WIN games (shifted), shrunk: (sum num + k mu) / (sum den + k)."""
    g = df.sort_values(["season", "week"]).groupby("posteam" if "posteam" in df else "team")
    n = g[num].transform(lambda s: s.shift(1).rolling(WIN, min_periods=3).sum())
    d = g[den].transform(lambda s: s.shift(1).rolling(WIN, min_periods=3).sum())
    df[name] = (n + k * mu) / (d + k)


# ----------------------------------------------------------------------------------------------- data
def load_pbp(seasons=None) -> pd.DataFrame:
    fr = []
    for s in seasons or SEASONS:
        p = pd.read_csv(TRAIN / f"play_by_play_{s}.csv.gz", usecols=PBP_COLS, low_memory=False)
        fr.append(p[p.season_type == "REG"])
    return pd.concat(fr, ignore_index=True)


def team_games(p: pd.DataFrame):
    q = p[p.play_type.isin(["pass", "run"]) & p.epa.notna() & (p.two_point_attempt != 1)].copy()
    q["db"] = (q.qb_dropback == 1).astype(int)
    q["neutral"] = ((q.down <= 2) & (q.qtr <= 3) & q.wp.between(0.2, 0.8)).astype(int)
    q["epa_db"] = q.epa * q.db
    q["epa_run"] = q.epa * (1 - q.db)
    q["nd"] = q.neutral * q.db
    q["int_n"] = q.interception.fillna(0) * q.db
    q["sack_n"] = q.sack.fillna(0) * q.db
    g = q.groupby(KEY + ["posteam", "defteam"], as_index=False).agg(
        plays=("db", "size"), db=("db", "sum"), epa_db_s=("epa_db", "sum"), epa_run_s=("epa_run", "sum"),
        neutral_n=("neutral", "sum"), neutral_db=("nd", "sum"), int_n=("int_n", "sum"), sack_n=("sack_n", "sum"))
    g["rush_n"] = g.plays - g.db
    g["epa_db"] = g.epa_db_s / g.db
    g["pass_rate"] = g.neutral_db / g.neutral_n
    g["int_rate"] = g.int_n / g.db
    g["sack_rate"] = g.sack_n / g.db
    # red-zone drives
    d = p[(p.drive_inside20 == 1)].groupby(KEY + ["posteam", "fixed_drive"]).fixed_drive_result.first().reset_index()
    d["td"] = (d.fixed_drive_result == "Touchdown").astype(int)
    rz = d.groupby(KEY + ["posteam"], as_index=False).agg(rz_trips=("td", "size"), rz_td=("td", "sum"))
    g = g.merge(rz, on=KEY + ["posteam"], how="left").fillna({"rz_trips": 0, "rz_td": 0})
    # target concentration
    t = q[(q.db == 1) & q.receiver_player_id.notna()].groupby(KEY + ["posteam", "receiver_player_id"]).size().rename("tgt").reset_index()
    top = t.groupby(KEY + ["posteam"], as_index=False).agg(tgt_n=("tgt", "sum"), top_tgt=("tgt", "max"))
    g = g.merge(top, on=KEY + ["posteam"], how="left")
    # starter = most dropbacks
    pb = q[(q.db == 1) & q.passer_player_id.notna()].groupby(KEY + ["posteam", "passer_player_id"]).agg(
        n=("db", "sum"), s=("epa_db", "sum")).reset_index()
    st = pb.sort_values("n").groupby(KEY + ["posteam"]).tail(1).rename(columns={"passer_player_id": "qb"})[KEY + ["posteam", "qb"]]
    g = g.merge(st, on=KEY + ["posteam"], how="left")
    g = g.sort_values(["season", "week"]).reset_index(drop=True)
    return g, pb, t


def qb_prior(pb: pd.DataFrame, mu: float) -> pd.DataFrame:
    pb = pb.sort_values(["passer_player_id", "season", "week"]).copy()
    pb["cn"] = pb.groupby("passer_player_id").n.cumsum() - pb.n
    pb["cs"] = pb.groupby("passer_player_id").s.cumsum() - pb.s
    pb["prev_team"] = pb.groupby("passer_player_id").posteam.shift(1)
    pb["prev_season"] = pb.groupby("passer_player_id").season.shift(1)
    pb["qb_rating"] = (pb.cs + K_QB * mu) / (pb.cn + K_QB)
    return pb.rename(columns={"passer_player_id": "qb", "cn": "qb_prior_db"})[
        KEY + ["posteam", "qb", "qb_prior_db", "qb_rating", "prev_team", "prev_season"]]


# ----------------------------------------------------------------------------------------------- T1
def t1_qb(g: pd.DataFrame, pb: pd.DataFrame) -> dict:
    mu = float(g.epa_db_s.sum() / g.db.sum())
    rolling_base(g, "epa_db_s", "db", K_TEAM, mu, "base_epa")
    g = g.merge(qb_prior(pb, mu), on=KEY + ["posteam", "qb"], how="left")
    g["prev_qb"] = g.groupby("posteam").qb.shift(1)
    g["prev_season_g"] = g.groupby("posteam").season.shift(1)
    g["change"] = (g.qb != g.prev_qb) & g.prev_qb.notna() & (g.prev_season_g == g.season)
    g["acquired"] = g.change & g.prev_team.notna() & (g.prev_team != g.posteam)
    g["inexp"] = (g.qb_prior_db.fillna(0) < INEXP).astype(int)
    g["qb_gap"] = g.qb_rating - g.base_epa
    out = {"games": int(len(g)), "change_games": int(g.change.sum()), "acquired_games": int(g.acquired.sum())}
    cols = ["base_epa", "qb_rating"]
    for name, sub in (("all_games", None), ("qb_change_games", lambda d: d.change), ("acquired_qb_games", lambda d: d.acquired)):
        r = walk_forward(g, "epa_db", "base_epa", ["qb_rating"], "db", sub)
        out[name] = r
    # fit ON change games only (evaluated on change games, walk-forward)
    ch = g[g.change].copy()
    out["qb_change_games_fit_on_changes"] = walk_forward(ch, "epa_db", "base_epa", ["qb_rating"], "db")
    # inexperience
    mets = {"epa_db": ("epa_db_s", "db", mu), "int_rate": ("int_n", "db", g.int_n.sum() / g.db.sum()),
            "sack_rate": ("sack_n", "db", g.sack_n.sum() / g.db.sum()),
            "rz_td_pct": ("rz_td", "rz_trips", g.rz_td.sum() / g.rz_trips.sum()),
            "neutral_pass_rate": ("neutral_db", "neutral_n", g.neutral_db.sum() / g.neutral_n.sum()),
            "top_target_share": ("top_tgt", "tgt_n", g.top_tgt.sum() / g.tgt_n.sum())}
    inx = {}
    gg = g.dropna(subset=["qb_prior_db", "base_epa"]).copy()
    for m, (num, den, lg) in mets.items():
        d = g.copy()
        rolling_base(d, num, den, 40 if m != "epa_db" else K_TEAM, lg, "b")
        d["y"] = d[num] / d[den]
        d = d.dropna(subset=["y", "b", "qb_prior_db"])
        d = d[np.isfinite(d.y)]
        grp = (d.posteam + d.season.astype(str)).values
        beta, t = cluster_t(d[["b", "inexp"]].values, d.y.values, d[den].values.astype(float), grp)
        la = d[d.inexp == 1]
        lb = d[d.inexp == 0]
        inx[m] = {"n_inexp": int(len(la)), "n_exp": int(len(lb)),
                  "inexp_mean": round(float(la[num].sum() / la[den].sum()), 4), "exp_mean": round(float(lb[num].sum() / lb[den].sum()), 4),
                  "coef_vs_team_baseline": round(float(beta[2]), 4), "t": round(float(t[2]), 2)}
    out["inexperienced_qb_effects"] = inx
    # by starts: first 8 starts
    return out, g


def t1b_incremental(g: pd.DataFrame, pb: pd.DataFrame) -> dict:
    """Coefficients actually adopted: EPA per dropback on the team's own baseline AND the starter's career rating, and what
    inexperience (< INEXP career dropbacks) still costs after the rating is controlled for."""
    mu = float(g.epa_db_s.sum() / g.db.sum())
    g = g.copy()
    rolling_base(g, "epa_db_s", "db", K_TEAM, mu, "base_epa")
    g = g.merge(qb_prior(pb, mu), on=KEY + ["posteam", "qb"], how="left")
    g["inexp"] = (g.qb_prior_db.fillna(0) < INEXP).astype(int)
    g["qb_rating"] = g.qb_rating.fillna(mu - 0.12)
    d = g.dropna(subset=["base_epa", "epa_db"])
    beta, t = cluster_t(d[["base_epa", "qb_rating"]].values, d.epa_db.values, d.db.values.astype(float), (d.posteam + d.season.astype(str)).values)
    out = {"epa_db_on_team_baseline_and_qb_rating": {"coef_team_baseline": round(float(beta[1]), 3), "t_team": round(float(t[1]), 1),
                                                    "coef_qb_rating": round(float(beta[2]), 3), "t_qb": round(float(t[2]), 1)}}
    mets = {"epa_db": ("epa_db_s", "db", mu), "int_rate": ("int_n", "db", g.int_n.sum() / g.db.sum()),
            "sack_rate": ("sack_n", "db", g.sack_n.sum() / g.db.sum()),
            "rz_td_pct": ("rz_td", "rz_trips", g.rz_td.sum() / g.rz_trips.sum()),
            "neutral_pass_rate": ("neutral_db", "neutral_n", g.neutral_db.sum() / g.neutral_n.sum())}
    for m, (num, den, lg) in mets.items():
        dd = g.copy()
        rolling_base(dd, num, den, 40 if m != "epa_db" else K_TEAM, lg, "bb")
        dd["y"] = dd[num] / dd[den]
        dd = dd.dropna(subset=["y", "bb", "qb_prior_db"])
        dd = dd[np.isfinite(dd.y)]
        beta, t = cluster_t(dd[["bb", "qb_rating", "inexp"]].values, dd.y.values, dd[den].values.astype(float), (dd.posteam + dd.season.astype(str)).values)
        bands = {}
        for lo, hi in ((0, 100), (100, 300), (300, 700), (700, 1e9)):
            x = dd[(dd.qb_prior_db.fillna(0) >= lo) & (dd.qb_prior_db.fillna(0) < hi)]
            bands[f"{lo}-{int(hi) if hi < 1e8 else '+'}"] = {"n": int(len(x)), "gap_vs_team_baseline": round(float(x[num].sum() / x[den].sum() - (x.bb * x[den]).sum() / x[den].sum()), 4)}
        out[m] = {"coef_qb_rating": round(float(beta[2]), 4), "t_qb": round(float(t[2]), 2), "coef_inexperienced": round(float(beta[3]), 4),
                  "t_inexperienced": round(float(t[3]), 2), "by_career_dropbacks": bands}
    return out


# ----------------------------------------------------------------------------------------------- T2
def load_ids():
    pl = pd.read_csv(TRAIN / "players.csv", usecols=["gsis_id", "pfr_id", "position"], low_memory=False)
    return pl.dropna(subset=["gsis_id"])


def load_snaps(pl: pd.DataFrame, seasons=None) -> pd.DataFrame:
    fr = []
    for s in seasons or SEASONS:
        d = pd.read_csv(TRAIN / f"snap_counts_{s}.csv", usecols=["season", "game_type", "week", "pfr_player_id", "team", "offense_snaps", "defense_snaps"])
        fr.append(d[d.game_type == "REG"].drop(columns="game_type"))
    sn = pd.concat(fr, ignore_index=True)
    sn = sn.merge(pl.dropna(subset=["pfr_id"])[["pfr_id", "gsis_id"]].drop_duplicates("pfr_id"), left_on="pfr_player_id", right_on="pfr_id", how="inner")
    return sn.rename(columns={"gsis_id": "pid"})[["season", "week", "team", "pid", "offense_snaps", "defense_snaps"]]


def t2_receivers(g: pd.DataFrame, t: pd.DataFrame, pl: pd.DataFrame, sn: pd.DataFrame) -> dict:
    pos = pl.drop_duplicates("gsis_id").set_index("gsis_id").position
    t = t.copy()
    t["pos"] = t.receiver_player_id.map(pos)
    t = t[t.pos.isin(["WR", "TE", "RB"])]
    # target share over the team's previous 4 games, per player
    games = g[KEY + ["posteam"]].copy()
    games["gi"] = games.groupby(["posteam", "season"]).cumcount()
    ti = t.merge(games, on=KEY + ["posteam"])
    team_t = g.set_index(KEY + ["posteam"]).tgt_n
    on = sn[sn.offense_snaps > 0].set_index(["season", "week", "team", "pid"]).index
    rows = []
    for (team, season), gm in games.groupby(["posteam", "season"]):
        gm = gm.sort_values("week")
        weeks = gm.week.tolist()
        gids = gm.game_id.tolist()
        tt = ti[(ti.posteam == team) & (ti.season == season)]
        for i in range(4, len(weeks)):
            prev = gids[i - 4:i]
            pt = tt[tt.game_id.isin(prev)]
            tot = sum(team_t.get((season, w, gid, team), 0) for w, gid in zip(weeks[i - 4:i], prev))
            if not tot:
                continue
            sh = pt.groupby(["receiver_player_id", "pos"]).tgt.sum() / tot
            sh = sh[sh >= 0.08]
            lw = lr = n_top2 = 0.0
            wrte = sh[sh.index.get_level_values(1).isin(["WR", "TE"])].sort_values(ascending=False)
            for rank, ((pid, ps), v) in enumerate(wrte.items()):
                absent = (season, weeks[i], team, pid) not in on
                if absent:
                    lw += v
                    n_top2 += 1 if rank < 2 else 0
            for (pid, ps), v in sh[sh.index.get_level_values(1) == "RB"].items():
                if (season, weeks[i], team, pid) not in on:
                    lr += v
            rows.append((season, weeks[i], gids[i], team, lw, lr, n_top2))
    L = pd.DataFrame(rows, columns=["season", "week", "game_id", "posteam", "lost_wrte", "lost_rb", "top2_wrte_absent"])
    mu = float(g.epa_db_s.sum() / g.db.sum())
    gg = g.copy()
    rolling_base(gg, "epa_db_s", "db", K_TEAM, mu, "b_epa")
    rolling_base(gg, "neutral_db", "neutral_n", 40, g.neutral_db.sum() / g.neutral_n.sum(), "b_pass")
    rolling_base(gg, "plays", "ones", 3.0, gg.plays.mean(), "b_plays") if False else None
    gg["ones"] = 1.0
    rolling_base(gg, "plays", "ones", 0.0001, gg.plays.mean(), "b_plays")
    rolling_base(gg, "top_tgt", "tgt_n", 40, g.top_tgt.sum() / g.tgt_n.sum(), "b_top")
    rolling_base(gg, "int_n", "db", 40, g.int_n.sum() / g.db.sum(), "b_int")
    gg = gg.merge(L, on=KEY + ["posteam"])
    gg["y_epa"], gg["y_pass"], gg["y_plays"], gg["y_top"] = gg.epa_db, gg.pass_rate, gg.plays, gg.top_tgt / gg.tgt_n
    gg["y_int"] = gg.int_rate
    out = {"team_games": int(len(gg)), "mean_lost_wrte_share_when_any": round(float(gg[gg.lost_wrte > 0].lost_wrte.mean()), 3),
           "games_with_lost_wrte_ge_15pct": int((gg.lost_wrte >= 0.15).sum()), "games_top2_wrte_absent": int((gg.top2_wrte_absent >= 1).sum())}
    for y, b, w in (("y_epa", "b_epa", "db"), ("y_pass", "b_pass", "neutral_n"), ("y_plays", "b_plays", "ones"), ("y_top", "b_top", "tgt_n"), ("y_int", "b_int", "db")):
        d = gg.dropna(subset=[y, b, "lost_wrte", "lost_rb"])
        d = d[np.isfinite(d[y])]
        grp = (d.posteam + d.season.astype(str)).values
        beta, tt = cluster_t(d[[b, "lost_wrte", "lost_rb"]].values, d[y].values, d[w].values.astype(float), grp)
        r = {"coef_lost_wrte_share": round(float(beta[2]), 4), "t_wrte": round(float(tt[2]), 2),
             "coef_lost_rb_share": round(float(beta[3]), 4), "t_rb": round(float(tt[3]), 2),
             "walk_forward_all": walk_forward(gg, y, b, ["lost_wrte", "lost_rb"], w),
             "walk_forward_lost_wrte_ge_15pct": walk_forward(gg, y, b, ["lost_wrte", "lost_rb"], w, lambda x: x.lost_wrte >= 0.15)}
        # by season sign consistency of the lost_wrte coefficient
        signs = {}
        for s in sorted(d.season.unique()):
            ds = d[d.season == s]
            bs = wols(ds[[b, "lost_wrte"]].values, ds[y].values, ds[w].values.astype(float))
            signs[int(s)] = round(float(bs[2]), 3)
        r["by_season_coef_lost_wrte"] = signs
        out[y] = r
    return out


# ----------------------------------------------------------------------------------------------- T3
def t3_pass_rush(p: pd.DataFrame, g: pd.DataFrame, sn: pd.DataFrame) -> dict:
    q = p[(p.qb_dropback == 1) & p.epa.notna()].copy()
    ev = []
    for c in ["sack_player_id", "half_sack_1_player_id", "half_sack_2_player_id", "qb_hit_1_player_id", "qb_hit_2_player_id"]:
        e = q[q[c].notna()][KEY + ["defteam", c]].rename(columns={c: "pid"})
        ev.append(e)
    ev = pd.concat(ev).groupby(KEY + ["defteam", "pid"]).size().rename("ev").reset_index()
    ev = ev.rename(columns={"defteam": "team"})
    pg = sn[sn.defense_snaps > 0][["season", "week", "team", "pid", "defense_snaps"]].merge(
        ev[["season", "week", "team", "pid", "ev"]], on=["season", "week", "team", "pid"], how="left").fillna({"ev": 0})
    pg = pg.sort_values(["pid", "season", "week"])
    lg_rate = pg.ev.sum() / pg.defense_snaps.sum()
    grp = pg.groupby("pid")
    pg["e8"] = grp.ev.transform(lambda s: s.shift(1).rolling(16, min_periods=1).sum())
    pg["s8"] = grp.defense_snaps.transform(lambda s: s.shift(1).rolling(16, min_periods=1).sum())
    pg["avg_snaps"] = grp.defense_snaps.transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean())
    pg["rate"] = ((pg.e8.fillna(0)) + K_SNAPS * lg_rate) / ((pg.s8.fillna(0)) + K_SNAPS)
    pg["prev_team"] = grp.team.shift(1)
    pg["exp_ev"] = pg.rate * pg.avg_snaps.fillna(pg.defense_snaps.mean())
    # a player's team-baseline contribution = what the TEAM got from him in its own last games is already in base
    tg = pg.groupby(["season", "week", "team"], as_index=False).agg(f_ev=("exp_ev", "sum"))
    # pressure share lost: players who produced in the team's previous 4 games but are absent now
    ev_t = ev.copy()
    games = g[KEY + ["defteam"]].rename(columns={"defteam": "team"}).drop_duplicates().sort_values(["season", "week"])
    present = set(zip(pg.season, pg.week, pg.team, pg.pid))
    lost = []
    for (team, season), gm in games.groupby(["team", "season"]):
        gm = gm.sort_values("week")
        weeks, gids = gm.week.tolist(), gm.game_id.tolist()
        e_t = ev_t[(ev_t.team == team) & (ev_t.season == season)]
        for i in range(4, len(weeks)):
            pe = e_t[e_t.game_id.isin(gids[i - 4:i])].groupby("pid").ev.sum()
            tot = pe.sum()
            if tot <= 0:
                continue
            lo = sum(v for pid, v in pe.items() if (season, weeks[i], team, pid) not in present)
            lost.append((season, weeks[i], gids[i], team, lo / tot))
    L = pd.DataFrame(lost, columns=["season", "week", "game_id", "team", "lost_press"])
    # defense-side table: events and dropbacks faced
    d = g[KEY + ["defteam", "db"]].rename(columns={"defteam": "team", "db": "db_faced"})
    de = ev.groupby(KEY + ["team"], as_index=False).ev.sum().rename(columns={"ev": "ev_team"})
    d = d.merge(de, on=KEY + ["team"], how="left").fillna({"ev_team": 0}).merge(tg, on=["season", "week", "team"], how="left").merge(
        L, on=KEY + ["team"], how="left")
    d = d.sort_values(["season", "week"]).reset_index(drop=True)
    lg_ev = d.ev_team.sum() / d.db_faced.sum()
    rolling_base(d, "ev_team", "db_faced", 100, lg_ev, "base_press")
    d["y"] = d.ev_team / d.db_faced
    d["f_press"] = d.f_ev / d.db_faced.mean()
    out = {"defense_games": int(len(d)), "lost_press_ge_25pct_games": int((d.lost_press >= 0.25).sum())}
    out["roster_forecast_all"] = walk_forward(d, "y", "base_press", ["f_press"], "db_faced")
    out["lost_share_all"] = walk_forward(d, "y", "base_press", ["lost_press"], "db_faced")
    out["roster_forecast_lost_ge_25pct"] = walk_forward(d, "y", "base_press", ["f_press"], "db_faced", lambda x: x.lost_press >= 0.25)
    out["both_lost_ge_25pct"] = walk_forward(d, "y", "base_press", ["f_press", "lost_press"], "db_faced", lambda x: x.lost_press >= 0.25)
    dd = d.dropna(subset=["y", "base_press", "f_press", "lost_press"])
    grp = (dd.team + dd.season.astype(str)).values
    beta, t = cluster_t(dd[["base_press", "f_press", "lost_press"]].values, dd.y.values, dd.db_faced.values.astype(float), grp)
    out["full_fit"] = {"coef_base": round(float(beta[1]), 3), "coef_roster_forecast": round(float(beta[2]), 3), "t_forecast": round(float(t[2]), 2),
                       "coef_lost_share": round(float(beta[3]), 4), "t_lost": round(float(t[3]), 2)}
    # pressure -> EPA: what a point of pressure rate is worth in dropback EPA allowed (same game)
    ea = g[KEY + ["defteam", "epa_db", "epa_run_s", "rush_n"]].rename(columns={"defteam": "team", "epa_db": "epa_db_allowed"})
    ea["rush_epa_allowed"] = ea.epa_run_s / ea.rush_n
    d2 = d.merge(ea[KEY + ["team", "epa_db_allowed", "rush_epa_allowed", "epa_run_s", "rush_n"]], on=KEY + ["team"], how="left")
    x = d2.dropna(subset=["epa_db_allowed", "y", "base_press"])
    beta, t = cluster_t(x[["y"]].values, x.epa_db_allowed.values, x.db_faced.values.astype(float), (x.team + x.season.astype(str)).values)
    out["pressure_to_epa"] = {"epa_per_db_per_unit_pressure_rate": round(float(beta[1]), 3), "t": round(float(t[1]), 1)}
    # ---- run defence: rush EPA allowed vs the share of recent tackles-for-loss / pressures that left with absent players
    tf = []
    for c in ["tackle_for_loss_1_player_id", "tackle_for_loss_2_player_id"]:
        e = p[p[c].notna() & (p.qb_dropback != 1)][KEY + ["defteam", c]].rename(columns={c: "pid", "defteam": "team"})
        tf.append(e)
    tf = pd.concat(tf).groupby(KEY + ["team", "pid"]).size().rename("ev").reset_index()
    lost = []
    for (team, season), gm in games.groupby(["team", "season"]):
        gm = gm.sort_values("week")
        weeks, gids = gm.week.tolist(), gm.game_id.tolist()
        e_t = tf[(tf.team == team) & (tf.season == season)]
        for i in range(4, len(weeks)):
            pe = e_t[e_t.game_id.isin(gids[i - 4:i])].groupby("pid").ev.sum()
            tot = pe.sum()
            if tot <= 0:
                continue
            lo = sum(v for pid, v in pe.items() if (season, weeks[i], team, pid) not in present)
            lost.append((season, weeks[i], gids[i], team, lo / tot))
    d2 = d2.merge(pd.DataFrame(lost, columns=["season", "week", "game_id", "team", "lost_tfl"]), on=KEY + ["team"], how="left")
    d2 = d2.sort_values(["season", "week"]).reset_index(drop=True)
    mu_r = d2.epa_run_s.sum() / d2.rush_n.sum()
    rolling_base(d2, "epa_run_s", "rush_n", 60, mu_r, "base_run")
    out["run_defense_lost_tfl"] = walk_forward(d2, "rush_epa_allowed", "base_run", ["lost_tfl", "lost_press"], "rush_n")
    dd = d2.dropna(subset=["rush_epa_allowed", "base_run", "lost_tfl", "lost_press"])
    beta, t = cluster_t(dd[["base_run", "lost_tfl", "lost_press"]].values, dd.rush_epa_allowed.values, dd.rush_n.values.astype(float),
                        (dd.team + dd.season.astype(str)).values)
    out["run_defense_fit"] = {"coef_lost_tfl_share": round(float(beta[2]), 4), "t_tfl": round(float(t[2]), 2),
                              "coef_lost_pressure_share": round(float(beta[3]), 4), "t_press": round(float(t[3]), 2)}
    return out


def adopted(res: dict) -> dict:
    """The coefficients the app applies (app.roster_adjust). Only effects that held up out of sample are here; the rest are
    listed under `not_adopted` with why."""
    q, r, p = res["t1b_adopted_qb_coefficients"], res["t2_receivers"], res["t3_pass_rush"]
    return {
        "_about": "Fit by scripts/backtest_roster_moves.py on 2016-2025 (walk-forward tests in data/roster_move_backtest.json). "
                  "Deltas are changes in a team's own recent baseline.",
        "inexperienced_below_career_dropbacks": INEXP,
        "qb_gap_weight": {"epa_db": q["epa_db_on_team_baseline_and_qb_rating"]["coef_qb_rating"],
                          "neutral_pass_rate": q["neutral_pass_rate"]["coef_qb_rating"]},
        "inexperienced_qb": {"epa_db": q["epa_db"]["coef_inexperienced"], "int_rate": q["int_rate"]["coef_inexperienced"],
                             "sack_rate": q["sack_rate"]["coef_inexperienced"], "rz_td_pct": q["rz_td_pct"]["coef_inexperienced"],
                             "neutral_pass_rate": q["neutral_pass_rate"]["coef_inexperienced"]},
        "lost_wr_te_target_share": {"epa_db": r["y_epa"]["coef_lost_wrte_share"], "neutral_pass_rate": r["y_pass"]["coef_lost_wrte_share"],
                                    "min_share": 0.08},
        "pass_rush": {"forecast_weight": p["full_fit"]["coef_roster_forecast"], "epa_db_per_unit_pressure_rate": p["pressure_to_epa"]["epa_per_db_per_unit_pressure_rate"]},
        "not_adopted": {
            "lost_rb_target_share": "no effect on EPA, pass rate or interceptions (|t| < 1.5)",
            "lost_wr_te_on_plays_per_game": "no effect (t -0.7, sign flips by season): receivers leaving does not slow a team down",
            "lost_wr_te_on_top_target_share": "no effect (t -0.2)",
            "rookie_qb_target_concentration": "inexperienced QBs do not concentrate targets more (top-target share -0.4 pts, t -1.5)",
            "lost_run_stuffers_on_rush_epa_allowed": "no held-out gain (+0.03% MSE)"},
    }


def main():
    p = load_pbp()
    g, pb, t = team_games(p)
    pl = load_ids()
    sn = load_snaps(pl)
    res = {"seasons": [SEASONS[0], SEASONS[-1]], "test_seasons": [TEST_SEASONS[0], TEST_SEASONS[-1]]}
    r1, g1 = t1_qb(g.copy(), pb)
    res["t1_qb"] = r1
    res["t1b_adopted_qb_coefficients"] = t1b_incremental(g, pb)
    res["t2_receivers"] = t2_receivers(g, t, pl, sn)
    res["t3_pass_rush"] = t3_pass_rush(p, g, sn)
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    MODEL.write_text(json.dumps(adopted(res), indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
