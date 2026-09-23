"""Pydantic response models shared between app/schedule.py, app/slates.py and
app/main.py."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TeamTrend(BaseModel):
    """A team's own trailing average of some metric over their last N real
    games, reaching back into the prior season if the current one doesn't
    yet have N games played."""

    l3: float | None = None
    l6: float | None = None
    l9: float | None = None


class PaceStat(BaseModel):
    actual_plays: float | None = None    # this game's offensive plays (pass att + rush att + sacks taken)
    baseline_plays: float | None = None  # season-to-date avg entering this game, or prior season's full avg
    delta: float | None = None           # actual - baseline; positive = faster pace than expected
    trend: TeamTrend | None = None       # trailing plays-per-game (independent of this specific game)


class GameContext(BaseModel):
    """Real pre-game betting lines (nflverse, sourced from actual sportsbook
    closing lines) plus, once the game is final, how it actually performed
    against each of them."""

    away_spread: float | None = None   # negative = away favored by that many points
    home_spread: float | None = None   # negative = home favored by that many points
    total_line: float | None = None    # the over/under
    away_implied_total: float | None = None
    home_implied_total: float | None = None

    away_spread_trend: TeamTrend | None = None      # away team's own trailing avg spread (their games, not this one)
    home_spread_trend: TeamTrend | None = None
    away_total_trend: TeamTrend | None = None        # trailing avg game total in away team's own games
    home_total_trend: TeamTrend | None = None
    away_implied_total_trend: TeamTrend | None = None  # trailing avg of away team's own implied total
    home_implied_total_trend: TeamTrend | None = None

    is_final: bool = False
    away_score: int | None = None
    home_score: int | None = None

    spread_result: float | None = None  # home margin vs. home_spread; + = home covered, - = away covered
    total_result: float | None = None   # actual combined score - total_line; + = went over

    away_pace: PaceStat | None = None
    home_pace: PaceStat | None = None


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
    context: GameContext | None = None  # real spread/total/pace + performance-vs-line, once available


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
    trend_l3: float | None = None     # real DK-style FPPG over the player's last 3 games
    trend_l6: float | None = None     # ...last 6 games
    trend_l9: float | None = None     # ...last 9 games
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


class WeekData(BaseModel):
    """Bundles what /api/schedule and /api/slates each already compute from
    one underlying app.slates.list_slates() call, so the frontend's initial
    page load can fetch both in a single round trip instead of two."""

    schedule: WeekSchedule
    slates: list[Slate]


class TeamStatLine(BaseModel):
    """A team's real trailing box-score profile entering this game, each
    with its 1-32 league rank among teams that have a trailing value.
    Ranks are always "1 = best for that side of the ball": e.g. rank 1 in
    yards_allowed_per_play is the stingiest defense, not the most yards
    allowed."""

    team: str
    points_for: float | None = None
    points_for_rank: int | None = None
    points_against: float | None = None
    points_against_rank: int | None = None
    yards_per_play: float | None = None
    yards_per_play_rank: int | None = None
    yards_allowed_per_play: float | None = None
    yards_allowed_per_play_rank: int | None = None
    pace_plays: float | None = None
    pace_rank: int | None = None
    pass_pct: float | None = None
    rush_pct: float | None = None
    opp_pass_pct_allowed: float | None = None      # how often opponents have thrown against this defense
    opp_pass_pct_allowed_rank: int | None = None   # 1 = biggest pass funnel
    opp_rush_pct_allowed: float | None = None
    opp_rush_pct_allowed_rank: int | None = None   # 1 = biggest rush funnel


class TopPlayer(BaseModel):
    """A real DK salary + trailing performance snapshot, used for a quick
    "players to watch" callout per team on the breakdown page."""

    name: str
    position: str
    salary: int
    trend_l3: float | None = None


class GameBreakdown(BaseModel):
    game: Game
    away_stats: TeamStatLine
    home_stats: TeamStatLine
    total_rank_this_week: int | None = None          # 1 = highest game total of the week
    away_implied_rank_this_week: int | None = None   # 1 = highest team implied total of the week (all 32 teams)
    home_implied_rank_this_week: int | None = None
    takeaways: list[str]        # short, original, template-generated from the real numbers above
    away_top_players: list[TopPlayer]
    home_top_players: list[TopPlayer]


class WeekBreakdown(BaseModel):
    season: int
    week: int
    games: list[GameBreakdown]
