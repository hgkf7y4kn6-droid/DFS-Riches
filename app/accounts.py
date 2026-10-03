"""User accounts: Clerk sign-in and saved data that follows the user between
devices.

Auth      The app sends Clerk's session token (a short-lived RS256 JWT) as
          `Authorization: Bearer <token>`. It's verified against the Clerk
          instance's public JWKS, found from the publishable key, so the
          server needs no secret to know who is calling.

Storage   Each user's saved data is a few JSON documents ("keys"):
            saved_lineups  builder lineups saved per season:week:slate
            submissions    logged contest entries (balance card, P/L)
            pool_tags      Prioritize / Neutral / Fade calls per pool
            settings       small preferences (matchup-rank mode, ...)
          Primary store: Neon Postgres (DATABASE_URL), one row per user and
          key, with no size worries. Clerk user metadata (CLERK_SECRET_KEY)
          always gets a compact profile (what's stored, counts, last sync)
          and, when no database is configured, holds the data itself --
          trimmed to Clerk's ~8 KB metadata limit.

Master    Accounts whose verified email is in MASTER_EMAILS, whose id is in
          MASTER_USER_IDS, or with Clerk public metadata {"role": "master"},
          keep everything forever. Other accounts keep
          saved lineups and pool tags for the last RETAIN_WEEKS weeks (contest
          entries are always kept), which keeps the free database small.

Writes are last-write-wins per key by the client's `updated_at`.
"""
from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import jwt

from app.config import DEFAULT_CLERK_PUBLISHABLE_KEY

KEYS = ("saved_lineups", "submissions", "pool_tags", "settings")
MAX_BYTES = 512 * 1024              # per key, for regular accounts
MASTER_MAX_BYTES = 8 * 1024 * 1024
RETAIN_WEEKS = 6
METADATA_BUDGET = 7000              # bytes of Clerk private metadata we allow ourselves
CLERK_API = "https://api.clerk.com/v1"
USER_CACHE_SECONDS = 120


class AuthError(Exception):
    pass


# ----------------------------------------------------------------- config
def publishable_key() -> str:
    return os.environ.get("CLERK_PUBLISHABLE_KEY") or DEFAULT_CLERK_PUBLISHABLE_KEY


def frontend_api(pk: str | None = None) -> str:
    """The Clerk instance host encoded in a publishable key
    ("pk_test_" + base64("related-cougar-2190.clerk.accounts.dev$"))."""
    pk = pk or publishable_key()
    encoded = pk.split("_", 2)[-1]
    host = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    return host.rstrip("$")


def _secret() -> str | None:
    return os.environ.get("CLERK_SECRET_KEY") or None


def _database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def storage_mode() -> str:
    if _database_url():
        return "neon"
    return "clerk" if _secret() else "none"


# ------------------------------------------------------------------- auth
_JWKS: dict[str, Any] = {"at": 0.0, "keys": {}}


async def _signing_key(kid: str):
    if kid not in _JWKS["keys"] or time.time() - _JWKS["at"] > 3600:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"https://{frontend_api()}/.well-known/jwks.json")
            resp.raise_for_status()
        _JWKS["keys"] = {k["kid"]: jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(k)) for k in resp.json()["keys"]}
        _JWKS["at"] = time.time()
    key = _JWKS["keys"].get(kid)
    if key is None:
        raise AuthError("unknown signing key")
    return key


