"""Pydantic response models shared between app/schedule.py, app/slates.py and
app/main.py."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Game(BaseModel):
    game_id: str
    season: int
    week: int
    away: str
    home: str
    kickoff_utc: datetime
    kickoff_et: str        # pre-formatted for display, e.g. "Wed 9/9 8:20 PM ET"
    network: str | None = None
    day_part: str          # WED_NIGHT, THU_NIGHT, SUN_EARLY, SUN_LATE, SUN_NIGHT, MON_NIGHT, ...
    isolated: bool = False # True => the lone game in an isolated (Wed/Thu/Sun/Mon night) window


class WeekSchedule(BaseModel):
    season: int
    week: int
    games: list[Game]
    isolated_games: list[Game]


class Player(BaseModel):
    name: str
    team: str
    opponent: str
    position: str
    roster_slot: str          # "" for classic, "CPT" or "FLEX" for showdown
    salary: int
    proj_points: float         # primary projection used for Value: DraftKings' own FPPG,
                                # x1.5 for the Showdown Captain slot
    dk_fppg: float | None = None      # DraftKings' season Fantasy-Points-Per-Game (raw, no CPT bump)
    sleeper_proj: float | None = None  # Sleeper's week-specific PPR projection, when Sleeper has one
    value_per_1k: float
    game_info: str
    injury: str | None = None
    sleeper_player_id: str | None = None
    dk_draftable_id: int | None = None


class Slate(BaseModel):
    slate_id: str              # e.g. "classic", "showdown_wed", "showdown_thu"
    label: str
    slate_type: str            # "classic" | "showdown"
    day_part: str | None = None
    draft_group_id: int | None = None
    games: list[Game]
    available: bool
    source: str                # "live" | "override" | "unavailable"


class SlatePlayers(BaseModel):
    slate: Slate
    players: list[Player]
    unmatched_dk_names: list[str]
    match_count: int
    total_count: int
