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
        play-by-play data this app doesn't otherwise need). The same rows'
        defensive columns, combined with points allowed from games.csv,
        feed app.dk_scoring.dk_dst_points for a team's real trailing DST
        fantasy scoring.
  - releases/stats_player/stats_player_week_{season}.csv (nflverse/nflverse-data)
        One row per skill-position player per game with real box-score
        stats. Joined onto a DK salary row by normalized name + position
        (see player_key below) and fed through app.dk_scoring.dk_offense_points
        for real trailing DK-style FPPG.

nflverse spells the Rams "LA"; every other team code already matches the
abbreviations Sleeper/DraftKings use (see app.config.NFLVERSE_TO_APP_TEAM).
"""
from __future__ import annotations

import csv
import io
from typing import Any

import httpx

from app import dk_scoring
from app.cache import cached_fetch
from app.config import (
    NFLVERSE_GAMES_CSV_URL,
    NFLVERSE_PLAYER_STATS_URL_TMPL,
    NFLVERSE_TEAM_STATS_URL_TMPL,
    NFLVERSE_TO_APP_TEAM,
    TTL_NFLVERSE_GAMES,
    TTL_NFLVERSE_TEAM_STATS,
)
from app.matching import normalize_name, resolve_alias

_HEADERS = {"User-Agent": "DFSRiches/1.0 (+https://github.com/)"}


def to_app_team(team: str) -> str:
    return NFLVERSE_TO_APP_TEAM.get(team, team)


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


async def _fetch_csv_rows(url: str, cache_key: str) -> list[dict]:
    async def fetch() -> list[dict]:
        text = await _fetch_csv_text(url)
        return list(csv.DictReader(io.StringIO(text)))

    try:
        return await cached_fetch(cache_key, TTL_NFLVERSE_TEAM_STATS, fetch)
    except Exception:
        return []


async def _fetch_team_week_rows(season: int) -> list[dict]:
    url = NFLVERSE_TEAM_STATS_URL_TMPL.format(season=season)
    return await _fetch_csv_rows(url, f"nflverse_team_stats_{season}")


async def _fetch_player_week_rows(season: int) -> list[dict]:
    url = NFLVERSE_PLAYER_STATS_URL_TMPL.format(season=season)
    return await _fetch_csv_rows(url, f"nflverse_player_stats_{season}")


async def get_team_week_plays(season: int) -> dict[tuple[int, str], float]:
    """{(week, team): offensive_plays} for one season, where offensive plays
    = pass attempts + rush attempts + sacks taken (the standard simple
    "plays run" pace stat), keyed by app-convention team codes."""
    rows = await _fetch_team_week_rows(season)

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


async def _points_allowed_by_week_team(season: int) -> dict[tuple[int, str], float]:
    games = await get_games(season)
    allowed: dict[tuple[int, str], float] = {}
    for (week, away, home), row in games.items():
        if not row["is_final"]:
            continue
        allowed[(week, away)] = row["home_score"]
        allowed[(week, home)] = row["away_score"]
    return allowed


def _trailing_avg(entries: list[list], season: int, week: int, n: int) -> float | None:
    """entries: [[season, week, points], ...], any order. Averages the last
    n entries strictly before (season, week), chronologically -- i.e. the
    n most recent games, reaching back into a prior season if the current
    one doesn't yet have n games played."""
    prior = sorted(e for e in entries if (e[0], e[1]) < (season, week))
    if not prior:
        return None
    tail = prior[-n:]
    return round(sum(e[2] for e in tail) / len(tail), 2)


def player_key(name: str, position: str) -> str:
    """Join key between a DK salary row and nflverse's per-game player
    stats. Sleeper's player_id can't be used directly here: only ~19% of
    Sleeper's skill-position players carry the gsis_id cross-reference that
    would otherwise give a clean id-to-id join (verified against the live
    2026 player dict), so this falls back to the same normalized-name
    approach app.matching uses for DK<->Sleeper, keyed with position to
    avoid name collisions across positions."""
    return f"{resolve_alias(normalize_name(name))}|{position.upper()}"


