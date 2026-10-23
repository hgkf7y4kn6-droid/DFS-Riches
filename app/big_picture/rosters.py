"""Injury designations and next-man-up, cross-checked across four sources.

* Sleeper -- every player's injury designation, depth-chart slot and order.
* ESPN -- the league injury feed (designation, date, injury detail) and each
  team's depth charts (every offensive, defensive and special-teams formation).
* The team's own site (the NFL club platform every team uses) -- the official
  weekly injury report for the coming game: Wednesday-Friday practice
  participation and the final game status, plus the team's depth chart.
* DraftKings DFS -- the status DraftKings shows on the player (skill players).

reconcile() decides each player's designation for the coming game: the team's
official game status once it's posted; otherwise the sources' agreement, or,
when they disagree, the most recently updated one -- and the disagreement is
reported. The next player up is read from every depth chart (skipping anyone
ruled out) and labeled with how many sources agree. A source that can't be
read for a team is listed as unavailable, never guessed.
"""
from __future__ import annotations

import asyncio
import html as htmllib
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx

from app.matching import normalize_name
from app.sources import ESPN_TEAMS, TEAM_NAMES

log = logging.getLogger(__name__)

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
SLEEPER_PLAYERS = "https://api.sleeper.app/v1/players/nfl"
ESPN_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
ESPN_DEPTH = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{id}/depthcharts"
TEAM_SITES = {
    "ARI": "azcardinals.com", "ATL": "atlantafalcons.com", "BAL": "baltimoreravens.com", "BUF": "buffalobills.com",
    "CAR": "panthers.com", "CHI": "chicagobears.com", "CIN": "bengals.com", "CLE": "clevelandbrowns.com",
    "DAL": "dallascowboys.com", "DEN": "denverbroncos.com", "DET": "detroitlions.com", "GB": "packers.com",
    "HOU": "houstontexans.com", "IND": "colts.com", "JAX": "jaguars.com", "KC": "chiefs.com", "LV": "raiders.com",
    "LAC": "chargers.com", "LAR": "therams.com", "MIA": "miamidolphins.com", "MIN": "vikings.com",
    "NE": "patriots.com", "NO": "neworleanssaints.com", "NYG": "giants.com", "NYJ": "newyorkjets.com",
    "PHI": "philadelphiaeagles.com", "PIT": "steelers.com", "SF": "49ers.com", "SEA": "seahawks.com",
    "TB": "buccaneers.com", "TEN": "tennesseetitans.com", "WAS": "commanders.com",
}
ESPN_IDS = {abbr: i for i, abbr in ESPN_TEAMS.items()}
SPECIAL_TEAMS_ROWS = {"KR", "PR", "H", "LS", "KO", "PK", "K", "P"}

NOT_INJURY = ("coach's decision", "not injury related", "nir", "personal", "rest")
SEVERITY = {"Out": 0, "IR": 0, "PUP": 0, "Suspended": 0, "Doubtful": 1, "Questionable": 2, "Day-to-day": 2}
DK_CODES = {"O": "Out", "OUT": "Out", "IR": "IR", "D": "Doubtful", "Q": "Questionable"}


