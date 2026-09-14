"""Attaches real pre-game betting context (spread, total, implied team
totals, pace-of-play baseline, and trailing 3/6/9-game trends for each of
those) to each Game in a schedule, and -- once a game is final -- how far
the actual result landed above or below each of those lines. All of it
comes from nflverse (app.nflverse_client); nothing here is estimated or
fabricated.

Formulas (home-team perspective; away is the mirror image):
  - home_spread: nflverse's spread_line is published from the away team's
    perspective (negative = away favored), so home_spread = -spread_line.
  - implied team total: split total_line by the spread around its midpoint,
    e.g. a 3-point favorite in a 45 total is implied for 24, the dog for 21.
  - spread_result (ATS margin): (home_score - away_score) + home_spread.
    Positive means the home team beat the spread by that many points;
    negative means the away team did.
  - total_result: (home_score + away_score) - total_line. Positive means
    the game went over; negative means it went under.
  - pace delta: actual offensive plays this game - the team's own
    season-to-date average (or, in Week 1, their prior season's average).
  - trends (spread/total/implied-total/pace): each team's own trailing
    3/6/9-game average of that metric across their real game history,
    independent of the specific matchup -- shown whether or not this game
    has been played yet.
"""
from __future__ import annotations

import asyncio

from app import nflverse_client
from app.models import Game, GameContext, PaceStat, TeamTrend, WeekSchedule


def _implied_totals(total_line: float | None, home_spread: float | None) -> tuple[float | None, float | None]:
    if total_line is None or home_spread is None:
        return None, None
    half = total_line / 2
    edge = -home_spread / 2  # home_spread negative (favored) -> positive edge added to home's half
    return round(half - edge, 1), round(half + edge, 1)  # (away, home)


def _pace_stat(actual: float | None, baseline: float | None, trend: dict) -> PaceStat | None:
    if actual is None and baseline is None and not any(trend.values()):
        return None
    delta = round(actual - baseline, 1) if actual is not None and baseline is not None else None
    return PaceStat(
        actual_plays=actual,
        baseline_plays=round(baseline, 1) if baseline is not None else None,
        delta=delta,
        trend=TeamTrend(**trend),
    )


async def _build_context(game: Game, line_row: dict | None, team_trends: dict) -> GameContext | None:
    if line_row is None:
        return None

    spread_line = line_row.get("spread_line")  # away-perspective
    away_spread = spread_line
    home_spread = -spread_line if spread_line is not None else None
    total_line = line_row.get("total_line")
    away_implied, home_implied = _implied_totals(total_line, home_spread)

    is_final = line_row.get("is_final", False)
    away_score = line_row.get("away_score")
    home_score = line_row.get("home_score")

    spread_result = None
    total_result = None
    if is_final and home_spread is not None:
        spread_result = round((home_score - away_score) + home_spread, 1)
    if is_final and total_line is not None:
        total_result = round((home_score + away_score) - total_line, 1)

    away_actual = home_actual = away_baseline = home_baseline = None
    if is_final:
        away_actual, home_actual, away_baseline, home_baseline = await asyncio.gather(
            _actual_plays(game.season, game.week, game.away),
            _actual_plays(game.season, game.week, game.home),
            nflverse_client.get_baseline_plays(game.season, game.week, game.away),
            nflverse_client.get_baseline_plays(game.season, game.week, game.home),
        )
    # Pace trend reflects each team's own game history and is meaningful
    # pre-game too; actual/baseline/delta only exist once the game is final.
    away_pace = _pace_stat(away_actual, away_baseline, team_trends["away"]["plays"])
    home_pace = _pace_stat(home_actual, home_baseline, team_trends["home"]["plays"])

    return GameContext(
        away_spread=away_spread,
        home_spread=home_spread,
        total_line=total_line,
        away_implied_total=away_implied,
        home_implied_total=home_implied,
        away_spread_trend=TeamTrend(**team_trends["away"]["spread"]),
        home_spread_trend=TeamTrend(**team_trends["home"]["spread"]),
        away_total_trend=TeamTrend(**team_trends["away"]["total"]),
        home_total_trend=TeamTrend(**team_trends["home"]["total"]),
        away_implied_total_trend=TeamTrend(**team_trends["away"]["implied_total"]),
        home_implied_total_trend=TeamTrend(**team_trends["home"]["implied_total"]),
        is_final=is_final,
        away_score=away_score,
        home_score=home_score,
        spread_result=spread_result,
        total_result=total_result,
        away_pace=away_pace,
        home_pace=home_pace,
    )


async def _actual_plays(season: int, week: int, team: str) -> float | None:
    plays_by_week = await nflverse_client.get_team_week_plays(season)
    return plays_by_week.get((week, team))


def _team_trends_for_game(index: dict, game: Game) -> dict:
    metrics = ("spread", "total", "implied_total", "plays")
    return {
        side: {
            metric: nflverse_client.team_trend(index, team, metric, game.season, game.week)
            for metric in metrics
        }
        for side, team in (("away", game.away), ("home", game.home))
    }


async def attach_game_context(schedule: WeekSchedule) -> None:
    """Mutates every Game in schedule.games (and schedule.isolated_games,
    which shares the same Game objects) in place, adding real context.
    Failures degrade to no context for that game rather than breaking the
    schedule -- this is enrichment, not a hard dependency."""
    try:
        lines = await nflverse_client.get_games(schedule.season)
    except Exception:
        lines = {}

    try:
        trend_index = await nflverse_client.get_team_context_trailing_index(schedule.season)
    except Exception:
        trend_index = {}

    async def enrich(game: Game) -> None:
        line_row = lines.get((game.week, game.away, game.home))
        try:
            team_trends = _team_trends_for_game(trend_index, game)
            game.context = await _build_context(game, line_row, team_trends)
        except Exception:
            game.context = None

    await asyncio.gather(*(enrich(g) for g in schedule.games))
