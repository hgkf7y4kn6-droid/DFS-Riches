"""The drill-down view for one game on the Week Breakdown page: the numbers
behind the card, arranged for charts, plus a short plain-English note per
section on what it likely means for the game and for DFS lineups. Every
note is generated here from the real numbers, like the card takeaways.
"""
from __future__ import annotations

import statistics

from app import nflverse_client as nc
from app import trenches
from app.breakdown import WeekData, game_breakdown, load_week
from app.models import Game, GameDetail, LeagueContext, PositionMatchup, TeamStatLine, UsageShare

POSITIONS = ("QB", "RB", "WR", "TE")
USAGE_PLAYERS = 5
EDGE = 0.05          # +-5% vs league average counts as a real strength/weakness
TOP, BOTTOM = 10, 23


def _pct(x: float) -> str:
    return f"{x:+.0%}"


def _vs_avg(x: float, verb: str, noun: str) -> str:
    """(0.08, "gains", "yards per play") -> "gains 8% more yards per play than average"."""
    if abs(x) < 0.015:
        return f"{verb} about as many {noun} as average"
    return f"{verb} {abs(x):.0%} {'more' if x > 0 else 'fewer'} {noun} than average"


def league_context(wd: WeekData) -> LeagueContext:
    def values(metric: str) -> list[float]:
        return [v for t in wd.index if (v := nc.team_trailing(wd.index, t, metric, wd.season, wd.week, 8)) is not None]

    def mean(metric: str) -> float | None:
        v = values(metric)
        return round(statistics.fmean(v), 3) if v else None

    tempo, plays = values("neutral_secs"), values("plays")
    return LeagueContext(
        yards_per_play=mean("yards_per_play"),
        points=mean("points_for"),
        tempo_secs=mean("neutral_secs"),
        tempo_min=min(tempo) if tempo else None,
        tempo_max=max(tempo) if tempo else None,
        plays=mean("plays"),
        plays_min=min(plays) if plays else None,
        plays_max=max(plays) if plays else None,
        pass_rate=mean("pass_pct"),
    )


def defense_vs_positions(wd: WeekData, defense: str) -> list[PositionMatchup]:
    ctx = wd.ceiling_ctx
    out = []
    for pos in POSITIONS:
        allowed_by_team = {
            t: statistics.fmean(v) for t, by_pos in ctx.def_vs_pos.items()
            if (v := nc.recent_values(by_pos.get(pos, []), wd.season, wd.week, 8))
        }
        allowed, league = allowed_by_team.get(defense), ctx.league_allowed.get(pos)
        ranked = sorted(allowed_by_team, key=lambda t: -allowed_by_team[t])
        out.append(PositionMatchup(
            position=pos,
            allowed=round(allowed, 1) if allowed is not None else None,
            league_avg=round(league, 1) if league else None,
            vs_avg=round(allowed / league - 1, 2) if allowed is not None and league else None,  # whole percent: chart and text agree
            rank=ranked.index(defense) + 1 if defense in allowed_by_team else None,
        ))
    return out


def usage_leaders(wd: WeekData, team: str) -> list[UsageShare]:
    rows = []
    for p in wd.players:
        if p.team != team or p.position not in ("RB", "WR", "TE") or p.roster_slot == "CPT":
            continue
        entries = wd.ceiling_ctx.players.get(nc.player_key(p.name, p.position), [])
        s3 = nc.recent_values(entries, wd.season, wd.week, 3, col=3)
        s8 = nc.recent_values(entries, wd.season, wd.week, 8, col=3)
        if not s3 or not any(e[0] == wd.season for e in entries):
            continue
        rows.append(UsageShare(name=p.name, position=p.position, injury=p.injury,
                               share_l3=round(statistics.fmean(s3), 3),
                               share_l8=round(statistics.fmean(s8), 3) if s8 else None))
    return sorted(rows, key=lambda r: -r.share_l3)[:USAGE_PLAYERS]


# --- insights -----------------------------------------------------------------

def vegas_insight(game: Game, implied_rank: dict[str, int], total_rank: int | None, n_games: int) -> str | None:
    c = game.context
    if c is None or c.total_line is None or c.home_spread is None or c.away_implied_total is None:
        return None
    if abs(c.home_spread) < 3:
        script = "A close spread keeps both offenses aggressive all game — good conditions for stacking both sides."
    else:
        fav, dog = (game.home, game.away) if c.home_spread < 0 else (game.away, game.home)
        script = (f"{fav} is favored by {abs(c.home_spread):g}: a lead would lean {fav} on its run game late, "
                  f"while {dog} would likely need to throw more to keep up (a boost for {dog}'s pass catchers).")
    if total_rank is not None and total_rank <= 4:
        env = f"The {total_rank}{'st' if total_rank == 1 else 'nd' if total_rank == 2 else 'rd' if total_rank == 3 else 'th'}-highest total of the week ({c.total_line:g}) makes this a prime game-stack spot."
    elif total_rank is not None and total_rank > n_games - 4:
        env = f"One of the week's lowest totals ({c.total_line:g}): keep exposure to the clearest plays."
    else:
        env = f"A middle-of-the-pack total ({c.total_line:g})."
    return f"{env} {script}"