def norm_status(raw) -> str | None:
    """Any source's designation -> Out | IR | PUP | Suspended | Doubtful | Questionable | Day-to-day | None."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or s in ("(-)", "-", "--", "na", "n/a", "healthy", "active", "none", "probable", "full"):
        return None
    if s in ("o", "out"):
        return "Out"
    if s in ("d", "doubtful"):
        return "Doubtful"
    if s in ("q", "questionable"):
        return "Questionable"
    if "injured reserve" in s or s in ("ir", "ir-r", "ir-nfi"):
        return "IR"
    if "pup" in s or "physically unable" in s or "non-football" in s or s == "nfi":
        return "PUP"
    if "susp" in s:
        return "Suspended"
    if "day-to-day" in s or "day to day" in s:
        return "Day-to-day"
    return None


def _key(name: str | None) -> str:
    return normalize_name(name or "")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _strip_number(name: str) -> str:
    return re.sub(r"^\d{1,2}\s+", "", name).strip()


# ------------------------------------------------------------------ Sleeper
async def sleeper(client: httpx.AsyncClient) -> tuple[dict, dict]:
    """(statuses, depth): team -> {key: {...}}, team -> [[slot, [names in order]]]."""
    r = await client.get(SLEEPER_PLAYERS, timeout=60)
    r.raise_for_status()
    statuses: dict[str, dict] = {}
    slots: dict[tuple, list] = {}
    for p in r.json().values():
        team = p.get("team")
        if not team or p.get("status") == "Retired":
            continue
        name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        if p.get("depth_chart_position") and p.get("depth_chart_order"):
            slots.setdefault((team, p["depth_chart_position"]), []).append((p["depth_chart_order"], name))
        if p.get("injury_status"):
            statuses.setdefault(team, {})[_key(name)] = {
                "name": name, "position": p.get("position"), "status": norm_status(p.get("injury_status")),
                "raw": p.get("injury_status"), "body_part": p.get("injury_body_part"),
                "updated": datetime.fromtimestamp(p["news_updated"] / 1000, timezone.utc).isoformat(timespec="minutes")
                if p.get("news_updated") else None}
    depth: dict[str, list] = {}
    for (team, slot), rows in slots.items():
        depth.setdefault(team, []).append([slot, [n for _o, n in sorted(rows)]])
    return statuses, depth


# ------------------------------------------------------------------ ESPN
async def espn_injuries(client: httpx.AsyncClient) -> dict:
    r = await client.get(ESPN_INJURIES, timeout=45)
    r.raise_for_status()
    out: dict[str, dict] = {}
    for t in r.json().get("injuries") or []:
        team = TEAM_NAMES.get(t.get("displayName") or "")
        if not team:
            continue
        for i in t.get("injuries") or []:
            a = i.get("athlete") or {}
            d = i.get("details") or {}
            out.setdefault(team, {})[_key(a.get("displayName"))] = {
                "name": a.get("displayName"), "position": ((a.get("position") or {}).get("abbreviation")),
                "status": norm_status(i.get("status") or (i.get("type") or {}).get("description")),
                "raw": i.get("status"), "updated": i.get("date"),
                "body_part": d.get("type"), "detail": d.get("detail"), "return_date": d.get("returnDate")}
    return out


async def espn_depth(client: httpx.AsyncClient, team: str) -> list | None:
    tid = ESPN_IDS.get(team)
    if not tid:
        return None
    r = await client.get(ESPN_DEPTH.format(id=tid), timeout=30)
    r.raise_for_status()
    rows = []
    for formation in r.json().get("depthchart") or []:
        for key, pos in (formation.get("positions") or {}).items():
            slot = ((pos.get("position") or {}).get("abbreviation") or key).upper()
            names = [a.get("displayName") for a in pos.get("athletes") or [] if a.get("displayName")]
            if names:
                rows.append([slot, names])
    return rows


# ------------------------------------------------------------------ the team's own site
def report_week(page: str) -> int | None:
    """The week the club site actually shows (it falls back to its latest report for an unpublished week)."""
    m = re.search(r'<option value="[^"]*/injury-report/week/REG-(\d+)"\s+selected', page)
    return int(m.group(1)) if m else None


def parse_team_injury_report(page: str, week: int | None = None) -> dict | None:
    """The club site's weekly injury report: {key: {name, position, injury, practice: {day: code}, game_status}}.
    None when the page has no report table for `week` (not published yet, or a bye)."""
    if week is not None and report_week(page) not in (week, None):
        return None
    i = page.find("Table - Injury report")
    if i < 0:
        return None
    table = page[i: page.find("</table>", i)]
    head = re.search(r"<thead>(.*?)</thead>", table, re.S)
    headers = [_text(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", head.group(1), re.S)] if head else []
    days = headers[3:-1]
    out = {}
    for row in re.findall(r"<tr>(.*?)</tr>", table[table.find("<tbody>"):], re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 4:
            continue
        name_m = re.search(r'player-name">\s*<a[^>]*>(.*?)</a>', cells[0], re.S)
        name = _text(name_m.group(1)) if name_m else _text(cells[0])
        practice = {d: _text(c) for d, c in zip(days, cells[3:-1]) if _text(c) not in ("", "--")}
        out[_key(name)] = {"name": name, "position": _text(cells[1]), "injury": _text(cells[2]),
                           "practice": practice, "game_status": norm_status(_text(cells[-1])),
                           "game_status_raw": _text(cells[-1])}
    return out


def parse_team_depth_chart(page: str) -> list | None:
    """[[slot, [names in order]], ...] from every table whose first column is the position."""
    rows = []
    for table in re.findall(r"<table[^>]*>(.*?)</table>", page, re.S):
        head = re.search(r"<thead>(.*?)</thead>", table, re.S)
        first = _text(re.findall(r"<th[^>]*>(.*?)</th>", head.group(1), re.S)[0]) if head else ""
        if first.lower() != "position":
            continue
        for row in re.findall(r"<tr>(.*?)</tr>", table, re.S):
            cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            if len(cells) >= 2 and cells[0]:
                names = [_strip_number(c) for c in cells[1:] if c]
                if names:
                    rows.append([cells[0].upper(), names])
    return rows or None


async def team_report(client: httpx.AsyncClient, team: str, week: int) -> dict | None:
    """Just the club site's injury report for the week (see parse_team_injury_report); None when unpublished."""
    domain = TEAM_SITES.get(team)
    if not domain:
        return None
    r = await client.get(f"https://www.{domain}/team/injury-report/week/REG-{week}", timeout=30, follow_redirects=True)
    return parse_team_injury_report(r.text, week) if r.status_code == 200 else None


