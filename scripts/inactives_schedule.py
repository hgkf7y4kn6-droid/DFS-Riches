"""When to refresh lineups after inactives: one run per distinct kickoff time.

NFL teams declare inactives 90 minutes before kickoff, and DraftKings flips
those players to Out within minutes. This prints, for the current week (or
--season/--week), one run time per distinct kickoff -- kickoff minus
LEAD_MINUTES -- covering every game, including international morning games
and any Wednesday/Friday/Saturday games.

    python -m scripts.inactives_schedule                   # Sleeper's current week, upcoming runs only
    python -m scripts.inactives_schedule --season 2026 --week 4 --all

Output is JSON: [{"run_at": UTC ISO time, "run_at_et": "...", "kickoff_utc": ...,
"games": ["PIT@CLE", ...]}, ...], sorted by run time.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.config import ET
from app.schedule import get_week_schedule
from app.sleeper_client import get_nfl_state

INACTIVES_BEFORE_KICKOFF = timedelta(minutes=90)
LEAD_MINUTES = 83            # inactives at -90; give DraftKings a few minutes to update statuses


def inactive_runs(games, now: datetime | None = None, *, include_past: bool = False) -> list[dict]:
    """One run per distinct kickoff, LEAD_MINUTES before it; upcoming only unless include_past."""
    now = now or datetime.now(timezone.utc)
    by_kickoff: dict[datetime, list[str]] = {}
    for g in games:
        by_kickoff.setdefault(g.kickoff_utc, []).append(f"{g.away}@{g.home}")
    runs = []
    for kickoff in sorted(by_kickoff):
        run_at = kickoff - timedelta(minutes=LEAD_MINUTES)
        if not include_past and run_at <= now:
            continue
        runs.append({
            "run_at": run_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"),
            "run_at_et": run_at.astimezone(ET).strftime("%a %m/%d %I:%M %p ET"),
            "kickoff_utc": kickoff.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"),
            "inactives_at_utc": (kickoff - INACTIVES_BEFORE_KICKOFF).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:00Z"),
            "games": sorted(by_kickoff[kickoff]),
        })
    return runs


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--all", action="store_true", help="include runs whose time has passed")
    args = parser.parse_args()
    if args.season is None or args.week is None:
        state = await get_nfl_state()
        season = args.season or int(state["season"])
        week = args.week or int(state.get("display_week") or state["week"])
    else:
        season, week = args.season, args.week
    schedule = await get_week_schedule(season, week)
    print(json.dumps({"season": season, "week": week, "runs": inactive_runs(schedule.games, include_past=args.all)}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