def offense_insight(team: str, opp: str, off: TeamStatLine, de: TeamStatLine, league: LeagueContext) -> str | None:
    if off.yards_per_play is None or de.yards_allowed_per_play is None or not league.yards_per_play:
        return None
    o = off.yards_per_play / league.yards_per_play - 1
    d = de.yards_allowed_per_play / league.yards_per_play - 1
    lead = f"{team} {_vs_avg(o, 'gains', 'yards per play')}; {opp}'s defense {_vs_avg(d, 'allows', 'yards per play')}."
    if o >= EDGE and d >= EDGE:
        return f"{lead} A clear edge: {team} should move the ball, which boosts its top skill players and makes it a strong stack."
    if o >= EDGE and d <= -EDGE:
        return f"{lead} Strength vs strength: expect {team} closer to its average — favor its highest-usage players over deep stacks."
    if o <= -EDGE and d >= EDGE:
        return f"{lead} {team} has been inefficient but draws a soft defense: a bounce-back spot for its top options."
    if o <= -EDGE and d <= -EDGE:
        return f"{lead} A tough spot for a struggling offense: limit {team} exposure to cheap, high-usage pieces."
    return f"{lead} Near average on both sides, so {team}'s outlook rides on volume and the position matchups below."


def tempo_insight(game: Game, away: TeamStatLine, home: TeamStatLine, league: LeagueContext) -> str | None:
    if away.tempo_rank is None or home.tempo_rank is None:
        return None
    plays = (away.plays_per_game or 0) + (home.plays_per_game or 0)
    avg = 2 * (league.plays or 0)
    snaps = f"Together they average {plays:.0f} plays per game (league: {avg:.0f})."
    if away.tempo_rank <= TOP and home.tempo_rank <= TOP:
        return f"Both offenses play fast before the snap (#{away.tempo_rank} and #{home.tempo_rank} in neutral tempo). {snaps} More snaps raise every player's ceiling — a game-stack environment."
    if away.tempo_rank >= BOTTOM and home.tempo_rank >= BOTTOM:
        return f"Both offenses play slow (#{away.tempo_rank} and #{home.tempo_rank} in neutral tempo). {snaps} Fewer snaps cap ceilings; target only the clearest matchups."
    fast, slow = ((game.away, away), (game.home, home)) if away.tempo_rank < home.tempo_rank else ((game.home, home), (game.away, away))
    return (f"{fast[0]} plays faster (#{fast[1].tempo_rank}, {fast[1].tempo_secs:.1f}s/snap) than {slow[0]} "
            f"(#{slow[1].tempo_rank}, {slow[1].tempo_secs:.1f}s/snap). {snaps}")


def tendency_insight(game: Game, away: TeamStatLine, home: TeamStatLine, league: LeagueContext) -> str | None:
    parts = []
    for team, off, de in ((game.away, away, home), (game.home, home, away)):
        if off.pass_pct is None:
            continue
        s = f"{team} throws on {off.pass_pct:.0%} of neutral plays (league {league.pass_rate:.0%})"
        if de.opp_pass_pct_allowed_rank is not None and de.opp_pass_pct_allowed_rank <= TOP:
            s += f" and faces a pass funnel (#{de.opp_pass_pct_allowed_rank}) — extra volume for its QB and receivers"
        elif de.opp_rush_pct_allowed_rank is not None and de.opp_rush_pct_allowed_rank <= TOP:
            s += f" and faces a rush funnel (#{de.opp_rush_pct_allowed_rank}) — extra carries for its RBs"
        parts.append(s + ".")
    return " ".join(parts) or None


def positions_insight(game: Game, away_def: list[PositionMatchup], home_def: list[PositionMatchup]) -> str | None:
    parts = []
    for offense, defense, rows in ((game.home, game.away, away_def), (game.away, game.home, home_def)):
        known = [r for r in rows if r.vs_avg is not None]
        if not known:
            continue
        best = max(known, key=lambda r: r.vs_avg)
        worst = min(known, key=lambda r: r.vs_avg)
        s = f"{offense}'s best matchup: {best.position}s vs {defense} ({_pct(best.vs_avg)} DK pts allowed)"
        if worst.vs_avg <= -0.10:
            s += f"; toughest: {worst.position}s ({_pct(worst.vs_avg)})"
        parts.append(s + ".")
    if not parts:
        return None
    return " ".join(parts) + " Build around the positions above average; pay up at the below-average ones only for elite volume."


