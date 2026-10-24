"""Weekly Pro Picks: Pro users rank the players they think will be the top DraftKings scorers at each position
on the week's Classic Sunday Main, and are scored against how the slate actually finished.

Lists (the DFS Bros weekly MVP sheet): top 5 QBs, 10 RBs, 15 WRs, 3 TEs and 5 DSTs. Entries are optional and
can be changed until the Main's first kickoff; other users' entries stay hidden until then.

Scoring, per position, for each ranked player who finished in that position's actual top N:
  HIT_POINTS          for making the list at all, whatever the spot
  EXACT_BONUS         more when he finished at exactly the spot he was ranked
  -LOWER_PENALTY      per spot he finished below where he was ranked
  -HIGHER_PENALTY     per spot he finished above it (finishing higher is the smaller miss)
Players who missed the top N score nothing. The deductions only break ties: the largest possible deduction
(14 spots on the WR list, 7 points) is smaller than one hit. Tied actual scores share the spots they span, so
a player ranked anywhere inside his tie is "exact". A perfect entry scores PERFECT.

Stored in the Neon database (DATABASE_URL, table pro_picks), else a JSON file under data/cache/competition/
(local runs and tests).
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.config import CACHE_DIR

MAIN_SLATE = "classic_sunday"
SIZES = {"QB": 5, "RB": 10, "WR": 15, "TE": 3, "DST": 5}
HIT_POINTS = 10.0
EXACT_BONUS = 3.0
LOWER_PENALTY = 0.5
HIGHER_PENALTY = 0.25
PERFECT = sum(n * (HIT_POINTS + EXACT_BONUS) for n in SIZES.values())
NAME_MAX = 24

SCHEMA = """
create table if not exists pro_picks (
    season      int         not null,
    week        int         not null,
    user_id     text        not null,
    name        text        not null,
    picks       jsonb       not null,
    updated_at  timestamptz not null,
    primary key (season, week, user_id)
);
"""
LOCAL_DIR = CACHE_DIR / "competition"
_LOCK = threading.Lock()
_READY = {"done": False}


# ------------------------------------------------------------------ scoring
def finish_ranges(points: dict[int, float]) -> dict[int, tuple[int, int]]:
    """{player id: (best, worst) finishing spot} by actual points, highest first; tied scores share the
    spots they span (two players tied for 2nd both cover spots 2-3)."""
    order = sorted(points.items(), key=lambda kv: -kv[1])
    out: dict[int, tuple[int, int]] = {}
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and order[j + 1][1] == order[i][1]:
            j += 1
        for k in range(i, j + 1):
            out[order[k][0]] = (i + 1, j + 1)
        i = j + 1
    return out


def score_position(picks: list[int], ranges: dict[int, tuple[int, int]], size: int) -> dict:
    """One position's score: {points, hits, exact, rows: [{id, ranked, finished, points}]}."""
    rows, total, hits, exact = [], 0.0, 0, 0
    for ranked, pid in enumerate(picks[:size], start=1):
        best, worst = ranges.get(pid, (10 ** 6, 10 ** 6))
        if best > size:                                   # missed the top N
            rows.append({"id": pid, "ranked": ranked, "finished": best if best < 10 ** 6 else None, "points": 0.0})
            continue
        if best <= ranked <= worst:
            finished, pts = ranked, HIT_POINTS + EXACT_BONUS
            exact += 1
        elif best > ranked:                               # finished lower (a bigger number) than ranked
            finished, pts = best, HIT_POINTS - LOWER_PENALTY * (best - ranked)
        else:                                             # finished higher than ranked
            finished, pts = worst, HIT_POINTS - HIGHER_PENALTY * (ranked - worst)
        hits += 1
        total += pts
        rows.append({"id": pid, "ranked": ranked, "finished": finished, "points": round(pts, 2)})
    return {"points": round(total, 2), "hits": hits, "exact": exact, "rows": rows}


def score_entry(picks: dict[str, list[int]], actual: dict[str, dict[int, float]]) -> dict:
    """{points, hits, exact, pct_of_perfect, positions: {pos: score_position}} for one entry."""
    positions = {pos: score_position(picks.get(pos) or [], finish_ranges(actual.get(pos) or {}), n) for pos, n in SIZES.items()}
    points = round(sum(p["points"] for p in positions.values()), 2)
    return {"points": points, "hits": sum(p["hits"] for p in positions.values()),
            "exact": sum(p["exact"] for p in positions.values()),
            "pct_of_perfect": round(100 * points / PERFECT, 1), "positions": positions}


def standings(entries: list[dict], actual: dict[str, dict[int, float]], me: str | None = None) -> list[dict]:
    """Every entry scored and ranked (equal points share a rank); `me` marks the caller's row."""
    rows = [{"name": e["name"], "me": e["user_id"] == me, **score_entry(e["picks"], actual)} for e in entries]
    rows.sort(key=lambda r: (-r["points"], -r["hits"], -r["exact"], r["name"].lower()))
    rank = 0
    for i, r in enumerate(rows):
        if i == 0 or r["points"] != rows[i - 1]["points"]:
            rank = i + 1
        r["rank"] = rank
    return rows


