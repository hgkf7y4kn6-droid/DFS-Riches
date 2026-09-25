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
        each team's play volume (plays/game). The same rows' defensive
        columns, combined with points allowed from games.csv, feed
        app.dk_scoring.dk_dst_points for a team's real trailing DST
        fantasy scoring.
  - releases/pbp/play_by_play_{season}.csv.gz (nflverse/nflverse-data)
        Every play. Aggregated per team-game into neutral-situation tempo
        (seconds per snap) and dropback rate, for offense and for the
        defense facing it -- see neutral_stats_from_pbp. Plays/game alone
        measures volume, not how fast or pass-happy a team operates.
  - releases/stats_player/stats_player_week_{season}.csv (nflverse/nflverse-data)
        One row per skill-position player per game with real box-score
        stats. Joined onto a DK salary row by normalized name + position
        (see player_key below) and fed through app.dk_scoring.dk_offense_points
        for real trailing DK-style FPPG.

nflverse spells the Rams "LA"; every other team code already matches the
abbreviations Sleeper/DraftKings use (see app.config.NFLVERSE_TO_APP_TEAM).
"""
from __future__ import annotations

import asyncio
import csv
import gzip
import io
from typing import Any, Iterable

import httpx

from app import dk_scoring
from app.cache import cached_fetch
from app.config import (
    DEFAULT_SEASON,
    NFLVERSE_GAMES_CSV_URL,
    NFLVERSE_PBP_URL_TMPL,
    NFLVERSE_PLAYER_STATS_URL_TMPL,
    NFLVERSE_TEAM_STATS_URL_TMPL,
    NFLVERSE_TO_APP_TEAM,
    TTL_NFLVERSE_GAMES,
    TTL_NFLVERSE_PBP_PAST,
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


def _is_neutral(qtr: float | None, score_diff: float | None, half_secs: float | None) -> bool:
    """Sharp Football's neutral definition: quarters 1-3, score within 14
    points, excluding the final two minutes of the half."""
    return (
        qtr in (1, 2, 3)
        and score_diff is not None and abs(score_diff) <= 14
        and half_secs is not None and half_secs > 120
    )


def _clock_kept_running(prev: dict) -> bool:
    """True if the game clock ran from the end of this play to the next snap,
    so the elapsed game clock between the two snaps measures the offense's
    tempo (play duration + time to the next snap) rather than a stoppage."""
    return (
        (prev["play_type"] == "run" or (prev["play_type"] == "pass" and prev.get("complete_pass") == "1"))
        and prev.get("out_of_bounds") == "0"
        and prev.get("penalty") in ("0", "NA", "")
        and prev.get("timeout") in ("0", "NA", "")
        and prev.get("touchdown") == "0"
        and prev.get("fumble_lost") == "0"
    )


def neutral_stats_from_pbp(rows: Iterable[dict]) -> dict[str, dict]:
    """Aggregates nflverse play-by-play rows (dicts of strings, in play
    order) into per team-game neutral-situation stats, keyed "week|team":

    offense  neutral_pass_rate  dropbacks (incl. sacks & scrambles) / scrimmage plays
             neutral_secs       seconds of game clock from snap to snap when the
                                clock kept running, adjusted for the league's
                                typical gap after a run vs a completion
    defense  opp_neutral_pass_rate  the same dropback rate for offenses it faced
    """
    off: dict[str, dict[str, float]] = {}
    de: dict[str, dict[str, float]] = {}
    gaps_by_kind = {"run": [0.0, 0], "pass": [0.0, 0]}
    prev: dict | None = None
    for r in rows:
        if r.get("play_type") not in ("pass", "run"):
            continue
        week = _to_int(r.get("week"))
        team, opp = to_app_team(r.get("posteam", "")), to_app_team(r.get("defteam", ""))
        if week is None or not team:
            prev = r
            continue
        if _is_neutral(_to_float(r.get("qtr")), _to_float(r.get("score_differential")), _to_float(r.get("half_seconds_remaining"))):
            dropback = 1.0 if r.get("qb_dropback") == "1" else 0.0
            o = off.setdefault(f"{week}|{team}", {"drop": 0.0, "plays": 0, "run_sum": 0.0, "run_n": 0, "pass_sum": 0.0, "pass_n": 0})
            o["drop"] += dropback
            o["plays"] += 1
            d = de.setdefault(f"{week}|{opp}", {"drop": 0.0, "plays": 0})
            d["drop"] += dropback
            d["plays"] += 1
            if (prev is not None and prev.get("game_id") == r.get("game_id") and prev.get("drive") == r.get("drive")
                    and prev.get("qtr") == r.get("qtr") and _clock_kept_running(prev)):
                start, end = _to_float(prev.get("game_seconds_remaining")), _to_float(r.get("game_seconds_remaining"))
                if start is not None and end is not None and 5 <= start - end <= 60:
                    kind = "run" if prev["play_type"] == "run" else "pass"
                    o[f"{kind}_sum"] += start - end
                    o[f"{kind}_n"] += 1
                    gaps_by_kind[kind][0] += start - end
                    gaps_by_kind[kind][1] += 1
        prev = r

    total_n = gaps_by_kind["run"][1] + gaps_by_kind["pass"][1]
    league = (gaps_by_kind["run"][0] + gaps_by_kind["pass"][0]) / total_n if total_n else None
    kind_mean = {k: (s / n if n else 0.0) for k, (s, n) in gaps_by_kind.items()}

    offense = {}
    for key, o in off.items():
        n = o["run_n"] + o["pass_n"]
        secs = None
        if n and league is not None:
            residual = (o["run_sum"] - o["run_n"] * kind_mean["run"]) + (o["pass_sum"] - o["pass_n"] * kind_mean["pass"])
            secs = round(league + residual / n, 2)
        offense[key] = {"neutral_pass_rate": round(o["drop"] / o["plays"], 4), "neutral_secs": secs}
    defense = {key: {"opp_neutral_pass_rate": round(d["drop"] / d["plays"], 4)} for key, d in de.items()}
    return {"offense": offense, "defense": defense}


async def get_pbp_aggregates(season: int, current_season: int | None = None) -> dict:
    """One parse of a season's play-by-play feeds every per-play aggregate:
    {"neutral": neutral_stats_from_pbp(...), "trenches": app.trenches
    TrenchAccumulator counts (joined to FTN charting when published)}."""
    from app import trenches

    async def fetch() -> dict:
        ftn = await trenches.get_ftn_index(season)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(NFLVERSE_PBP_URL_TMPL.format(season=season), headers=_HEADERS, timeout=120)
            resp.raise_for_status()
            raw = resp.content

        def parse() -> dict:
            text = io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(raw)), encoding="utf-8")
            acc = trenches.TrenchAccumulator(ftn)

            def tap(rows):
                for r in rows:
                    acc.add(r)
                    yield r
            return {"neutral": neutral_stats_from_pbp(tap(csv.DictReader(text))), "trenches": acc.result()}

        # ~50k plays x ~370 columns for a full season: keep it off the event loop.
        return await asyncio.to_thread(parse)

    current = current_season if current_season is not None else DEFAULT_SEASON
    ttl = TTL_NFLVERSE_TEAM_STATS if season >= current else TTL_NFLVERSE_PBP_PAST
    try:
        return await cached_fetch(f"nflverse_pbp_aggregates_v1_{season}", ttl, fetch)
    except Exception:
        return {"neutral": {"offense": {}, "defense": {}}, "trenches": {}}


async def _team_week_neutral(season: int, current_season: int) -> dict[str, dict]:
    return (await get_pbp_aggregates(season, current_season))["neutral"]


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


_SKILL_POSITIONS = ("QB", "RB", "WR", "TE")


def recent_values(entries: list[list], season: int, week: int, n: int, col: int = 2) -> list[float]:
    """The col-th value of the last n entries strictly before (season, week),
    oldest first, skipping entries whose value is None."""
    prior = sorted(e for e in entries if (e[0], e[1]) < (season, week) and e[col] is not None)
    return [e[col] for e in prior[-n:]]


async def get_player_game_log_index(season: int) -> dict:
    """Per-game data behind the Ceiling column, for this season and the prior:

    players:    player_key -> [[season, week, dk_points, opportunity_share], ...]
                opportunity_share = (targets + carries) / (team pass attempts +
                team carries); None for QBs.
    def_vs_pos: defense team -> position -> [[season, week, dk_points_allowed], ...]
                the summed DK points every player at that position scored
                against that defense in that game.
    """

    async def fetch() -> dict:
        players: dict[str, list[list]] = {}
        def_vs_pos: dict[str, dict[str, dict[tuple, float]]] = {}
        for szn in (season - 1, season):
            team_opps: dict[tuple[int, str], float] = {}
            for row in await _fetch_team_week_rows(szn):
                week = _to_int(row.get("week"))
                if week is None:
                    continue
                opps = (_to_float(row.get("attempts")) or 0.0) + (_to_float(row.get("carries")) or 0.0)
                team_opps[(week, to_app_team(row.get("team", "")))] = opps

            for row in await _fetch_player_week_rows(szn):
                name, position = row.get("player_display_name"), row.get("position")
                week = _to_int(row.get("week"))
                if not name or position not in _SKILL_POSITIONS or week is None:
                    continue
                points = dk_scoring.dk_offense_points(row)
                share = None
                if position != "QB":
                    denom = team_opps.get((week, to_app_team(row.get("team", ""))))
                    if denom:
                        touches = (_to_float(row.get("targets")) or 0.0) + (_to_float(row.get("carries")) or 0.0)
                        share = round(touches / denom, 4)
                players.setdefault(player_key(name, position), []).append([szn, week, points, share])

                opp = to_app_team(row.get("opponent_team", ""))
                if opp:
                    games = def_vs_pos.setdefault(opp, {}).setdefault(position, {})
                    games[(szn, week)] = games.get((szn, week), 0.0) + points

        return {
            "players": players,
            "def_vs_pos": {
                team: {pos: [[s, w, round(p, 2)] for (s, w), p in sorted(games.items())] for pos, games in by_pos.items()}
                for team, by_pos in def_vs_pos.items()
            },
        }

    return await cached_fetch(f"nflverse_player_game_log_index_{season}", TTL_NFLVERSE_TEAM_STATS, fetch)


async def get_week_actuals(season: int, week: int) -> dict:
    """Actual DraftKings points scored in one week, from nflverse box scores:

    players: player_key -> points (QB/RB/WR/TE, and K with Showdown kicker scoring)
    dst:     team -> DST points
    teams:   teams with a box-score row that week, i.e. whose stats are in
    """
    players: dict[str, float] = {}
    for row in await _fetch_player_week_rows(season):
        if _to_int(row.get("week")) != week or not row.get("player_display_name"):
            continue
        position = row.get("position")
        if position in _SKILL_POSITIONS:
            points = dk_scoring.dk_offense_points(row)
        elif position == "K":
            points = dk_scoring.dk_kicker_points(row)
        else:
            continue
        players[player_key(row["player_display_name"], position)] = points

    dst = {team: e[2] for team, entries in (await get_team_dst_trailing_index(season)).items()
           for e in entries if e[0] == season and e[1] == week}
    teams = sorted({to_app_team(r.get("team", "")) for r in await _fetch_team_week_rows(season) if _to_int(r.get("week")) == week})
    return {"players": players, "dst": dst, "teams": teams}


def actual_points(actuals: dict, *, name: str, position: str, team: str, roster_slot: str = "") -> float:
    """A DK player's actual points from get_week_actuals; 0 when they have no
    box-score row (didn't record a stat). Showdown Captains score 1.5x."""
    if position == "DST":
        points = actuals["dst"].get(team, 0.0)
    else:
        points = actuals["players"].get(player_key(name, position), 0.0)
    return round(points * (1.5 if roster_slot == "CPT" else 1.0), 2)


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
    "spread", "total", "implied_total", "plays", "neutral_secs",
    "points_for", "points_against", "yards_per_play", "yards_allowed_per_play",
    "pass_pct", "rush_pct", "opp_pass_pct_allowed", "opp_rush_pct_allowed",
    "sacks_taken", "giveaways",
)