def usage_insight(game: Game, away_usage: list[UsageShare], home_usage: list[UsageShare]) -> str | None:
    parts = []
    for team, rows in ((game.away, away_usage), (game.home, home_usage)):
        if not rows:
            continue
        top = rows[0]
        trend = ""
        if top.share_l8:
            if top.share_l3 > top.share_l8 * 1.05:
                trend = f", up from {top.share_l8:.0%}"
            elif top.share_l3 < top.share_l8 * 0.95:
                trend = f", down from {top.share_l8:.0%}"
        if top.share_l3 >= 0.30:
            parts.append(f"{top.name} handles {top.share_l3:.0%} of {team}'s targets + carries{trend} — a locked-in workload that holds up in any script.")
        else:
            parts.append(f"{team} spreads the ball around (leader: {top.name}, {top.share_l3:.0%}{trend}), so its skill players are less predictable.")
    return " ".join(parts) or None


def weather_insight(game: Game) -> str | None:
    w = game.weather or {}
    if not w:
        return None
    if w.get("roof") == "dome":
        return f"Indoors at {w.get('venue')}: no weather adjustment."
    if w.get("roof") == "retractable":
        return f"{w.get('venue')} has a retractable roof -- {w.get('summary')}. No weather adjustment."
    if not w.get("available"):
        return f"{w.get('summary')} for {w.get('venue') or 'this venue'}."
    lead = "Played in" if w.get("observed") else "Kickoff forecast"
    text = f"{lead} at {w.get('venue')}: {w.get('summary')}."
    if w.get("observed"):
        return text
    if w.get("impact"):
        text += f" Projections adjusted for it: {w['impact']} (fit on 2016-2025 games)."
    elif w.get("severity") in ("poor", "severe"):
        text += " Historically, conditions like these barely move projections."
    else:
        text += " No meaningful weather effect."
    if w.get("long_range"):
        text += " Long-range forecast: adjustments at half strength until it firms up."
    return text


def trench_section(tw: dict | None, game: Game) -> dict | None:
    """Both teams' unit ranks and scheme rates, each offense's matchup vs the
    other defense, and a short DFS read built from the strongest edges."""
    away, home = trenches.team_card(tw, game.away), trenches.team_card(tw, game.home)
    if not away or not home:
        return None
    away_off, home_off = trenches.matchup(tw, game.away, game.home), trenches.matchup(tw, game.home, game.away)
    ranked = sorted(((abs(e["edge"]), m["notes_by"][k]) for m in (away_off, home_off) for k, e in m["edges"].items()
                     if e["strength"] != "neutral" and k in m["notes_by"]), key=lambda x: -x[0])
    insight = " ".join(n for _e, n in ranked[:2]) or "No meaningful line or efficiency mismatch on either side -- the trenches grade as a wash."
    return {
        "away": away, "home": home, "away_offense": away_off, "home_offense": home_off,
        "league": tw["league"], "coverage_season": tw.get("coverage_season"), "has_ftn": tw.get("has_ftn"),
        "window": tw.get("window"), "sources": tw.get("sources"), "note": tw.get("note"),
        "references": tw.get("references"), "insight": insight,
    }


async def build_game_detail(season: int, week: int, game_id: str) -> GameDetail:
    wd = await load_week(season, week)
    game = next((g for g in wd.schedule.games if g.game_id == game_id), None)
    if game is None:
        raise ValueError(f"Unknown game_id: {game_id}")

    gb = game_breakdown(wd, game)
    league = league_context(wd)
    away_def, home_def = defense_vs_positions(wd, game.away), defense_vs_positions(wd, game.home)
    away_usage, home_usage = usage_leaders(wd, game.away), usage_leaders(wd, game.home)

    insights = {
        "vegas": vegas_insight(game, wd.implied_rank, wd.total_rank.get(game_id), len(wd.schedule.games)),
        "away_offense": offense_insight(game.away, game.home, gb.away_stats, gb.home_stats, league),
        "home_offense": offense_insight(game.home, game.away, gb.home_stats, gb.away_stats, league),
        "tempo": tempo_insight(game, gb.away_stats, gb.home_stats, league),
        "weather": weather_insight(game),
        "tendency": tendency_insight(game, gb.away_stats, gb.home_stats, league),
        "positions": positions_insight(game, away_def, home_def),
        "usage": usage_insight(game, away_usage, home_usage),
    }
    trench = trench_section(wd.trenches, game)
    if trench:
        insights["trenches"] = trench["insight"]
    return GameDetail(
        breakdown=gb,
        league=league,
        away_def_vs_pos=away_def,
        home_def_vs_pos=home_def,
        away_usage=away_usage,
        home_usage=home_usage,
        insights={k: v for k, v in insights.items() if v},
        trenches=trench,
    )
