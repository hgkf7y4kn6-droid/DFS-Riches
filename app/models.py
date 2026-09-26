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
    weather: dict | None = None         # app.weather: venue, roof, kickoff-window forecast, projection multipliers


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
    proj_points: float         # DK points from the projected stat line, matchup-adjusted
                                # (app.projections); DK FPPG when there's no line; x1.5 for CPT
    proj_notes: list[str] = []  # how proj_points was built, one line per step
    dk_fppg: float | None = None      # DraftKings' season Fantasy-Points-Per-Game (raw, no CPT bump)
    sleeper_proj: float | None = None  # Sleeper's week-specific PPR projection, when Sleeper has one
    trend_l3: float | None = None     # real DK-style FPPG over the player's last 3 games
    trend_l6: float | None = None     # ...last 6 games
    trend_l9: float | None = None     # ...last 9 games
    ceiling: float | None = None      # 85th-percentile DK score estimate (app.ceiling), x1.5 for CPT
    ceiling_notes: list[str] = []     # one line per factor behind the ceiling
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
    plays_per_game: float | None = None            # volume, from box scores
    plays_rank: int | None = None                  # 1 = most plays/game
    tempo_secs: float | None = None                # neutral-situation seconds from snap to snap
    tempo_rank: int | None = None                  # 1 = fastest tempo
    pass_pct: float | None = None                  # neutral-situation dropback rate
    rush_pct: float | None = None
    opp_pass_pct_allowed: float | None = None      # neutral dropback rate of offenses this defense faced
    opp_pass_pct_allowed_rank: int | None = None   # 1 = biggest pass funnel
    opp_rush_pct_allowed: float | None = None
    opp_rush_pct_allowed_rank: int | None = None   # 1 = biggest rush funnel


class TopPlayer(BaseModel):
    """A DFS target for one team in one game (app.targets): real DK salary,
    trailing performance, the matchup-adjusted ceiling, and why."""

    name: str
    position: str
    salary: int
    trend_l3: float | None = None
    ceiling: float | None = None
    proj_points: float | None = None
    role: str = "Core"                 # "Core" or "Value"
    usage_l3: float | None = None      # share of team targets + carries, last 3 games
    reasons: list[str] = []


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
    postgame: dict | None = None  # app.postgame.summarize once the game is final


class PositionMatchup(BaseModel):
    """What one defense allows to a position: DK points/game (last 8) vs league."""

    position: str
    allowed: float | None = None
    league_avg: float | None = None
    vs_avg: float | None = None        # +0.42 = allows 42% more than average
    rank: int | None = None            # 1 = allows the most (softest)


class UsageShare(BaseModel):
    name: str
    position: str
    injury: str = "Healthy"
    share_l3: float                    # share of team targets + carries, last 3 games
    share_l8: float | None = None


class LeagueContext(BaseModel):
    """League averages (and tempo/volume ranges) this week, for chart reference lines."""

    yards_per_play: float | None = None
    points: float | None = None
    tempo_secs: float | None = None
    tempo_min: float | None = None
    tempo_max: float | None = None
    plays: float | None = None
    plays_min: float | None = None
    plays_max: float | None = None
    pass_rate: float | None = None


class GameDetail(BaseModel):
    breakdown: GameBreakdown
    league: LeagueContext
    away_def_vs_pos: list[PositionMatchup]   # what the AWAY defense allows (the home offense attacks it)
    home_def_vs_pos: list[PositionMatchup]
    away_usage: list[UsageShare]
    home_usage: list[UsageShare]
    insights: dict[str, str]                 # section -> 1-2 sentence game/DFS impact, generated from the numbers
    trenches: dict | None = None             # unit ranks, scheme rates and matchup edges (app.trenches); None if unavailable


class WeekBreakdown(BaseModel):
    season: int
    week: int
    games: list[GameBreakdown]
