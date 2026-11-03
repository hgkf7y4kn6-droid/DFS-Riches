"""Beat-writer tracking: what the reporters who cover each team are saying about who plays and how much.

Context first, not a projection input. A beat writer's post says something about a player's availability or role
before the numbers catch up, so the app reads it as a lean on how that player's playing time -- and so the field's
ownership of him -- may move ("Out" -> ownership likely down, a teammate's role up). It does not change any
projection, play chance or ownership estimate. Only a signal type that has been graded against what happened and
beat its base rate (`grade`, recorded in data/beat_signal_evidence.json "promoted") is allowed to do more; that file
ships empty, so today every signal is display-only.

Sources are free and public: Bluesky author feeds (public AppView, no key) and RSS/Atom feeds. Writers live in
data/beat_writers.json; one is `verified` only after a person confirmed the account is that reporter
(scripts/discover_beat_writers.py proposes candidates, never trusts them). Posts are kept as a short excerpt with a
link back to the original and the writer's name -- not republished in full. Reading is rule-based on purpose
(phrase lists, no model): deterministic, free, and easy to audit. Questions and reposts are ignored.

Every signal is stored with its time so it can be graded after the games: that record is how the data earns a bigger
role, if it does.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from app.cache import cached_fetch
from app.config import CACHE_DIR
from app.matching import normalize_name

log = logging.getLogger(__name__)

WRITERS_FILE = Path(__file__).resolve().parent.parent / "data" / "beat_writers.json"
EVIDENCE_FILE = Path(__file__).resolve().parent.parent / "data" / "beat_signal_evidence.json"
DISK = CACHE_DIR / "beat_signals.json"
BSKY_FEED = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
FEED_TTL = 60 * 10
MAX_AGE = timedelta(days=6)        # older posts describe another week
MAX_EXCERPT = 240
MAX_FEED_BYTES = 2_000_000
CONCURRENCY = 6
MIN_GRADED = 40                    # signals of one kind needed before it can be promoted
HEADERS = {"User-Agent": "RichesAnalytics/1.0 (beat-writer reader; public posts only)"}

# --------------------------------------------------------------------------- reading a post
# (type, direction) -> phrases. Checked per clause; a "not expected to play" is one negative phrase, so the
# positive "expected to play" inside it is dropped.
_PATTERNS: dict[tuple[str, str], re.Pattern] = {
    ("availability", "down"): re.compile(
        r"\b(?:ruled out|will not play|won'?t play|(?:is|are|will be|has been|officially) out(?!\s+(?:of|on|there|here|to|with)\b)|doubtful|"
        r"placed on (?:injured reserve|ir)|inactive|not expected to play|will miss|sidelined|did not practice|dnp)\b", re.I),
    ("availability", "up"): re.compile(
        r"\b(?:expected to play|will play|plans to play|good to go|cleared to play|full practice|full participant|"
        r"fully participated|(?:is|will be) active|returns? to practice|back at practice)\b", re.I),
    ("availability", "uncertain"): re.compile(
        r"\b(?:questionable|game-?time decision|day-to-day|limited (?:in|at|during) practice|limited participant)\b", re.I),
    ("role", "up"): re.compile(
        r"\b(?:will start|named (?:the )?starter|lead back|bell ?cow|featured back|primary (?:back|receiver)|"
        r"expected to (?:see|get) (?:more|an increased)|increased (?:role|workload|snaps)|more (?:snaps|touches|targets))\b", re.I),
    ("role", "down"): re.compile(
        r"\b(?:committee|time ?share|split (?:carries|touches|snaps)|reduced (?:role|workload|snaps)|snap count|"
        r"limited snaps|benched|demoted|will rotate|backup role|fewer (?:snaps|touches|targets))\b", re.I),
}
_CLAUSE = re.compile(r"[.;!\n]+")


def classify(text: str) -> list[tuple[str, str]]:
    """The (type, direction) signals one clause of text carries. A question carries none."""
    if "?" in text:
        return []
    found: list[tuple[str, str, tuple[int, int]]] = []
    for (kind, direction), pat in _PATTERNS.items():
        for m in pat.finditer(text):
            found.append((kind, direction, m.span()))
    negatives = [s for k, d, s in found if k == "availability" and d == "down"]
    out = []
    for kind, direction, (a, b) in found:
        if kind == "availability" and direction == "up" and any(x <= a and b <= y for x, y in negatives):
            continue                                    # "not expected to play" is not "expected to play"
        if (kind, direction) not in out:
            out.append((kind, direction))
    return out


def find_players(text: str, roster: list[tuple[str, str, str]], team: str | None) -> list[tuple[str, str]]:
    """[(name, team)] mentioned in `text`, from the writer's team (all teams when he has none). A full name
    matches; so does a last name of 4+ letters that is unique on that team."""
    pool = [(n, t) for n, t, pos in roster if pos != "DST" and (not team or t == team)]
    norm = " " + normalize_name(text) + " "
    hits = [(n, t) for n, t in pool if f" {normalize_name(n)} " in norm]
    if hits:
        return hits
    last: dict[str, list[tuple[str, str]]] = {}
    for n, t in pool:
        parts = normalize_name(n).split()
        if parts and len(parts[-1]) >= 4:
            last.setdefault(parts[-1], []).append((n, t))
    return [v[0] for k, v in last.items() if len(v) == 1 and f" {k} " in norm]


def read_post(text: str, roster: list[tuple[str, str, str]], team: str | None) -> list[dict]:
    """[{player, team, type, direction}] a post says. Each clause's signals go to the players that clause names;
    a clause naming nobody uses the post's single named player, if there is exactly one."""
    overall = find_players(text, roster, team)
    out, seen = [], set()
    for clause in _CLAUSE.split(text):
        signals = classify(clause)
        if not signals:
            continue
        who = find_players(clause, roster, team) or (overall if len(overall) == 1 else [])
        for name, t in who:
            for kind, direction in signals:
                if (name, kind, direction) not in seen:
                    seen.add((name, kind, direction))
                    out.append({"player": name, "team": t, "type": kind, "direction": direction})
    return out


