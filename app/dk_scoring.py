"""Computes DraftKings Classic fantasy points from real box-score stats
(nflverse's stats_player_week / stats_team_week), using DraftKings' own
published scoring rules. This is what lets the app show a trailing
3/6/9-game DK-style FPPG rather than only DraftKings' single season-long
FPPG number (which is all their API exposes).

DraftKings Classic scoring (offense):
  Passing: 0.04 pt/yard, 4 pt/TD, -1 pt/INT, +3 for 300+ yard game
  Rushing: 0.1 pt/yard, 6 pt/TD, +3 for 100+ yard game
  Receiving: 1 pt/reception (full PPR), 0.1 pt/yard, 6 pt/TD, +3 for 100+ yard game
  -1 pt/fumble lost, +2 pt/2-point conversion, +6 pt/return or fumble-recovery TD

DraftKings Classic scoring (DST, per team per game):
  +1/sack, +2/interception, +2/fumble recovery, +2/safety, +2/blocked kick,
  +6/defensive or return TD, then points-allowed tiers:
  0 -> +10, 1-6 -> +7, 7-13 -> +4, 14-20 -> +1, 21-27 -> 0, 28-34 -> -1, 35+ -> -4
"""
from __future__ import annotations


def _f(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def dk_offense_points(row: dict) -> float:
    """row: a stats_player_week_{season}.csv record (dict of strings)."""
    points = 0.0

    passing_yards = _f(row, "passing_yards")
    points += passing_yards * 0.04
    points += _f(row, "passing_tds") * 4
    points += _f(row, "passing_interceptions") * -1
    if passing_yards >= 300:
        points += 3

    rushing_yards = _f(row, "rushing_yards")
    points += rushing_yards * 0.1
    points += _f(row, "rushing_tds") * 6
    if rushing_yards >= 100:
        points += 3

    receiving_yards = _f(row, "receiving_yards")
    points += _f(row, "receptions") * 1
    points += receiving_yards * 0.1
    points += _f(row, "receiving_tds") * 6
    if receiving_yards >= 100:
        points += 3

    points += _f(row, "fumbles_lost_total") * -1
    points += (
        _f(row, "passing_2pt_conversions")
        + _f(row, "rushing_2pt_conversions")
        + _f(row, "receiving_2pt_conversions")
    ) * 2
    points += _f(row, "special_teams_tds") * 6
    points += _f(row, "fumble_recovery_tds") * 6

    return round(points, 2)


def _points_allowed_bonus(points_allowed: float | None) -> float:
    if points_allowed is None:
        return 0.0
    if points_allowed == 0:
        return 10.0
    if points_allowed <= 6:
        return 7.0
    if points_allowed <= 13:
        return 4.0
    if points_allowed <= 20:
        return 1.0
    if points_allowed <= 27:
        return 0.0
    if points_allowed <= 34:
        return -1.0
    return -4.0


def dk_dst_points(row: dict, points_allowed: float | None) -> float:
    """row: a stats_team_week_{season}.csv record (dict of strings)."""
    points = 0.0
    points += _f(row, "def_sacks") * 1
    points += _f(row, "def_interceptions") * 2
    points += _f(row, "fumble_recovery_opp") * 2
    points += _f(row, "def_safeties") * 2
    points += (_f(row, "def_punt_blocks") + _f(row, "def_pat_blocks") + _f(row, "def_fg_blocks")) * 2
    points += _f(row, "def_tds") * 6
    points += _points_allowed_bonus(points_allowed)
    return round(points, 2)
