"""Each team's offense and defense as units: per-game yards (total, passing,
rushing), DraftKings fantasy points, and giveaways / takeaways, with the
league rank of each and trailing 3/6/9-game averages for the trend.

Window: this season's games before the requested week only. A trailing
window shows only once the team has played that many games (Week 4: L3
only), so a "trend" never mixes in last season.

Definitions (from nflverse stats_team_week and stats_player_week):
  passing yards   net: passing yards minus sack yards lost
  yards           net passing + rushing
  fantasy points  the DK points the team's QBs, RBs, WRs and TEs scored
                  (allowed: what the opponents' scored against the defense)
  giveaways       interceptions thrown + fumbles lost
  takeaways       the opponents' giveaways

Ranks run 1..32 with 1 the best: most yards / points / takeaways for an
offense metric, fewest allowed / giveaways otherwise.
"""
from __future__ import annotations

from app import matchups
from app import nflverse_client as nc
from app.cache import cached_fetch
from app.config import TTL_NFLVERSE_TEAM_STATS

WINDOWS = (3, 6, 9)

# side -> [(metric, label, unit, better)]; better = "high" or "low"
METRICS: dict[str, list[tuple[str, str, str, str]]] = {
    "offense": [
        ("yards", "Yards / game", "yds", "high"),
        ("pass_yards", "Passing yards / game", "yds", "high"),
        ("rush_yards", "Rushing yards / game", "yds", "high"),
        ("fantasy_points", "DK points / game", "pts", "high"),
        ("giveaways", "Giveaways / game", "", "low"),
    ],
    "defense": [
        ("yards", "Yards allowed / game", "yds", "low"),
        ("pass_yards", "Passing yards allowed / game", "yds", "low"),
        ("rush_yards", "Rushing yards allowed / game", "yds", "low"),
        ("fantasy_points", "DK points allowed / game", "pts", "low"),
        ("takeaways", "Takeaways / game", "", "high"),
    ],
}


def _f(row: dict, col: str) -> float:
    v = nc._to_float(row.get(col))
    return 0.0 if v is None else v


def team_games(team_rows: list[dict], fp_records: dict[str, list[dict]], season: int, week: int) -> dict[str, list[dict]]:
    """team -> [{week, offense: {...}, defense: {...}}, ...] for this season's
    regular-season games before `week`, oldest first."""
    fp: dict[tuple[int, str], float] = {}
    for pos in ("QB", "RB", "WR", "TE"):
        for r in fp_records.get(pos, []):
            if r["season"] == season:
                fp[(r["week"], r["producer"])] = fp.get((r["week"], r["producer"]), 0.0) + r["fp"]
    off: dict[tuple[int, str], dict] = {}
    for row in team_rows:
        wk, team = nc._to_int(row.get("week")), nc.to_app_team(row.get("team", ""))
        if wk is None or not team or wk >= week or (row.get("season_type") or "REG") != "REG":
            continue
        pass_yds = _f(row, "passing_yards") - _f(row, "sack_yards_lost")
        rush_yds = _f(row, "rushing_yards")
        off[(wk, team)] = {
            "opponent": nc.to_app_team(row.get("opponent_team", "")),
            "yards": pass_yds + rush_yds, "pass_yards": pass_yds, "rush_yards": rush_yds,
            "fantasy_points": round(fp.get((wk, team), 0.0), 2),
            "giveaways": _f(row, "passing_interceptions") + _f(row, "fumbles_lost_total"),
        }
    games: dict[str, list[dict]] = {}
    for (wk, team), o in off.items():
        opp = off.get((wk, o["opponent"]))
        if opp is None:
            continue
        d = {"yards": opp["yards"], "pass_yards": opp["pass_yards"], "rush_yards": opp["rush_yards"],
             "fantasy_points": opp["fantasy_points"], "takeaways": opp["giveaways"]}
        games.setdefault(team, []).append({"week": wk, "offense": {k: v for k, v in o.items() if k != "opponent"}, "defense": d})
    for g in games.values():
        g.sort(key=lambda x: x["week"])
    return games


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def table(games: dict[str, list[dict]]) -> dict:
    """{"teams": team -> {games, offense: {metric: {value, rank, l3, l6, l9}}, defense: ...},
    "league": side -> metric -> {avg, label, unit, better}, "teams_ranked": n}."""
    teams: dict[str, dict] = {t: {"games": len(g), "offense": {}, "defense": {}} for t, g in games.items()}
    league: dict[str, dict] = {"offense": {}, "defense": {}}
    for side, metrics in METRICS.items():
        for metric, label, unit, better in metrics:
            season_avg = {t: _avg([x[side][metric] for x in g]) for t, g in games.items()}
            season_avg = {t: v for t, v in season_avg.items() if v is not None}
            order = sorted(season_avg, key=lambda t: season_avg[t], reverse=(better == "high"))
            for t, g in games.items():
                if t not in season_avg:
                    continue
                series = [x[side][metric] for x in g]
                teams[t][side][metric] = {
                    "value": season_avg[t],
                    "rank": order.index(t) + 1,
                    **{f"l{n}": _avg(series[-n:]) if len(series) >= n else None for n in WINDOWS},
                }
            league[side][metric] = {"avg": _avg(list(season_avg.values())), "label": label, "unit": unit, "better": better}
    return {"teams": teams, "league": league, "teams_ranked": len(games)}


async def unit_table(season: int, week: int) -> dict:
    async def fetch() -> dict:
        rows = await nc._fetch_team_week_rows(season)
        records = await matchups.game_records(season)
        return table(team_games(rows, records, season, week))

    return await cached_fetch(f"team_units_v1_{season}_{week}", TTL_NFLVERSE_TEAM_STATS, fetch)


def game_units(t: dict | None, away: str, home: str) -> dict | None:
    """Both teams' units for the game breakdown, plus the league reference."""
    if not t or away not in t["teams"] or home not in t["teams"]:
        return None
    return {"away": t["teams"][away], "home": t["teams"][home], "league": t["league"], "teams_ranked": t["teams_ranked"]}
