"""Tiny on-disk JSON cache with a TTL, so repeated requests to Sleeper/DraftKings
don't re-fetch large payloads (the Sleeper player dict alone is several MB) on
every page load.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.config import CACHE_DIR


def _cache_path(key: str) -> Path:
    safe = key.replace("/", "_").replace(":", "_").replace("?", "_").replace("&", "_")
    return CACHE_DIR / f"{safe}.json"


def read_cache(key: str, ttl_seconds: float) -> Any | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl_seconds:
        return None
    try:
        with path.open("r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_cache(key: str, value: Any) -> None:
    path = _cache_path(key)
    try:
        with path.open("w") as f:
            json.dump(value, f)
    except OSError:
        pass


def read_stale_cache(key: str) -> Any | None:
    """Return cached data regardless of age. Used as a last-resort fallback
    when a live fetch fails, so a network hiccup degrades to "slightly old
    data" instead of a broken page."""
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        with path.open("r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


async def cached_fetch(
    key: str,
    ttl_seconds: float,
    fetch_fn: Callable[[], Awaitable[Any]],
) -> Any:
    """Return fresh-enough cached data, otherwise call fetch_fn, cache the
    result, and return it. If fetch_fn raises, fall back to stale cache
    (if any) rather than propagating the error."""
    cached = read_cache(key, ttl_seconds)
    if cached is not None:
        return cached
    try:
        fresh = await fetch_fn()
    except Exception:
        stale = read_stale_cache(key)
        if stale is not None:
            return stale
        raise
    write_cache(key, fresh)
    return fresh
