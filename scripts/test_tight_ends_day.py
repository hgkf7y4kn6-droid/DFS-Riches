"""Do tight ends outscore expectations on National Tight Ends Day?

    python -m scripts.test_tight_ends_day [--data DIR] [--live-week N]

National Tight Ends Day is the fourth Sunday of October (first held 2019). Three looks, each comparing the holiday's week
with the other mid-season weeks (4-14) of the same seasons:

1. vs projection (2022-2025, Sleeper's projection scored with DraftKings rules): every TE projected 3+ points who played.
2. vs his own form (2019-2025): actual / his average over his earlier games that season (3+ games, 5+ point average).
3. The position's share (2019-2025): TEs' share of each team's receiving targets and of its pass catchers' DK points.
4. Touchdowns (2019-2025): TE touchdowns per team-game, TEs' share of each team's offensive touchdowns, and the share
   of TEs with a role (3+ targets) who scored.
5. Were TEs projected higher? (2022-2025, and this season's holiday week live): each TE's projected DK points and
   projected touchdowns that week / his average projection over the season's other mid-season weeks.

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
PROJ_SEASONS = (2022, 2023, 2024, 2025)
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


def te_projections(d: Path, season: int, weeks) -> dict[str, dict[int, tuple[float, float]]]:
    """{TE key: {week: (projected DK points, projected TDs)}} from Sleeper's weekly projections."""
    out: dict[str, dict[int, tuple[float, float]]] = defaultdict(dict)
    for w in weeks:
        for e in sleeper_week(d, season, w):
            pl = e.get("player") or {}
            if pl.get("position") != "TE" or not e.get("team"):
                continue
            k = pm.key(f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip(), "TE")
            st = e.get("stats") or {}
            out[k][w] = (projections.dk_points_from_line(st, "TE"), float(st.get("rec_td") or 0))
    return out


def this_season(d: Path, week: int | None) -> dict:
    """The current season's holiday week vs its earlier weeks: each TE projected 3+ points this week, his projection
    and projected TDs over his average for weeks 4 on (3+ of them)."""
    if not week:
        return {}
    season = dt.date.today().year
    by = te_projections(d, season, range(4, week + 1))
    lift, td_lift = [], []
    for games in by.values():
        if week not in games:
            continue
        proj, td = games[week]
        others = [v for x, v in games.items() if x != week]
        avg = statistics.fmean(p for p, _ in others) if len(others) >= 3 else 0.0
        if proj >= 3 and avg >= 3:
            lift.append(proj / avg)
            avg_td = statistics.fmean(t for _, t in others)
            if avg_td > 0:
                td_lift.append(td / avg_td)
    return {"season": season, "week": week, "n": len(lift),
            "projection_over_earlier_weeks": round(statistics.fmean(lift), 3) if lift else None,
            "projected_tds_over_earlier_weeks": round(statistics.fmean(td_lift), 3) if td_lift else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--live-week", type=int, default=None, help="this season's holiday week, to check its projections")
    args = ap.parse_args()
    d = Path(args.data)
    weeks = {s: w for s, w in holiday_weeks(d).items() if s in SEASONS}
    vs_proj, vs_form, tgt_share, pts_share = (defaultdict(lambda: defaultdict(list)) for _ in range(4))
    boom = defaultdict(lambda: defaultdict(list))
    td_per_team, td_share, td_scored = (defaultdict(lambda: defaultdict(list)) for _ in range(3))
    proj_lift, proj_td_lift = (defaultdict(lambda: defaultdict(list)) for _ in range(2))
    for s in SEASONS:
        rows = [r for r in csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{s}.csv",
                                                     d / f"stats_player_week_{s}.csv"), newline=""))
                if r.get("season_type", "REG") == "REG" and r.get("week")]
        pts = {}
        team_tgt, team_pts = defaultdict(float), defaultdict(float)
        te_tgt, te_pts = defaultdict(float), defaultdict(float)
        team_td, te_td = defaultdict(float), defaultdict(float)
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
            tds = float(r.get("rushing_tds") or 0) + float(r.get("receiving_tds") or 0)
            team_td[(w, r["team"])] += tds
            if pos == "TE":
                te_td[(w, r["team"])] += tds
                if float(r.get("targets") or 0) >= 3:
                    td_scored[s][w].append(float(tds > 0))
        for (w, tm), n in team_td.items():
            td_per_team[s][w].append(te_td[(w, tm)])
            if n > 0:
                td_share[s][w].append(te_td[(w, tm)] / n)
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
            for k, by_week in te_projections(d, s, MID).items():
                for w, (proj, td) in by_week.items():
                    others = [v for x, v in by_week.items() if x != w]
                    avg = statistics.fmean(p for p, _ in others) if len(others) >= 3 else 0.0
                    if proj >= 3 and avg >= 3:
                        proj_lift[s][w].append(proj / avg)
                        avg_td = statistics.fmean(t for _, t in others)
                        if avg_td > 0:
                            proj_td_lift[s][w].append(td / avg_td)
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
        "te_points_minus_projection_2022_2025": summarize(vs_proj, {s: w for s, w in weeks.items() if s in PROJ_SEASONS}),
        "te_boom_rate_1_5x_projection_2022_2025": summarize(boom, {s: w for s, w in weeks.items() if s in PROJ_SEASONS}),
        "te_points_over_own_average_2019_2025": summarize(vs_form, weeks),
        "te_share_of_targets_2019_2025": summarize(tgt_share, weeks),
        "te_share_of_receiving_points_2019_2025": summarize(pts_share, weeks),
        "te_touchdowns_per_team_game_2019_2025": summarize(td_per_team, weeks),
        "te_share_of_offensive_touchdowns_2019_2025": summarize(td_share, weeks),
        "te_with_3_targets_who_scored_2019_2025": summarize(td_scored, weeks),
        "te_projection_over_his_other_weeks_2022_2025": summarize(proj_lift, {s: w for s, w in weeks.items() if s in PROJ_SEASONS}),
        "te_projected_tds_over_his_other_weeks_2022_2025": summarize(proj_td_lift, {s: w for s, w in weeks.items() if s in PROJ_SEASONS}),
        "this_season": this_season(d, args.live_week),
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
