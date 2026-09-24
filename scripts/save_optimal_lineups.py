"""Keeps data/optimal_lineups.json current (a scheduled job runs this weekly):

  - the current week: records optimal lineups for every slate that hasn't
    kicked off yet (slates already underway are left as recorded);
  - the previous week: once a slate's games are all final, scores its saved
    lineups with actual points and adds the hindsight best-possible lineup.

    python -m scripts.save_optimal_lineups                 # Sleeper's current week + the one before
    python -m scripts.save_optimal_lineups --season 2026 --week 1   # just that week
"""
from __future__ import annotations

import argparse
import asyncio

from app import optimal, slates
from app.sleeper_client import get_nfl_state


async def process_week(season: int, week: int) -> None:
    print(f"Season {season} Week {week}")
    _schedule, slate_list = await slates.list_slates(season, week)
    for slate in slate_list:
        r = await optimal.get_optimal(season, week, slate.slate_id)
        parts = [f"{lu['label']} proj {lu['proj_points']} / ceil {lu['ceiling']}"
                 + (f" / actual {lu['actual']}" if "actual" in lu else "") for lu in r["lineups"]]
        if r["hindsight"]:
            parts.append(f"{r['hindsight']['label']} {r['hindsight']['actual']}")
        print(f"  {slate.slate_id}: {r['status']} {', '.join(parts) or 'no lineups'}")


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    args = parser.parse_args()

    if args.week is not None:
        season = args.season or int((await get_nfl_state())["season"])
        await process_week(season, args.week)
        return

    state = await get_nfl_state()
    season, week = args.season or int(state["season"]), int(state["week"])
    if week > 1:
        await process_week(season, week - 1)
    await process_week(season, week)


if __name__ == "__main__":
    asyncio.run(_main())
