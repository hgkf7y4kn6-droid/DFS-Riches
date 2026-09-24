"""Saves the optimal lineups for every slate of a week that hasn't kicked off
yet into data/optimal_lineups.json (slates already underway are left as
recorded). Run before the week's first kickoff (a scheduled job does this
weekly, right after scripts.record_draft_groups):

    python -m scripts.save_optimal_lineups                 # Sleeper's current week
    python -m scripts.save_optimal_lineups --season 2026 --week 4
"""
from __future__ import annotations

import argparse
import asyncio

from app import optimal, slates
from app.sleeper_client import get_nfl_state


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    args = parser.parse_args()

    season, week = args.season, args.week
    if season is None or week is None:
        state = await get_nfl_state()
        season = season or int(state["season"])
        week = week or int(state["week"])

    print(f"Season {season} Week {week}")
    _schedule, slate_list = await slates.list_slates(season, week)
    for slate in slate_list:
        result = await optimal.get_optimal(season, week, slate.slate_id)
        summary = ", ".join(f"{lu['label']} proj {lu['proj_points']} / ceil {lu['ceiling']}" for lu in result["lineups"])
        print(f"  {slate.slate_id}: {result['status']} (saved {result['saved_at']}) {summary or 'no lineups'}")


if __name__ == "__main__":
    asyncio.run(_main())
