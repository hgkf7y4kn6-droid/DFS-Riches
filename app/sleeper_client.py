"""Client for the (unofficial, public, read-only) Sleeper API.

Endpoints used:
  - /v1/state/nfl                         current season/week
  - /v1/players/nfl                       full player metadata dict (~5MB)
  - /v1/projections/nfl/{season}/{week}   weekly fantasy projections
  - /scores/nfl/{season_type}/{season}/{week}
        per-game data including real kickoff time (epoch ms) and broadcaster,
        used to build the schedule and detect isolated Wed/Thu/Sun/Mon games.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.cache import cached_fetch
from app.config import SLEEPER_BASE, TTL_PLAYERS, TTL_PROJECTIONS, TTL_SCHEDULE

_HEADERS = {"User-Agent": "DFSRiches/1.0 (+https://github.com/)"}


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    resp = await client.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


async def get_nfl_state() -> dict:
    async with httpx.AsyncClient() as client:
        return await _get_json(client, f"{SLEEPER_BASE}/v1/state/nfl")


async def get_players() -> dict[str, dict]:
    """Full Sleeper player_id -> metadata dict. Large and slow-changing, so
    cached aggressively."""

    async def fetch() -> dict:
        async with httpx.AsyncClient() as client:
            return await _get_json(client, f"{SLEEPER_BASE}/v1/players/nfl")

    return await cached_fetch("sleeper_players_nfl", TTL_PLAYERS, fetch)


async def get_projections(season: int, week: int, season_type: str = "regular") -> dict[str, float]:
    """player_id -> projected PPR points for the given week.

    Note: as of this writing Sleeper's public /v1/projections endpoint
    responds 200 with a per-player dict but every player's stats come back
    as {} (verified against both an already-played and a future week), so
    this returns an empty mapping in practice. It's kept as the shape the
    app expects and merged in as a bonus "Sleeper Proj" column so it starts
    populating automatically if/when Sleeper's endpoint does; DraftKings'
    own per-player FPPG (app.dk_client) is the primary, reliably-populated
    projection the app's Value column is computed from.
    """

    async def fetch() -> Any:
        async with httpx.AsyncClient() as client:
            url = f"{SLEEPER_BASE}/v1/projections/nfl/{season}/{week}?season_type={season_type}"
            return await _get_json(client, url)

    key = f"sleeper_projections_{season}_{season_type}_{week}"
    raw = await cached_fetch(key, TTL_PROJECTIONS, fetch)

    def _extract_points(stats: dict) -> float | None:
        pts = stats.get("pts_ppr")
        if pts is None:
            pts = stats.get("pts_half_ppr", stats.get("pts_std"))
        return None if pts is None else round(float(pts), 2)

    projections: dict[str, float] = {}
    if isinstance(raw, dict):
        # Observed shape: {player_id: {stat: value, ...}}
        for pid, stats in raw.items():
            pts = _extract_points(stats or {})
            if pts:
                projections[pid] = pts
    elif isinstance(raw, list):
        # Alternate shape some Sleeper endpoints use: [{"player_id":..., "stats": {...}}]
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            pid = entry.get("player_id")
            if not pid:
                continue
            pts = _extract_points(entry.get("stats") or {})
            if pts:
                projections[pid] = pts
    return projections


async def get_week_games(season: int, week: int, season_type: str = "regular") -> list[dict]:
    """Raw per-game score/schedule entries for a week, including real kickoff
    time and broadcaster -- used by app.schedule to build the slate list."""

    async def fetch() -> list[dict]:
        async with httpx.AsyncClient() as client:
            url = f"{SLEEPER_BASE}/scores/nfl/{season_type}/{season}/{week}"
            return await _get_json(client, url)

    key = f"sleeper_scores_{season}_{season_type}_{week}"
    return await cached_fetch(key, TTL_SCHEDULE, fetch)
