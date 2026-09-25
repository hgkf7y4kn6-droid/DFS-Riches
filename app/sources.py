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
  FFToday      /rankings/playerwkproj.php -- no DST stat lines, no fumbles
  FantasyPros  /nfl/projections/{pos}.php -- the public page lists only the
               top 10 at each position (the rest needs a premium account, which
               this app doesn't bypass), so it covers few players

Not used, and why: NFL.com (its API's robots.txt disallows all crawling),
FantasySharks (returns 403 to non-browser clients), NumberFire (shut down;
redirects to FanDuel Research), Fantasy Football Analytics (an R tool that
scrapes these same sites, not a source of its own).

A source that doesn't list a player simply has no projection for him; that
absence is reported, never filled in.
"""
from __future__ import annotations

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
    "fftoday": "FFToday",
    "fantasypros": "FantasyPros",
}
SOURCE_URLS = {
    "sleeper": "https://api.sleeper.com/projections/nfl/",
    "espn": "https://fantasy.espn.com/football/players/projections",
    "cbs": "https://www.cbssports.com/fantasy/football/stats/QB/{season}/{week}/projections/ppr/",
    "fftoday": "https://www.fftoday.com/rankings/playerwkproj.php",
    "fantasypros": "https://www.fantasypros.com/nfl/projections/qb.php?week={week}",
}
UNAVAILABLE = {
    "NFL.com": "robots.txt disallows automated access to its fantasy API",
    "FantasySharks": "blocks non-browser clients (HTTP 403)",
    "NumberFire": "shut down (now redirects to FanDuel Research)",
    "Fantasy Football Analytics": "aggregates the sources above rather than publishing its own",
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


# ---------------------------------------------------------------- FantasyPros
FP_MAP = {
    "PASSING_ATT": "pass_att", "PASSING_CMP": "pass_cmp", "PASSING_YDS": "pass_yd", "PASSING_TDS": "pass_td",
    "PASSING_INTS": "pass_int", "RUSHING_ATT": "rush_att", "RUSHING_YDS": "rush_yd", "RUSHING_TDS": "rush_td",
    "RECEIVING_REC": "rec", "RECEIVING_YDS": "rec_yd", "RECEIVING_TDS": "rec_td", "MISC_FL": "fum_lost",
    "SACK": "sack", "INT": "int", "FR": "fum_rec", "TD": "def_td", "SAFETY": "safe", "PA": "pts_allow",
}


def parse_fantasypros(page: str, position: str) -> list[dict]:
    start = page.find('id="data"')
    if start < 0:
        return []
    table = page[start:page.find("</table>", start)]
    head, _, body = table.partition("</thead>")
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", head, re.S)
    groups: list[str] = []
    if len(trs) == 2:
        for attrs, cell in re.findall(r"<t[hd]([^>]*)>(.*?)</t[hd]>", trs[0], re.S):
            span = re.search(r'colspan="(\d+)"', attrs)
            groups += [_text(cell).upper()] * (int(span.group(1)) if span else 1)
    labels = [_text(c).upper() for c in re.findall(r"<th[^>]*>(.*?)</th>", trs[-1], re.S)]
    cols = [(f"{groups[i]}_{lab}" if i < len(groups) and groups[i] and groups[i] != "\xa0" and groups[i].strip() else lab)
            for i, lab in enumerate(labels)]
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(cells) != len(cols):
            continue
        name_m = re.search(r'fp-player-name="([^"]+)"', cells[0])
        label = _text(cells[0])
        if position == "DST":
            team = TEAM_NAMES.get(label)
            name = label
        else:
            if not name_m:
                continue
            name = htmllib.unescape(name_m.group(1))
            team = team_code(label.rsplit(" ", 1)[-1]) if " " in label else ""
        if not team:
            continue
        values = {c: _num(_text(v)) for c, v in zip(cols, cells)}
        out.append({"name": name, "team": team, "position": position, "stats": _stat_row(values, FP_MAP)})
    return out


async def fantasypros(season: int, week: int, current: bool) -> list[dict]:
    rows = []
    for pos in ("QB", "RB", "WR", "TE", "DST"):
        params = {"week": week, "scoring": "PPR"}
        if not current:
            params["year"] = season
        page = (await _get(f"https://www.fantasypros.com/nfl/projections/{pos.lower()}.php", params=params)).text
        if not re.search(rf"Week {week}\b", page[:5000] + page[page.find("<title"):page.find("</title>")]):
            continue
        rows += parse_fantasypros(page, pos)
    return rows


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
    rows = []
    for pos in ("QB", "RB", "WR", "TE", "DST"):
        page = (await _get(f"https://www.cbssports.com/fantasy/football/stats/{pos}/{season}/{week}/projections/ppr/")).text
        if cbs_week(page) != week:
            return []
        rows += parse_cbs(page, pos)
    return rows


# -------------------------------------------------------------------- FFToday
FFT_POS = {"QB": 10, "RB": 20, "WR": 30, "TE": 40}
FFT_MAP = {
    "PASSING_COMP": "pass_cmp", "PASSING_ATT": "pass_att", "PASSING_YARD": "pass_yd", "PASSING_TD": "pass_td",
    "PASSING_INT": "pass_int", "RUSHING_ATT": "rush_att", "RUSHING_YARD": "rush_yd", "RUSHING_TD": "rush_td",
    "RECEIVING_REC": "rec", "RECEIVING_YARD": "rec_yd", "RECEIVING_TD": "rec_td",
}


def parse_fftoday(page: str, position: str, season: int, week: int) -> list[dict]:
    if not re.search(rf"<title>[^<]*{season} Week {week}\b", page):
        return []
    i = page.find("tableclmhdr")
    if i < 0:
        return []
    grp_html = page[page.rfind("tablehdr", 0, i):i]
    groups: list[str] = []
    for attrs, cell in re.findall(r"<TD([^>]*)>(.*?)</TD>", grp_html, re.S | re.I):
        span = re.search(r"COLSPAN=.?(\d+)", attrs, re.I)
        groups += [_text(cell).upper()] * (int(span.group(1)) if span else 1)
    j = page.find("</TR>", i)
    labels = [_text(re.sub(r"Sort First.*", "", c, flags=re.S)).upper()
              for c in re.findall(r"<TD[^>]*>(.*?)</TD>", page[i:j], re.S | re.I)]
    cols = [f"{groups[k]}_{lab}" if k < len(groups) and groups[k] else lab for k, lab in enumerate(labels)]
    out = []
    for tr in re.findall(r'<TR>\s*<TD class="bodycontent".*?</TR>', page[j:], re.S):
        cells = [_text(c) for c in re.findall(r"<TD[^>]*>(.*?)</TD>", tr, re.S)]
        if len(cells) != len(cols):
            continue
        row = dict(zip(labels, cells))
        name, team = row.get("PLAYER", "").strip(), team_code(row.get("TEAM", ""))
        if not name or not team:
            continue
        values = {c: _num(v) for c, v in zip(cols, cells)}
        out.append({"name": name, "team": team, "position": position, "stats": _stat_row(values, FFT_MAP)})
    return out


async def fftoday(season: int, week: int, current: bool) -> list[dict]:
    rows = []
    for pos, pos_id in FFT_POS.items():
        for page_no in range(4):
            params = {"Season": season, "GameWeek": week, "PosID": pos_id, "LeagueID": 1}
            if page_no:
                params["cur_page"] = page_no
            page = (await _get("https://www.fftoday.com/rankings/playerwkproj.php", params=params)).content.decode("latin-1")
            got = parse_fftoday(page, pos, season, week)
            rows += got
            if not got or f"cur_page={page_no + 1}" not in page:
                break
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


FETCHERS = {"sleeper": sleeper, "espn": espn, "cbs": cbs, "fftoday": fftoday, "fantasypros": fantasypros}


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
