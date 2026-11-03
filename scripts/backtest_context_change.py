"""Does knowing who is actually playing improve on a team's plain season-to-date rating?

For every team-game we weight the team's PRIOR games that season by how similar the starting lineup was (share of
the current top-11 offensive / defensive snap-getters who also started that game; weight = similarity ** POWER).
The context adjustment is (lineup-weighted EPA/play - plain EPA/play), per unit, shrunk toward 0. Converted to points
(x ~62 plays) and summed for both teams, it is tested against how the game finished relative to the CLOSING total and
spread: if the market already prices who is playing, the slope will be ~0.

LINEUP modes: "known" = the lineup that actually played that game (what the Sunday inactives list would give you, with
a little hindsight from in-game injuries); "last" = last game's lineup (a no-news proxy); "report" = last 3 games' snap leaders minus players Out/Doubtful on this
week's injury report (known before kickoff, no hindsight); "active" = the game-day active list (ACT status) plus the report,
ranked by recent per-game snaps so returning starters are included (known ~90 minutes before kickoff; the version to trust).
Needs pandas (analysis only). Data: data/cache/train/play_by_play_YYYY.csv.gz, games.csv, snap_counts_YYYY.csv
(download: https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_YYYY.csv).
    python -m scripts.backtest_context_change
Writes data/context_change_backtest.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

TRAIN = Path(__file__).resolve().parents[1] / "data" / "cache" / "train"
OUT = Path(__file__).resolve().parents[1] / "data" / "context_change_backtest.json"
SEASONS = list(range(2016, 2026))
MIN_WEEK = 5
POWER = 4
SHRINK_GAMES = 3          # pseudo-games of "no adjustment"
PLAYS = 62


def unit_epa() -> pd.DataFrame:
    rows = []
    for s in SEASONS:
        p = pd.read_csv(TRAIN / f"play_by_play_{s}.csv.gz", low_memory=False,
                        usecols=["season_type", "week", "posteam", "defteam", "play_type", "epa"])
        p = p[(p.season_type == "REG") & p.play_type.isin(["pass", "run"]) & p.epa.notna()]
        g = p.groupby(["week", "posteam", "defteam"]).epa.mean().reset_index()
        g["season"] = s
        rows.append(g)
    d = pd.concat(rows).rename(columns={"posteam": "team", "defteam": "opp", "epa": "off_epa"})
    d["def_epa"] = d.merge(d[["season", "week", "team", "off_epa"]].rename(columns={"team": "opp", "off_epa": "opp_off"}),
                           on=["season", "week", "opp"], how="left").opp_off.values     # EPA this team's defense allowed
    return d


def lineups() -> dict:
    """(season, week, team) -> {"off": set(top 11 offensive snappers), "def": set(top 11 defensive snappers)}."""
    out = {}
    for s in SEASONS:
        f = TRAIN / f"snap_counts_{s}.csv"
        if not f.exists():
            continue
        sc = pd.read_csv(f)
        sc = sc[sc.game_type == "REG"].copy()
        sc["key"] = sc.player.map(norm)
        for (w, t), g in sc.groupby(["week", "team"]):
            out[(s, int(w), t)] = {"off": set(g.nlargest(11, "offense_snaps").key), "def": set(g.nlargest(11, "defense_snaps").key),
                                   "snaps": {k: (o, d) for k, o, d in zip(g.key, g.offense_snaps, g.defense_snaps)}}
    return out


def norm(name) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def reported_out() -> dict:
    """(season, week, team) -> normalized names listed Out or Doubtful on that week's injury report (known before kickoff)."""
    out = {}
    for s in SEASONS:
        f = TRAIN / f"injuries_{s}.csv"
        if not f.exists():
            continue
        d = pd.read_csv(f)
        d = d[(d.game_type == "REG") & d.report_status.isin(["Out", "Doubtful"])]
        for (w, t), g in d.groupby(["week", "team"]):
            out[(s, int(w), t)] = {norm(n) for n in g.full_name}
    return out


def active_lists() -> dict:
    """(season, week, team) -> normalized names with roster status ACT that week (the game-day active list: inactives, IR and
    practice-squad players are not ACT). Announced ~90 minutes before kickoff."""
    out = {}
    for s in SEASONS:
        f = TRAIN / f"roster_weekly_{s}.csv"
        if not f.exists():
            continue
        d = pd.read_csv(f, usecols=["season", "team", "week", "status", "full_name", "game_type"], low_memory=False)
        d = d[(d.game_type == "REG") & (d.status == "ACT")]
        for (w, t), g in d.groupby(["week", "team"]):
            out[(s, int(w), t)] = {norm(n) for n in g.full_name}
    return out


def active_lineup(lu: dict, outs: dict, actives: dict, season: int, week: int, team: str, unit: str):
    """Expected lineup from everything known on game day: who is ACTIVE (not inactive/IR) and not Out/Doubtful on the report,
    ranked by their average snaps in the games they played over the last 6 (so a returning starter counts, a bench player does not)."""
    act = actives.get((season, week, team))
    if not act:
        return None
    games = [lu[(season, w, team)] for w in range(week - 1, 0, -1) if (season, w, team) in lu][:6]
    idx = 0 if unit == "off" else 1
    played: dict[str, list[float]] = {}
    for g in games:
        for k, v in g["snaps"].items():
            if v[idx] > 0:
                played.setdefault(k, []).append(v[idx])
    gone = outs.get((season, week, team), set())
    cand = {k: float(np.mean(v)) for k, v in played.items() if k in act and k not in gone and len(v) >= 2}
    if len(cand) < 11:
        return None
    return set(sorted(cand, key=lambda k: -cand[k])[:11])


