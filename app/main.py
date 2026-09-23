"""DFSRiches -- a DraftKings DFS explorer for the NFL.

Merges real DraftKings salaries (Classic full-slate + Showdown Captain Mode
for every isolated Wednesday/Thursday/Sunday/Monday night game) with real
Sleeper weekly fantasy projections, keyed on the real Week N schedule pulled
live from Sleeper.

Deployment: this is a normal long-running ASGI app (FastAPI/Uvicorn), meant
to run on a regular host/container behind Cloudflare's proxy/CDN (or a
Cloudflare Tunnel) -- not inside a Cloudflare Worker, whose V8-isolate/
Pyodide runtime can't run Uvicorn, httpx's socket-based transport, or this
app's on-disk cache as-is. See README.md's "Deploying behind Cloudflare"
section.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import slates
from app.config import BASE_DIR, DEFAULT_SEASON, DEFAULT_WEEK
from app.models import SlatePlayers, WeekData, WeekSchedule
from app.sleeper_client import get_nfl_state


class _CachedStaticFiles(StaticFiles):
    """Adds a short edge-cacheable Cache-Control header so Cloudflare (or
    any CDN in front of this app) can serve static/* from cache instead of
    round-tripping to the origin on every request, without risking long
    staleness after a deploy (there's no cache-busting filename hash)."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "public, max-age=300")
        return response


app = FastAPI(title="DFSRiches", description="DraftKings DFS explorer")

app.mount("/static", _CachedStaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/healthz")
async def healthz():
    """Liveness/readiness check for a platform's or Cloudflare's origin
    health monitoring. Deliberately makes no outbound calls -- it only
    confirms this process is up and serving requests."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "default_season": DEFAULT_SEASON, "default_week": DEFAULT_WEEK},
    )


@app.get("/api/state")
async def api_state():
    try:
        state = await get_nfl_state()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Sleeper: {exc}") from exc
    return state


@app.get("/api/schedule", response_model=WeekSchedule)
async def api_schedule(season: int = DEFAULT_SEASON, week: int = DEFAULT_WEEK):
    try:
        schedule, _slates = await slates.list_slates(season, week)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build schedule: {exc}") from exc
    return schedule


@app.get("/api/slates")
async def api_slates(season: int = DEFAULT_SEASON, week: int = DEFAULT_WEEK):
    try:
        _schedule, slate_list = await slates.list_slates(season, week)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not list slates: {exc}") from exc
    return slate_list


@app.get("/api/week", response_model=WeekData)
async def api_week(season: int = DEFAULT_SEASON, week: int = DEFAULT_WEEK):
    """Combines /api/schedule and /api/slates into one response, since both
    already come from the same list_slates() call -- lets the frontend's
    initial load skip a redundant round trip."""
    try:
        schedule, slate_list = await slates.list_slates(season, week)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load week: {exc}") from exc
    return WeekData(schedule=schedule, slates=slate_list)


@app.get("/api/slates/{slate_id}/players", response_model=SlatePlayers)
async def api_slate_players(slate_id: str, season: int = DEFAULT_SEASON, week: int = DEFAULT_WEEK):
    try:
        return await slates.get_slate_players(season, week, slate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load slate players: {exc}") from exc


if __name__ == "__main__":
    # Production entrypoint: `python -m app.main`. Reads $PORT (the
    # convention most container platforms inject) and trusts proxy headers
    # from any upstream (proxy_headers=True + forwarded_allow_ips="*") so
    # request.url.scheme/client reflect the real visitor, not Cloudflare's
    # edge IP -- correct behind Cloudflare's proxy/CDN or a Cloudflare
    # Tunnel. The Dockerfile's CMD is the source of truth for container
    # deploys; this exists for platforms that run the app directly.
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
