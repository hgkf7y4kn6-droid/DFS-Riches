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

import asyncio
import hashlib
import json
import os
import re

from typing import Annotated

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import breakdown as breakdown_module
from app import dfs_model
from app import ownership_learning, ownership_report, ownership_store
from app import game_detail as game_detail_module
from app import optimal as optimal_module
from app import slates
from app.cache import memoize_async
from app.config import BASE_DIR, DEFAULT_SEASON, DEFAULT_WEEK
from app.models import GameDetail, SlatePlayers, WeekBreakdown, WeekData, WeekSchedule
from app.sleeper_client import get_nfl_state


def _asset_version() -> str:
    """Content hash of static/*, appended to asset URLs (?v=...) so they can be
    cached for a year and still change the moment a deploy changes them."""
    h = hashlib.sha1()
    for f in sorted((BASE_DIR / "static").glob("*")):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:10]


ASSET_VERSION = _asset_version()


class _CachedStaticFiles(StaticFiles):
    """Versioned asset URLs (?v=hash) are immutable; anything else gets a short TTL."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        versioned = b"v=" in scope.get("query_string", b"")
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable" if versioned else "public, max-age=300")
        return response


Season = Annotated[int, Query(ge=2000, le=2100)]
Week = Annotated[int, Query(ge=1, le=22)]

app = FastAPI(title="DFSRiches", description="DraftKings DFS explorer")
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.mount("/static", _CachedStaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/healthz")
async def healthz():
    """Liveness/readiness check for a platform's or Cloudflare's origin
    health monitoring. Deliberately makes no outbound calls -- it only
    confirms this process is up and serving requests."""
    return {"status": "ok"}


@memoize_async(ttl_seconds=1800)
async def current_season_week() -> tuple[int, int]:
    """The current NFL season and week from Sleeper: week 1 before the regular
    season starts, week 18 once it's over; the configured default if Sleeper
    can't be reached."""
    try:
        state = await get_nfl_state()
        season = int(state.get("season") or DEFAULT_SEASON)
        kind = state.get("season_type")
        week = int(state.get("display_week") or state.get("week") or DEFAULT_WEEK)
    except Exception:
        return DEFAULT_SEASON, DEFAULT_WEEK
    if kind == "pre":
        week = 1
    elif kind in ("post", "off"):
        week = 18
    return season, max(1, min(18, week))


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


async def _page(request: Request, template: str, active: str, season_q: str | None, week_q: str | None):
    season, week = _int(season_q), _int(week_q)
    if not (season and week and 2000 <= season <= 2100 and 1 <= week <= 18):
        season, week = await current_season_week()
    return templates.TemplateResponse(request, template, {"season": season, "week": week, "active": active,
                                                          "asset_version": ASSET_VERSION})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, season: str | None = None, week: str | None = None):
    return await _page(request, "index.html", "/", season, week)


@app.get("/api/state")
async def api_state():
    try:
        state = await get_nfl_state()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Sleeper: {exc}") from exc
    return state