def pregame_lineup(lu: dict, outs: dict, season: int, week: int, team: str, unit: str):
    """No-hindsight expected lineup: the top 11 by average snaps over the last 3 games, minus anyone Out/Doubtful this week."""
    games = [lu[(season, w, team)] for w in range(week - 1, 0, -1) if (season, w, team) in lu][:3]
    if not games:
        return None
    idx = 0 if unit == "off" else 1
    tot: dict[str, float] = {}
    for g in games:
        for k, v in g["snaps"].items():
            tot[k] = tot.get(k, 0.0) + v[idx]
    gone = outs.get((season, week, team), set())
    ranked = sorted((k for k in tot if k not in gone), key=lambda k: -tot[k])
    return set(ranked[:11])


def adjustment(unit: str, col: str, team: str, season: int, week: int, target, hist: pd.DataFrame, lu: dict) -> float:
    prior = hist[(hist.season == season) & (hist.team == team) & (hist.week < week)]
    if len(prior) < 3 or not target:
        return 0.0
    sims, vals = [], []
    for _, r in prior.iterrows():
        l = lu.get((season, int(r.week), team))
        if not l:
            continue
        sims.append(len(target & l[unit]) / 11.0)
        vals.append(r[col])
    if len(vals) < 3:
        return 0.0
    w = np.array(sims) ** POWER
    if w.sum() == 0:
        return 0.0
    weighted, plain = float((w * vals).sum() / w.sum()), float(np.mean(vals))
    shrink = len(vals) / (len(vals) + SHRINK_GAMES)
    return (weighted - plain) * shrink


def fit(x: np.ndarray, y: np.ndarray) -> dict:
    n = len(x)
    if n < 30 or x.std() == 0:
        return {"n": n}
    slope, icpt = np.polyfit(x, y, 1)
    resid = y - (slope * x + icpt)
    se = np.sqrt(resid.var(ddof=2) / ((x - x.mean()) ** 2).sum())
    return {"n": n, "slope": round(float(slope), 3), "t": round(float(slope / se), 2), "sd_x_pts": round(float(x.std()), 2)}


def main() -> None:
    hist = unit_epa()
    lu = lineups()
    outs = reported_out()
    actives = active_lists()
    games = pd.read_csv(TRAIN / "games.csv")
    games = games[(games.game_type == "REG") & games.season.isin(SEASONS) & (games.week >= MIN_WEEK)].dropna(subset=["total_line", "spread_line", "result"])
    rows = []
    for mode in ("known", "last", "report", "active"):
        for _, g in games.iterrows():
            eff = {}
            for team, opp in ((g.away_team, g.home_team), (g.home_team, g.away_team)):
                def target(t, unit):
                    if mode == "active":
                        return active_lineup(lu, outs, actives, g.season, g.week, t, unit)
                    if mode == "report":
                        return pregame_lineup(lu, outs, g.season, g.week, t, unit)
                    wk = g.week if mode == "known" else g.week - 1
                    for w in range(wk, 0, -1):
                        l = lu.get((g.season, w, t))
                        if l:
                            return l[unit]
                    return None
                d_off = adjustment("off", "off_epa", team, g.season, g.week, target(team, "off"), hist, lu)
                d_def = adjustment("def", "def_epa", opp, g.season, g.week, target(opp, "def"), hist, lu)
                eff[team] = (d_off + d_def) * PLAYS          # points above the plain rating this offense should score
            rows.append(dict(mode=mode, season=g.season, away=eff[g.away_team], home=eff[g.home_team],
                             vs_total=g.total - g.total_line, vs_spread=g.result - g.spread_line))
    df = pd.DataFrame(rows)
    report = {}
    for mode, m in df.groupby("mode"):
        x_tot = (m.away + m.home).to_numpy()
        x_spr = (m.home - m.away).to_numpy()
        res = {"total": fit(x_tot, m.vs_total.to_numpy()), "spread": fit(x_spr, m.vs_spread.to_numpy())}
        big = m[(m.away + m.home).abs() >= 1.5]
        if len(big):
            hit = (np.sign(big.away + big.home) == np.sign(big.vs_total))[big.vs_total != 0]
            res["total_hit_rate_when_abs_adj_ge_1.5"] = dict(n=int(len(hit)), pct=round(100 * float(hit.mean()), 1))
        bigs = m[(m.home - m.away).abs() >= 1.5]
        if len(bigs):
            hit = (np.sign(bigs.home - bigs.away) == np.sign(bigs.vs_spread))[bigs.vs_spread != 0]
            res["spread_hit_rate_when_abs_adj_ge_1.5"] = dict(n=int(len(hit)), pct=round(100 * float(hit.mean()), 1))
        res["by_season_total_slope"] = {int(s): fit((g.away + g.home).to_numpy(), g.vs_total.to_numpy()).get("slope") for s, g in m.groupby("season")}
        report[mode] = res
    OUT.write_text(json.dumps(report, indent=1, default=float))
    print(json.dumps(report, indent=1, default=float))


if __name__ == "__main__":
    main()
