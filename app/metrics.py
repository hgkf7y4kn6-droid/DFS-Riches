"""In-process performance counters: cache hit rates, fetch and compute times, API latency.

  cache     per data family (a cache key with its season / week / id stripped: "dk_draftables_155197" ->
            "dk_draftables"): memory hits, disk hits, fetches, stale fallbacks (a fetch failed and an
            expired copy was served), errors, and fetch seconds
  memo      per memoized function (app.cache.memoize_async): hits, misses and compute seconds
  requests  per API route template ("/api/slates/{slate_id}/players"): count, 5xx errors, and p50 / p95 / p99
            over the last LATENCY_WINDOW requests

Requests slower than SLOW_REQUEST_SECONDS are logged as they happen, and app.main logs a one-line summary every
SUMMARY_INTERVAL (Render keeps the logs); GET /api/metrics (master accounts) returns snapshot(). Counters live
in memory and reset when the process restarts. Nothing here records users or request contents.
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque

# The app's own log lines (dfsriches.*) at INFO on stdout: uvicorn only configures its own loggers, and the
# root logger would show warnings only.
_root = logging.getLogger("dfsriches")
if not _root.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _root.addHandler(_handler)
    _root.setLevel(logging.INFO)
    _root.propagate = False
log = logging.getLogger("dfsriches.metrics")

LATENCY_WINDOW = 500
SLOW_REQUEST_SECONDS = 3.0
SUMMARY_INTERVAL = 15 * 60
CACHE_EVENTS = ("memory", "disk", "fetch", "stale", "error")

STARTED = time.time()
_cache: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(CACHE_EVENTS + ("fetch_seconds",), 0.0))
_memo: dict[str, dict[str, float]] = defaultdict(lambda: {"hit": 0.0, "miss": 0.0, "seconds": 0.0})
_requests: dict[str, dict] = defaultdict(lambda: {"count": 0, "errors": 0, "latency": deque(maxlen=LATENCY_WINDOW)})

_FAMILY_RE = re.compile(r"(?:[_.,]-?\d[\d.,\-]*)+$")   # trailing numeric segments: "_2026_7", "_41.86,-87.62"


def family(key: str) -> str:
    """A cache key without its trailing season / week / id / coordinates."""
    return _FAMILY_RE.sub("", key) or key


def cache_event(key: str, event: str, seconds: float | None = None) -> None:
    c = _cache[family(key)]
    c[event] += 1
    if seconds is not None:
        c["fetch_seconds"] += seconds


def memo_event(name: str, hit: bool, seconds: float | None = None) -> None:
    m = _memo[name]
    m["hit" if hit else "miss"] += 1
    if seconds is not None:
        m["seconds"] += seconds


def request_done(route: str, seconds: float, status: int) -> None:
    r = _requests[route]
    r["count"] += 1
    r["errors"] += status >= 500
    r["latency"].append(seconds)
    if seconds >= SLOW_REQUEST_SECONDS:
        log.warning("slow request %s %.2fs (status %d)", route, seconds, status)


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 3)


def snapshot() -> dict:
    cache = {}
    for fam, c in sorted(_cache.items()):
        reads = c["memory"] + c["disk"] + c["fetch"] + c["stale"]
        cache[fam] = {**{k: int(v) for k, v in c.items() if k != "fetch_seconds"},
                      "hit_rate": round((c["memory"] + c["disk"]) / reads, 3) if reads else None,
                      "avg_fetch_seconds": round(c["fetch_seconds"] / c["fetch"], 2) if c["fetch"] else None}
    memo = {name: {"hit": int(m["hit"]), "miss": int(m["miss"]),
                   "hit_rate": round(m["hit"] / (m["hit"] + m["miss"]), 3) if m["hit"] + m["miss"] else None,
                   "avg_compute_seconds": round(m["seconds"] / m["miss"], 2) if m["miss"] else None}
            for name, m in sorted(_memo.items())}
    requests = {route: {"count": r["count"], "errors": r["errors"], "p50": _pct(list(r["latency"]), 0.5),
                        "p95": _pct(list(r["latency"]), 0.95), "p99": _pct(list(r["latency"]), 0.99)}
                for route, r in sorted(_requests.items())}
    totals = {k: sum(c[k] for c in _cache.values()) for k in CACHE_EVENTS}
    reads = totals["memory"] + totals["disk"] + totals["fetch"] + totals["stale"]
    return {"uptime_seconds": round(time.time() - STARTED), "cache": cache, "memo": memo, "requests": requests,
            "cache_hit_rate": round((totals["memory"] + totals["disk"]) / reads, 3) if reads else None}


def summary_line() -> str:
    s = snapshot()
    busiest = sorted(s["requests"].items(), key=lambda kv: -kv[1]["count"])[:5]
    routes = "; ".join(f"{r} n={v['count']} p50={v['p50']}s p95={v['p95']}s" for r, v in busiest) or "no requests"
    slow_fetch = sorted(((f, c["avg_fetch_seconds"]) for f, c in s["cache"].items() if c["avg_fetch_seconds"]),
                        key=lambda x: -x[1])[:3]
    return (f"metrics: up {s['uptime_seconds']}s, cache hit rate {s['cache_hit_rate']}; {routes}; slowest fetches "
            + (", ".join(f"{f} {t}s" for f, t in slow_fetch) or "none"))
