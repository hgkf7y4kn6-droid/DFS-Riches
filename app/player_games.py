"""Recent game logs for the Cash and GPP tabs' expandable player cards: per
game, snap share, DraftKings points, and only the box-score lines that matter
for the position (passing + rushing for QBs, rushing + receiving for RBs,
receiving for WRs and TEs, team defense for DSTs).

Sources (nflverse, no API key):
  - stats_player_week_{season}.csv: box scores, scored with app.dk_scoring.
  - snap_counts_{season}.csv: offense_snaps / offense_pct (a 0-1 fraction),
        joined on (week, team, normalized name) -- snap rows carry PFR's
        position labels (FB, etc.), so position isn't part of that join.
  - stats_team_week_{season}.csv + games.csv: DST lines and points allowed.
"""
from __future__ import annotations

from app import dk_scoring
from app import nflverse_client as nc
from app.cache import cached_fetch
from app.config import NFLVERSE_SNAP_COUNTS_URL_TMPL, TTL_NFLVERSE_TEAM_STATS
from app.matching import normalize_name, resolve_alias

DEFAULT_GAMES = 5

# (output key, nflverse column) per stat group.
PASSING = [("cmp", "completions"), ("att", "attempts"), ("yds", "passing_yards"), ("td", "passing_tds"),
           ("int", "passing_interceptions"), ("sacks", "sacks_suffered")]
RUSHING = [("att", "carries"), ("yds", "rushing_yards"), ("td", "rushing_tds")]
RECEIVING = [("tgt", "targets"), ("rec", "receptions"), ("yds", "receiving_yards"), ("td", "receiving_tds")]
GROUPS = {"QB": ("passing", "rushing"), "RB": ("rushing", "receiving"), "WR": ("receiving", "rushing"),
          "TE": ("receiving",)}
_COLUMNS = {"passing": PASSING, "rushing": RUSHING, "receiving": RECEIVING}


def _name(name: str) -> str:
    return resolve_alias(normalize_name(name))


def _short(name: str) -> str:
    """First initial + last name, the fallback join for nicknames (Kenny / Kenneth Gainwell)."""
    parts = _name(name).split(" ")
    return f"{parts[0][:1]} {parts[-1]}"


def _num(row: dict, col: str) -> float:
    v = nc._to_float(row.get(col))
    return 0.0 if v is None else v


def stat_line(row: dict, position: str) -> dict:
    """The position's relevant stat groups from one stats_player_week row; a
    WR's rushing group only when they actually ran the ball."""
    out = {}
    for group in GROUPS.get(position, ()):
        line = {key: int(_num(row, col)) for key, col in _COLUMNS[group]}
        if group == "rushing" and position == "WR" and not line["att"]:
            continue
        out[group] = line
    if out.get("receiving") and out["receiving"]["tgt"]:
        out["receiving"]["target_share"] = round(_num(row, "target_share"), 3)
    return out


async def _snap_rows(season: int) -> list[dict]:
    return await nc._fetch_csv_rows(NFLVERSE_SNAP_COUNTS_URL_TMPL.format(season=season), f"nflverse_snap_counts_{season}")


async def get_index(season: int) -> dict:
    """{"players": player_key -> [game, ...], "dst": team -> [game, ...]} for
    this season and the prior one, oldest first. A game is
    {season, week, opponent, dk_points, snap_pct, offense_snaps, stats}."""

    async def fetch() -> dict:
        players: dict[str, list[dict]] = {}
        dst: dict[str, list[dict]] = {}
        for szn in (season - 1, season):
            snaps, short = {}, {}
            for r in await _snap_rows(szn):
                week = nc._to_int(r.get("week"))
                if week is not None and r.get("player"):
                    team = nc.to_app_team(r.get("team", ""))
                    value = (nc._to_float(r.get("offense_pct")), nc._to_int(r.get("offense_snaps")))
                    snaps[(week, team, _name(r["player"]))] = value
                    k = (week, team, _short(r["player"]))
                    short[k] = None if k in short else value      # ambiguous -> no fallback
            for row in await nc._fetch_player_week_rows(szn):
                name, position, week = row.get("player_display_name"), row.get("position"), nc._to_int(row.get("week"))
                if not name or position not in GROUPS or week is None:
                    continue
                team = nc.to_app_team(row.get("team", ""))
                pct, count = snaps.get((week, team, _name(name))) or short.get((week, team, _short(name))) or (None, None)
                players.setdefault(nc.player_key(name, position), []).append({
                    "season": szn, "week": week, "team": team,
                    "opponent": nc.to_app_team(row.get("opponent_team", "")),
                    "dk_points": dk_scoring.dk_offense_points(row),
                    "snap_pct": None if pct is None else round(pct * 100, 1),
                    "offense_snaps": count,
                    "stats": stat_line(row, position),
                })

            allowed = await nc._points_allowed_by_week_team(szn)
            for row in await nc._fetch_team_week_rows(szn):
                team, week = nc.to_app_team(row.get("team", "")), nc._to_int(row.get("week"))
                if not team or week is None:
                    continue
                pa = allowed.get((week, team))
                dst.setdefault(team, []).append({
                    "season": szn, "week": week, "team": team,
                    "opponent": nc.to_app_team(row.get("opponent_team", "")),
                    "dk_points": dk_scoring.dk_dst_points(row, pa),
                    "snap_pct": None, "offense_snaps": None,
                    "stats": {"defense": {
                        "sacks": _num(row, "def_sacks"), "int": int(_num(row, "def_interceptions")),
                        "fum_rec": int(_num(row, "fumble_recovery_opp")),
                        "td": int(_num(row, "def_tds") + _num(row, "special_teams_tds")),
                        "pts_allowed": None if pa is None else int(pa)}},
                })
        for games in (*players.values(), *dst.values()):
            games.sort(key=lambda g: (g["season"], g["week"]))
        return {"players": players, "dst": dst}

    return await cached_fetch(f"player_game_logs_{season}", TTL_NFLVERSE_TEAM_STATS, fetch)


def recent_games(index: dict, *, season: int, week: int, name: str, position: str, team: str,
                 n: int = DEFAULT_GAMES) -> list[dict]:
    """The player's last n games strictly before (season, week), newest first."""
    position = position.upper()
    if position == "DST":
        games = index["dst"].get(team.upper(), [])
    else:
        games = index["players"].get(nc.player_key(name, position), [])
    prior = [g for g in games if (g["season"], g["week"]) < (season, week)]
    return list(reversed(prior[-n:]))


def summarize(games: list[dict]) -> dict:
    """Averages over the returned games: DK points and snap share."""
    pts = [g["dk_points"] for g in games]
    snaps = [g["snap_pct"] for g in games if g["snap_pct"] is not None]
    return {
        "games": len(games),
        "avg_dk_points": round(sum(pts) / len(pts), 2) if pts else None,
        "avg_snap_pct": round(sum(snaps) / len(snaps), 1) if snaps else None,
    }


async def player_games(season: int, week: int, *, name: str, position: str, team: str, n: int = DEFAULT_GAMES) -> dict:
    index = await get_index(season)
    games = recent_games(index, season=season, week=week, name=name, position=position, team=team, n=n)
    return {"name": name, "position": position.upper(), "team": team.upper(), "games": games,
            "summary": summarize(games)}
