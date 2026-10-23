"""Breaking news entered by hand: a player ruled Out (or Doubtful, Questionable, or confirmed Playing) by his coach
before DraftKings, ESPN or the team's injury report catch up.

Master accounts enter it (Settings > Breaking news, POST /api/news-overrides) for a season and week. It applies
everywhere the official designations do -- projections, the player pool, the DFS model, the plays, the optimal
lineups -- and, for linemen and defenders who aren't on a DraftKings slate, the game model's starters-out counts.

Official news still wins where it's stronger: a manual Out / Doubtful / Questionable only makes a player's status
worse, and a manual Playing only clears a Questionable tag or a stale IR / PUP roster tag (a player designated to
return) -- never an official Out or Doubtful, which also beat it when they arrive later). The newest entry for a player is the one that counts; removing it restores the feeds.

Kept in Postgres (DATABASE_URL, the account-sync database) so a redeploy doesn't lose it; without one, on disk.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from app.config import CACHE_DIR
from app.matching import normalize_name

log = logging.getLogger(__name__)

STATUSES = {"OUT": "Out", "D": "Doubtful", "Q": "Questionable", "PLAYING": "Playing"}
WORSE = {"OUT": {None, "", "Healthy", "Q", "D"}, "D": {None, "", "Healthy", "Q"}, "Q": {None, "", "Healthy"}}
DISK = CACHE_DIR / "news_overrides.json"
READ_TTL = 15              # seconds: other server instances see a new entry this soon
MAX_NOTE = 280

SCHEMA = """
create table if not exists news_overrides (
    id          text        primary key,
    season      int         not null,
    week        int         not null,
    team        text        not null,
    name        text        not null,
    status      text        not null,
    note        text,
    on_slate    boolean     not null default true,
    created_at  timestamptz not null,
    created_by  text
);
"""

_writes = 0
_read: dict[tuple[int, int], tuple[float, list[dict]]] = {}


def data_version() -> tuple[int]:
    """Changes with every entry added or removed here: part of the DFS model's cache key."""
    return (_writes,)


def _url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def _connect():
    import psycopg
    conn = psycopg.connect(_url(), autocommit=True, connect_timeout=10)
    conn.execute(SCHEMA)
    return conn


def _disk() -> list[dict]:
    try:
        return json.loads(DISK.read_text())
    except (OSError, ValueError):
        return []


def _load(season: int, week: int) -> list[dict]:
    if _url():
        try:
            with _connect() as conn:
                rows = conn.execute("select id, season, week, team, name, status, note, on_slate, created_at, created_by "
                                    "from news_overrides where season = %s and week = %s order by created_at",
                                    (season, week)).fetchall()
            return [{"id": r[0], "season": r[1], "week": r[2], "team": r[3], "name": r[4], "status": r[5], "note": r[6],
                     "on_slate": r[7], "created_at": r[8].isoformat(timespec="milliseconds"), "created_by": r[9]} for r in rows]
        except Exception as exc:          # fall back to whatever is on disk
            log.warning("news_overrides: database read failed: %s", exc)
    return [e for e in _disk() if e["season"] == season and e["week"] == week]


async def entries(season: int, week: int) -> list[dict]:
    """The week's entries, oldest first."""
    hit = _read.get((season, week))
    if hit and time.time() - hit[0] < READ_TTL:
        return hit[1]
    rows = await asyncio.to_thread(_load, season, week)
    _read[(season, week)] = (time.time(), rows)
    return rows


def _changed(season: int, week: int) -> None:
    global _writes
    _writes += 1
    _read.pop((season, week), None)


async def add(season: int, week: int, team: str, name: str, status: str, note: str = "", on_slate: bool = True,
              by: str | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    entry = {"id": uuid.uuid4().hex[:12], "season": season, "week": week, "team": team, "name": name, "status": status,
             "note": (note or "").strip()[:MAX_NOTE], "on_slate": on_slate,
             "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "created_by": by}

    def write() -> bool:
        if _url():
            try:
                with _connect() as conn:
                    conn.execute("insert into news_overrides (id, season, week, team, name, status, note, on_slate, created_at, created_by) "
                                 "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                                 tuple(entry[k] for k in ("id", "season", "week", "team", "name", "status", "note", "on_slate",
                                                          "created_at", "created_by")))
                return True
            except Exception as exc:
                log.warning("news_overrides: database write failed, kept on disk: %s", exc)
        DISK.write_text(json.dumps(_disk() + [entry]))
        return False

    entry["persisted"] = await asyncio.to_thread(write)
    _changed(season, week)
    return entry


async def remove(season: int, week: int, entry_id: str) -> bool:
    def delete() -> bool:
        gone = False
        if _url():
            try:
                with _connect() as conn:
                    gone = conn.execute("delete from news_overrides where id = %s", (entry_id,)).rowcount > 0
            except Exception as exc:
                log.warning("news_overrides: database delete failed: %s", exc)
        rows = _disk()
        keep = [e for e in rows if e["id"] != entry_id]
        if len(keep) != len(rows):
            DISK.write_text(json.dumps(keep))
            gone = True
        return gone

    gone = await asyncio.to_thread(delete)
    _changed(season, week)
    return gone


def latest(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """{(team, normalized name): the newest entry for him}."""
    out = {}
    for e in rows:
        out[(e["team"], normalize_name(e["name"]))] = e
    return out


def _note(e: dict, was: str | None) -> str:
    when = e["created_at"][11:16] + " UTC" if len(e.get("created_at") or "") >= 16 else ""
    return (f"Breaking news ({when}): {STATUSES[e['status']]}" + (f" -- {e['note']}" if e.get("note") else "")
            + f" (was {was or 'Healthy'})")


def apply(players, rows: list[dict]) -> None:
    """Each player's newest entry: Out / Doubtful / Questionable when that's worse than his current status;
    Playing clears a Questionable tag or a stale IR / PUP roster tag."""
    news = latest(rows)
    for p in players:
        e = news.get((p.team, normalize_name(p.name)))
        if not e:
            continue
        was = p.injury
        if e["status"] == "PLAYING":
            if was not in ("Q", "IR", "PUP"):
                continue
            p.injury = "Healthy"
        elif was in WORSE[e["status"]]:
            p.injury = e["status"]
        else:
            continue
        p.proj_notes = p.proj_notes + [_note(e, was)]


def as_news(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Out / Doubtful entries in app.injury_news.espn_statuses' shape, for the game model's starters-out counts."""
    return {k: {"code": e["status"], "status": STATUSES[e["status"]], "updated": e["created_at"]}
            for k, e in latest(rows).items() if e["status"] in ("OUT", "D")}
