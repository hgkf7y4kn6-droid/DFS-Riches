"""Recent usage profiles from nflverse box scores -- the opportunity side of
the DFS framework (who actually gets the ball).

Per player, averaged over this season's games before the week (last
season's when he has fewer than MIN_GAMES this season):

  targets, target_share, air_yards_share, adot (receiving air yards per
  target), carries, carry_share (of team carries), receptions,
  QB: pass_att, ypa (passing yards per attempt), td_rate (pass TDs per
  attempt), rush_att, rush_yds.

Per team: pass-catcher concentration = the top two target shares combined.

nflverse doesn't publish snaps, routes, red-zone targets or goal-line work,
so those stay unknown here (listed as missing in the DFS Model), never
guessed.
"""
from __future__ import annotations

from app import nflverse_client as nc
from app.cache import cached_fetch
from app.config import TTL_NFLVERSE_TEAM_STATS

MIN_GAMES = 2
RECENT_GAMES = 4


def _f(row: dict, key: str) -> float:
    return nc._to_float(row.get(key)) or 0.0


def _avg(games: list[dict], key: str) -> float | None:
    vals = [g[key] for g in games if g.get(key) is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def summarize(games: list[dict]) -> dict:
    """Average one player's per-game rows (already filtered and ordered)."""
    out = {"games": len(games)}
    for key in ("targets", "target_share", "air_yards_share", "carries", "carry_share", "receptions",
                "pass_att", "rush_att", "rush_yds"):
        out[key] = _avg(games, key)
    tgt = sum(g.get("targets") or 0 for g in games)
    air = sum(g.get("air_yards") or 0 for g in games)
    out["adot"] = round(air / tgt, 1) if tgt else None
    att = sum(g.get("pass_att") or 0 for g in games)
    out["ypa"] = round(sum(g.get("pass_yds") or 0 for g in games) / att, 2) if att else None
    out["td_rate"] = round(sum(g.get("pass_td") or 0 for g in games) / att, 3) if att else None
    return out


async def usage_profiles(season: int, week: int) -> dict:
    """{"players": player_key -> profile, "teams": team -> {"concentration": x}}."""

    async def fetch() -> dict:
        per_player: dict[str, list[dict]] = {}
        for szn in (season - 1, season):
            team_carries: dict[tuple[int, str], float] = {}
            for row in await nc._fetch_team_week_rows(szn):
                w = nc._to_int(row.get("week"))
                if w is not None:
                    team_carries[(w, nc.to_app_team(row.get("team", "")))] = _f(row, "carries")
            for row in await nc._fetch_player_week_rows(szn):
                w = nc._to_int(row.get("week"))
                pos = row.get("position")
                if (w is None or pos not in ("QB", "RB", "WR", "TE") or not row.get("player_display_name")
                        or row.get("season_type", "REG") != "REG" or (szn == season and w >= week)):
                    continue
                team = nc.to_app_team(row.get("team", ""))
                tc = team_carries.get((w, team))
                carries = _f(row, "carries")
                per_player.setdefault(nc.player_key(row["player_display_name"], pos), []).append({
                    "season": szn, "week": w, "team": team,
                    "targets": _f(row, "targets"), "target_share": nc._to_float(row.get("target_share")),
                    "air_yards_share": nc._to_float(row.get("air_yards_share")),
                    "air_yards": _f(row, "receiving_air_yards"), "receptions": _f(row, "receptions"),
                    "carries": carries, "carry_share": round(carries / tc, 3) if tc else None,
                    "pass_att": _f(row, "attempts") if pos == "QB" else None,
                    "pass_yds": _f(row, "passing_yards") if pos == "QB" else None,
                    "pass_td": _f(row, "passing_tds") if pos == "QB" else None,
                    "rush_att": carries if pos == "QB" else None,
                    "rush_yds": _f(row, "rushing_yards") if pos == "QB" else None,
                })
        players = {}
        for key, games in per_player.items():
            games.sort(key=lambda g: (g["season"], g["week"]))
            this = [g for g in games if g["season"] == season]
            use = this[-RECENT_GAMES:] if len(this) >= MIN_GAMES else games[-RECENT_GAMES:]
            prof = summarize(use)
            prof["team"] = use[-1]["team"] if use else None
            prof["this_season_games"] = len(this)
            players[key] = prof
        teams: dict[str, list[float]] = {}
        for prof in players.values():
            if prof.get("target_share") and prof.get("team") and prof["this_season_games"] >= 1:
                teams.setdefault(prof["team"], []).append(prof["target_share"])
        return {"players": players,
                "teams": {t: {"concentration": round(sum(sorted(v, reverse=True)[:2]), 3)} for t, v in teams.items()}}

    try:
        return await cached_fetch(f"usage_profiles_{season}_{week}", TTL_NFLVERSE_TEAM_STATS, fetch)
    except Exception:
        return {"players": {}, "teams": {}}
