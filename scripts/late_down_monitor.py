"""Late-down monitor: does fading teams whose 3rd/4th-down success runs ahead of their early-down pace beat the
closing line?

    python -m scripts.late_down_monitor [--season 2026] [--baseline 2023 2024 2025]

For every regular-season game, each team's late-down gap entering the game (app.trenches late_downs: late-down
success minus what early-down success implies, offense minus defense, with last season weighted as PRIOR_GAMES
games) is compared with how the game finished against nflverse's closing spread. "Fade" picks the team whose
gap is lower; "flagged" games have a team flagged hot or cold. The research backtest (2023-2025) found a
correlation of -0.02 with the line's miss and -0.14 on 2026 Weeks 1-6 (92 games), within noise; this script is
how that gets rechecked as the season fills in. Prints only aggregates.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import statistics

from app import nflverse_client as nc, trenches


async def season_rows(season: int, current: int) -> list[dict]:
    cur, prev = await nc.get_pbp_aggregates(season, current), await nc.get_pbp_aggregates(season - 1, current)
    cur_t, prev_t = trenches.index_counts(cur.get("trenches")), trenches.index_counts(prev.get("trenches"))
    games = await nc.get_games(season)
    rows, by_week = [], {}
    for (week, away, home), g in sorted(games.items()):
        if week > 18 or not g["is_final"] or g["spread_line"] is None:
            continue
        if week not in by_week:
            by_week[week] = trenches.build_teams(week, cur_t, prev_t)
        a, h = (by_week[week].get(t, {}).get("late_downs") for t in (away, home))
        if not a or not h:
            continue
        rows.append({"season": season, "week": week, "gap": h["net"] - a["net"],
                     "flagged": bool(a.get("flag") or h.get("flag")),
                     "miss": (g["home_score"] - g["away_score"]) - g["spread_line"]})
    return rows


def summarize(rows: list[dict]) -> dict:
    out = {"games": len(rows)}
    if len(rows) >= 3:
        out["corr_with_line_miss"] = round(statistics.correlation([r["gap"] for r in rows], [r["miss"] for r in rows]), 3)
        out["noise_band"] = round(2 / math.sqrt(len(rows)), 3)
    for name, sel in (("fade_ats", rows), ("fade_ats_flagged", [r for r in rows if r["flagged"]])):
        picks = [r for r in sel if r["miss"] != 0 and r["gap"] != 0]
        wins = sum((r["gap"] < 0) == (r["miss"] > 0) for r in picks)    # fade the higher gap: home when home's gap is lower
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
    rows = {s: await season_rows(s, args.season) for s in [*baseline, args.season]}
    base = [r for s in baseline for r in rows[s]]
    print("Late-down monitor (break-even against -110 is 52.4%)")
    print(f"  baseline {baseline}: {summarize(base)}")
    print(f"  {args.season}: {summarize(rows[args.season])}")


if __name__ == "__main__":
    asyncio.run(main())