async def team_site(client: httpx.AsyncClient, team: str, week: int) -> dict:
    domain = TEAM_SITES.get(team)
    if not domain:
        return {"report": None, "depth": None, "report_status": "no team site on file", "depth_status": "no team site on file"}
    out: dict = {"url": f"https://www.{domain}/team/injury-report/week/REG-{week}"}
    try:
        r = await client.get(out["url"], timeout=30, follow_redirects=True)
        out["report"] = parse_team_injury_report(r.text, week) if r.status_code == 200 else None
        out["report_status"] = "ok" if out["report"] is not None else (
            f"Week {week} report not published yet" if r.status_code == 200 else f"HTTP {r.status_code}")
    except Exception as exc:
        out["report"], out["report_status"] = None, f"unreachable ({type(exc).__name__})"
    try:
        r = await client.get(f"https://www.{domain}/team/depth-chart", timeout=30, follow_redirects=True)
        out["depth"] = parse_team_depth_chart(r.text) if r.status_code == 200 else None
        out["depth_status"] = "ok" if out["depth"] else ("no readable depth chart" if r.status_code == 200 else f"HTTP {r.status_code}")
    except Exception as exc:
        out["depth"], out["depth_status"] = None, f"unreachable ({type(exc).__name__})"
    return out


# ------------------------------------------------------------------ gather
async def gather(teams: list[str], week: int) -> dict:
    """Every source for the week's teams. Failures are recorded per source, never raised."""
    data: dict = {"sleeper": {}, "sleeper_depth": {}, "espn": {}, "espn_depth": {}, "team": {}, "status": {}}
    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(headers=UA) as client:
        async def guarded(coro):
            async with sem:
                return await coro

        async def safe(label, coro):
            try:
                return await guarded(coro)
            except Exception as exc:
                data["status"][label] = f"unavailable ({type(exc).__name__})"
                return None

        sl, ei = await asyncio.gather(safe("sleeper", sleeper(client)), safe("espn_injuries", espn_injuries(client)))
        if sl:
            data["sleeper"], data["sleeper_depth"] = sl
            data["status"]["sleeper"] = "ok"
        if ei is not None:
            data["espn"], data["status"]["espn_injuries"] = ei, "ok"
        depths = await asyncio.gather(*(safe(f"espn_depth_{t}", espn_depth(client, t)) for t in teams))
        data["espn_depth"] = {t: d for t, d in zip(teams, depths) if d}
        sites = await asyncio.gather(*(guarded(team_site(client, t, week)) for t in teams))
        data["team"] = dict(zip(teams, sites))
    data["coverage"] = {
        "teams": len(teams),
        "team_reports": sum(1 for s in data["team"].values() if s.get("report") is not None),
        "team_depth_charts": sum(1 for s in data["team"].values() if s.get("depth")),
        "espn_depth_charts": len(data["espn_depth"]),
        "sleeper": data["status"].get("sleeper", "unavailable"),
        "espn_injuries": data["status"].get("espn_injuries", "unavailable"),
    }
    return data