async def verify(authorization: str | None) -> str:
    """The Clerk user id behind `Authorization: Bearer <session token>`."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("sign in required")
    token = authorization.split(" ", 1)[1].strip()
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        claims = jwt.decode(token, await _signing_key(kid), algorithms=["RS256"], leeway=30,
                            options={"verify_aud": False, "require": ["exp", "sub"]})
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"invalid session: {exc}") from exc
    if claims.get("iss") and frontend_api() not in claims["iss"]:
        raise AuthError("session from another Clerk instance")
    return claims["sub"]


# ------------------------------------------------------------- clerk API
async def _clerk(method: str, path: str, body: dict | None = None) -> dict | None:
    secret = _secret()
    if not secret:
        return None
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.request(method, f"{CLERK_API}{path}", json=body,
                                    headers={"Authorization": f"Bearer {secret}"})
        resp.raise_for_status()
        return resp.json()


_USERS: dict[str, tuple[float, dict]] = {}


async def clerk_user(user_id: str) -> dict:
    hit = _USERS.get(user_id)
    if hit and time.time() - hit[0] < USER_CACHE_SECONDS:
        return hit[1]
    user = await _clerk("GET", f"/users/{user_id}") or {}
    _USERS[user_id] = (time.time(), user)
    return user


async def is_master(user_id: str) -> bool:
    ids = {u.strip() for u in os.environ.get("MASTER_USER_IDS", "").split(",") if u.strip()}
    if user_id in ids:
        return True
    try:
        user = await clerk_user(user_id)
    except Exception:
        return False
    if (user.get("public_metadata") or {}).get("role") == "master":
        return True
    emails = {e.strip().lower() for e in os.environ.get("MASTER_EMAILS", "").split(",") if e.strip()}
    verified = {(e.get("email_address") or "").lower() for e in user.get("email_addresses") or []
                if (e.get("verification") or {}).get("status") == "verified"}
    return bool(emails & verified)


# ----------------------------------------------------------- retention
def _week_of(key: str) -> tuple[int, int] | None:
    """(season, week) from a "season:week:..." pool/slate key."""
    parts = key.split(":")
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None


def prune(key: str, value: Any, master: bool) -> Any:
    """Regular accounts keep the last RETAIN_WEEKS weeks of saved lineups and
    pool tags; masters keep everything; contest entries are never pruned."""
    if master or key not in ("saved_lineups", "pool_tags") or not isinstance(value, dict):
        return value
    weeks = sorted({w for k in value if (w := _week_of(k))})
    keep = set(weeks[-RETAIN_WEEKS:])
    return {k: v for k, v in value.items() if _week_of(k) in keep or _week_of(k) is None}


def validate(key: str, value: Any, master: bool) -> None:
    if key not in KEYS:
        raise ValueError(f"unknown key {key!r}")
    size = len(json.dumps(value, separators=(",", ":")))
    if size > (MASTER_MAX_BYTES if master else MAX_BYTES):
        raise ValueError(f"{key} is too large ({size // 1024} KB)")


# ------------------------------------------------------------------ store
SCHEMA = """
create table if not exists user_data (
    user_id    text        not null,
    key        text        not null,
    value      jsonb       not null,
    updated_at timestamptz not null,
    primary key (user_id, key)
)
"""
_SCHEMA_READY = {"done": False}


async def _connect():
    import psycopg

    conn = await psycopg.AsyncConnection.connect(_database_url(), autocommit=True, connect_timeout=15)
    if not _SCHEMA_READY["done"]:
        await conn.execute(SCHEMA)
        _SCHEMA_READY["done"] = True
    return conn


async def _db_load(user_id: str) -> dict[str, dict]:
    conn = await _connect()
    async with conn:
        cur = await conn.execute("select key, value, updated_at from user_data where user_id = %s", (user_id,))
        rows = await cur.fetchall()
    return {k: {"value": v, "updated_at": ts.isoformat()} for k, v, ts in rows}


async def _db_save(user_id: str, key: str, value: Any, updated_at: datetime) -> dict:
    from psycopg.types.json import Jsonb

    conn = await _connect()
    async with conn:
        cur = await conn.execute(
            """insert into user_data (user_id, key, value, updated_at) values (%s, %s, %s, %s)
               on conflict (user_id, key) do update set value = excluded.value, updated_at = excluded.updated_at
               where user_data.updated_at <= excluded.updated_at
               returning value, updated_at""",
            (user_id, key, Jsonb(value), updated_at))
        row = await cur.fetchone()
        if row is None:     # a newer copy is already stored: return it
            cur = await conn.execute("select value, updated_at from user_data where user_id = %s and key = %s",
                                     (user_id, key))
            row = await cur.fetchone()
    return {"value": row[0], "updated_at": row[1].isoformat()}


def _compact(key: str, value: Any) -> Any:
    """What fits in Clerk metadata when it's the only store: the latest week
    of lineups and pool tags, the 40 newest contest entries."""
    if key in ("saved_lineups", "pool_tags") and isinstance(value, dict):
        weeks = sorted({w for k in value if (w := _week_of(k))})
        return {k: v for k, v in value.items() if weeks and _week_of(k) == weeks[-1]}
    if key == "submissions" and isinstance(value, list):
        return value[:40]
    return value


async def _meta_load(user_id: str) -> dict[str, dict]:
    user = await clerk_user(user_id)
    return ((user.get("private_metadata") or {}).get("dfsriches") or {}).get("data") or {}


async def _meta_write(user_id: str, data: dict | None, profile: dict) -> None:
    body = {"dfsriches": {"profile": profile, **({"data": data} if data is not None else {})}}
    await _clerk("PATCH", f"/users/{user_id}/metadata", {"private_metadata": body})
    _USERS.pop(user_id, None)


def _profile(docs: dict[str, dict], master: bool) -> dict:
    def count(d):
        v = d.get("value")
        return len(v) if isinstance(v, (list, dict)) else 1
    return {"storage": storage_mode(), "master": master, "synced_at": datetime.now(timezone.utc).isoformat(),
            "counts": {k: count(d) for k, d in docs.items()},
            "settings": (docs.get("settings") or {}).get("value")}


# -------------------------------------------------------------------- api
async def load(user_id: str) -> dict:
    master = await is_master(user_id)
    mode = storage_mode()
    docs = await _db_load(user_id) if mode == "neon" else await _meta_load(user_id) if mode == "clerk" else {}
    return {"user_id": user_id, "master": master, "storage": mode, "data": docs}


async def save(user_id: str, key: str, value: Any, updated_at: str | None) -> dict:
    master = await is_master(user_id)
    validate(key, value, master)
    value = prune(key, value, master)
    ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00")) if updated_at else datetime.now(timezone.utc)
    mode = storage_mode()
    if mode == "neon":
        stored = await _db_save(user_id, key, value, ts)
        try:   # compact profile on the Clerk account (best effort)
            docs = await _db_load(user_id)
            await _meta_write(user_id, None, _profile(docs, master))
        except Exception:
            pass
        return stored
    if mode == "clerk":
        docs = await _meta_load(user_id)
        current = docs.get(key)
        if current and current["updated_at"] > ts.isoformat():
            return current
        docs[key] = {"value": _compact(key, value), "updated_at": ts.isoformat()}
        while len(json.dumps(docs)) > METADATA_BUDGET and docs.get("submissions", {}).get("value"):
            docs["submissions"]["value"] = docs["submissions"]["value"][:-5]
        await _meta_write(user_id, docs, _profile(docs, master))
        return docs[key]
    raise RuntimeError("account storage isn't configured (set DATABASE_URL or CLERK_SECRET_KEY)")
