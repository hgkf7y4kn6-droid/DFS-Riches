"""Two-layer cache for the external API responses this app re-reads
constantly within a single request cycle (every route handler calls
through app.slates.list_slates, which pulls the same schedule/lines/stats
data several times): an in-memory layer for near-zero-cost repeat reads
within a process, backed by an on-disk JSON layer so a fresh process (or a
TTL expiry) doesn't have to re-fetch large payloads from Sleeper/DraftKings/
nflverse (the Sleeper player dict alone is several MB).

Concurrent callers requesting the same not-yet-cached key share a single
in-flight fetch rather than each re-downloading/re-parsing it.
"""
from __future__ import annotations

import asyncio
import functools
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.config import CACHE_DIR

_memory: dict[str, tuple[float, Any]] = {}
_in_flight: dict[str, asyncio.Task] = {}


def _cache_path(key: str) -> Path:
    safe = key.replace("/", "_").replace(":", "_").replace("?", "_").replace("&", "_")
    return CACHE_DIR / f"{safe}.json"


def _read_disk(key: str, ttl_seconds: float | None) -> Any | None:
    """ttl_seconds=None reads regardless of age (the stale-fallback path)."""
    path = _cache_path(key)
    if not path.exists():
        return None
    if ttl_seconds is not None and time.time() - path.stat().st_mtime > ttl_seconds:
        return None
    try:
        with path.open("r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_disk(key: str, value: Any) -> None:
    try:
        with _cache_path(key).open("w") as f:
            json.dump(value, f)
    except OSError:
        pass


async def _fetch_and_store(key: str, fetch_fn: Callable[[], Awaitable[Any]]) -> Any:
    try:
        value = await fetch_fn()
    except Exception:
        stale = _read_disk(key, ttl_seconds=None)
        if stale is not None:
            _memory[key] = (time.time(), stale)
            return stale
        raise
    _write_disk(key, value)
    _memory[key] = (time.time(), value)
    return value


async def cached_fetch(
    key: str,
    ttl_seconds: float,
    fetch_fn: Callable[[], Awaitable[Any]],
) -> Any:
    """Return fresh-enough cached data (memory, then disk), otherwise call
    fetch_fn, cache the result at both layers, and return it. If fetch_fn
    raises, fall back to stale disk cache (if any) rather than propagating
    the error. Concurrent calls for the same key that isn't already cached
    share one underlying fetch."""
    now = time.time()

    hit = _memory.get(key)
    if hit is not None and now - hit[0] < ttl_seconds:
        return hit[1]

    disk = _read_disk(key, ttl_seconds)
    if disk is not None:
        _memory[key] = (now, disk)
        return disk

    task = _in_flight.get(key)
    if task is None:
        task = asyncio.ensure_future(_fetch_and_store(key, fetch_fn))
        _in_flight[key] = task
    try:
        return await task
    finally:
        if _in_flight.get(key) is task:
            del _in_flight[key]


def memoize_async(ttl_seconds: float, max_entries: int = 32):
    """In-memory memoization for an async function, keyed by its arguments.
    For deriving a Python object from data that's already cheap to fetch
    (via cached_fetch) but non-trivial to rebuild each call -- e.g. a name
    lookup index, or a whole request's worth of orchestration that multiple
    routes independently repeat. Concurrent calls with the same arguments
    share one underlying computation. Holds at most max_entries results
    (oldest evicted), so arbitrary request parameters can't grow memory."""

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        store: dict[tuple, tuple[float, Any]] = {}
        in_flight: dict[tuple, asyncio.Task] = {}

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()

            hit = store.get(key)
            if hit is not None and now - hit[0] < ttl_seconds:
                return hit[1]

            task = in_flight.get(key)
            if task is None:

                async def run() -> Any:
                    value = await fn(*args, **kwargs)
                    store.pop(key, None)
                    store[key] = (time.time(), value)
                    while len(store) > max_entries:
                        del store[next(iter(store))]
                    return value

                task = asyncio.ensure_future(run())
                in_flight[key] = task
            try:
                return await task
            finally:
                if in_flight.get(key) is task:
                    del in_flight[key]

        return wrapper

    return decorator
