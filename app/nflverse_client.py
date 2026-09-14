"""Client for nflverse (https://github.com/nflverse), a free, public,
no-API-key dataset of real NFL data maintained by the open-source
nfl-data community. Two files are used:

  - data/games.csv (nflverse/nfldata)
        One row per game, every season, including the real closing
        sportsbook lines (spread_line, total_line, moneylines) and final
        scores. This is the source for pre-game spread / total / implied
        team totals and for grading how the game actually played out
        against them. Sleeper's own schedule feed (app.sleeper_client)
        carries a "spread" field too, but it disagreed wildly with this
        file on at least one 2026 Week 1 game while every other game
        matched within a point -- nflverse's number is used as the
        source of truth here since it's internally consistent across the
        full slate.
  - releases/stats_team/stats_team_week_{season}.csv (nflverse/nflverse-data)
        One row per team per game with real box-score stats. Total
        offensive plays (pass attempts + rush attempts + sacks taken) is
        used as the "pace of play" metric -- the standard, simplest real
        pace stat (as opposed to seconds-per-play, which needs full
        play-by-play data this app doesn't otherwise need).

nflverse spells the Rams "LA"; every other team code already matches the
abbreviations Sleeper/DraftKings use (see app.config.NFLVERSE_TO_APP_TEAM).
"""
from __future__ import annotations

import csv
import io
from typing import Any

import httpx

from app.cache import cached_fetch
from app.config import (
    APP_TO_NFLVERSE_TEAM,
    NFLVERSE_GAMES_CSV_URL,
    NFLVERSE_TEAM_STATS_URL_TMPL,
    NFLVERSE_TO_APP_TEAM,
    TTL_NFLVERSE_GAMES,
    TTL_NFLVERSE_TEAM_STATS,
)

_HEADERS = {"User-Agent": "DFSRiches/1.0 (+https://github.com/)"}


def to_app_team(team: str) -> str:
    return NFLVERSE_TO_APP_TEAM.get(team, team)


def to_nflverse_team(team: str) -> str:
    return APP_TO_NFLVERSE_TEAM.get(team, team)


def _to_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    f = _to_float(value)
    return None if f is None else int(f)


async def _fetch_csv_text(url: str) -> str:
    # GitHub release assets 302-redirect to Azure blob storage.
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url, headers=_HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.text


async def get_games(season: int) -> dict[tuple[int, str, str], dict[str, Any]]:
    """{(week, away_team, home_team): {spread_line, total_line, away_moneyline,
    home_moneyline, away_score, home_score, is_final}} for one season, keyed
    by app-convention team codes (LAR, not nflverse's LA)."""

    async def fetch() -> list[dict]:
        text = await _fetch_csv_text(NFLVERSE_GAMES_CSV_URL)
        reader = csv.DictReader(io.StringIO(text))
        return [row for row in reader if row.get("season") == str(season)]

    rows = await cached_fetch(f"nflverse_games_{season}", TTL_NFLVERSE_GAMES, fetch)

    games: dict[tuple[int, str, str], dict[str, Any]] = {}
    for row in rows:
        try:
            week = int(row["week"])
        except (KeyError, ValueError):
            continue
        away = to_app_team(row["away_team"])
        home = to_app_team(row["home_team"])
        away_score = _to_int(row.get("away_score"))
        home_score = _to_int(row.get("home_score"))
        games[(week, away, home)] = {
            "spread_line": _to_float(row.get("spread_line")),
            "total_line": _to_float(row.get("total_line")),
            "away_moneyline": _to_int(row.get("away_moneyline")),
            "home_moneyline": _to_int(row.get("home_moneyline")),
            "away_score": away_score,
            "home_score": home_score,
            "is_final": away_score is not None and home_score is not None,
        }
    return games


async def get_team_week_plays(season: int) -> dict[tuple[int, str], float]:
    """{(week, team): offensive_plays} for one season, where offensive plays
    = pass attempts + rush attempts + sacks taken (the standard simple
    "plays run" pace stat), keyed by app-convention team codes."""

    async def fetch() -> list[dict]:
        url = NFLVERSE_TEAM_STATS_URL_TMPL.format(season=season)
        text = await _fetch_csv_text(url)
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)

    try:
        rows = await cached_fetch(f"nflverse_team_stats_{season}", TTL_NFLVERSE_TEAM_STATS, fetch)
    except Exception:
        return {}

    plays: dict[tuple[int, str], float] = {}
    for row in rows:
        try:
            week = int(row["week"])
        except (KeyError, ValueError):
            continue
        team = to_app_team(row["team"])
        attempts = _to_float(row.get("attempts")) or 0.0
        carries = _to_float(row.get("carries")) or 0.0
        sacks = _to_float(row.get("sacks_suffered")) or 0.0
        plays[(week, team)] = attempts + carries + sacks
    return plays


async def get_baseline_plays(season: int, week: int, team: str) -> float | None:
    """A defensible real-data pre-game pace expectation: the team's own
    season-to-date average plays/game entering this week, falling back to
    their full prior-season average when there's no current-season history
    yet (i.e. Week 1)."""
    current = await get_team_week_plays(season)
    prior_this_season = [v for (w, t), v in current.items() if t == team and w < week]
    if prior_this_season:
        return sum(prior_this_season) / len(prior_this_season)

    previous_season = await get_team_week_plays(season - 1)
    prior_season_values = [v for (_w, t), v in previous_season.items() if t == team]
    if prior_season_values:
        return sum(prior_season_values) / len(prior_season_values)

    return None