# --------------------------------------------------------------------------- reading a feed
def _when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_bluesky(payload: dict, handle: str) -> list[dict]:
    """[{id, text, url, posted_at}] from an author feed. Reposts and replies are skipped."""
    out = []
    for item in payload.get("feed") or []:
        post, rec = item.get("post") or {}, (item.get("post") or {}).get("record") or {}
        if item.get("reason") or rec.get("reply") or not rec.get("text"):
            continue
        posted = _when(rec.get("createdAt"))
        uri = post.get("uri") or ""
        if posted is None or not uri:
            continue
        out.append({"id": uri, "text": rec["text"], "posted_at": posted,
                    "url": f"https://bsky.app/profile/{handle}/post/{uri.rsplit('/', 1)[-1]}"})
    return out


def parse_feed(xml_text: str) -> list[dict]:
    """[{id, text, url, posted_at}] from an RSS or Atom document. Refuses DTDs/entities (untrusted XML)."""
    head = xml_text[:4096].lower()
    if "<!doctype" in head or "<!entity" in xml_text.lower() or len(xml_text) > MAX_FEED_BYTES:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    strip = lambda s: re.sub(r"<[^>]+>", " ", s or "")  # noqa: E731
    out = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        kids = {c.tag.rsplit("}", 1)[-1]: c for c in el}
        title = (kids["title"].text or "") if "title" in kids else ""
        body = ""
        for k in ("description", "summary", "content"):
            if k in kids and kids[k].text:
                body = kids[k].text
                break
        link = kids["link"].get("href") or (kids["link"].text or "") if "link" in kids else ""
        stamp = next((kids[k].text for k in ("pubDate", "published", "updated") if k in kids), None)
        posted = _when(stamp)
        if posted is None or not link:
            continue
        text = re.sub(r"\s+", " ", strip(f"{title}. {body}")).strip()
        out.append({"id": link, "text": text, "url": link, "posted_at": posted})
    return out


# --------------------------------------------------------------------------- writers
def load_writers() -> list[dict]:
    """The tracked writers: those with a Bluesky handle or an RSS feed and not marked rejected."""
    try:
        rows = json.loads(WRITERS_FILE.read_text()).get("writers", [])
    except (OSError, ValueError):
        return []
    return [w for w in rows if (w.get("bluesky") or w.get("rss")) and w.get("status") != "rejected"]


