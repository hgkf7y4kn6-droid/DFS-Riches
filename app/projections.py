"""Proj: DraftKings points from each player's projected stat line, lightly
adjusted for how this week's opponent has fared against expectations.

1. The line. Sleeper's week-specific projected stat line (rushing and
   receiving yards, receptions, touchdowns, passing, turnovers; sacks,
   takeaways and points allowed for defenses) run through DraftKings'
   scoring. The 100/300-yard bonuses are left out: applied to a projected
   mean they made the projection run high. Backtested on 2,950 player-games
   (2025 Weeks 4-17 + 2026 Weeks 1-2) against actual DK points: mean
   absolute error 5.83 with +0.06 bias, vs 6.18 for a trailing 8-game DK
   average and 6.54 for trailing 3 games.

2. The matchup adjustment. For each defense and position, the DK points
   opposing players actually scored in earlier weeks this season vs what
   their lines projected. A defense whose RBs have beaten their projections
   nudges this week's RB projections up, and vice versa. It's deliberately
   slight -- shrunk by sample size (n games / (n + 4)), half-strength, capped
   at +-5% -- because that's what helped in the 2025 backtest (MAE 5.716 ->
   5.709); stronger versions, or adjusting on a player's own record vs his
   projections, made projections worse (regression to the mean).

3. Weather (app.weather). Outdoor games only: the projected line rescored
   with weather-scaled stats (passing/receiving yards and TDs, rushing yards
   and TDs), using effects fit on 2016-2025 games and applied only to the
   extent projections don't already price weather in
   (scripts/weather_effects.py). DSTs use the fitted DST-points effect.

Players without a Sleeper line (kickers, deep backups) fall back to
DraftKings' season FPPG.
"""
from __future__ import annotations

from dataclasses import dataclass

from app import dk_scoring, weather
from app import nflverse_client as nc
from app import sleeper_client
from app.cache import cached_fetch, memoize_async
from app.config import TTL_PROJECTIONS

SKILL = ("QB", "RB", "WR", "TE")
MIN_LINE_POINTS = 5.0        # only meaningful projections feed the defense's over/under record
MIN_ROLE_PROJ = 3.0          # below this, a skill player isn't projected for a real role this week
SHRINK_GAMES = 4
STRENGTH = 0.5
MAX_ADJUST = 0.05


def dk_points_from_line(stats: dict, position: str) -> float:
    g = lambda k: float(stats.get(k) or 0)  # noqa: E731
    if position in ("DST", "DEF"):
        pts = g("sack") + 2 * (g("int") + g("fum_rec") + g("safe") + g("blk_kick")) + 6 * (g("def_td") + g("st_td"))
        pts += dk_scoring._points_allowed_bonus(g("pts_allow")) if "pts_allow" in stats else 0.0
        return round(pts, 2)
    pts = g("pass_yd") * 0.04 + g("pass_td") * 4 - g("pass_int")
    pts += g("rush_yd") * 0.1 + g("rush_td") * 6
    pts += g("rec") + g("rec_yd") * 0.1 + g("rec_td") * 6
    pts -= g("fum_lost")
    pts += 2 * (g("pass_2pt") + g("rush_2pt") + g("rec_2pt"))
    return round(pts, 2)


def describe_line(stats: dict, position: str) -> str:
    g = lambda k: float(stats.get(k) or 0)  # noqa: E731
    if position in ("DST", "DEF"):
        parts = [f"{g('sack'):.1f} sacks", f"{g('int') + g('fum_rec'):.1f} takeaways", f"{g('pts_allow'):.1f} pts allowed"]
    else:
        parts = []
        if g("pass_att") >= 5:
            parts += [f"{g('pass_yd'):.0f} pass yds", f"{g('pass_td'):.1f} pass TD", f"{g('pass_int'):.1f} INT"]
        if g("rush_att") >= 1.5:
            parts += [f"{g('rush_yd'):.0f} rush yds", f"{g('rush_td'):.1f} rush TD"]
        if g("rec") >= 0.8:
            parts += [f"{g('rec'):.1f} rec", f"{g('rec_yd'):.0f} rec yds", f"{g('rec_td'):.1f} rec TD"]
    return ", ".join(parts)


