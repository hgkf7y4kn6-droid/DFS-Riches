"""Do tight ends outscore expectations on National Tight Ends Day?

    python -m scripts.test_tight_ends_day [--data DIR]

National Tight Ends Day is the fourth Sunday of October (first held 2019). Three looks, each comparing the holiday's week
with the other mid-season weeks (4-14) of the same seasons:

1. vs projection (2023-2025, Sleeper's projection scored with DraftKings rules): every TE projected 3+ points who played.
2. vs his own form (2019-2025): actual / his average over his earlier games that season (3+ games, 5+ point average).
3. The position's share (2019-2025): TEs' share of each team's receiving targets and of its pass catchers' DK points.

For each: the holiday's mean, the other weeks' mean, the gap with a standard error, each season's gap, and where the
holiday week ranks among the season's mid-season weeks. Writes data/tight_ends_day_tests.json.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import statistics
from collections import defaultdict
from pathlib import Path

from app import dk_scoring, player_model as pm, projections
from scripts.train_game_model import GAMES_URL, REL, fetch
from scripts.train_player_model import sleeper_week

OUT = Path(__file__).resolve().parent.parent / "data" / "tight_ends_day_tests.json"
SEASONS = tuple(range(2019, 2026))
PROJ_SEASONS = (2023, 2024, 2025)
MID = range(4, 15)


def fourth_sunday(year: int) -> str:
    d = dt.date(year, 10, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)
    return (d + dt.timedelta(days=21)).isoformat()


def holiday_weeks(d: Path) -> dict[int, int]:
    out = {}
    for g in csv.DictReader(open(fetch(GAMES_URL, d / "games.csv"), newline="")):
        if g["game_type"] == "REG" and g["gameday"] == fourth_sunday(int(g["season"])):
            out[int(g["season"])] = int(g["week"])
    return out


def summarize(vals: dict[int, dict[int, list[float]]], weeks: dict[int, int]) -> dict:
    """vals: {season: {week: [values]}} -> holiday vs other mid-season weeks."""
    hol = [v for s, w in weeks.items() for v in vals.get(s, {}).get(w, [])]
    rest = [v for s, w in weeks.items() for x, vs in vals.get(s, {}).items() if x in MID and x != w for v in vs]
    if not hol or not rest:
        return {}
    gap = statistics.fmean(hol) - statistics.fmean(rest)
    se = (statistics.pvariance(rest) / len(hol) + statistics.pvariance(rest) / len(rest)) ** 0.5
    by_season, ranks = {}, []
    for s, w in weeks.items():
        wk = {x: statistics.fmean(vs) for x, vs in vals.get(s, {}).items() if x in MID and vs}
        if w not in wk:
            continue
        others = [v for x, v in wk.items() if x != w]
        by_season[s] = {"week": w, "holiday": round(wk[w], 3), "other_weeks": round(statistics.fmean(others), 3),
                        "gap": round(wk[w] - statistics.fmean(others), 3),
                        "rank": f"{1 + sum(v > wk[w] for v in others)} of {len(wk)}"}
        ranks.append((1 + sum(v > wk[w] for v in others)) / len(wk))
    return {"n_holiday": len(hol), "n_other": len(rest), "holiday": round(statistics.fmean(hol), 3),
            "other_weeks": round(statistics.fmean(rest), 3), "gap": round(gap, 3), "se": round(se, 3),
            "z": round(gap / se, 2) if se else None,
            "seasons_above": sum(1 for v in by_season.values() if v["gap"] > 0), "seasons": len(by_season),
            "avg_rank_pct": round(statistics.fmean(ranks), 2) if ranks else None, "by_season": by_season}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    args = ap.parse_args()
    d = Path(args.data)
    weeks = {s: w for s, w in holiday_weeks(d).items() if s in SEASONS}
    vs_proj, vs_form, tgt_share, pts_share = (defaultdict(lambda: defaultdict(list)) for _ in range(4))
    boom = defaultdict(lambda: defaultdict(list))
    for s in SEASONS:
        rows = [r for r in csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{s}.csv",
                                                     d / f"stats_player_week_{s}.csv"), newline=""))
                if r.get("season_type", "REG") == "REG" and r.get("week")]
        pts = {}
        team_tgt, team_pts = defaultdict(float), defaultdict(float)
        te_tgt, te_pts = defaultdict(float), defaultdict(float)
        for r in rows:
            w, pos = int(r["week"]), r.get("position")
            p = dk_scoring.dk_offense_points(r)
            if pos == "TE":
                pts.setdefault(pm.key(r["player_display_name"], "TE"), {})[w] = p
            if pos in ("WR", "TE", "RB"):
                k = (w, r["team"])
                t = float(r.get("targets") or 0)
                rec = float(r.get("receiving_yards") or 0) * 0.1 + float(r.get("receptions") or 0) + float(r.get("receiving_tds") or 0) * 6
                team_tgt[k] += t
                team_pts[k] += rec
                if pos == "TE":
                    te_tgt[k] += t
                    te_pts[k] += rec
        for (w, tm), n in team_tgt.items():
            if n >= 15:
                tgt_share[s][w].append(te_tgt[(w, tm)] / n)
            if team_pts[(w, tm)] >= 10:
                pts_share[s][w].append(te_pts[(w, tm)] / team_pts[(w, tm)])
        for games in pts.values():
            for w, p in games.items():
                prior = [games[x] for x in games if x < w]
                if len(prior) >= 3 and statistics.fmean(prior) >= 5:
                    vs_form[s][w].append(p / statistics.fmean(prior))
        if s in PROJ_SEASONS:
            for w in MID:
                for e in sleeper_week(d, s, w):
                    pl = e.get("player") or {}
                    if pl.get("position") != "TE" or not e.get("team"):
                        continue
                    k = pm.key(f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip(), "TE")
                    proj = projections.dk_points_from_line(e.get("stats") or {}, "TE")
                    if proj >= 3 and w in pts.get(k, {}):
                        vs_proj[s][w].append(pts[k][w] - proj)
                        boom[s][w].append(float(pts[k][w] >= 1.5 * proj))
    res = {
        "holiday": "fourth Sunday of October",
        "weeks": {s: w for s, w in sorted(weeks.items())},
        "te_points_minus_projection_2023_2025": summarize(vs_proj, {s: w for s, w in weeks.items() if s in PROJ_SEASONS}),
        "te_boom_rate_1_5x_projection_2023_2025": summarize(boom, {s: w for s, w in weeks.items() if s in PROJ_SEASONS}),
        "te_points_over_own_average_2019_2025": summarize(vs_form, weeks),
        "te_share_of_targets_2019_2025": summarize(tgt_share, weeks),
        "te_share_of_receiving_points_2019_2025": summarize(pts_share, weeks),
    }
    OUT.write_text(json.dumps(res, indent=1))
    for k, v in res.items():
        if isinstance(v, dict) and "gap" in v:
            print(f"{k}: holiday {v['holiday']} vs {v['other_weeks']} gap {v['gap']:+} (z {v['z']}) "
                  f"above in {v['seasons_above']}/{v['seasons']} seasons, avg rank pct {v['avg_rank_pct']}")
            for s, b in v["by_season"].items():
                print(f"   {s} wk{b['week']}: {b['holiday']} vs {b['other_weeks']} ({b['gap']:+}) rank {b['rank']}")


if __name__ == "__main__":
    main()
