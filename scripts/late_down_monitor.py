"""Luck monitor: does fading teams whose recent results ran ahead of their underlying play beat the closing line?

    python -m scripts.late_down_monitor [--season 2026] [--baseline 2023 2024 2025]

Two signals, each compared with how the game finished against nflverse's closing spread:

  late-down gap       each team's late-down gap entering the game (app.trenches late_downs: late-down success minus
                      what early-down success implies, offense minus defense, with last season weighted as
                      PRIOR_GAMES games). Research backtest: r = -0.02 with the line's miss on 2023-2025, -0.14 on
                      2026 Weeks 1-6 (92 games), within noise.
  penalty-drive luck  over each team's last LUCK_GAMES games this season, the share of its drives on which the
                      defense was flagged (accepted penalty) that ended in points, shrunk toward the league rate
                      by LUCK_SHRINK drives, minus the league rate (Week 5 on). Research backtest: fading it went
                      320-277 (53.6%) on 2023-2025, z = 1.76 against a coin flip, positive in each season; its
                      separate effect against the line was t = -1.4 once recent offense was accounted for.

"Fade" picks the team with the lower value; "flagged" (late downs only) is games with a team flagged hot or cold.
Prints only aggregates.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import statistics

from app import nflverse_client as nc, trenches

LUCK_GAMES = 4
LUCK_SHRINK = 10          # drives of league-average results added to each team's recent sample
LUCK_FROM_WEEK = 5


def league_flag_score_rate(pen_by_season: dict[int, dict]) -> float:
    """Share of drives with an accepted defensive penalty that ended in points, across the given seasons."""
    n = sum(c["flag_drives"] for pen in pen_by_season.values() for c in pen.values())
    s = sum(c["flag_scored"] for pen in pen_by_season.values() for c in pen.values())
    return s / n if n else 0.0


def penalty_luck(pen: dict, team: str, week: int, league: float) -> float | None:
    """Penalty-drive luck entering `week` from this season's counts ({"week|team": {...}})."""
    played = sorted(int(k.split("|")[0]) for k in pen if k.endswith(f"|{team}") and int(k.split("|")[0]) < week)
    recent = [pen[f"{w}|{team}"] for w in played[-LUCK_GAMES:]]
    if len(recent) < LUCK_GAMES:
        return None
    n = sum(c["flag_drives"] for c in recent)
    s = sum(c["flag_scored"] for c in recent)
    return (s + LUCK_SHRINK * league) / (n + LUCK_SHRINK) - league


async def season_rows(season: int, current: int, league: float | None = None) -> tuple[list[dict], dict]:
    cur, prev = await nc.get_pbp_aggregates(season, current), await nc.get_pbp_aggregates(season - 1, current)
    cur_t, prev_t = trenches.index_counts(cur.get("trenches")), trenches.index_counts(prev.get("trenches"))
    pen = cur.get("penalty_drives") or {}
    league = league_flag_score_rate({season: pen}) if league is None else league
    games = await nc.get_games(season)
    rows, by_week = [], {}
    for (week, away, home), g in sorted(games.items()):
        if week > 18 or not g["is_final"] or g["spread_line"] is None:
            continue
        if week not in by_week:
            by_week[week] = trenches.build_teams(week, cur_t, prev_t)
        row = {"season": season, "week": week, "miss": (g["home_score"] - g["away_score"]) - g["spread_line"]}
        a, h = (by_week[week].get(t, {}).get("late_downs") for t in (away, home))
        if a and h:
            row.update(gap=h["net"] - a["net"], flagged=bool(a.get("flag") or h.get("flag")))
        if week >= LUCK_FROM_WEEK:
            la, lh = penalty_luck(pen, away, week, league), penalty_luck(pen, home, week, league)
            if la is not None and lh is not None:
                row["luck"] = lh - la
        rows.append(row)
    return rows, pen


def summarize(rows: list[dict], key: str, flagged: bool = False) -> dict:
    rows = [r for r in rows if key in r]
    out: dict = {"games": len(rows)}
    if len(rows) >= 3:
        out["corr_with_line_miss"] = round(statistics.correlation([r[key] for r in rows], [r["miss"] for r in rows]), 3)
        out["noise_band"] = round(2 / math.sqrt(len(rows)), 3)
    sets = [("fade_ats", rows)] + ([("fade_ats_flagged", [r for r in rows if r.get("flagged")])] if flagged else [])
    for name, sel in sets:
        picks = [r for r in sel if r["miss"] != 0 and r[key] != 0]
        wins = sum((r[key] < 0) == (r["miss"] > 0) for r in picks)    # fade the higher value: home when home's is lower
        out[name] = f"{wins}-{len(picks) - wins} ({wins / len(picks):.1%})" if picks else "no games"
    return out


async def main() -> None:
    from app.sleeper_client import get_nfl_state
    state = await get_nfl_state()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=int(state.get("league_season") or state.get("season")))
    ap.add_argument("--baseline", type=int, nargs="*", default=None)
    args = ap.parse_args()
    baseline = args.baseline if args.baseline is not None else [args.season - 3, args.season - 2, args.season - 1]
    pens = {s: (await nc.get_pbp_aggregates(s, args.season)).get("penalty_drives") or {} for s in baseline}
    league = league_flag_score_rate(pens)          # the baseline's rate, also used for the current season
    rows = {s: (await season_rows(s, args.season, league))[0] for s in [*baseline, args.season]}
    base = [r for s in baseline for r in rows[s]]
    print("Luck monitor (break-even against -110 is 52.4%)")
    print(f"  league: {league:.1%} of drives with an accepted defensive penalty ended in points ({baseline})")
    for key, label, flagged in (("gap", "late-down gap", True), ("luck", "penalty-drive luck", False)):
        print(f"  {label}")
        print(f"    baseline {baseline}: {summarize(base, key, flagged)}")
        print(f"    {args.season}: {summarize(rows[args.season], key, flagged)}")


if __name__ == "__main__":
    asyncio.run(main())
