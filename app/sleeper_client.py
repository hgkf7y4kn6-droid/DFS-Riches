"""Client for the (unofficial, public, read-only) Sleeper API.

Endpoints used:
  - /v1/state/nfl                         current season/week
  - /v1/players/nfl                       full player metadata dict (~5MB)
  - api.sleeper.com/projections/nfl/{season}/{week}   weekly fantasy projections
  - /scores/nfl/{season_type}/{season}/{week}
        per-game data including real kickoff time (epoch ms) and broadcaster,
        used to build the schedule and detect isolated Wed/Thu/Sun/Mon games.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.cache import cached_fetch
from app.config import SLEEPER_BASE, SLEEPER_PROJECTIONS_BASE, TTL_PLAYERS, TTL_PROJECTIONS, TTL_SCHEDULE

_PROJECTION_POSITIONS = ("QB", "RB", "WR", "TE", "DEF")

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


async def _raw_projections(season: int, week: int, season_type: str = "regular") -> Any:
    async def fetch() -> Any:
        async with httpx.AsyncClient() as client:
            positions = "&".join(f"position[]={p}" for p in _PROJECTION_POSITIONS)
            url = f"{SLEEPER_PROJECTIONS_BASE}/projections/nfl/{season}/{week}?season_type={season_type}&{positions}"
            return await _get_json(client, url)

    key = f"sleeper_projections_v2_{season}_{season_type}_{week}"
    return await cached_fetch(key, TTL_PROJECTIONS, fetch)


def _entries(raw: Any):
    """(player_id, entry) pairs from either response shape: the list
    api.sleeper.com returns ([{"player_id", "stats", "team", ...}]) or a
    {player_id: stats} dict."""
    if isinstance(raw, dict):
        for pid, stats in raw.items():
            yield pid, {"stats": stats or {}}
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and entry.get("player_id"):
                yield entry["player_id"], entry


async def get_projections(season: int, week: int, season_type: str = "regular") -> dict[str, float]:
    """player_id -> projected PPR points for the given week. DEF entries are
    keyed by team abbreviation, matching Sleeper's DEF player_ids."""
    projections: dict[str, float] = {}
    for pid, entry in _entries(await _raw_projections(season, week, season_type)):
        stats = entry.get("stats") or {}
        pts = stats.get("pts_ppr")
        if pts is None:
            pts = stats.get("pts_half_ppr", stats.get("pts_std"))
        if pts:
            projections[pid] = round(float(pts), 2)
    return projections


async def get_projection_lines(season: int, week: int, season_type: str = "regular") -> dict[str, dict]:
    """player_id -> {"stats": projected stat line (rush_yd, rec, rec_yd, pass_yd,
    TDs, ... or sack/int/pts_allow for DEF), "team", "opponent", "position"}."""
    lines: dict[str, dict] = {}
    for pid, entry in _entries(await _raw_projections(season, week, season_type)):
        player = entry.get("player") or {}
        lines[pid] = {
            "stats": entry.get("stats") or {},
            "team": entry.get("team"),
            "opponent": entry.get("opponent"),
            "position": player.get("position"),
            "name": f"{player.get('first_name', '')} {player.get('last_name', '')}".strip(),
        }
    return lines


async def get_week_games(season: int, week: int, season_type: str = "regular") -> list[dict]:
    """Raw per-game score/schedule entries for a week, including real kickoff
    time and broadcaster -- used by app.schedule to build the slate list."""

    async def fetch() -> list[dict]:
        async with httpx.AsyncClient() as client:
            url = f"{SLEEPER_BASE}/scores/nfl/{season_type}/{season}/{week}"
            return await _get_json(client, url)

    key = f"sleeper_scores_{season}_{season_type}_{week}"
    return await cached_fetch(key, TTL_SCHEDULE, fetch)
