"""Keeps uploaded actual contest ownership (and what the ownership models
learned from it) across redeploys.

The ownership store (app.ownership_store) lives on the host's disk, which a
redeploy wipes. Each actual-ownership upload is therefore also written to
Postgres (DATABASE_URL, the same Neon database as account sync) as one small
row -- the matched players and percentages, not the field's lineups -- and
the learned model state is kept as a single row. On startup, restore()
replays every stored upload into the disk store (idempotent by batch id) and
puts the learning file back.

No DATABASE_URL: everything is a no-op and the store stays disk-only.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

SCHEMA = """
create table if not exists ownership_actuals (
    batch       text        primary key,
    season      int         not null,
    week        int         not null,
    slate_id    text        not null,
    contest     text        not null,
    uploaded_at timestamptz not null,
    entries     int,
    observations jsonb      not null
);
create table if not exists ownership_learning (
    id          int         primary key,
    value       jsonb       not null,
    updated_at  timestamptz not null default now()
);
"""


def _url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def _connect():
    import psycopg
    conn = psycopg.connect(_url(), autocommit=True, connect_timeout=10)
    conn.execute(SCHEMA)
    return conn


def save_upload(season: int, week: int, slate_id: str, contest: str, batch: str, uploaded_at: str,
                entries: int | None, observations: list[dict]) -> bool:
    if not _url() or not observations:
        return False
    try:
        from psycopg.types.json import Jsonb
        with _connect() as conn:
            conn.execute(
                "insert into ownership_actuals (batch, season, week, slate_id, contest, uploaded_at, entries, observations) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s) on conflict (batch) do nothing",
                (batch, season, week, slate_id, contest, uploaded_at, entries, Jsonb(observations)))
        return True
    except Exception as exc:          # the upload still works from disk; just log
        log.warning("ownership_persist.save_upload failed: %s", exc)
        return False


def save_learning(learning: dict) -> None:
    if not _url():
        return
    try:
        from psycopg.types.json import Jsonb
        with _connect() as conn:
            conn.execute("insert into ownership_learning (id, value, updated_at) values (1, %s, now()) "
                         "on conflict (id) do update set value = excluded.value, updated_at = now()", (Jsonb(learning),))
    except Exception as exc:
        log.warning("ownership_persist.save_learning failed: %s", exc)


def restore() -> dict:
    """Replays stored uploads into the disk store and restores the learning
    file. Returns {"uploads": n replayed, "learning": bool}."""
    from app import ownership_store as store
    if not _url():
        return {"uploads": 0, "learning": False}
    replayed, learned = 0, False
    try:
        with _connect() as conn:
            rows = conn.execute("select season, week, slate_id, batch, observations from ownership_actuals order by uploaded_at").fetchall()
            for season, week, slate_id, batch, obs in rows:
                data = store.load(season, week, slate_id)
                if any(o.get("batch") == batch for o in data["observations"]):
                    continue
                data["observations"].extend(obs if isinstance(obs, list) else json.loads(obs))
                store.save(data)
                replayed += 1
            row = conn.execute("select value from ownership_learning where id = 1").fetchone()
            if row and not store.LEARNING_PATH.exists():
                store.write_learning_file(row[0] if isinstance(row[0], dict) else json.loads(row[0]))
                learned = True
    except Exception as exc:
        log.warning("ownership_persist.restore failed: %s", exc)
    if replayed:
        store.bump()
    return {"uploads": replayed, "learning": learned}