# ------------------------------------------------------------------ entries
def clean_name(raw: str | None, fallback: str) -> str:
    name = re.sub(r"\s+", " ", re.sub(r"[^\w .'\-]", "", str(raw or ""))).strip()[:NAME_MAX]
    return name or fallback


def validate_picks(raw: dict, eligible: dict[int, str]) -> dict[str, list[int]]:
    """{pos: [dk ids]} from a submission: each id on the slate at that position, no repeats, at most the list
    size. Lists may be partial or empty (entering is optional; an empty spot just scores nothing)."""
    if not isinstance(raw, dict):
        raise ValueError("picks must be an object of position lists")
    out, seen = {}, set()
    for pos, size in SIZES.items():
        ids = raw.get(pos) or []
        if not isinstance(ids, list) or len(ids) > size:
            raise ValueError(f"{pos}: rank at most {size} players")
        clean = []
        for x in ids:
            pid = int(x)
            if eligible.get(pid) != pos:
                raise ValueError(f"{pos}: player {pid} isn't a {pos} on the main slate")
            if pid in seen:
                raise ValueError("Each player can be ranked once")
            seen.add(pid)
            clean.append(pid)
        out[pos] = clean
    return out


def _url() -> str | None:
    from app.big_picture.run import clean_database_url
    return clean_database_url(os.environ.get("DATABASE_URL")) or None


def _connect():
    import psycopg
    conn = psycopg.connect(_url(), autocommit=True, connect_timeout=15)
    if not _READY["done"]:
        conn.execute(SCHEMA)
        _READY["done"] = True
    return conn


def _local() -> Path:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    return LOCAL_DIR / "entries.json"


def load_entries(season: int, week: int) -> list[dict]:
    """[{user_id, name, picks, updated_at}] for one week."""
    if _url():
        with _connect() as conn:
            cur = conn.execute("select user_id, name, picks, updated_at from pro_picks where season = %s and week = %s",
                               (season, week))
            return [{"user_id": r[0], "name": r[1], "picks": r[2], "updated_at": r[3].isoformat()} for r in cur.fetchall()]
    with _LOCK:
        p = _local()
        data = json.loads(p.read_text()) if p.exists() else []
    return [e for e in data if e["season"] == season and e["week"] == week]


def save_entry(season: int, week: int, user_id: str, name: str, picks: dict[str, list[int]]) -> dict:
    now = datetime.now(timezone.utc)
    if _url():
        from psycopg.types.json import Jsonb
        with _connect() as conn:
            conn.execute("insert into pro_picks (season, week, user_id, name, picks, updated_at) values (%s, %s, %s, %s, %s, %s) "
                         "on conflict (season, week, user_id) do update set name = excluded.name, picks = excluded.picks, "
                         "updated_at = excluded.updated_at", (season, week, user_id, name, Jsonb(picks), now))
    else:
        with _LOCK:
            p = _local()
            data = json.loads(p.read_text()) if p.exists() else []
            data = [e for e in data if not (e["season"] == season and e["week"] == week and e["user_id"] == user_id)]
            data.append({"season": season, "week": week, "user_id": user_id, "name": name, "picks": picks,
                         "updated_at": now.isoformat()})
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(p)
    return {"user_id": user_id, "name": name, "picks": picks, "updated_at": now.isoformat()}


# ------------------------------------------------------------------ the week
async def main_slate(season: int, week: int):
    """(slate, players at the five positions) for the week's Classic Sunday Main; (None, []) before salaries."""
    from app import slates
    _schedule, slate_list = await slates.list_slates(season, week)
    slate = next((s for s in slate_list if s.slate_id == MAIN_SLATE), None)
    if slate is None or not slate.available:
        return slate, []
    players = (await slates.get_slate_players(season, week, MAIN_SLATE)).players
    return slate, [p for p in players if p.position in SIZES and p.dk_draftable_id is not None]


def lock_time(slate) -> datetime | None:
    return min((g.kickoff_utc for g in slate.games), default=None) if slate is not None else None


async def actual_points(season: int, week: int, slate, players: list) -> dict[str, dict[int, float]] | None:
    """{pos: {dk id: actual DK points}} once every Main game is final and its box scores are in, else None."""
    from app import nflverse_client as nc
    from app.optimal import slate_complete
    actuals = await nc.get_week_actuals(season, week)
    if not slate_complete(slate, actuals):
        return None
    out: dict[str, dict[int, float]] = {pos: {} for pos in SIZES}
    for p in players:
        out[p.position][p.dk_draftable_id] = nc.actual_points(actuals, name=p.name, position=p.position, team=p.team)
    return out


def default_name(user: dict) -> str:
    """A leaderboard name from the Clerk account: first name and last initial, else the username."""
    first, last = (user.get("first_name") or "").strip(), (user.get("last_name") or "").strip()
    if first:
        return clean_name(f"{first} {last[:1]}." if last else first, "Pro user")
    return clean_name(user.get("username"), "Pro user")