def coverage(writers: list[dict]) -> dict:
    teams = {w.get("team") for w in writers if w.get("team")}
    return {"writers": len(writers), "verified": sum(1 for w in writers if w.get("verified")), "teams": len(teams)}


async def _fetch_writer(client: httpx.AsyncClient, w: dict) -> list[dict]:
    if w.get("bluesky"):
        handle = w["bluesky"].lstrip("@")

        async def get() -> dict:
            r = await client.get(BSKY_FEED, params={"actor": handle, "limit": 30, "filter": "posts_no_replies"})
            r.raise_for_status()
            return r.json()

        return parse_bluesky(await cached_fetch(f"beat_bsky_{handle}", FEED_TTL, get), handle)

    async def get_rss() -> str:
        r = await client.get(w["rss"])
        r.raise_for_status()
        return r.text

    return parse_feed(await cached_fetch("beat_rss_" + hashlib.sha1(w["rss"].encode()).hexdigest()[:16], FEED_TTL, get_rss))


async def collect(writers: list[dict], roster: list[tuple[str, str, str]], season: int, week: int,
                  now: datetime | None = None) -> tuple[list[dict], list[str]]:
    """(signals, names of writers whose feed couldn't be read). A failed feed is reported, never hidden."""
    now = now or datetime.now(timezone.utc)
    sem = asyncio.Semaphore(CONCURRENCY)
    signals: list[dict] = []
    failed: list[str] = []

    async with httpx.AsyncClient(timeout=10, headers=HEADERS, follow_redirects=True) as client:
        async def one(w: dict) -> None:
            async with sem:
                try:
                    posts = await _fetch_writer(client, w)
                except Exception as exc:
                    log.warning("beat_news: %s failed: %s", w.get("name"), exc)
                    failed.append(w.get("name") or w.get("bluesky") or w.get("rss"))
                    return
            for post in posts:
                if now - post["posted_at"] > MAX_AGE or post["posted_at"] > now + timedelta(hours=1):
                    continue
                for s in read_post(post["text"], roster, w.get("team")):
                    sid = hashlib.sha1(f"{post['id']}|{s['player']}|{s['type']}|{s['direction']}".encode()).hexdigest()[:16]
                    signals.append({"id": sid, "season": season, "week": week, **s, "writer": w.get("name"),
                                    "outlet": w.get("outlet"), "verified": bool(w.get("verified")),
                                    "text": post["text"][:MAX_EXCERPT], "url": post["url"],
                                    "posted_at": post["posted_at"].isoformat(timespec="seconds"),
                                    "seen_at": now.isoformat(timespec="seconds")})

        await asyncio.gather(*(one(w) for w in writers))
    return signals, failed


# --------------------------------------------------------------------------- storage (Postgres, else disk)
SCHEMA = """
create table if not exists beat_signals (
    id text primary key, season int not null, week int not null, team text not null, player text not null,
    writer text, outlet text, verified boolean not null default false, type text not null, direction text not null,
    text text, url text, posted_at timestamptz not null, seen_at timestamptz not null
);
"""
_COLS = ("id", "season", "week", "team", "player", "writer", "outlet", "verified", "type", "direction", "text", "url",
         "posted_at", "seen_at")


def _db_url() -> str | None:
    import os
    return os.environ.get("DATABASE_URL") or None


def _disk() -> list[dict]:
    try:
        return json.loads(DISK.read_text())
    except (OSError, ValueError):
        return []


def save(signals: list[dict]) -> int:
    """Store signals not seen before (by id); returns how many were new."""
    if not signals:
        return 0
    if _db_url():
        try:
            import psycopg
            with psycopg.connect(_db_url(), autocommit=True, connect_timeout=10) as conn:
                conn.execute(SCHEMA)
                new = 0
                for s in signals:
                    new += conn.execute(f"insert into beat_signals ({', '.join(_COLS)}) values ({', '.join(['%s'] * len(_COLS))}) "
                                        "on conflict (id) do nothing", tuple(s[c] for c in _COLS)).rowcount
                return new
        except Exception as exc:
            log.warning("beat_news: database write failed, kept on disk: %s", exc)
    have = {s["id"] for s in _disk()}
    fresh = [s for s in signals if s["id"] not in have]
    if fresh:
        DISK.write_text(json.dumps(_disk() + fresh))
    return len(fresh)


