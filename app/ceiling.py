"""Ceiling: an estimate of a player's 85th-percentile DraftKings score this
week -- a score they'd reach or beat roughly one game in seven.

    ceiling = history x matchup x game environment x breakdown flags x usage

history   The player's own last HISTORY_GAMES games (nflverse box scores run
          through DK scoring), recency-weighted: mean + 1.04 x spread, the
          normal 85th percentile. The spread is blended with PRIOR_GAMES
          pseudo-games of the position's typical game-to-game variability
          (measured from the same data), so a 2-game sample can't produce a
          wild ceiling.
matchup   DK points the opponent allowed to this position over its last
          MATCHUP_WINDOW games vs the league average (DST: the opponent
          offense's points scored vs league average).
game env  The team's implied total this week vs the slate average (DST: the
          opponent's implied total, inverted).
breakdown The same flags the Week Breakdown page raises: pass/rush funnel
          defense, both offenses top-10 pace, yards/play efficiency mismatch.
usage     The player's share of team targets + carries over the last 3 games
          vs the last 8 -- a growing role raises the ceiling (RB/WR/TE).

Every multiplier is shrunk toward 1.0 and clamped (~15% max each), and
their product is capped at -20%/+25% since matchup and implied total
partly measure the same thing.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from app import nflverse_client as nc
from app.models import WeekSchedule

HISTORY_GAMES = 12
RECENCY_DECAY = 0.85  # each older game counts 15% less than the one after it
PRIOR_GAMES = 4
MAX_COMBINED, MIN_COMBINED = 1.25, 0.80  # matchup and implied total overlap, so cap the product
Z_85 = 1.04
MATCHUP_WINDOW = 8
MATCHUP_MIN_GAMES = 3
USAGE_RECENT, USAGE_BASE, USAGE_MIN_GAMES = 3, 8, 4
TOP_RANK = 10
BOTTOM_RANK = 23  # bottom 10 of 32
DEFAULT_CV = 0.6

_RANK_METRICS = {
    "opp_pass_pct_allowed": True,
    "opp_rush_pct_allowed": True,
    "plays": True,
    "yards_per_play": True,
    "yards_allowed_per_play": False,
}


@dataclass
class CeilingContext:
    season: int
    week: int
    players: dict
    def_vs_pos: dict
    dst_index: dict
    league_allowed: dict[str, float]
    cv_by_pos: dict[str, float]
    implied: dict[str, float]
    slate_avg_implied: float | None
    ranks: dict[str, dict[str, int]]
    points_for: dict[str, float]
    league_points_for: float | None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _shrunk(ratio: float, weight: float, lo: float, hi: float) -> float:
    return round(_clamp(1 + weight * (ratio - 1), lo, hi), 3)


def _typical_cv(series_list, season: int, week: int) -> float | None:
    cvs = []
    for entries in series_list:
        vals = nc.recent_values(entries, season, week, 16)
        if len(vals) >= 6:
            mean = statistics.fmean(vals)
            if mean >= 3:
                cvs.append(statistics.pstdev(vals) / mean)
    return round(statistics.median(cvs), 3) if cvs else None


async def build_context(season: int, week: int, schedule: WeekSchedule) -> CeilingContext:
    log = await nc.get_player_game_log_index(season)
    dst_index = await nc.get_team_dst_trailing_index(season)
    team_index = await nc.get_team_context_trailing_index(season)

    players, def_vs_pos = log["players"], log["def_vs_pos"]

    league_allowed: dict[str, float] = {}
    for pos in nc._SKILL_POSITIONS:
        avgs = [statistics.fmean(v) for d in def_vs_pos.values()
                if (v := nc.recent_values(d.get(pos, []), season, week, MATCHUP_WINDOW))]
        if avgs:
            league_allowed[pos] = statistics.fmean(avgs)

    by_pos: dict[str, list] = {}
    for key, entries in players.items():
        by_pos.setdefault(key.rsplit("|", 1)[1], []).append(entries)
    cv_by_pos = {pos: cv for pos, series in by_pos.items() if (cv := _typical_cv(series, season, week))}
    if (dst_cv := _typical_cv(dst_index.values(), season, week)):
        cv_by_pos["DST"] = dst_cv

    implied: dict[str, float] = {}
    for g in schedule.games:
        if g.context and g.context.away_implied_total is not None:
            implied[g.away] = g.context.away_implied_total
            implied[g.home] = g.context.home_implied_total

    points_for = {t: v for t in team_index
                  if (v := nc.team_trailing(team_index, t, "points_for", season, week, MATCHUP_WINDOW)) is not None}

    return CeilingContext(
        season=season,
        week=week,
        players=players,
        def_vs_pos=def_vs_pos,
        dst_index=dst_index,
        league_allowed=league_allowed,
        cv_by_pos=cv_by_pos,
        implied=implied,
        slate_avg_implied=statistics.fmean(implied.values()) if implied else None,
        ranks={m: nc.rank_teams(team_index, m, season, week, n=8, descending=d) for m, d in _RANK_METRICS.items()},
        points_for=points_for,
        league_points_for=statistics.fmean(points_for.values()) if points_for else None,
    )


def _weighted_stats(vals: list[float]) -> tuple[float, float, float]:
    """Recency-weighted (mean, sd, effective sample size); vals oldest first."""
    weights = [RECENCY_DECAY ** (len(vals) - 1 - i) for i in range(len(vals))]
    total = sum(weights)
    mean = sum(w * v for w, v in zip(weights, vals)) / total
    var = sum(w * (v - mean) ** 2 for w, v in zip(weights, vals)) / total
    return mean, math.sqrt(var), total**2 / sum(w * w for w in weights)


def _history(ctx: CeilingContext, entries: list, position: str, fallback_mean: float | None):
    vals = nc.recent_values(entries, ctx.season, ctx.week, HISTORY_GAMES)
    cv = ctx.cv_by_pos.get(position, DEFAULT_CV)
    if vals:
        mean, own_sd, n_eff = _weighted_stats(vals)
    elif fallback_mean:
        mean, own_sd, n_eff = fallback_mean, 0.0, 0.0
    else:
        return None, None
    sd = math.sqrt((n_eff * own_sd**2 + PRIOR_GAMES * (cv * mean) ** 2) / (n_eff + PRIOR_GAMES))
    base = max(0.0, mean + Z_85 * sd)
    n = len(vals)
    if n:
        note = f"History: {base:.1f} (85th pct of last {n} game{'s' if n != 1 else ''}, recency-weighted avg {mean:.1f})"
    else:
        note = f"History: {base:.1f} (no box-score games; from DK FPPG {mean:.1f})"
    return base, note


def player_ceiling(
    ctx: CeilingContext, *, name: str, position: str, team: str, opponent: str, fallback_mean: float | None
) -> tuple[float | None, list[str]]:
    is_dst = position == "DST"
    entries = ctx.dst_index.get(team, []) if is_dst else ctx.players.get(nc.player_key(name, position), [])
    base, history_note = _history(ctx, entries, position, fallback_mean)
    if base is None:
        return None, []
    notes = [history_note]
    mult = 1.0

    # Matchup
    if is_dst:
        opp_pf = ctx.points_for.get(opponent)
        if opp_pf and ctx.league_points_for:
            m = _shrunk(ctx.league_points_for / opp_pf, 0.5, 0.85, 1.15)
            mult *= m
            notes.append(f"Matchup x{m:.2f}: {opponent} score {opp_pf:.1f} pts/gm (L8) vs {ctx.league_points_for:.1f} avg")
    else:
        allowed = nc.recent_values(ctx.def_vs_pos.get(opponent, {}).get(position, []), ctx.season, ctx.week, MATCHUP_WINDOW)
        league = ctx.league_allowed.get(position)
        if len(allowed) >= MATCHUP_MIN_GAMES and league:
            avg = statistics.fmean(allowed)
            m = _shrunk(avg / league, 0.5, 0.85, 1.15)
            mult *= m
            notes.append(f"Matchup x{m:.2f}: {opponent} allow {avg:.1f} DK pts/gm to {position}s (L8) vs {league:.1f} avg")

    # Game environment
    avg_imp = ctx.slate_avg_implied
    side = opponent if is_dst else team
    imp = ctx.implied.get(side)
    if imp and avg_imp:
        m = _shrunk((avg_imp / imp) if is_dst else (imp / avg_imp), 0.6, 0.85, 1.15)
        mult *= m
        notes.append(f"Game env x{m:.2f}: {side} implied {imp:g} vs {avg_imp:.1f} slate avg")

    # Week Breakdown flags
    r = ctx.ranks
    flags: list[tuple[float, str]] = []
    if is_dst:
        ypp = r["yards_per_play"].get(opponent)
        if ypp and ypp >= BOTTOM_RANK:
            flags.append((0.04, f"{opponent} offense #{ypp} in yards/play"))
    else:
        pass_rank = r["opp_pass_pct_allowed"].get(opponent)
        rush_rank = r["opp_rush_pct_allowed"].get(opponent)
        if position in ("QB", "WR", "TE") and pass_rank and pass_rank <= TOP_RANK:
            flags.append((0.04, f"{opponent} D is a pass funnel (#{pass_rank})"))
        if position == "RB" and rush_rank and rush_rank <= TOP_RANK:
            flags.append((0.04, f"{opponent} D is a rush funnel (#{rush_rank})"))
        tp, op = r["plays"].get(team), r["plays"].get(opponent)
        if tp and op and tp <= TOP_RANK and op <= TOP_RANK:
            flags.append((0.03, "both offenses top-10 pace"))
        ypp, ypa = r["yards_per_play"].get(team), r["yards_allowed_per_play"].get(opponent)
        if ypp and ypa and ypp <= TOP_RANK and ypa >= BOTTOM_RANK:
            flags.append((0.03, f"efficiency mismatch ({team} #{ypp} yds/play vs {opponent} D #{ypa})"))
    if flags:
        m = round(1 + min(sum(f[0] for f in flags), 0.08), 3)
        mult *= m
        notes.append(f"Breakdown x{m:.2f}: " + "; ".join(f[1] for f in flags))

    # Team utilization
    if position in ("RB", "WR", "TE"):
        base_shares = nc.recent_values(entries, ctx.season, ctx.week, USAGE_BASE, col=3)
        recent_shares = nc.recent_values(entries, ctx.season, ctx.week, USAGE_RECENT, col=3)
        if len(base_shares) >= USAGE_MIN_GAMES and statistics.fmean(base_shares) > 0:
            s3, s8 = statistics.fmean(recent_shares), statistics.fmean(base_shares)
            m = _shrunk(s3 / s8, 0.5, 0.9, 1.15)
            mult *= m
            notes.append(f"Usage x{m:.2f}: {s3:.0%} of team targets+carries (L3) vs {s8:.0%} (L8)")

    capped = _clamp(mult, MIN_COMBINED, MAX_COMBINED)
    if capped != mult:
        notes.append(f"Combined adjustments capped at x{capped:.2f} (were x{mult:.2f})")
    return round(base * capped, 1), notes
