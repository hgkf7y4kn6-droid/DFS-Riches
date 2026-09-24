"""Records a week's live DraftKings draftGroupIds into data/dk_overrides.json.

DraftKings drops a slate from its "Upcoming" listing once its games kick off,
so a week's ids have to be saved before then for that week to keep loading.
Run this after salaries post and before the first kickoff (a scheduled job
does this weekly):

    python -m scripts.record_draft_groups                 # Sleeper's current week
    python -m scripts.record_draft_groups --season 2026 --week 4

Only groups that live discovery finds and that actually have salaried players
are recorded; existing entries are updated only if DraftKings' id changed.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app import dk_client
from app.config import DK_OVERRIDES_PATH
from app.schedule import get_week_schedule
from app.sleeper_client import get_nfl_state


def merge_discovery(overrides: dict, season: int, week: int, discovery: dict, has_salaries) -> list[str]:
    """Merges live discovery results into overrides in place; returns a line
    per slate describing what happened. has_salaries(draft_group_id, slate_type)
    decides whether a group is real enough to record."""
    week_entry = overrides.setdefault(str(season), {}).setdefault(str(week), {})
    report: list[str] = []

    def consider(name: str, slate_type: str, found: dict | None, existing: dict | None, store) -> None:
        if not found or found["source"] != "live":
            report.append(f"{name}: not in DraftKings' live listing (kept {existing['draft_group_id'] if existing else 'nothing'})")
            return
        new = {k: v for k, v in found.items() if k != "source"}
        if not has_salaries(new["draft_group_id"], slate_type):
            report.append(f"{name}: group {new['draft_group_id']} has no salaries yet, not recorded")
            return
        if existing == new:
            report.append(f"{name}: {new['draft_group_id']} already recorded")
            return
        store(new)
        if existing and existing["draft_group_id"] == new["draft_group_id"]:
            report.append(f"{name}: {new['draft_group_id']} details updated")
        else:
            report.append(f"{name}: recorded {new['draft_group_id']}" + (f" (was {existing['draft_group_id']})" if existing else ""))

    for key in ("classic_sunday", "classic"):
        consider(key, "classic", discovery.get(key), week_entry.get(key),
                 lambda v, k=key: week_entry.__setitem__(k, v))
    for day_part, found in sorted(discovery.get("showdown", {}).items()):
        existing = week_entry.get("showdown", {}).get(day_part)
        consider(f"showdown {day_part}", "showdown", found, existing,
                 lambda v, dp=day_part: week_entry.setdefault("showdown", {}).__setitem__(dp, v))

    if not week_entry:
        del overrides[str(season)][str(week)]
    return report


def _sorted_overrides(overrides: dict) -> dict:
    out = {k: v for k, v in overrides.items() if k.startswith("_")}
    for season in sorted((k for k in overrides if not k.startswith("_")), key=int):
        weeks = overrides[season]
        out[season] = {w: weeks[w] for w in sorted(weeks, key=int)}
    return out


async def record(season: int, week: int) -> list[str]:
    schedule = await get_week_schedule(season, week)
    discovery = await dk_client.discover_draft_groups(schedule)

    salaried: dict[int, bool] = {}
    leaves = [("classic", discovery["classic"]), ("classic", discovery["classic_sunday"])]
    leaves += [("showdown", leaf) for leaf in discovery["showdown"].values()]
    for slate_type, leaf in leaves:
        if leaf and leaf["source"] == "live":
            raw = await dk_client.fetch_draftables(leaf["draft_group_id"])
            salaried[leaf["draft_group_id"]] = bool(dk_client.parse_draftables(raw, slate_type))

    overrides = json.loads(DK_OVERRIDES_PATH.read_text()) if DK_OVERRIDES_PATH.exists() else {}
    report = merge_discovery(overrides, season, week, discovery, lambda gid, _t: salaried.get(gid, False))
    DK_OVERRIDES_PATH.write_text(json.dumps(_sorted_overrides(overrides), indent=2) + "\n")
    return report


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
    for line in await record(season, week):
        print("  " + line)


if __name__ == "__main__":
    asyncio.run(_main())
