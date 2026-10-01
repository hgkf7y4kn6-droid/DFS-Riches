"""Scoring from a Sleeper league's own scoring_settings (config.SLEEPER_LEAGUE_ID,
"The Breakfast Brunch"), applied to Sleeper's projected stat lines (Proj) and
to nflverse box scores (the history behind Ceiling).

Sleeper scores a player as sum(stat x weight) over the league's
scoring_settings keys; line_points does exactly that, so a projection here
matches what the league shows. Box-score rows use nflverse column names, so
offense_points/dst_points map them onto the same keys. Weekly box scores
carry no TD distances, so the league's 40+/50+ yard TD bonuses can't be
applied to history; yardage bonuses (bonus_*_yd_100/300) are applied when
the league has them.

Every function takes scoring=None to mean "no league available" and the
callers then fall back to DraftKings scoring.
"""
from __future__ import annotations

import hashlib
import json

from app import sleeper_client
from app.config import SLEEPER_LEAGUE_ID

_PTS_ALLOW_TIERS = (  # (key, upper bound inclusive)
    ("pts_allow_0", 0), ("pts_allow_1_6", 6), ("pts_allow_7_13", 13), ("pts_allow_14_20", 20),
    ("pts_allow_21_27", 27), ("pts_allow_28_34", 34), ("pts_allow_35p", float("inf")),
)

# nflverse stats_player_week column -> Sleeper scoring key
_OFFENSE_COLUMNS = {
    "passing_yards": "pass_yd", "passing_tds": "pass_td", "passing_interceptions": "pass_int",
    "rushing_yards": "rush_yd", "rushing_tds": "rush_td",
    "receptions": "rec", "receiving_yards": "rec_yd", "receiving_tds": "rec_td",
    "fumbles_lost_total": "fum_lost",
    "passing_2pt_conversions": "pass_2pt", "rushing_2pt_conversions": "rush_2pt", "receiving_2pt_conversions": "rec_2pt",
    "special_teams_tds": "st_td", "fumble_recovery_tds": "fum_rec_td",
}
_YARDAGE_BONUSES = (("passing_yards", "bonus_pass_yd_300", 300), ("rushing_yards", "bonus_rush_yd_100", 100),
                    ("receiving_yards", "bonus_rec_yd_100", 100))
# nflverse stats_team_week column(s) -> Sleeper scoring key
_DST_COLUMNS = {
    "def_sacks": "sack", "def_interceptions": "int", "fumble_recovery_opp": "fum_rec", "def_safeties": "safe",
    "def_fumbles_forced": "ff", "def_tds": "def_td",
}
_DST_BLOCKS = ("def_punt_blocks", "def_pat_blocks", "def_fg_blocks")


async def get_scoring() -> dict[str, float] | None:
    """The league's scoring_settings, or None if Sleeper can't be reached."""
    try:
        league = await sleeper_client.get_league(SLEEPER_LEAGUE_ID)
    except Exception:
        return None
    scoring = (league or {}).get("scoring_settings")
    return {k: float(v) for k, v in scoring.items()} if scoring else None


def scoring_key(scoring: dict | None) -> str:
    """A short, stable id for a scoring table, for cache keys."""
    if not scoring:
        return "dk"
    return hashlib.sha1(json.dumps(scoring, sort_keys=True).encode()).hexdigest()[:10]


def _f(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def points_allowed_bonus(points_allowed: float | None, scoring: dict) -> float:
    if points_allowed is None:
        return 0.0
    for key, upper in _PTS_ALLOW_TIERS:
        if points_allowed <= upper:
            return scoring.get(key, 0.0)
    return 0.0


def line_points(stats: dict, scoring: dict) -> float:
    """A projected stat line scored the way Sleeper scores it for the league.
    Sleeper's DEF lines carry the projected points-allowed tier as a
    pts_allow_* indicator; if only pts_allow is present, its tier is used."""
    pts = sum(_f(stats, k) * w for k, w in scoring.items())
    if "pts_allow" in stats and not any(k in stats for k, _ in _PTS_ALLOW_TIERS):
        pts += points_allowed_bonus(_f(stats, "pts_allow"), scoring)
    return round(pts, 2)


def offense_points(row: dict, scoring: dict) -> float:
    """row: a stats_player_week_{season}.csv record."""
    pts = sum(_f(row, col) * scoring.get(key, 0.0) for col, key in _OFFENSE_COLUMNS.items())
    for col, key, threshold in _YARDAGE_BONUSES:
        if _f(row, col) >= threshold:
            pts += scoring.get(key, 0.0)
    return round(pts, 2)


def dst_points(row: dict, points_allowed: float | None, scoring: dict) -> float:
    """row: a stats_team_week_{season}.csv record."""
    pts = sum(_f(row, col) * scoring.get(key, 0.0) for col, key in _DST_COLUMNS.items())
    pts += sum(_f(row, col) for col in _DST_BLOCKS) * scoring.get("blk_kick", 0.0)
    pts += points_allowed_bonus(points_allowed, scoring)
    return round(pts, 2)