async def get_player_trailing_index(season: int) -> dict[str, list[list]]:
    """player_key(name, position) -> [[season, week, dk_points], ...]
    combining this season and the prior one, for computing a trailing
    DK-FPPG at any (season, week) without re-fetching or re-scanning per
    player."""

    async def fetch() -> dict[str, list[list]]:
        index: dict[str, list[list]] = {}
        for szn in (season - 1, season):
            for row in await _fetch_player_week_rows(szn):
                name = row.get("player_display_name")
                position = row.get("position")
                if not name or not position:
                    continue
                try:
                    week = int(row["week"])
                except (KeyError, ValueError):
                    continue
                key = player_key(name, position)
                points = dk_scoring.dk_offense_points(row)
                index.setdefault(key, []).append([szn, week, points])
        return index

    return await cached_fetch(f"nflverse_player_trailing_index_{season}", TTL_NFLVERSE_TEAM_STATS, fetch)


async def get_team_dst_trailing_index(season: int) -> dict[str, list[list]]:
    """team -> [[season, week, dk_points], ...] combining this season and
    the prior one, for a team's trailing DST fantasy scoring."""

    async def fetch() -> dict[str, list[list]]:
        index: dict[str, list[list]] = {}
        for szn in (season - 1, season):
            points_allowed = await _points_allowed_by_week_team(szn)
            for row in await _fetch_team_week_rows(szn):
                team = to_app_team(row.get("team", ""))
                if not team:
                    continue
                try:
                    week = int(row["week"])
                except (KeyError, ValueError):
                    continue
                allowed = points_allowed.get((week, team))
                points = dk_scoring.dk_dst_points(row, allowed)
                index.setdefault(team, []).append([szn, week, points])
        return index

    return await cached_fetch(f"nflverse_team_dst_trailing_index_{season}", TTL_NFLVERSE_TEAM_STATS, fetch)


def trailing_dk_fppg(season: int, week: int, n: int, *, player_index: dict, name: str, position: str) -> float | None:
    key = player_key(name, position)
    return _trailing_avg(player_index.get(key, []), season, week, n)


def trailing_dst_points(season: int, week: int, n: int, *, team_index: dict, team: str) -> float | None:
    return _trailing_avg(team_index.get(team, []), season, week, n)


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


_TEAM_METRICS = (
    "spread", "total", "implied_total", "plays",
    "points_for", "points_against", "yards_per_play", "yards_allowed_per_play",
    "pass_pct", "rush_pct", "opp_pass_pct_allowed", "opp_rush_pct_allowed",
)


async def _team_week_box_scores(season: int) -> dict[tuple[int, str], dict]:
    """{(week, team): {opponent, plays, yards_per_play, pass_pct, rush_pct}}
    from real per-game box-score stats, one season."""
    scores: dict[tuple[int, str], dict] = {}
    for row in await _fetch_team_week_rows(season):
        try:
            week = int(row["week"])
        except (KeyError, ValueError):
            continue
        team = to_app_team(row["team"])
        attempts = _to_float(row.get("attempts")) or 0.0
        carries = _to_float(row.get("carries")) or 0.0
        sacks = _to_float(row.get("sacks_suffered")) or 0.0
        plays = attempts + carries + sacks
        total_yards = (_to_float(row.get("passing_yards")) or 0.0) + (_to_float(row.get("rushing_yards")) or 0.0)
        scores[(week, team)] = {
            "opponent": to_app_team(row.get("opponent_team", "")),
            "plays": plays,
            "yards_per_play": round(total_yards / plays, 2) if plays else None,
            "pass_pct": round(attempts / plays, 3) if plays else None,
            "rush_pct": round(carries / plays, 3) if plays else None,
        }
    return scores


