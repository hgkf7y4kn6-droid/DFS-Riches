"""DraftKings Sportsbook NFL odds: the Big Picture's only market source.

Reads DraftKings' public sportsbook JSON (the same data its website loads):
game lines (spread, total, moneyline) and, when listed, team totals. Each
fetch is stored as a snapshot (app.big_picture.store, only quotes that
changed), so the first quote we captured for a market is its "opening" line
as far as this app knows, and every later move is kept with its timestamp.

DraftKings sometimes refuses requests from cloud servers; then nothing is
stored and the report says DraftKings prices are unavailable rather than
guessing.
"""
from __future__ import annotations

import logging
import time

import httpx

from app.big_picture import quant, store
from app.sources import TEAM_FIX, TEAM_NAMES

log = logging.getLogger(__name__)

SOURCE = "DraftKings Sportsbook"
NFL_LEAGUE = 88808
BASE = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusnj/v1/leagues"
GAME_LINES = 492
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://sportsbook.draftkings.com",
    "Referer": "https://sportsbook.draftkings.com/",
}
MIN_FETCH_SECONDS = 600          # at most one DraftKings fetch per 10 minutes
_LAST: dict = {"at": 0.0, "status": None}

NICKNAMES = {full.split()[-1].lower(): abbr for full, abbr in TEAM_NAMES.items()}


def team_abbr(name: str | None) -> str | None:
    """DraftKings participant names ("KC Chiefs", "NY Jets", "Kansas City Chiefs") -> app abbreviations."""
    if not name:
        return None
    s = name.strip()
    up = s.upper()
    if up in TEAM_NAMES.values():
        return up
    if up in TEAM_FIX:
        return TEAM_FIX[up]
    if s in TEAM_NAMES:
        return TEAM_NAMES[s]
    nick = s.split()[-1].lower()
    return NICKNAMES.get(nick)


# ------------------------------------------------------------------ parsing
def _participants(obj: dict) -> dict[str, str]:
    """venueRole ("Home"/"Away") -> team abbreviation."""
    out = {}
    for p in obj.get("participants") or []:
        role = (p.get("venueRole") or "").lower()
        abbr = team_abbr(p.get("name"))
        if role in ("home", "away") and abbr:
            out[role] = abbr
    return out


def parse(payload: dict) -> list[dict]:
    """DraftKings' sportscontent payload -> quotes {game "AWAY@HOME", market, side, line, price, kickoff}."""
    events = {}
    for e in payload.get("events") or []:
        teams = _participants(e)
        if "home" in teams and "away" in teams:
            events[str(e.get("id"))] = {"game": f"{teams['away']}@{teams['home']}", "kickoff": e.get("startEventDate"),
                                        "home": teams["home"], "away": teams["away"]}
    markets = {}
    for m in payload.get("markets") or []:
        ev = events.get(str(m.get("eventId")))
        if not ev:
            continue
        mtype = ((m.get("marketType") or {}).get("name") or m.get("name") or "").lower()
        name = (m.get("name") or "").lower()
        if "alternate" in mtype or "alternate" in name or "1st" in name or "half" in name or "quarter" in name:
            continue
        if mtype in ("spread", "point spread"):
            kind = "spread"
        elif mtype in ("total", "total points"):
            kind = "total"
        elif mtype in ("moneyline", "money line"):
            kind = "moneyline"
        elif "team total" in mtype or "team total" in name:
            kind = "team_total"
        else:
            continue
        markets[str(m.get("id"))] = {"kind": kind, "event": ev, "name": m.get("name") or ""}
    quotes: dict[tuple, dict] = {}
    for s in payload.get("selections") or []:
        mk = markets.get(str(s.get("marketId")))
        if not mk:
            continue
        ev, kind = mk["event"], mk["kind"]
        price = quant.american(((s.get("displayOdds") or {}).get("american")) or s.get("oddsAmerican"))
        if price is None:
            continue
        line = s.get("points")
        outcome = (s.get("outcomeType") or s.get("label") or "").lower()
        if kind in ("spread", "moneyline"):
            role = _participants(s)
            side = "home" if outcome == "home" or role.get("home") or team_abbr(s.get("label")) == ev["home"] \
                else "away" if outcome == "away" or role.get("away") or team_abbr(s.get("label")) == ev["away"] else None
            market = kind
        elif kind == "total":
            side = "over" if outcome.startswith("over") else "under" if outcome.startswith("under") else None
            market = "total"
        else:   # team total: which team, from the market name or the selection's participant
            team = _participants(s)
            whose = next((r for r in ("home", "away") if team.get(r)), None)
            if whose is None:
                label = mk["name"].replace(":", " ").split()
                hits = {team_abbr(w) for w in label} | {team_abbr(" ".join(label[:2]))}
                whose = "home" if ev["home"] in hits else "away" if ev["away"] in hits else None
            side = "over" if outcome.startswith("over") or (s.get("label") or "").lower().startswith("over") \
                else "under" if outcome.startswith("under") or (s.get("label") or "").lower().startswith("under") else None
            market = f"team_total_{whose}" if whose else None
        if side is None or market is None or (kind != "moneyline" and line is None):
            continue
        key = (ev["game"], market, side)
        # Several selections for one key would be alternates: keep the one priced closest to even.
        prev = quotes.get(key)
        if prev is None or abs(abs(price) - 110) < abs(abs(prev["price"]) - 110):
            quotes[key] = {"game": ev["game"], "market": market, "side": side,
                           "line": float(line) if line is not None else None, "price": price, "kickoff": ev["kickoff"]}
    return list(quotes.values())