@app.get("/api/schedule", response_model=WeekSchedule)
async def api_schedule(season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    try:
        schedule, _slates = await slates.list_slates(season, week)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build schedule: {exc}") from exc
    return schedule


@app.get("/api/slates")
async def api_slates(season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    try:
        _schedule, slate_list = await slates.list_slates(season, week)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not list slates: {exc}") from exc
    return slate_list


@app.get("/api/week", response_model=WeekData)
async def api_week(season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    """Combines /api/schedule and /api/slates into one response, since both
    already come from the same list_slates() call -- lets the frontend's
    initial load skip a redundant round trip."""
    try:
        schedule, slate_list = await slates.list_slates(season, week)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load week: {exc}") from exc
    return WeekData(schedule=schedule, slates=slate_list)


@app.get("/api/slates/{slate_id}/players", response_model=SlatePlayers)
async def api_slate_players(slate_id: str, season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    try:
        return await slates.get_slate_players(season, week, slate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load slate players: {exc}") from exc


@memoize_async(ttl_seconds=60)
async def _optimal(season: int, week: int, slate_id: str) -> dict:
    return await optimal_module.get_optimal(season, week, slate_id)


@app.get("/api/slates/{slate_id}/optimal")
async def api_slate_optimal(slate_id: str, season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    try:
        return await _optimal(season, week, slate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build optimal lineups: {exc}") from exc


@app.get("/breakdown", response_class=HTMLResponse)
async def breakdown_page(request: Request, season: str | None = None, week: str | None = None):
    return await _page(request, "breakdown.html", "/breakdown", season, week)


@app.get("/dfs-model", response_class=HTMLResponse)
async def dfs_model_page(request: Request, season: str | None = None, week: str | None = None):
    return await _page(request, "dfs_model.html", "/dfs-model", season, week)


@app.get("/api/breakdown/game/{game_id}", response_model=GameDetail)
async def api_game_detail(game_id: str, season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    try:
        return await game_detail_module.build_game_detail(season, week, game_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build game detail: {exc}") from exc


@app.get("/api/breakdown", response_model=WeekBreakdown)
async def api_breakdown(season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    try:
        return await breakdown_module.build_week_breakdown(season, week)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build week breakdown: {exc}") from exc


def _json_default(o):
    if hasattr(o, "item"):          # numpy scalars
        return o.item()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(f"Not JSON serializable: {type(o).__name__}")


@memoize_async(ttl_seconds=120)
async def _dfs_model(season: int, week: int, slate_id: str | None, contest: str, contest_size: int | None,
                     version: tuple) -> bytes:
    """The model, serialized once: repeat requests reuse the bytes."""
    result = await dfs_model.build(season, week, slate_id, contest, contest_size)
    return json.dumps(result, separators=(",", ":"), default=_json_default).encode()


def _check_contest(contest: str) -> str:
    if contest not in ownership_store.CLASSIC_CONTESTS:
        raise HTTPException(status_code=400, detail=f"Unknown contest type: {contest}")
    return contest


@app.get("/api/dfs-model")
async def api_dfs_model(season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK, slate_id: str | None = None,
                        contest: str = "gpp", contest_size: int | None = None):
    """Weekly projection, ownership & lineup analysis for a Classic slate (app.dfs_model)."""
    _check_contest(contest)
    if contest_size is not None and not 2 <= contest_size <= 2_000_000:
        raise HTTPException(status_code=400, detail="contest_size must be between 2 and 2,000,000")
    try:
        body = await _dfs_model(season, week, slate_id, contest, contest_size, ownership_store.data_version())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build the DFS model: {exc}") from exc
    return Response(body, media_type="application/json")


def _slate_args(body: dict) -> tuple[int, int, str]:
    season, week, slate_id = int(body["season"]), int(body["week"]), str(body["slate_id"])
    if not (2000 <= season <= 2100 and 1 <= week <= 22 and re.fullmatch(r"[a-z_]{1,40}", slate_id)):
        raise ValueError("Invalid season, week or slate_id")
    return season, week, slate_id


async def _resolver_players(season: int, week: int, slate_id: str) -> list[dict]:
    sp = await slates.get_slate_players(season, week, slate_id)
    out = []
    for p in sp.players:
        key = ownership_store.player_key(p.name, p.team, p.position)
        if sp.slate.slate_type == "showdown":
            key += "|CPT" if p.roster_slot == "CPT" else "|FLEX"
        out.append({"key": key, "name": p.name, "team": p.team, "position": p.position, "roster_slot": p.roster_slot})
    return out


@app.post("/api/ownership/source")
async def api_ownership_source(body: dict = Body(...)):
    """Ownership projections pasted from a named source: {season, week, slate_id, contest, source, text}."""
    try:
        season, week, slate_id = _slate_args(body)
        source = str(body.get("source") or "").strip()
        if not source:
            raise HTTPException(status_code=400, detail="Name the source")
        players = await _resolver_players(season, week, slate_id)
        entries = ownership_store.parse_lines(str(body.get("text") or "")[:60000])
        return ownership_store.add_observations(season, week, slate_id, "source", str(body.get("contest") or "gpp"),
                                                entries, players, source=source)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ownership/crowd")
async def api_ownership_crowd(body: dict = Body(...)):
    """A crowdsourced submission: {season, week, slate_id, contest, user_id, display_name, confidence (1-5), text}."""
    try:
        season, week, slate_id = _slate_args(body)
        user_id = str(body.get("user_id") or "").strip()
        if not 8 <= len(user_id) <= 64:
            raise HTTPException(status_code=400, detail="Missing contributor id")
        conf = int(body.get("confidence") or 3)
        players = await _resolver_players(season, week, slate_id)
        entries = ownership_store.parse_lines(str(body.get("text") or "")[:60000])
        return ownership_store.add_observations(season, week, slate_id, "crowd", str(body.get("contest") or "gpp"),
                                                entries, players, user_id=user_id,
                                                display_name=str(body.get("display_name") or ""),
                                                confidence=max(1, min(5, conf)))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ownership/actual")
async def api_ownership_actual(body: dict = Body(...)):
    """Actual contest ownership: a DraftKings contest-standings CSV (preferred: also carries every
    field lineup) or "Name, pct" lines. {season, week, slate_id, contest, text}. Triggers relearning."""
    try:
        season, week, slate_id = _slate_args(body)
        contest = str(body.get("contest") or "gpp")
        text = str(body.get("text") or "")[:30_000_000]
        players = await _resolver_players(season, week, slate_id)
        if "%Drafted" in text[:5000]:
            parsed = ownership_store.parse_dk_standings(text)
            entries = [{"name": name, "pct": pct, "slot": slot if slot in ("CPT",) else ""}
                       for (name, slot), pct in parsed["ownership"].items()]
            result = ownership_store.add_observations(season, week, slate_id, "actual", contest, entries, players,
                                                      source="dk_standings")
            lineups = []
            for lu in parsed["lineups"]:
                keys = []
                for slot, name in lu:
                    p = ownership_store.resolve(players, name, slot="CPT" if slot == "CPT" else "")
                    if p:
                        keys.append(p["key"])
                if len(keys) == len(lu):
                    lineups.append(keys)
            ownership_store.add_field_lineups(season, week, slate_id, contest, lineups)
            result["field_lineups"] = len(lineups)
            result["entries"] = parsed["entries"]
        else:
            result = ownership_store.add_observations(season, week, slate_id, "actual", contest,
                                                      ownership_store.parse_lines(text), players, source="pasted")
        learning = await asyncio.to_thread(ownership_learning.relearn)
        result["learned"] = {"slates_with_actuals": learning.get("slates_with_actuals")}
        return result
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ownership/duplication")
async def api_ownership_duplication(body: dict = Body(...)):
    """Duplication + exposure leverage for your own Lineup Builder lineups:
    {season, week, slate_id, contest, contest_size, lineups: [[dk_draftable_id, ...], ...]}."""
    try:
        season, week, slate_id = _slate_args(body)
        contest = _check_contest(str(body.get("contest") or "gpp"))
        size = int(body.get("contest_size") or ownership_report.DEFAULT_CONTEST_SIZE[contest])
        lineups = [[int(x) for x in lu] for lu in (body.get("lineups") or [])[:5] if isinstance(lu, list) and len(lu) == 9]
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _dfs_model(season, week, slate_id, contest, None, ownership_store.data_version())
    state = dfs_model._STATE.get((season, week, slate_id, contest))
    if state is None:
        raise HTTPException(status_code=404, detail="Build the DFS model for this slate first")
    rep = await asyncio.to_thread(ownership_report.report, state, contest=contest, contest_size=size,
                                  model_lineups={f"Your lineup {i + 1}": lu for i, lu in enumerate(lineups)},
                                  exposure_lineups=lineups)
    return {"duplication": rep["duplication"], "leverage": rep["leverage"], "contest_size": size}


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