# ------------------------------------------------------------------ reconcile
def _row_of(depth: list | None, key: str) -> tuple[list, int] | None:
    """The depth-chart row a player sits highest in (special-teams rows only as a last resort)."""
    best = None
    for slot, names in depth or []:
        keys = [_key(n) for n in names]
        if key in keys:
            idx = keys.index(key)
            rank = (slot in SPECIAL_TEAMS_ROWS, idx)
            if best is None or rank < best[0]:
                best = (rank, (slot, names), idx)
    return (best[1], best[2]) if best else None


def _next_up(depth: list | None, key: str, unavailable: set[str]) -> tuple[str | None, str | None, bool]:
    """(next player up, slot, is_starter) in one source's depth chart."""
    found = _row_of(depth, key)
    if not found:
        return None, None, False
    (slot, names), idx = found
    nxt = next((n for n in names[idx + 1:] if _key(n) not in unavailable), None)
    return nxt, slot, idx == 0


def _recent(ts: str | None, days: int = 30) -> bool:
    if not ts:
        return False
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    return t >= datetime.now(timezone.utc) - timedelta(days=days)


def team_injuries(team: str, data: dict, dk_rows: list[dict]) -> tuple[list[dict], dict]:
    """(designated players who matter for the coming game, the team's source coverage)."""
    sl = data["sleeper"].get(team, {})
    es = data["espn"].get(team, {})
    site = data["team"].get(team) or {}
    report = site.get("report") or {}
    dk = {_key(r["name"]): r for r in dk_rows if r.get("team") == team}
    depths = {"team site": site.get("depth"), "ESPN": data["espn_depth"].get(team), "Sleeper": data["sleeper_depth"].get(team)}

    keys = set(sl) | set(es) | set(report) | {k for k, r in dk.items() if DK_CODES.get(str(r.get("injury") or "").upper())}
    resolved: dict[str, dict] = {}
    for k in keys:
        views = {
            "official": report.get(k, {}).get("game_status") if k in report else None,
            "Sleeper": sl.get(k, {}).get("status"),
            "ESPN": es.get(k, {}).get("status"),
            "DraftKings": DK_CODES.get(str((dk.get(k) or {}).get("injury") or "").upper()),
        }
        votes = {s: v for s, v in views.items() if s != "official" and v}
        # Last game's coach's-decision inactives linger in the feeds: they aren't designations for this game.
        reasons = " ".join(str(x.get(f) or "") for x in (sl.get(k, {}), es.get(k, {})) for f in ("body_part", "detail")).lower()
        if not views["official"] and any(w in reasons for w in NOT_INJURY):
            continue
        if views["official"]:
            status, basis = views["official"], "official team injury report"
        elif votes:
            # IR, PUP and suspensions all mean "won't play": they agree with Out.
            classes = Counter(SEVERITY.get(v, 3) for v in votes.values())
            counts = Counter(votes.values())
            top, n = counts.most_common(1)[0]
            if len(classes) == 1:
                specific = [v for v in votes.values() if v != "Out"]
                top = specific[0] if specific and SEVERITY.get(specific[0]) == 0 else top
                status, basis = top, " + ".join(votes) + (" agree" if len(votes) > 1 else " only")
            elif n > len(votes) / 2:
                others = ", ".join(f"{src} shows {v}" for src, v in votes.items() if v != top)
                status, basis = top, f"majority ({', '.join(s for s, v in votes.items() if v == top)}); {others}"
            else:
                # An even split: the most recently updated timestamped source wins.
                stamped = [(sl.get(k, {}).get("updated") or "", "Sleeper"), (es.get(k, {}).get("updated") or "", "ESPN")]
                stamped = [(t, s) for t, s in stamped if t and votes.get(s)]
                src = max(stamped)[1] if stamped else max(votes, key=lambda s: counts[votes[s]])
                status, basis = votes[src], f"using {src}, the most recently updated"
        else:
            status, basis = None, "no designation for this game"
        all_views = set(votes.values()) | ({views["official"]} if views["official"] else set())
        resolved[k] = {"status": status, "basis": basis, "views": views,
                       "agree": len({SEVERITY.get(v, 3) for v in all_views}) <= 1}

    unavailable = {k for k, r in resolved.items() if r["status"] and SEVERITY.get(r["status"], 3) == 0}
    out = []
    for k, r in resolved.items():
        if not r["status"]:
            continue
        info = sl.get(k) or es.get(k) or report.get(k) or {}
        d = dk.get(k)
        name = info.get("name") or (d or {}).get("name")
        position = info.get("position") or (d or {}).get("position")
        if r["status"] in ("IR", "PUP", "Suspended") and not (_recent(sl.get(k, {}).get("updated")) or _recent(es.get(k, {}).get("updated"))):
            continue                          # long-term absences already priced in, unless news is fresh
        next_by, slot_by, starter_by = {}, {}, []
        for src, depth in depths.items():
            nxt, slot, starter = _next_up(depth, k, unavailable)
            if slot:
                slot_by[src] = slot
                starter_by.append(starter)
                if nxt:
                    next_by[src] = nxt
        starter = any(starter_by)
        relevant = position != "LS" and (position == "QB" or starter or (d and (d.get("salary") or 0) >= 4500))
        if not relevant:
            continue
        votes = Counter(_key(n) for n in next_by.values())
        next_up, agree_n = None, 0
        if votes:
            order = {s: i for i, s in enumerate(depths)}           # tie-break: team site, ESPN, Sleeper
            best_key, agree_n = max(votes.items(), key=lambda kv: (kv[1], -min(order[s] for s, n in next_by.items() if _key(n) == kv[0])))
            next_up = next(n for n in next_by.values() if _key(n) == best_key)
        rep = report.get(k) or {}
        row = {
            "name": name, "position": position, "unit": None, "slot": next(iter(slot_by.values()), None),
            "starter": starter, "status": r["status"], "status_basis": r["basis"], "sources_agree": r["agree"],
            "designations": {s: v for s, v in r["views"].items() if v or s == "official"},
            "practice": rep.get("practice") or None, "official_injury": rep.get("injury"),
            "body_part": (sl.get(k) or {}).get("body_part") or (es.get(k) or {}).get("body_part") or rep.get("injury"),
            "espn_detail": (es.get(k) or {}).get("detail"), "return_date": (es.get(k) or {}).get("return_date"),
            "status_updated": max(filter(None, [(sl.get(k) or {}).get("updated"), (es.get(k) or {}).get("updated")]), default=None),
            "next_up": next_up, "next_up_by_source": next_by,
            "next_up_agreement": f"{agree_n} of {len(next_by)} depth charts" if next_by else "not on a readable depth chart",
        }
        if d:
            row.update(dk_status=d.get("injury"), salary=d.get("salary"), proj=d.get("final"), own=d.get("ownership"))
        out.append(row)
    out.sort(key=lambda x: (SEVERITY.get(x["status"], 3), x["position"] != "QB", not x["starter"], x["name"] or ""))
    coverage = {"team_report": site.get("report_status"), "team_depth_chart": site.get("depth_status"),
                "espn_depth_chart": "ok" if depths["ESPN"] else "unavailable",
                "sleeper": "ok" if team in data["sleeper_depth"] else "unavailable",
                "team_report_url": site.get("url")}
    return out, coverage