async def get_team_context_trailing_index(season: int) -> dict[str, dict[str, list[list]]]:
    """team -> {metric: [[season,week,value],...]} for each of _TEAM_METRICS,
    combining this season and the prior one. "spread"/"implied_total" are
    from the team's own perspective (negative spread = they were favored)
    regardless of home/away, so a team's trend is comparable game to game.
    "opp_*_allowed" metrics are what that team's DEFENSE has faced: the
    opponent's own pass/rush split in that game (a real, direct measure of
    which offenses funnel their opponents to the air vs. the ground)."""

    async def fetch() -> dict[str, dict[str, list[list]]]:
        index: dict[str, dict[str, list[list]]] = {}
        for szn in (season - 1, season):
            games = await get_games(szn)
            box_scores = await _team_week_box_scores(szn)

            for (week, away, home), row in games.items():
                spread_line = row.get("spread_line")
                total_line = row.get("total_line")
                is_final = row.get("is_final")
                for team, opp, team_spread, pf, pa in (
                    (away, home, spread_line, row.get("away_score"), row.get("home_score")),
                    (home, away, -spread_line if spread_line is not None else None, row.get("home_score"), row.get("away_score")),
                ):
                    d = index.setdefault(team, {m: [] for m in _TEAM_METRICS})
                    if team_spread is not None:
                        d["spread"].append([szn, week, team_spread])
                    if total_line is not None:
                        d["total"].append([szn, week, total_line])
                    if team_spread is not None and total_line is not None:
                        implied = round(total_line / 2 - team_spread / 2, 1)
                        d["implied_total"].append([szn, week, implied])
                    if is_final and pf is not None:
                        d["points_for"].append([szn, week, pf])
                    if is_final and pa is not None:
                        d["points_against"].append([szn, week, pa])

                    own = box_scores.get((week, team))
                    if own:
                        if own["plays"]:
                            d["plays"].append([szn, week, own["plays"]])
                        if own["yards_per_play"] is not None:
                            d["yards_per_play"].append([szn, week, own["yards_per_play"]])
                        if own["pass_pct"] is not None:
                            d["pass_pct"].append([szn, week, own["pass_pct"]])
                        if own["rush_pct"] is not None:
                            d["rush_pct"].append([szn, week, own["rush_pct"]])

                    opp_box = box_scores.get((week, opp))
                    if opp_box:
                        if opp_box["yards_per_play"] is not None:
                            d["yards_allowed_per_play"].append([szn, week, opp_box["yards_per_play"]])
                        if opp_box["pass_pct"] is not None:
                            d["opp_pass_pct_allowed"].append([szn, week, opp_box["pass_pct"]])
                        if opp_box["rush_pct"] is not None:
                            d["opp_rush_pct_allowed"].append([szn, week, opp_box["rush_pct"]])
        return index

    return await cached_fetch(f"nflverse_team_context_trailing_index_{season}", TTL_NFLVERSE_GAMES, fetch)


def team_trend(index: dict, team: str, metric: str, season: int, week: int) -> dict[str, float | None]:
    """Returns a {"l3":..., "l6":..., "l9":...} dict of trailing averages
    for one team/metric, built from get_team_context_trailing_index."""
    series = index.get(team, {}).get(metric, [])
    return {
        "l3": _trailing_avg(series, season, week, 3),
        "l6": _trailing_avg(series, season, week, 6),
        "l9": _trailing_avg(series, season, week, 9),
    }


def team_trailing(index: dict, team: str, metric: str, season: int, week: int, n: int = 8) -> float | None:
    """A single trailing n-game average for one team/metric, from
    get_team_context_trailing_index."""
    return _trailing_avg(index.get(team, {}).get(metric, []), season, week, n)


def rank_teams(
    index: dict, metric: str, season: int, week: int, *, n: int = 8, descending: bool = True
) -> dict[str, int]:
    """team -> 1-based league rank by trailing n-game average of metric
    among all teams that have one. descending=True means higher is
    better/rank 1 (points scored, yards/play); descending=False means
    lower is better/rank 1 (points allowed, yards/play allowed)."""
    values: dict[str, float] = {}
    for team, metrics in index.items():
        v = _trailing_avg(metrics.get(metric, []), season, week, n)
        if v is not None:
            values[team] = v
    ranked = sorted(values.items(), key=lambda kv: kv[1], reverse=descending)
    return {team: i + 1 for i, (team, _v) in enumerate(ranked)}
