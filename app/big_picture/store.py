"""Append-only storage for the Big Picture: DraftKings odds snapshots and
report versions. Postgres (DATABASE_URL, the same Neon database as account
sync) when configured, else JSON files under data/cache/big_picture/ (local
runs and tests). Rows are only ever inserted -- a forecast, once published,
is never rewritten; later versions sit beside it.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.config import CACHE_DIR

SCHEMA = """
create table if not exists bp_odds (
    id          bigserial   primary key,
    captured_at timestamptz not null,
    season      int         not null,
    week        int         not null,
    game        text        not null,
    market      text        not null,
    side        text        not null,
    line        double precision,
    price       int,
    source      text        not null
);
create index if not exists bp_odds_week on bp_odds (season, week, game, market, side, captured_at);
create table if not exists bp_reports (
    id          bigserial   primary key,
    created_at  timestamptz not null,
    season      int         not null,
    week        int         not null,
    kind        text        not null,
    summary     jsonb       not null,
    dossier     jsonb       not null,
    report      jsonb       not null
);
create index if not exists bp_reports_week on bp_reports (season, week, created_at);
"""

LOCAL_DIR = CACHE_DIR / "big_picture"
_LOCK = threading.Lock()
_READY = {"done": False}


def _url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def _connect():
    import psycopg
    conn = psycopg.connect(_url(), autocommit=True, connect_timeout=15)
    if not _READY["done"]:
        conn.execute(SCHEMA)
        _READY["done"] = True
    return conn


def _local(name: str) -> Path:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    return LOCAL_DIR / name


def _read(name: str) -> list[dict]:
    p = _local(name)
    return json.loads(p.read_text()) if p.exists() else []


def _write(name: str, rows: list[dict]) -> None:
    p = _local(name)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, separators=(",", ":"), default=str))
    tmp.replace(p)


def now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ odds
ODDS_FIELDS = ("captured_at", "season", "week", "game", "market", "side", "line", "price", "source")


def odds_history(season: int, week: int) -> list[dict]:
    """Every stored DraftKings quote for the week, oldest first."""
    if _url():
        with _connect() as conn:
            cur = conn.execute(f"select {', '.join(ODDS_FIELDS)} from bp_odds where season = %s and week = %s "
                               "order by captured_at, id", (season, week))
            return [{**dict(zip(ODDS_FIELDS, r)), "captured_at": r[0].isoformat()} for r in cur.fetchall()]
    with _LOCK:
        return [r for r in _read("odds.json") if r["season"] == season and r["week"] == week]


def latest_quotes(history: list[dict]) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for r in history:
        out[(r["game"], r["market"], r["side"])] = r
    return out


def add_odds(rows: list[dict]) -> int:
    """Store quotes that differ from the last stored quote for the same game/market/side; returns how many."""
    if not rows:
        return 0
    season, week = rows[0]["season"], rows[0]["week"]
    last = latest_quotes(odds_history(season, week))
    new = [r for r in rows if (p := last.get((r["game"], r["market"], r["side"]))) is None
           or p["line"] != r["line"] or p["price"] != r["price"]]
    if not new:
        return 0
    if _url():
        with _connect() as conn, conn.cursor() as cur:
            cur.executemany(f"insert into bp_odds ({', '.join(ODDS_FIELDS)}) values ({', '.join(['%s'] * len(ODDS_FIELDS))})",
                            [tuple(r[f] for f in ODDS_FIELDS) for r in new])
        return len(new)
    with _LOCK:
        data = _read("odds.json")
        data.extend({f: r[f] for f in ODDS_FIELDS} for r in new)
        _write("odds.json", data)
    return len(new)


# ------------------------------------------------------------------ reports
def add_report(season: int, week: int, kind: str, summary: dict, dossier: dict, report: dict) -> dict:
    created = now()
    if _url():
        from psycopg.types.json import Jsonb
        with _connect() as conn:
            cur = conn.execute("insert into bp_reports (created_at, season, week, kind, summary, dossier, report) "
                               "values (%s, %s, %s, %s, %s, %s, %s) returning id",
                               (created, season, week, kind, Jsonb(summary), Jsonb(dossier), Jsonb(report)))
            rid = cur.fetchone()[0]
    else:
        with _LOCK:
            data = _read("reports.json")
            rid = (max((r["id"] for r in data), default=0)) + 1
            data.append({"id": rid, "created_at": created.isoformat(), "season": season, "week": week, "kind": kind,
                         "summary": summary, "dossier": dossier, "report": report})
            _write("reports.json", data)
    return {"id": rid, "created_at": created.isoformat()}


def list_reports(season: int | None = None, limit: int = 30) -> list[dict]:
    """Newest first: id, created_at, season, week, kind, summary (no bodies)."""
    if _url():
        with _connect() as conn:
            where, args = ("where season = %s", (season,)) if season else ("", ())
            cur = conn.execute(f"select id, created_at, season, week, kind, summary from bp_reports {where} "
                               "order by created_at desc, id desc limit %s", (*args, limit))
            return [{"id": r[0], "created_at": r[1].isoformat(), "season": r[2], "week": r[3], "kind": r[4], "summary": r[5]}
                    for r in cur.fetchall()]
    with _LOCK:
        rows = [r for r in _read("reports.json") if not season or r["season"] == season]
    rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
    return [{k: r[k] for k in ("id", "created_at", "season", "week", "kind", "summary")} for r in rows[:limit]]


def get_report(report_id: int | None = None, *, with_dossier: bool = True) -> dict | None:
    """One report (the newest when report_id is None)."""
    cols = "id, created_at, season, week, kind, summary, report" + (", dossier" if with_dossier else "")
    if _url():
        with _connect() as conn:
            cur = conn.execute(f"select {cols} from bp_reports " + ("where id = %s" if report_id else "")
                               + " order by created_at desc, id desc limit 1", (report_id,) if report_id else ())
            r = cur.fetchone()
        if not r:
            return None
        out = {"id": r[0], "created_at": r[1].isoformat(), "season": r[2], "week": r[3], "kind": r[4],
               "summary": r[5], "report": r[6]}
        if with_dossier:
            out["dossier"] = r[7]
        return out
    with _LOCK:
        rows = _read("reports.json")
    if report_id:
        rows = [r for r in rows if r["id"] == report_id]
    if not rows:
        return None
    r = max(rows, key=lambda r: (r["created_at"], r["id"]))
    return {k: v for k, v in r.items() if with_dossier or k != "dossier"}


def previous_dossiers(season: int, week: int, before: str | None = None, limit: int = 1) -> list[dict]:
    """The most recent stored dossiers for a week (newest first), optionally only those before a timestamp."""
    if _url():
        with _connect() as conn:
            cur = conn.execute("select created_at, dossier from bp_reports where season = %s and week = %s "
                               + ("and created_at < %s " if before else "")
                               + "order by created_at desc, id desc limit %s",
                               (season, week, *( [before] if before else []), limit))
            return [{**r[1], "_created_at": r[0].isoformat()} for r in cur.fetchall()]
    with _LOCK:
        rows = [r for r in _read("reports.json") if r["season"] == season and r["week"] == week
                and (not before or r["created_at"] < before)]
    rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
    return [{**r["dossier"], "_created_at": r["created_at"]} for r in rows[:limit]]