def _team_total_categories(league: dict) -> list[int]:
    ids = []
    for c in league.get("categories") or []:
        if "team" in (c.get("name") or "").lower() and ("total" in (c.get("name") or "").lower() or "prop" in (c.get("name") or "").lower()):
            ids.append(c.get("id"))
    for c in league.get("subcategories") or []:
        if "team total" in (c.get("name") or "").lower() and c.get("categoryId"):
            ids.append(c["categoryId"])
    return [i for i in dict.fromkeys(ids) if i]


async def fetch() -> tuple[list[dict], str]:
    """(quotes, status). Status "ok", or why DraftKings couldn't be read."""
    async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as client:
        r = await client.get(f"{BASE}/{NFL_LEAGUE}/categories/{GAME_LINES}")
        if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
            return [], f"DraftKings Sportsbook answered HTTP {r.status_code}"
        payload = r.json()
        quotes = parse(payload)
        try:
            for cat in _team_total_categories(payload)[:2]:
                t = await client.get(f"{BASE}/{NFL_LEAGUE}/categories/{cat}")
                if t.status_code == 200:
                    quotes += [q for q in parse(t.json()) if q["market"].startswith("team_total")]
        except Exception as exc:          # team totals are a bonus; game lines still count
            log.info("DraftKings team totals unavailable: %s", exc)
    return quotes, "ok" if quotes else "DraftKings Sportsbook returned no NFL game lines"


async def snapshot(season: int, week: int, games: list[tuple[str, str]], force: bool = False) -> dict:
    """Fetch DraftKings (at most every MIN_FETCH_SECONDS) and store this week's changed quotes."""
    if not force and time.time() - _LAST["at"] < MIN_FETCH_SECONDS:
        return {"status": _LAST["status"], "stored": 0, "fetched_at": _LAST.get("iso")}
    _LAST["at"] = time.time()
    try:
        quotes, status = await fetch()
    except Exception as exc:
        quotes, status = [], f"DraftKings Sportsbook unreachable ({type(exc).__name__})"
    wanted = {f"{a}@{h}" for a, h in games}
    captured = store.now()
    rows = [{**q, "season": season, "week": week, "captured_at": captured, "source": SOURCE}
            for q in quotes if q["game"] in wanted]
    if quotes and not rows:
        status = "DraftKings Sportsbook listed no games from this week"
    import asyncio
    stored = await asyncio.to_thread(store.add_odds, rows) if rows else 0
    _LAST.update(status=status, iso=captured.isoformat())
    log.info("DraftKings odds snapshot: %s, %d quotes for week %d, %d new", status, len(rows), week, stored)
    return {"status": status, "stored": stored, "quotes": len(rows), "fetched_at": captured.isoformat()}


def summarize(history: list[dict]) -> dict:
    """{game: {market: {side: {opening, current, moves}}}} from stored quotes (oldest first)."""
    out: dict = {}
    for r in history:
        side = out.setdefault(r["game"], {}).setdefault(r["market"], {}).setdefault(r["side"], {"opening": None, "current": None, "moves": []})
        q = {"line": r["line"], "price": r["price"], "at": r["captured_at"]}
        if side["opening"] is None:
            side["opening"] = q
        side["current"] = q
        side["moves"].append(q)
    for g in out.values():
        for m in g.values():
            for s in m.values():
                s["moves"] = s["moves"][-12:]
    return out


# ------------------------------------------------------------------ from a GitHub Actions runner
async def snapshot_via_runner(site: str) -> dict:
    """When the site's server can't read DraftKings, fetch it from here (a GitHub Actions runner) and store
    the week's changed quotes in the same database. Returns the capture status (no odds are printed)."""
    async with httpx.AsyncClient(timeout=120) as client:
        info = (await client.get(f"{site}/api/odds", params={"summary": 1})).json()
        season, week = info["season"], info["week"]
        if info.get("status") == "ok":
            return {"via": "site", **info}
        wk = (await client.get(f"{site}/api/week", params={"season": season, "week": week})).json()
    sched = wk.get("schedule") or {}
    games = [(g["away"], g["home"]) for g in (sched.get("games") or []) + (sched.get("isolated_games") or [])]
    if not store._url():
        quotes, status = await fetch()
        return {"via": "runner", "status": status, "quotes": len(quotes), "stored": 0, "note": "no DATABASE_URL: nothing stored"}
    out = await snapshot(season, week, games, force=True)
    return {"via": "runner", "season": season, "week": week, **out}


def main() -> None:
    import asyncio
    import json
    import os
    logging.basicConfig(level=logging.WARNING)
    site = os.environ.get("BIG_PICTURE_SITE", "https://dfsriches.richesdigitalventures.com")
    print(json.dumps(asyncio.run(snapshot_via_runner(site))))


if __name__ == "__main__":
    main()
