"""Defense vs position: how every NFL defense ranks against each fantasy
position, by DraftKings points allowed and by an efficiency metric, both raw
and strength-of-schedule adjusted. Feeds the app's matchup badges.

Window: each team's last 8 games before the requested week (this season,
then the end of last season while the sample is short).

Metrics allowed to each position (higher = softer defense = better matchup):
  QB   DK points; passing yards per attempt
  RB   DK points; yards per touch (rush + receiving yards / carries + catches)
  WR   DK points; yards per target
  TE   DK points; yards per target
  DST  the matchup is the opposing *offense*: DK points it gives up to
       defenses; giveaways per game (sacks taken + interceptions + fumbles lost)

Strength-of-schedule adjustment: each game is judged against what that
opponent normally produces. For a defense, every game it played is compared
with the offense's output at the position in its *other* recent games:

  adjusted points     = mean over games of (allowed - offense's usual output)
  adjusted efficiency = (yards allowed - offense's usual yards per unit x units)
                        / units

so a defense that only faced weak offenses stops looking stingy, and one that
faced a gauntlet stops looking soft. Positive = allows more than its opponents
usually get.

Ranks run 1..N with N (32nd) = allows the most -- the softest matchup -- and
1 = allows the least, the usual "32nd against the run" convention.
"""
from __future__ import annotations

from collections import defaultdict

from app import dk_scoring
from app import nflverse_client as nc
from app.cache import cached_fetch
from app.config import TTL_NFLVERSE_TEAM_STATS

WINDOW = 8
POSITIONS = ("QB", "RB", "WR", "TE", "DST")
EFFICIENCY = {
    "QB": "pass yds/att",
    "RB": "yds/touch",
    "WR": "yds/target",
    "TE": "yds/target",
    "DST": "giveaways/game",
}


def _f(row: dict, col: str) -> float:
    v = nc._to_float(row.get(col))
    return 0.0 if v is None else v


def _skill_numbers(row: dict, pos: str) -> tuple[float, float]:
    """(efficiency numerator, its volume) for one player's game."""
    if pos == "QB":
        return _f(row, "passing_yards"), _f(row, "attempts")
    if pos == "RB":
        return _f(row, "rushing_yards") + _f(row, "receiving_yards"), _f(row, "carries") + _f(row, "receptions")
    return _f(row, "receiving_yards"), _f(row, "targets")


async def game_records(season: int) -> dict[str, list[dict]]:
    """pos -> [{season, week, producer, allower, fp, num, vol}, ...] for this
    season and the prior one: one record per team-game at that position.
    Skill positions: producer = offense, allower = defense. DST: producer =
    the defense scoring DST points, allower = the offense giving them up."""
    games: dict[str, dict[tuple, dict]] = {p: {} for p in POSITIONS}
    for szn in (season - 1, season):
        for row in await nc._fetch_player_week_rows(szn):
            pos, week = row.get("position"), nc._to_int(row.get("week"))
            if pos not in EFFICIENCY or pos == "DST" or week is None:
                continue
            team, opp = nc.to_app_team(row.get("team", "")), nc.to_app_team(row.get("opponent_team", ""))
            if not team or not opp:
                continue
            rec = games[pos].setdefault((szn, week, team), {"season": szn, "week": week, "producer": team,
                                                            "allower": opp, "fp": 0.0, "num": 0.0, "vol": 0.0})
            num, vol = _skill_numbers(row, pos)
            rec["fp"] += dk_scoring.dk_offense_points(row)
            rec["num"] += num
            rec["vol"] += vol

        allowed = await nc._points_allowed_by_week_team(szn)
        team_rows = {}
        for row in await nc._fetch_team_week_rows(szn):
            week, team = nc._to_int(row.get("week")), nc.to_app_team(row.get("team", ""))
            if week is not None and team:
                team_rows[(week, team)] = row
        for (week, defense), row in team_rows.items():
            offense = nc.to_app_team(row.get("opponent_team", ""))
            off_row = team_rows.get((week, offense))
            if not offense or off_row is None:
                continue
            giveaways = _f(off_row, "sacks_suffered") + _f(off_row, "passing_interceptions") + _f(off_row, "fumbles_lost_total")
            games["DST"][(szn, week, defense)] = {
                "season": szn, "week": week, "producer": defense, "allower": offense,
                "fp": dk_scoring.dk_dst_points(row, allowed.get((week, defense))), "num": giveaways, "vol": 1.0}
    return {p: sorted(g.values(), key=lambda r: (r["season"], r["week"])) for p, g in games.items()}


