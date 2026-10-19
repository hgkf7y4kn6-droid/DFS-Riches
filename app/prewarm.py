"""Builds the current week's data ahead of the first visitor.

    python -m app.prewarm [--dfs]

Runs at two points:
  * the Docker image build (Dockerfile, with --dfs): the image ships with a filled disk cache -- the schedule
    and lines, last season's and this season's play-by-play aggregates (the team trends behind every game card),
    nflverse indexes, projections, DraftKings slates, and with --dfs the projection sources and the DFS model's
    inputs. Cached files keep their build-time timestamps, so each one still refreshes when its normal freshness
    window (app.config TTL_*) runs out.
  * server startup (app.main), slates only, to refresh whatever expired between the build and the start.

Best effort: a failure is logged and leaves everything to be built on demand, as before.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time

log = logging.getLogger("dfsriches.prewarm")
SLATES = ("classic_sunday", "classic")


async def warm(dfs: bool = False) -> dict:
    from app import dfs_model, slates
    from app.main import current_season_week

    t0 = time.perf_counter()
    done: dict[str, float] = {}
    season, week = await current_season_week()
    for slate_id in SLATES:
        t = time.perf_counter()
        try:
            await slates.get_slate_players(season, week, slate_id)
            done[slate_id] = round(time.perf_counter() - t, 1)
        except Exception as exc:
            log.warning("prewarm %s failed: %s", slate_id, exc)
    if dfs:
        t = time.perf_counter()
        try:
            await dfs_model.build(season, week, "classic_sunday", "gpp")
            done["dfs_model"] = round(time.perf_counter() - t, 1)
        except Exception as exc:
            log.warning("prewarm dfs_model failed: %s", exc)
    return {"season": season, "week": week, "seconds": done, "total": round(time.perf_counter() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dfs", action="store_true", help="also build the DFS model (projection sources, ownership)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        print("prewarm:", asyncio.run(warm(args.dfs)))
    except Exception as exc:          # never fail the image build over warming
        print("prewarm skipped:", exc)


if __name__ == "__main__":
    main()