async def defense_vs_expectation(season: int, week: int) -> dict[str, list]:
    """"DEF|POS" -> [actual DK pts, projected DK pts, games] for opposing
    players with a meaningful line, over this season's weeks before `week`."""

    async def fetch() -> dict[str, list]:
        actual: dict[tuple[int, str], tuple[float, str]] = {}
        for r in await nc._fetch_player_week_rows(season):
            w = nc._to_int(r.get("week"))
            if w is None or w >= week or r.get("position") not in SKILL or r.get("season_type", "REG") != "REG":
                continue
            actual[(w, nc.player_key(r["player_display_name"], r["position"]))] = (
                dk_scoring.dk_offense_points(r), nc.to_app_team(r.get("opponent_team", "")))
        out: dict[str, list] = {}
        for w in range(1, week):
            for line in (await sleeper_client.get_projection_lines(season, w)).values():
                pos = line.get("position")
                if pos not in SKILL or not line.get("name"):
                    continue
                proj = dk_points_from_line(line["stats"], pos)
                hit = actual.get((w, nc.player_key(line["name"], pos)))
                if proj < MIN_LINE_POINTS or hit is None:
                    continue   # no line worth grading, or didn't play (injury, not matchup)
                pts, opp = hit
                rec = out.setdefault(f"{opp}|{pos}", [0.0, 0.0, []])
                rec[0] += pts
                rec[1] += proj
                if w not in rec[2]:
                    rec[2].append(w)
        return {k: [round(a, 2), round(p, 2), len(ws)] for k, (a, p, ws) in out.items()}

    if week <= 1:
        return {}
    try:
        return await cached_fetch(f"defense_vs_expectation_{season}_{week}", TTL_PROJECTIONS, fetch)
    except Exception:
        return {}


def matchup_adjustment(record: list | None) -> float:
    if not record or record[1] <= 0:
        return 1.0
    actual, projected, games = record
    shrink = games / (games + SHRINK_GAMES)
    return round(1 + max(-MAX_ADJUST, min(MAX_ADJUST, STRENGTH * shrink * (actual / projected - 1))), 3)


@dataclass
class ProjectionContext:
    lines: dict[str, dict]
    vs_expectation: dict[str, list]


@memoize_async(120)
async def build_context(season: int, week: int) -> ProjectionContext:
    try:
        lines = await sleeper_client.get_projection_lines(season, week)
    except Exception:
        lines = {}
    return ProjectionContext(lines=lines, vs_expectation=await defense_vs_expectation(season, week))


def weather_note(w: dict, factor: float) -> str:
    return (f"Weather ({w.get('summary')}): x{factor:.2f}"
            + (" -- long-range forecast, half strength" if w.get("long_range") else ""))


def project(ctx: ProjectionContext, *, sleeper_id: str | None, position: str, opponent: str,
            fallback: float | None, game_weather: dict | None = None) -> tuple[float, list[str]]:
    """(DK points, one line of explanation per step) for one player."""
    line = ctx.lines.get(sleeper_id) if sleeper_id else None
    base = dk_points_from_line(line["stats"], position) if line and line.get("stats") else 0.0
    if base <= 0:
        value = round(fallback or 0.0, 2)
        return value, [f"No projected stat line this week; DK season FPPG {value:.1f}"]

    notes = [f"Line: {describe_line(line['stats'], position)} = {base:.1f} DK pts"]
    if position in SKILL:
        record = ctx.vs_expectation.get(f"{opponent}|{position}")
        m = matchup_adjustment(record)
        if record and m != 1.0:
            actual, projected, games = record
            notes.append(f"vs {opponent} this season: {position}s have scored {actual / projected - 1:+.0%} vs their "
                         f"projections ({games} game{'s' if games != 1 else ''}) -> x{m:.2f}")
        base *= m
    factor = weather.player_factor(game_weather, position, line["stats"], dk_points_from_line)
    if abs(factor - 1) >= 0.01:
        notes.append(weather_note(game_weather, factor))
        base *= factor
    return round(base, 2), notes


def has_projected_role(ctx: ProjectionContext, sleeper_id: str | None, position: str) -> bool:
    """False for a QB/RB/WR/TE whose projected line this week is missing or
    under MIN_ROLE_PROJ -- a backup or inactive, whatever last season's
    numbers say. True when there are no lines at all (data unavailable), and
    for positions without lines here (kickers)."""
    if position not in SKILL or not ctx.lines:
        return True
    line = ctx.lines.get(sleeper_id) if sleeper_id else None
    return bool(line) and dk_points_from_line(line.get("stats") or {}, position) >= MIN_ROLE_PROJ