def _recent(records: list[dict], season: int, week: int) -> list[dict]:
    return [r for r in records if (r["season"], r["week"]) < (season, week)][-WINDOW:]


def _ranks(values: dict[str, float]) -> dict[str, int]:
    """1 = the smallest value (allows the least); N = the largest (softest)."""
    order = sorted(values, key=lambda t: values[t])
    return {t: i for i, t in enumerate(order, 1)}


def table(records: dict[str, list[dict]], season: int, week: int) -> dict:
    teams: dict[str, dict] = defaultdict(dict)
    league = {}
    for pos in POSITIONS:
        by_allower: dict[str, list[dict]] = defaultdict(list)
        by_producer: dict[str, list[dict]] = defaultdict(list)
        for r in records.get(pos, []):
            by_allower[r["allower"]].append(r)
            by_producer[r["producer"]].append(r)
        windows = {t: _recent(rs, season, week) for t, rs in by_allower.items()}
        windows = {t: rs for t, rs in windows.items() if rs}
        usual = {t: _recent(rs, season, week) for t, rs in by_producer.items()}

        raw_fp, raw_eff, adj_fp, adj_eff, n_games = {}, {}, {}, {}, {}
        for t, rs in windows.items():
            n_games[t] = len(rs)
            raw_fp[t] = sum(r["fp"] for r in rs) / len(rs)
            vol = sum(r["vol"] for r in rs)
            raw_eff[t] = sum(r["num"] for r in rs) / vol if vol else 0.0
            fp_diffs, num_over, vol_used = [], 0.0, 0.0
            for r in rs:
                others = [o for o in usual.get(r["producer"], []) if o is not r]
                if not others:
                    continue
                fp_diffs.append(r["fp"] - sum(o["fp"] for o in others) / len(others))
                o_vol = sum(o["vol"] for o in others)
                if o_vol and r["vol"]:
                    num_over += r["num"] - sum(o["num"] for o in others) / o_vol * r["vol"]
                    vol_used += r["vol"]
            adj_fp[t] = sum(fp_diffs) / len(fp_diffs) if fp_diffs else 0.0
            adj_eff[t] = num_over / vol_used if vol_used else 0.0

        ranks = {k: _ranks(v) for k, v in (("raw_fp", raw_fp), ("raw_eff", raw_eff), ("adj_fp", adj_fp), ("adj_eff", adj_eff))}
        for t in windows:
            teams[t][pos] = {
                "games": n_games[t],
                "raw": {"fp": round(raw_fp[t], 2), "fp_rank": ranks["raw_fp"][t],
                        "eff": round(raw_eff[t], 2), "eff_rank": ranks["raw_eff"][t]},
                "adj": {"fp": round(adj_fp[t], 2), "fp_rank": ranks["adj_fp"][t],
                        "eff": round(adj_eff[t], 2), "eff_rank": ranks["adj_eff"][t]},
            }
        if raw_fp:
            league[pos] = {"fp": round(sum(raw_fp.values()) / len(raw_fp), 2),
                           "eff": round(sum(raw_eff.values()) / len(raw_eff), 2), "teams": len(raw_fp)}
    return {"season": season, "week": week, "window": WINDOW, "efficiency": EFFICIENCY, "league": league,
            "teams": dict(teams)}


async def defense_vs_position(season: int, week: int) -> dict:
    async def fetch() -> dict:
        return table(await game_records(season), season, week)

    return await cached_fetch(f"defense_vs_position_{season}_{week}", TTL_NFLVERSE_TEAM_STATS, fetch)
