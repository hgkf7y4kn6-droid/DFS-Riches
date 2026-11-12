"""Weekly projected stat lines from several public projection sources.

Every source is reduced to the same stat keys (Sleeper's names: pass_yd,
rush_td, rec, fum_lost, sack, pts_allow ...) so one scoring function
(app.projections.dk_points_from_line) turns each into DraftKings points --
the sources' own fantasy-point columns use other scoring systems and are
ignored.

Sources used (all public pages, fetched at most every PAGE_TTL and cached):

  Sleeper      api.sleeper.com weekly projections (already the app's base line)
  ESPN         ESPN Fantasy's public player feed, statSourceId 1 (projected)
  CBS Sports   /fantasy/football/stats/{POS}/{season}/{week}/projections/ppr/
               -- only ever serves the current week, so it is used only when
               the page says it's the requested week
Not used, and why: NFL.com (its API's robots.txt disallows all crawling),
FantasySharks (returns 403 to non-browser clients), NumberFire (shut down;
redirects to FanDuel Research), Fantasy Football Analytics (an R tool that
scrapes these same sites, not a source of its own), FFToday (returns 403 to the
app since October 2026), FantasyPros (its projections now load in the browser
from a private API instead of the page).

A source that doesn't list a player simply has no projection for him; that
absence is reported, never filled in.
"""
from __future__ import annotations

import asyncio
import html as htmllib
import re

import httpx

from app import sleeper_client
from app.cache import cached_fetch

PAGE_TTL = 60 * 60 * 2            # current-week pages
PAST_TTL = 60 * 60 * 24 * 30      # a finished week's projections don't change
UA = {"User-Agent": "Mozilla/5.0 (compatible; DFSRiches/1.0; personal DFS research tool)"}

SOURCES = {
    "sleeper": "Sleeper",
    "espn": "ESPN",
    "cbs": "CBS Sports",
}
UNAVAILABLE = {
    "NFL.com": "robots.txt disallows automated access to its fantasy API",
    "FantasySharks": "blocks non-browser clients (HTTP 403)",
    "NumberFire": "shut down (now redirects to FanDuel Research)",
    "Fantasy Football Analytics": "aggregates the sources above rather than publishing its own",
    "FFToday": "blocks the app (HTTP 403) since October 2026",
    "FantasyPros": "projections now load from a private API in the browser, not the page",
}

TEAM_FIX = {"JAC": "JAX", "WSH": "WAS", "LA": "LAR", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LAR"}
TEAM_NAMES = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}
ESPN_TEAMS = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB", 10: "TEN",
    11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ",
    21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS", 29: "CAR", 30: "JAX",
    33: "BAL", 34: "HOU",
}
ESPN_POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 16: "DST"}
# ESPN stat ids (verified against ESPN's own applied fantasy totals).
ESPN_STATS = {
    "0": "pass_att", "1": "pass_cmp", "3": "pass_yd", "4": "pass_td", "20": "pass_int", "19": "pass_2pt",
    "23": "rush_att", "24": "rush_yd", "25": "rush_td", "26": "rush_2pt",
    "58": "rec_tgt", "53": "rec", "42": "rec_yd", "43": "rec_td", "44": "rec_2pt", "72": "fum_lost",
    "99": "sack", "95": "int", "96": "fum_rec", "97": "blk_kick", "98": "safe", "105": "def_td", "120": "pts_allow",
}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _text(s: str) -> str:
    return _WS.sub(" ", htmllib.unescape(_TAG.sub(" ", s))).strip()


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def team_code(t: str) -> str:
    t = (t or "").strip().upper()
    return TEAM_FIX.get(t, t)


async def _get(url: str, **kw) -> httpx.Response:
    async with httpx.AsyncClient(timeout=25, headers={**UA, **kw.pop("headers", {})}, follow_redirects=True) as c:
        r = await c.get(url, **kw)
        r.raise_for_status()
        return r


def _stat_row(values: dict[str, float | None], mapping: dict[str, str]) -> dict[str, float]:
    return {dst: float(values[src]) for src, dst in mapping.items() if values.get(src) is not None}


# ------------------------------------------------------------------------ CBS
CBS_MAP = {
    "passing_att": "pass_att", "passing_cmp": "pass_cmp", "passing_yds": "pass_yd", "passing_td": "pass_td",
    "passing_int": "pass_int", "rushing_att": "rush_att", "rushing_yds": "rush_yd", "rushing_td": "rush_td",
    "receiving_tgt": "rec_tgt", "receiving_rec": "rec", "receiving_yds": "rec_yd", "receiving_td": "rec_td",
    "misc_fl": "fum_lost", "sck": "sack", "int": "int", "frec": "fum_rec", "dtd": "def_td", "sfty": "safe",
    "pts": "pts_allow",
}


