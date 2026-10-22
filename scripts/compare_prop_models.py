"""Backtest a proposed "4 pillars" algorithm against the app's current model, for player props, prop ladders and
DFS plays.

    python -m scripts.compare_prop_models [--data DIR]

The proposal (as written): receiving yards = projected targets x catch rate x aDOT x YAC expectation x pace
multiplier, with WOPR = 1.5 x target share + 0.7 x air-yards share, pace = (team plays / 62) x (1 + PROE); a prop
"over" when the projection beats the line by 12%+; the RACR buy signal (high WOPR, RACR under 0.55); lognormal
outcome distributions for ladders; and a DFS ceiling score = (0.1 x yards + receptions + 0.8 x 6 x end-zone
targets) per $1K of salary, flagged when it's in the top 15% of its salary tier and the prop edge is 12%+.

The app's current model: Sleeper's projected stat line corrected by the role & script model (app.player_model),
the 85th-percentile ceiling model (app.ceiling_model), two-piece normal outcome distributions
(app.field_ownership), and GPP plays ranked mostly on ceiling per $1K (app.play_rankings).

Data (no proprietary sources): nflverse weekly player and team stats, 2026 and 2025 play-by-play (end-zone
targets), Sleeper's weekly projections, closing lines, and this season's DraftKings Sunday main-slate salaries
(DraftKings' draftables API, by the draft group ids in data/optimal_lineups.json).

Limits, stated up front: there are no historical sportsbook player-prop lines here, so "prop" tests use two
stand-in lines -- Sleeper's projected stat line (a market-like median) and the trailing 3-game average (what the
proposal says books post). Route data (routes run, TPRR) isn't public, so it isn't used. The app's current
correction was fit on 2023-2025, so it's only out-of-sample on 2026.

Writes data/prop_model_comparison.json.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import special, stats as sps

from app import ceiling_model as cm, player_model as pm, projections
from scripts import train_ceiling_model as tcm
from scripts import train_player_model as tpm
from scripts.train_game_model import REL, fetch

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "prop_model_comparison.json"
SEASONS = (2023, 2024, 2025, 2026)
TRAIN, TEST = (2023, 2024), (2025, 2026)          # distribution widths are fit on TRAIN, graded on TEST
RECEIVERS = ("WR", "TE", "RB")
LADDER = (25, 50, 75, 100)
EDGE = 0.12
TIERS = ((0, 4500), (4500, 6000), (6000, 7500), (7500, 99999))
TOP_K = {"WR": 12, "TE": 5, "RB": 8}


def f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------- inputs
def stat_rows(d: Path, year: int) -> list[dict]:
    path = fetch(f"{REL}/stats_player/stats_player_week_{year}.csv", d / f"stats_player_week_{year}.csv")
    return [s for s in csv.DictReader(open(path, newline="")) if s.get("season_type", "REG") == "REG"]


def team_rows(d: Path, year: int) -> list[dict]:
    path = fetch(f"{REL}/stats_team/stats_team_week_{year}.csv", d / f"stats_team_week_{year}.csv")
    return [s for s in csv.DictReader(open(path, newline="")) if s.get("season_type", "REG") == "REG"]


def endzone_targets(d: Path, year: int) -> dict[tuple[int, str], int]:
    """{(week, player_id): targets whose air yards reached the end zone} from nflverse play-by-play."""
    path = fetch(f"{REL}/pbp/play_by_play_{year}.csv.gz", d / f"play_by_play_{year}.csv.gz")
    out: dict[tuple[int, str], int] = defaultdict(int)
    with gzip.open(path, "rt", newline="") as fh:
        for p in csv.DictReader(fh):
            if p.get("season_type") != "REG" or p.get("pass_attempt") != "1" or not p.get("receiver_player_id"):
                continue
            ay, yl = f(p.get("air_yards")), f(p.get("yardline_100"))
            if p.get("air_yards") and p.get("yardline_100") and ay >= yl:
                out[(int(p["week"]), p["receiver_player_id"])] += 1
    return out


def proposed_inputs(stats_by_key, team_games, ez, key: str, season: int, week: int) -> dict | None:
    """The proposal's components from the player's last 4 regular-season games before (season, week)."""
    past = [r for r in stats_by_key.get(key, []) if (int(r["season"]), int(r["week"])) < (season, week)][-4:]
    if len(past) < 2:
        return None
    tg = sum(f(r["targets"]) for r in past)
    rec = sum(f(r["receptions"]) for r in past)
    yds = sum(f(r["receiving_yards"]) for r in past)
    air = sum(f(r["receiving_air_yards"]) for r in past)
    n = len(past)
    ts = statistics.fmean(f(r["target_share"]) for r in past)
    ays = statistics.fmean(f(r["air_yards_share"]) for r in past)
    team = past[-1]["team"]
    tgames = [g for g in team_games.get(team, []) if (g[0], g[1]) < (season, week)][-4:]
    plays = statistics.fmean(g[2] for g in tgames) if tgames else 62.0
    pass_rate = statistics.fmean(g[3] for g in tgames) if tgames else 0.58
    catch = rec / tg if tg else 0.0
    adot = air / tg if tg else 0.0
    ypt = yds / tg if tg else 0.0
    ez_pg = sum(ez.get((int(r["season"]), int(r["week"]), r["player_id"]), 0) for r in past) / n
    return {
        "proj_targets": tg / n, "catch_rate": catch, "adot": adot,
        # YAC expectation as the multiplier that turns catch rate x aDOT into yards per target (trailing)
        "yac_mult": ypt / (catch * adot) if catch and adot else 1.0,
        "ypt": ypt, "racr": yds / air if air > 0 else None, "wopr": 1.5 * ts + 0.7 * ays,
        "team_plays": plays, "proe": pass_rate - LEAGUE_PASS_RATE, "ez_targets": ez_pg,
        "l3_yards": statistics.fmean(f(r["receiving_yards"]) for r in past[-3:]),
    }


LEAGUE_PASS_RATE = 0.58


def proposed_yards(x: dict) -> float:
    pace = (x["team_plays"] / 62.0) * (1.0 + x["proe"])
    return x["proj_targets"] * x["catch_rate"] * x["adot"] * x["yac_mult"] * pace


def proposed_dfs_score(x: dict, salary: float) -> float:
    yards = proposed_yards(x)
    return (yards * 0.1 + x["proj_targets"] * x["catch_rate"] * 1.0 + x["ez_targets"] * 0.8 * 6.0) / (salary / 1000.0)


# ---------------------------------------------------------- distributions
def two_piece_fit(resid: list[float]) -> tuple[float, float]:
    """sd_low / sd_high of a two-piece normal from residual quantiles (15th / 85th), as app.field_ownership uses."""
    q15, q50, q85 = np.quantile(resid, [0.15, 0.5, 0.85])
    return max((q50 - q15) / 1.0364, 1.0), max((q85 - q50) / 1.0364, 1.0)


def p_two_piece(t: float, center: float, lo: float, hi: float) -> float:
    sd = hi if t >= center else lo
    return float(1 - special.ndtr((t - center) / sd))


def p_lognormal(t: float, median: float, sigma: float, shift: float = 5.0) -> float:
    return float(1 - sps.norm.cdf((math.log(t + shift) - math.log(max(median, 0.0) + shift)) / sigma))


def brier(ps, ys) -> float:
    return float(np.mean((np.array(ps) - np.array(ys)) ** 2))


def logloss(ps, ys) -> float:
    p = np.clip(np.array(ps), 1e-4, 1 - 1e-4)
    y = np.array(ys)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


# -------------------------------------------------------------- the tests
def hit_rates(rows, model_key: str, line_key: str, edge: float) -> dict:
    over = [r for r in rows if r[line_key] > 0 and (r[model_key] - r[line_key]) / r[line_key] > edge]
    under = [r for r in rows if r[line_key] > 0 and (r[model_key] - r[line_key]) / r[line_key] < -edge]
    o = [r["actual_yd"] > r[line_key] for r in over if r["actual_yd"] != r[line_key]]
    u = [r["actual_yd"] < r[line_key] for r in under if r["actual_yd"] != r[line_key]]
    both = o + u
    return {"overs": len(o), "over_hit": round(sum(o) / len(o), 3) if o else None,
            "unders": len(u), "under_hit": round(sum(u) / len(u), 3) if u else None,
            "picks": len(both), "hit": round(sum(both) / len(both), 3) if both else None,
            # the share of picks a -110 bettor needs is 52.4%
            "z_vs_52_4": round((sum(both) / len(both) - 0.524) / math.sqrt(0.524 * 0.476 / len(both)), 2) if both else None}


def accuracy(rows, key: str) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["season"], r["week"], r["pos"])].append((r[key], r["actual_yd"]))
    rho = statistics.fmean(tpm.spearman([a for a, _ in v], [b for _, b in v]) for v in groups.values() if len(v) >= 8)
    return {"mae": round(statistics.fmean(abs(r[key] - r["actual_yd"]) for r in rows), 2),
            "bias": round(statistics.fmean(r[key] - r["actual_yd"] for r in rows), 2), "rank_rho": round(rho, 3)}


def draftables(d: Path, group: int) -> list[dict]:
    path = d / f"dk_draftables_{group}.json"
    if not path.exists():     # curl: DraftKings' edge refuses Python HTTP clients from here
        subprocess.run(["curl", "-sSf", "-o", str(path), f"https://api.draftkings.com/draftgroups/v1/draftgroups/{group}/draftables"],
                       check=True, timeout=120)
    return json.loads(path.read_text()).get("draftables", [])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    args = ap.parse_args()
    d = Path(args.data)
    d.mkdir(parents=True, exist_ok=True)

    global LEAGUE_PASS_RATE
    stats_all = {y: stat_rows(d, y) for y in (SEASONS[0] - 1, *SEASONS)}
    stats_by_key: dict[str, list[dict]] = defaultdict(list)
    actual_by: dict[tuple[int, int, str], dict] = {}
    for y, rows in stats_all.items():
        for s in rows:
            k = pm.key(s["player_display_name"], s["position"])
            stats_by_key[k].append(s)
            actual_by[(y, int(s["week"]), k)] = s
    for k in stats_by_key:
        stats_by_key[k].sort(key=lambda s: (int(s["season"]), int(s["week"])))
    team_games: dict[str, list] = defaultdict(list)
    rates = []
    for y in (SEASONS[0] - 1, *SEASONS):
        for t in team_rows(d, y):
            att, car, sk = f(t["attempts"]), f(t["carries"]), f(t["sacks_suffered"])
            if att + car:
                team_games[t["team"]].append((y, int(t["week"]), att + car + sk, (att + sk) / (att + car + sk)))
                rates.append((att + sk) / (att + car + sk))
    LEAGUE_PASS_RATE = statistics.fmean(rates)
    for t in team_games:
        team_games[t].sort()
    ez: dict[tuple[int, int, str], int] = {}
    for y in (2025, 2026):
        for (w, pid), n in endzone_targets(d, y).items():
            ez[(y, w, pid)] = n
    last_week_2026 = max(int(s["week"]) for s in stats_all[2026])

    # Player-weeks: the ceiling trainer's rows (Sleeper line, the app's corrected projection, history), receivers only.
    rows = []
    for y in SEASONS:
        weeks = range(2, (last_week_2026 if y == 2026 else 18) + 1)
        for r in tcm.rows_for(d, y, weeks):
            if r["pos"] not in RECEIVERS:
                continue
            line_yd = f(r["line"].get("rec_yd"))
            act = actual_by.get((y, r["week"], r["key"]))
            x = proposed_inputs(stats_by_key, team_games, ez, r["key"], y, r["week"])
            if line_yd < 15 or not act or not x:
                continue
            corrected_pts = r["proj"]          # Sleeper's DK projection plus the app's correction (app.player_model)
            raw_pts = sleeper_points(r)
            rows.append({
                "season": y, "week": r["week"], "key": r["key"], "pos": r["pos"], "player_id": act["player_id"],
                "actual_yd": f(act["receiving_yards"]), "actual_pts": r["actual"],
                "sleeper_yd": line_yd, "l3_yd": x["l3_yards"], "proposed_yd": proposed_yards(x),
                # the app's correction (DK points) carried proportionally to yards
                "current_yd": line_yd * (corrected_pts / raw_pts if raw_pts else 1.0),
                "x": x, "ceiling_row": r,
            })
    print(f"{len(rows)} receiver-weeks with a Sleeper receiving line of 15+ yards")

    result: dict = {"seasons": list(SEASONS), "receiver_weeks": len(rows), "edge_threshold": EDGE}

    # 1. Projection accuracy (receiving yards)
    result["accuracy"] = {}
    for label, sel in (("2025", [r for r in rows if r["season"] == 2025]), ("2026", [r for r in rows if r["season"] == 2026]),
                       ("2023-2024", [r for r in rows if r["season"] in TRAIN])):
        result["accuracy"][label] = {m: accuracy(sel, f"{m}_yd") for m in ("sleeper", "l3", "proposed", "current")}

    # 2. Prop picks vs the two stand-in lines
    result["props"] = {}
    for line in ("sleeper_yd", "l3_yd"):
        result["props"][line] = {}
        for season_label, sel in (("2023-2026", rows), ("2026", [r for r in rows if r["season"] == 2026])):
            result["props"][line][season_label] = {
                m: {f"edge_{int(e * 100)}": hit_rates(sel, f"{m}_yd", line, e) for e in (0.05, EDGE)}
                for m in ("proposed", "current", "sleeper", "l3") if f"{m}_yd" != line}
    # RACR buy signal: high WOPR, depressed RACR -> the over
    sig = []
    for r in rows:
        x = r["x"]
        if x["racr"] is not None and x["wopr"] >= 0.55 and x["racr"] < 0.55:
            sig.append(r)
    result["racr_signal"] = {
        line: {"n": len([r for r in sig if r["actual_yd"] != r[line]]),
               "over_hit": round(statistics.fmean(r["actual_yd"] > r[line] for r in sig if r["actual_yd"] != r[line]), 3) if sig else None}
        for line in ("sleeper_yd", "l3_yd")}
    # quartile version: top-quartile WOPR and bottom-quartile RACR among receivers
    wq = np.quantile([r["x"]["wopr"] for r in rows], 0.75)
    rq = np.quantile([r["x"]["racr"] for r in rows if r["x"]["racr"] is not None], 0.25)
    sig_q = [r for r in rows if r["x"]["racr"] is not None and r["x"]["wopr"] >= wq and r["x"]["racr"] <= rq]
    result["racr_signal_quartiles"] = {
        "wopr_cut": round(float(wq), 3), "racr_cut": round(float(rq), 3),
        **{line: {"n": len(sig_q), "over_hit": round(statistics.fmean(r["actual_yd"] > r[line] for r in sig_q if r["actual_yd"] != r[line]), 3)}
           for line in ("sleeper_yd", "l3_yd")}}

    # 3. Ladders: P(yards >= T), widths fit on 2023-2024, graded on 2025-2026
    train = [r for r in rows if r["season"] in TRAIN]
    test = [r for r in rows if r["season"] in TEST]
    widths = {}
    for pos in RECEIVERS:
        tr = [r for r in train if r["pos"] == pos]
        widths[pos] = {
            "lognormal_sigma": {c: float(np.std([math.log(max(r["actual_yd"], 0) + 5) - math.log(max(r[f"{c}_yd"], 0) + 5) for r in tr]))
                                for c in ("proposed", "current")},
            "two_piece": {c: two_piece_fit([r["actual_yd"] - r[f"{c}_yd"] for r in tr]) for c in ("proposed", "current")},
        }
    ladder = {}
    for t in LADDER:
        ys = [r["actual_yd"] >= t for r in test]
        ladder[str(t)] = {"base_rate": round(statistics.fmean(ys), 3)}
        for center in ("proposed", "current"):
            ln = [p_lognormal(t, r[f"{center}_yd"], widths[r["pos"]]["lognormal_sigma"][center]) for r in test]
            tp = [p_two_piece(t, r[f"{center}_yd"], *widths[r["pos"]]["two_piece"][center]) for r in test]
            ladder[str(t)][f"{center}_center"] = {
                "lognormal": {"brier": round(brier(ln, ys), 4), "logloss": round(logloss(ln, ys), 4)},
                "two_piece_normal": {"brier": round(brier(tp, ys), 4), "logloss": round(logloss(tp, ys), 4)}}
    result["ladders"] = ladder

    # 4. DFS plays on 2026 Sunday main slates with real salaries (WR/TE: the proposal's score is receiving-only)
    groups = json.loads((ROOT / "data" / "optimal_lineups.json").read_text())["2026"]
    dfs = defaultdict(lambda: defaultdict(list))
    flags = []
    for week in range(2, last_week_2026 + 1):
        g = (groups.get(str(week)) or {}).get("classic_sunday", {}).get("draft_group_id")
        if not g:
            continue
        sal = {}
        for p in draftables(d, g):
            if p.get("position") in RECEIVERS and p.get("salary"):
                sal.setdefault(pm.key(p["displayName"], p["position"]), p["salary"])
        wk = [r for r in rows if r["season"] == 2026 and r["week"] == week and r["key"] in sal]
        for r in wk:
            s = sal[r["key"]]
            cr = r["ceiling_row"]
            ceil = cm.ceiling(r["pos"], cm.inputs(r["pos"], cr["proj"], cr["history"], cr["line"], cr["implied"], cr["spread"],
                                                   cr["ts_l3"], cr["snap_l3"])) or cr["proj"]
            r["salary"] = s
            r["proposed_score"] = proposed_dfs_score(r["x"], s)
            r["current_score"] = ceil / (s / 1000)
            r["value_score"] = cr["proj"] / (s / 1000)
            r["hit4x"] = r["actual_pts"] >= 4 * s / 1000
            r["pts_per_k"] = r["actual_pts"] / (s / 1000)
            dfs[week][r["pos"]].append(r)
        for lo, hi in TIERS:
            tier = [r for r in wk if lo <= r["salary"] < hi and r["pos"] in ("WR", "TE")]
            if len(tier) >= 7:
                cut = np.quantile([r["proposed_score"] for r in tier], 0.85)
                flags += [r for r in tier if r["proposed_score"] >= cut and (r["proposed_yd"] - r["sleeper_yd"]) / r["sleeper_yd"] > EDGE]
    dfs_out = {}
    for pos in ("WR", "TE", "RB"):
        res = {}
        for score in ("proposed_score", "current_score", "value_score"):
            hits, ppk, rhos = [], [], []
            for week, by in dfs.items():
                pool = by.get(pos, [])
                if len(pool) < TOP_K[pos] * 2:
                    continue
                top = sorted(pool, key=lambda r: -r[score])[:TOP_K[pos]]
                hits += [r["hit4x"] for r in top]
                ppk += [r["pts_per_k"] for r in top]
                rhos.append(tpm.spearman([r[score] for r in pool], [r["pts_per_k"] for r in pool]))
            res[score] = {"picks": len(hits), "hit_4x": round(statistics.fmean(hits), 3) if hits else None,
                          "pts_per_k": round(statistics.fmean(ppk), 2) if ppk else None,
                          "rank_rho_pts_per_k": round(statistics.fmean(rhos), 3) if rhos else None}
        res["pool_hit_4x"] = round(statistics.fmean(r["hit4x"] for by in dfs.values() for r in by.get(pos, [])), 3) if dfs else None
        dfs_out[pos] = res
    dfs_out["proposed_flags"] = {"n": len(flags), "hit_4x": round(statistics.fmean(r["hit4x"] for r in flags), 3) if flags else None,
                                 "over_hit_vs_sleeper": round(statistics.fmean(r["actual_yd"] > r["sleeper_yd"] for r in flags), 3) if flags else None}
    result["dfs_2026"] = dfs_out

    OUT.write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


def sleeper_points(r: dict) -> float:
    """Sleeper's own DK projection for the row, before the app's correction."""
    return projections.dk_points_from_line(r["line"], r["pos"])


if __name__ == "__main__":
    main()