def load(season: int, week: int) -> list[dict]:
    if _db_url():
        try:
            import psycopg
            with psycopg.connect(_db_url(), autocommit=True, connect_timeout=10) as conn:
                conn.execute(SCHEMA)
                rows = conn.execute(f"select {', '.join(_COLS)} from beat_signals where season = %s and week = %s "
                                    "order by posted_at desc", (season, week)).fetchall()
            return [{c: (v.isoformat(timespec="seconds") if hasattr(v, "isoformat") else v) for c, v in zip(_COLS, r)} for r in rows]
        except Exception as exc:
            log.warning("beat_news: database read failed: %s", exc)
    return sorted((s for s in _disk() if s["season"] == season and s["week"] == week), key=lambda s: s["posted_at"], reverse=True)


# --------------------------------------------------------------------------- how it is used
_LEAN = {("availability", "down"): "down", ("availability", "up"): "up", ("availability", "uncertain"): "watch",
         ("role", "up"): "up", ("role", "down"): "down"}
_WHY = {("availability", "down"): "reported out or unlikely to play", ("availability", "up"): "reported expected to play",
        ("availability", "uncertain"): "status uncertain", ("role", "up"): "reported role increase",
        ("role", "down"): "reported role cut"}


def ownership_watch(signals: list[dict]) -> list[dict]:
    """Per player, which way the beat reporting leans for his playing time -- and so how the field's ownership of him
    may move -- as words and counts, never a number. Opposing reports are "mixed". Display-only."""
    by: dict[tuple[str, str], list[dict]] = {}
    for s in signals:
        by.setdefault((s["team"], s["player"]), []).append(s)
    out = []
    for (team, player), rows in by.items():
        leans = {_LEAN[(r["type"], r["direction"])] for r in rows}
        lean = leans.pop() if len(leans) == 1 else ("mixed" if {"up", "down"} <= leans else "watch")
        out.append({"player": player, "team": team, "lean": lean, "reports": len(rows),
                    "writers": sorted({r["writer"] for r in rows if r.get("writer")}),
                    "reasons": sorted({_WHY[(r["type"], r["direction"])] for r in rows}),
                    "latest": max(r["posted_at"] for r in rows),
                    "verified_only": all(r["verified"] for r in rows)})
    return sorted(out, key=lambda x: x["latest"], reverse=True)


# --------------------------------------------------------------------------- earning a bigger role
def promoted() -> set[tuple[str, str]]:
    """Signal kinds graded good enough to do more than inform (data/beat_signal_evidence.json). Empty today."""
    try:
        return {tuple(x) for x in json.loads(EVIDENCE_FILE.read_text()).get("promoted", [])}
    except (OSError, ValueError, TypeError):
        return set()


def _wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    p = hits / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d, (c + m) / d


def grade(graded: list[dict], baseline: dict[tuple[str, str], float], min_n: int = MIN_GRADED) -> dict[str, dict]:
    """How each signal kind did once the games were played. `graded`: [{type, direction, hit}] where `hit` is whether
    the outcome the signal predicted happened (an "up" availability report: he played; a "down" role report: his snap
    share fell ...). `baseline`: the rate that outcome has with no report. A kind is promotable only with min_n or more
    graded signals and a 95% Wilson interval that excludes its baseline."""
    out = {}
    kinds = {(g["type"], g["direction"]) for g in graded}
    for kind in sorted(kinds):
        rows = [g for g in graded if (g["type"], g["direction"]) == kind]
        n, hits = len(rows), sum(1 for g in rows if g["hit"])
        lo, hi = _wilson(hits, n)
        base = baseline.get(kind)
        out["|".join(kind)] = {"n": n, "rate": round(hits / n, 3), "low": round(lo, 3), "high": round(hi, 3), "baseline": base,
                               "promote": bool(base is not None and n >= min_n and (lo > base or hi < base))}
    return out