async def _team_week_box_scores(season: int) -> dict[tuple[int, str], dict]:
    """{(week, team): {opponent, plays, yards_per_play, sacks_taken, giveaways}}
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
            "sacks_taken": sacks,
            "giveaways": (_to_float(row.get("passing_interceptions")) or 0.0)
            + sum(_to_float(row.get(k)) or 0.0 for k in ("sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost")),
        }
    return scores


async def get_team_context_trailing_index(season: int) -> dict[str, dict[str, list[list]]]:
    """team -> {metric: [[season,week,value],...]} for each of _TEAM_METRICS,
    combining this season and the prior one. "spread"/"implied_total" are
    from the team's own perspective (negative spread = they were favored)
    regardless of home/away, so a team's trend is comparable game to game.
    "plays" is volume (plays/game, box scores). "neutral_secs" is tempo:
    seconds of game clock from snap to snap in neutral situations (lower =
    faster). "pass_pct"/"rush_pct" are the offense's neutral-situation
    dropback/run rates, and "opp_*_allowed" the same rates for the offenses
    that team's DEFENSE faced -- which defenses funnel opponents to the air
    vs. the ground. Neutral (quarters 1-3, within 14 points, outside the last
    two minutes of the half) keeps game script out of tendencies; see
    neutral_stats_from_pbp."""

    async def fetch() -> dict[str, dict[str, list[list]]]:
        index: dict[str, dict[str, list[list]]] = {}
        for szn in (season - 1, season):
            games = await get_games(szn)
            box_scores = await _team_week_box_scores(szn)
            neutral = await _team_week_neutral(szn, season)

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
                        d["sacks_taken"].append([szn, week, own["sacks_taken"]])
                        d["giveaways"].append([szn, week, own["giveaways"]])

                    opp_box = box_scores.get((week, opp))
                    if opp_box and opp_box["yards_per_play"] is not None:
                        d["yards_allowed_per_play"].append([szn, week, opp_box["yards_per_play"]])

                    n_off = neutral["offense"].get(f"{week}|{team}")
                    if n_off:
                        d["pass_pct"].append([szn, week, n_off["neutral_pass_rate"]])
                        d["rush_pct"].append([szn, week, round(1 - n_off["neutral_pass_rate"], 4)])
                        if n_off["neutral_secs"] is not None:
                            d["neutral_secs"].append([szn, week, n_off["neutral_secs"]])
                    n_def = neutral["defense"].get(f"{week}|{team}")
                    if n_def:
                        d["opp_pass_pct_allowed"].append([szn, week, n_def["opp_neutral_pass_rate"]])
                        d["opp_rush_pct_allowed"].append([szn, week, round(1 - n_def["opp_neutral_pass_rate"], 4)])
        return index

    return await cached_fetch(f"nflverse_team_context_trailing_index_v3_{season}", TTL_NFLVERSE_GAMES, fetch)


def team_trend(index: dict, team: str, metric: str, season: int, week: int) -> dict[str, float | None]:
    """Returns a {"l3":..., "l6":..., "l9":...} dict of trailing averages
    for one team/metric, built from get_team_context_trailing_index."""
    series = index.get(team, {}).get(metric, [])
    return {
        "l3": _trailing_avg(series, season, week, 3),
        "l6": _trailing_avg(series, season, week, 6),
        "l9": _trailing_avg(series, season, week, 9),
    }


# Scheme tendencies change with coordinators every offseason, so once a team
# has this many games this season, these use season-to-date only (as Sharp
# Football's pace page does) instead of reaching back into last season.
TENDENCY_METRICS = frozenset({"neutral_secs", "pass_pct", "rush_pct", "opp_pass_pct_allowed", "opp_rush_pct_allowed"})
MIN_CURRENT_SEASON_GAMES = 2


def _window_avg(entries: list[list], metric: str, season: int, week: int, n: int) -> float | None:
    if metric in TENDENCY_METRICS:
        current = [e[2] for e in entries if e[0] == season and e[1] < week]
        if len(current) >= MIN_CURRENT_SEASON_GAMES:
            return round(sum(current) / len(current), 4)
    return _trailing_avg(entries, season, week, n)


def team_trailing(index: dict, team: str, metric: str, season: int, week: int, n: int = 8) -> float | None:
    """One team/metric's value entering (season, week), from
    get_team_context_trailing_index: the trailing n-game average, or for
    TENDENCY_METRICS the season-to-date average once there are enough games."""
    return _window_avg(index.get(team, {}).get(metric, []), metric, season, week, n)


def rank_teams(
    index: dict, metric: str, season: int, week: int, *, n: int = 8, descending: bool = True
) -> dict[str, int]:
    """team -> 1-based league rank by metric (as team_trailing computes it)
    among all teams that have one. descending=True means higher is
    better/rank 1 (points scored, yards/play); descending=False means
    lower is better/rank 1 (points allowed, yards/play allowed)."""
    values: dict[str, float] = {}
    for team, metrics in index.items():
        v = _window_avg(metrics.get(metric, []), metric, season, week, n)
        if v is not None:
            values[team] = v
    ranked = sorted(values.items(), key=lambda kv: kv[1], reverse=descending)
    return {team: i + 1 for i, (team, _v) in enumerate(ranked)}
