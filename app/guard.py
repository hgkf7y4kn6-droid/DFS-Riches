"""Abuse protection: per-client rate limits and request-size caps, so bots
can't run up compute, database writes or bandwidth. Limits are generous for
a person using the app (and sign-up is untouched -- that's Clerk's side).

Buckets (requests per client per minute):
  write  POST / PUT                                    30
  heavy  model builds: plays, DFS model, ownership,     60
         optimal lineups, breakdowns
  api    any other /api/ call                           300
Pages, the web build and static files aren't limited (they're cheap and
cacheable).

The client is the visitor's IP as Render's Cloudflare edge reports it
(CF-Connecting-IP / True-Client-IP, which Cloudflare overwrites, so callers
can't spoof them), else the first X-Forwarded-For hop.
"""
from __future__ import annotations

import json
import os
import time
from collections import deque

LIMITS = {"write": 30, "heavy": 60, "api": 300}
WINDOW_SECONDS = 60
MAX_CLIENTS = 20_000                 # tracked (client, bucket) pairs; oldest dropped beyond this
MAX_BODY_BYTES = 2 * 1024 * 1024     # default request-body cap
# Larger bodies only where they're expected: master DK standings uploads, synced documents.
BODY_LIMITS = {"/api/ownership/actual": 32 * 1024 * 1024, "/api/me/data/": 9 * 1024 * 1024}
HEAVY_PREFIXES = ("/api/plays", "/api/dfs-model", "/api/breakdown", "/api/ownership/")
HEAVY_SUFFIXES = ("/ownership", "/optimal")


def _limit(name: str) -> int:
    try:
        return int(os.environ.get(f"RATE_LIMIT_{name.upper()}", LIMITS[name]))
    except ValueError:
        return LIMITS[name]


def bucket(method: str, path: str) -> str | None:
    if not path.startswith("/api/"):
        return None
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return "write"
    if path.startswith(HEAVY_PREFIXES) or path.endswith(HEAVY_SUFFIXES):
        return "heavy"
    return "api"


def body_limit(path: str) -> int:
    for prefix, size in BODY_LIMITS.items():
        if path.startswith(prefix):
            return size
    return MAX_BODY_BYTES


def client_ip(headers: dict[str, str], peer: str | None) -> str:
    for name in ("cf-connecting-ip", "true-client-ip"):
        if headers.get(name):
            return headers[name].strip()
    xff = headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return peer or "unknown"


class RateLimiter:
    """Sliding-window counts per (client, bucket), in memory (one instance)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque] = {}

    def check(self, client: str, name: str, now: float | None = None) -> float:
        """0 if allowed (and counted), else seconds until the next request is allowed."""
        now = time.monotonic() if now is None else now
        key = (client, name)
        hits = self._hits.pop(key, None) or deque()
        while hits and now - hits[0] >= WINDOW_SECONDS:
            hits.popleft()
        self._hits[key] = hits                          # re-insert: dict order = least recently seen first
        if len(hits) >= _limit(name):
            return max(1.0, WINDOW_SECONDS - (now - hits[0]))
        hits.append(now)
        while len(self._hits) > MAX_CLIENTS:
            self._hits.pop(next(iter(self._hits)))
        return 0.0


class GuardMiddleware:
    """ASGI middleware: rate limits and body-size caps for /api/ requests."""

    def __init__(self, app) -> None:
        self.app = app
        self.limiter = RateLimiter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        name = bucket(method, path)
        if name is None:
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        peer = (scope.get("client") or (None,))[0]
        retry = self.limiter.check(client_ip(headers, peer), name)
        if retry:
            return await _reject(send, 429, "Too many requests -- slow down and try again shortly.",
                                 {"retry-after": str(int(retry))})

        cap = body_limit(path)
        try:
            declared = int(headers.get("content-length") or 0)
        except ValueError:
            declared = 0
        if declared > cap:
            return await _reject(send, 413, "Request body too large.")

        received = 0

        async def capped_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > cap:
                    raise _TooLarge()
            return message

        try:
            return await self.app(scope, capped_receive, send)
        except _TooLarge:
            return await _reject(send, 413, "Request body too large.")


class _TooLarge(Exception):
    pass


async def _reject(send, status: int, detail: str, extra: dict[str, str] | None = None) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
               (b"access-control-allow-origin", b"*")]
    headers += [(k.encode(), v.encode()) for k, v in (extra or {}).items()]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