def cbs_week(page: str) -> int | None:
    m = re.search(r"<title>\s*Week (\d+) Proj", page)
    return int(m.group(1)) if m else None


def parse_cbs(page: str, position: str) -> list[dict]:
    start = page.find("<thead")
    if start < 0:
        return []
    head_end = page.find("</thead>", start)
    cols = re.findall(r"sortcol=(\w+)", page[start:head_end])
    seen: set[str] = set()
    keys = []
    for c in cols:  # the same sort key labels a total and its per-game column; the first is the total
        keys.append(c if c not in seen else f"_{c}_dup")
        seen.add(c)
    body = page[head_end:page.find("</tbody>", head_end)]
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(cells) != len(keys):
            continue
        if position == "DST":
            m = re.search(r"/nfl/teams/(\w+)/", cells[0])
            if not m:
                continue
            team, name = team_code(m.group(1)), _text(cells[0])
        else:
            long_ = re.search(r'CellPlayerName--long">(.*?)</span></span>', cells[0], re.S)
            if not long_:
                continue
            name_m = re.search(r"<a[^>]*>([^<]+)</a>", long_.group(1))
            team_m = re.search(r'CellPlayerName-team">\s*(\w+)', long_.group(1))
            if not name_m or not team_m:
                continue
            name, team = htmllib.unescape(name_m.group(1)).strip(), team_code(team_m.group(1))
        values = {k: _num(_text(v)) for k, v in zip(keys, cells)}
        out.append({"name": name, "team": team, "position": position, "stats": _stat_row(values, CBS_MAP)})
    return out


async def cbs(season: int, week: int, current: bool) -> list[dict]:
    if not current:
        return []   # CBS only serves the current week's projections
    positions = ("QB", "RB", "WR", "TE", "DST")
    pages = await asyncio.gather(*(_get(f"https://www.cbssports.com/fantasy/football/stats/{pos}/{season}/{week}/projections/ppr/")
                                   for pos in positions))
    rows = []
    for pos, resp in zip(positions, pages):
        if cbs_week(resp.text) != week:
            return []
        rows += parse_cbs(resp.text, pos)
    return rows


# ----------------------------------------------------------------------- ESPN
def parse_espn(payload: dict, season: int, week: int) -> list[dict]:
    stat_id = f"11{season}{week}"
    out = []
    for entry in payload.get("players", []):
        p = entry.get("player") or {}
        pos = ESPN_POSITIONS.get(p.get("defaultPositionId"))
        team = ESPN_TEAMS.get(p.get("proTeamId"))
        if not pos or not team:
            continue
        proj = next((s for s in p.get("stats") or [] if s.get("id") == stat_id and s.get("statSourceId") == 1), None)
        if not proj or not proj.get("stats"):
            continue
        stats = {ESPN_STATS[k]: float(v) for k, v in proj["stats"].items() if k in ESPN_STATS}
        out.append({"name": p.get("fullName", ""), "team": team, "position": pos, "stats": stats})
    return out


async def espn(season: int, week: int, current: bool) -> list[dict]:
    flt = ('{"players":{"filterSlotIds":{"value":[0,2,4,6,16]},"filterStatsForTopScoringPeriodIds":'
           f'{{"value":2,"additionalValue":["11{season}{week}"]}},"limit":1500,'
           '"sortPercOwned":{"sortPriority":1,"sortAsc":false}}}')
    r = await _get(f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3",
                   params={"scoringPeriodId": week, "view": "kona_player_info"}, headers={"X-Fantasy-Filter": flt})
    return parse_espn(r.json(), season, week)


# -------------------------------------------------------------------- Sleeper
async def sleeper(season: int, week: int, current: bool) -> list[dict]:
    lines = await sleeper_client.get_projection_lines(season, week)
    out = []
    for line in lines.values():
        pos = "DST" if line.get("position") in ("DEF", "DST") else line.get("position")
        if pos not in ("QB", "RB", "WR", "TE", "DST") or not line.get("stats"):
            continue
        name = line.get("name") or ""
        if pos == "DST":
            name = line.get("team") or name
        out.append({"name": name, "team": team_code(line.get("team") or ""), "position": pos, "stats": line["stats"]})
    return out


FETCHERS = {"sleeper": sleeper, "espn": espn, "cbs": cbs}


async def get_source(source: str, season: int, week: int, *, current: bool) -> list[dict]:
    """One source's stat lines for the week ([] when unavailable)."""
    async def fetch():
        return await FETCHERS[source](season, week, current)

    try:
        return await cached_fetch(f"proj_source_{source}_{season}_{week}", PAGE_TTL if current else PAST_TTL, fetch)
    except Exception:
        return []


async def get_all(season: int, week: int, *, current: bool) -> dict[str, list[dict]]:
    import asyncio
    names = list(FETCHERS)
    results = await asyncio.gather(*(get_source(s, season, week, current=current) for s in names))
    return dict(zip(names, results))
