"""Builds the real Week N schedule from Sleeper's per-game score/schedule feed
and classifies each game into a broadcast day-part, flagging the ones that
are the lone game in a Wednesday/Thursday/Sunday/Monday night window -- the
windows DraftKings builds single-game Showdown contests around.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from app import nflverse_client, sleeper_client, weather
from app.cache import memoize_async
from app.config import ET, ISOLATED_DAY_PARTS
from app.game_context import attach_game_context
from app.models import Game, WeekSchedule


def classify_day_part(kickoff_et: datetime) -> str:
    weekday = kickoff_et.weekday()  # Monday=0 ... Sunday=6
    hour = kickoff_et.hour

    if weekday == 2:
        return "WED_NIGHT"
    if weekday == 3:
        return "THU_NIGHT"
    if weekday == 4:
        return "FRI_NIGHT"
    if weekday == 5:
        return "SAT"
    if weekday == 6:  # Sunday
        if hour < 16:
            return "SUN_EARLY"
        if hour < 20:
            return "SUN_LATE"
        return "SUN_NIGHT"
    if weekday == 0:
        return "MON_NIGHT"
    return "OTHER"


def _format_et(dt_et: datetime) -> str:
    # Cross-platform strftime without leading zeros ("%-m", "%-I" are
    # POSIX-only but this container is Linux; avoided anyway for portability).
    day = dt_et.strftime("%a")
    date = f"{dt_et.month}/{dt_et.day}"
    time_ = dt_et.strftime("%I:%M %p").lstrip("0")
    return f"{day} {date} {time_} ET"


def mark_isolated_games(games: list[Game]) -> list[Game]:
    """Flags each game that is the lone game in an isolated (Wed/Thu/Sun/Mon
    night) day-part window -- i.e. the ones DraftKings builds single-game
    Showdown contests around. Pure function so it's testable without a
    network call."""
    day_part_counts = Counter(g.day_part for g in games)
    for g in games:
        g.isolated = g.day_part in ISOLATED_DAY_PARTS and day_part_counts[g.day_part] == 1
    return games


@memoize_async(60)
async def get_week_schedule(season: int, week: int, season_type: str = "regular") -> WeekSchedule:
    raw_games = await sleeper_client.get_week_games(season, week, season_type)

    games: list[Game] = []
    for raw in raw_games:
        start_ms = raw.get("start_time")
        if not start_ms:
            continue
        kickoff_utc = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        kickoff_et = kickoff_utc.astimezone(ET)
        meta = raw.get("metadata") or {}
        away = meta.get("away_team") or raw.get("away") or ""
        home = meta.get("home_team") or raw.get("home") or ""
        network = meta.get("channel")
        day_part = classify_day_part(kickoff_et)

        games.append(
            Game(
                game_id=str(raw.get("game_id")),
                season=season,
                week=week,
                away=away,
                home=home,
                kickoff_utc=kickoff_utc,
                kickoff_et=_format_et(kickoff_et),
                network=network,
                day_part=day_part,
                isolated=False,
            )
        )

    mark_isolated_games(games)
    games.sort(key=lambda g: g.kickoff_utc)
    isolated_games = [g for g in games if g.isolated]

    schedule = WeekSchedule(season=season, week=week, games=games, isolated_games=isolated_games)
    await attach_game_context(schedule)
    try:
        lines = await nflverse_client.get_games(season)
    except Exception:
        lines = {}
    await weather.attach_weather(schedule, lines)
    return schedule
