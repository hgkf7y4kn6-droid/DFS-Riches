"""Riches Analytics (formerly DFSRiches) -- a DraftKings DFS explorer for the NFL.

Merges real DraftKings salaries (Classic full-slate + Showdown Captain Mode
for every island game -- weeknight, Sunday night, international, holiday) with real
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
import logging
import os
import re
import subprocess
import tempfile
import time

from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import breakdown as breakdown_module
from app import leverage as leverage_module
from app import metrics, ownership_persist, ownership_slate, ownership_video
from app import trenches as trenches_module
from app import dfs_model
from app import accounts, contests, guard, matchups, news_overrides, ownership_learning, ownership_report, ownership_store, play_rankings, player_games
from app import game_detail as game_detail_module
from app import optimal as optimal_module
from app import slates
from app import team_units
from app.cache import memoize_async
from app.config import BASE_DIR, DEFAULT_SEASON, DEFAULT_WEEK
from app.models import GameDetail, SlatePlayers, WeekBreakdown, WeekData, WeekSchedule
from app import sleeper_client
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

log = logging.getLogger("dfsriches.main")
app = FastAPI(title="Riches Analytics", description="DraftKings DFS explorer")


@app.on_event("startup")
async def _restore_ownership() -> None:
    """Uploaded actual ownership and the models' learning survive redeploys via Postgres (app.ownership_persist)."""
    asyncio.get_running_loop().run_in_executor(None, ownership_persist.restore)


@app.on_event("startup")
async def _warm_contests() -> None:
    """Payout tables for every listed GPP, so the first Best contests ranking doesn't wait on them."""
    if os.environ.get("WARM_CONTESTS", "1") != "0":
        asyncio.ensure_future(contests.warm_payouts())


@app.on_event("startup")
async def _founding_pro() -> None:
    """The accounts created before FOUNDING_PRO_BEFORE get Pro (accounts.grant_founding_pro; idempotent,
    so it's safe at every start). FOUNDING_PRO=0 turns it off."""
    if os.environ.get("FOUNDING_PRO", "1") == "0":
        return

    async def run() -> None:
        try:
            log.info("founding Pro: %s", await accounts.grant_founding_pro())
        except Exception as exc:
            log.warning("founding Pro grant failed: %s", exc)
    asyncio.ensure_future(run())


@app.on_event("startup")
async def _warm_slates() -> None:
    """The current week's Classic slates (schedule, lines, projections, every index and model input behind the
    player table), so the first visit after a deploy -- when the disk cache starts empty -- doesn't wait on them."""
    if os.environ.get("WARM_SLATES", "1") != "0":
        asyncio.ensure_future(_warm_current_slates())


async def _warm_current_slates() -> None:
    from app import prewarm

    await asyncio.sleep(5)             # let the server answer its health check first
    try:
        log.info("slate warm-up: %s", await prewarm.warm())
    except Exception as exc:           # warming is best effort; requests still build everything on demand
        log.warning("slate warm-up failed: %s", exc)
    # Then the DFS model and both plays tabs for the default slate, so the first visitor doesn't wait on them.
    try:
        season, week = await current_season_week()
        version = _model_version()
        await _dfs_model(season, week, None, "gpp", None, version)
        await _dfs_model_without_props(season, week, None, "gpp", None, version)
        for contest in ("cash", "gpp"):
            await _plays(season, week, None, contest, version)
        log.info("model warm-up done for %s week %s", season, week)
    except Exception as exc:
        log.warning("model warm-up failed: %s", exc)


# Sign-in (Clerk production) only works on the site's own domain, so pages opened on
# Render's address (e.g. an old bookmark) move there. The API stays reachable on both
# (the native app calls it), and so does the health check.
CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "dfsriches.richesdigitalventures.com")


@app.middleware("http")
async def _timing(request: Request, call_next):
    """API latency per route template (app.metrics); slow requests are logged as they happen."""
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = getattr(request.scope.get("route"), "path", None) or "unmatched"
        metrics.request_done(f"{request.method} {route}", time.perf_counter() - started, status)


@app.on_event("startup")
async def _metrics_summary() -> None:
    """A one-line performance summary in the log every metrics.SUMMARY_INTERVAL (METRICS_LOG=0 turns it off)."""
    if os.environ.get("METRICS_LOG", "1") == "0":
        return

    async def loop() -> None:
        while True:
            await asyncio.sleep(metrics.SUMMARY_INTERVAL)
            log.info(metrics.summary_line())
    asyncio.ensure_future(loop())


@app.middleware("http")
async def _canonical_host(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":")[0].lower()
    path = request.url.path
    if (CANONICAL_HOST and host.endswith(".onrender.com") and request.method in ("GET", "HEAD")
            and not path.startswith(("/api/", "/healthz"))):
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(f"https://{CANONICAL_HOST}{path}{query}", status_code=301)
    return await call_next(request)


# The data behind the app is for signed-in accounts: every /api/ request needs
# a Clerk session token (`Authorization: Bearer`), which the app sends with each
# request and the classic pages send from clerk-js (static/common.js). Open:
# /api/odds -- DraftKings sportsbook lines and capture status, read by the
# odds-snapshot and Big Picture GitHub workflows. Preflights pass to CORS.
# REQUIRE_SIGN_IN=0 turns the check off (local development).
OPEN_API_PATHS = ("/api/odds",)


def sign_in_required() -> bool:
    return os.environ.get("REQUIRE_SIGN_IN", "1") != "0"


@app.middleware("http")
async def _require_sign_in(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in OPEN_API_PATHS or request.method == "OPTIONS" or not sign_in_required():
        return await call_next(request)
    try:
        request.state.claims = await accounts.verify_claims(request.headers.get("authorization"))
        request.state.user_id = request.state.claims["sub"]
    except accounts.AuthError as exc:
        return JSONResponse({"detail": f"Sign in to Riches Analytics to use this ({exc})."}, status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
    return await call_next(request)


app.add_middleware(GZipMiddleware, minimum_size=1000)
# The mobile app (mobile/) reads the JSON API with the user's session token; its
# web build can run on another origin, so allow cross-origin requests.
# Account sync adds authenticated PUTs (Bearer token, no cookies).
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "PUT", "POST"], allow_headers=["*"])
# Outermost: per-client rate limits and body-size caps on /api/ (app.guard).
app.add_middleware(guard.GuardMiddleware)

app.mount("/static", _CachedStaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# The website is the mobile app's web build (mobile/, `expo export --platform web`,
# built into web/ by the Dockerfile). The original pages live under /classic.
WEB_DIR = BASE_DIR / "web"


@app.get("/api/metrics")
async def api_metrics(authorization: Annotated[str | None, Header()] = None):
    """Cache hit rates, fetch / compute times and API latency since this process started (app.metrics)."""
    await _require_master(authorization)
    return metrics.snapshot()


@app.get("/healthz")
async def healthz(request: Request):
    """Liveness/readiness check for a platform's or Cloudflare's origin
    health monitoring. Deliberately makes no outbound calls -- it only
    confirms this process is up and serving requests. "accounts" says which
    account settings the environment provides -- yes/no only, never values."""
    headers = {k.lower(): v for k, v in request.headers.items()}
    client = guard.client_ip(headers, request.client.host if request.client else None)
    # "client": the caller's own address as the rate limiter sees it.
    return {"status": "ok", "accounts": accounts.config_status(), "client": client}


@memoize_async(ttl_seconds=1800)
async def current_season_week() -> tuple[int, int]:
    """The current NFL season and week from Sleeper: week 1 before the regular
    season starts, week 18 once it's over; the configured default if Sleeper
    can't be reached. Sleeper's display_week lags into midweek after a week's
    last game, so a week whose games are all complete moves on to the next."""
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
    week = max(1, min(18, week))
    if kind == "regular" and week < 18 and await _week_complete(season, week):
        week += 1
    return season, week


async def _week_complete(season: int, week: int) -> bool:
    try:
        games = await sleeper_client.get_week_games(season, week)
    except Exception:
        return False
    return bool(games) and all(g.get("status") == "complete" for g in games)


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


async def _page(request: Request, template: str, active: str, season_q: str | None, week_q: str | None):
    season, week = _int(season_q), _int(week_q)
    if not (season and week and 2000 <= season <= 2100 and 1 <= week <= 18):
        season, week = await current_season_week()
    # The page itself holds no data: its scripts load clerk-js and call the API
    # with the signed-in user's token, and send signed-out visitors to /sign-in.
    return templates.TemplateResponse(request, template, {"season": season, "week": week, "active": active,
                                                          "asset_version": ASSET_VERSION,
                                                          "require_sign_in": sign_in_required(),
                                                          "clerk_publishable_key": accounts.publishable_key(),
                                                          "clerk_frontend_api": accounts.frontend_api()})


@app.get("/classic", response_class=HTMLResponse)
async def index(request: Request, season: str | None = None, week: str | None = None):
    return await _page(request, "index.html", "/classic", season, week)


@app.get("/api/state")
async def api_state():
    try:
        state = await get_nfl_state()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Sleeper: {exc}") from exc
    # The app opens on display_week: use ours, which moves on once the week's games are all complete.
    season, week = await current_season_week()
    if str(state.get("season")) == str(season) and state.get("season_type") == "regular":
        state = {**state, "display_week": week}
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


@app.post("/api/slates/{slate_id}/build")
async def api_build(request: Request, slate_id: str, body: dict = Body(...)):
    """"Build for me": up to 5 distinct lineups for a slate from the model's projections
    {season, week, metric: proj_points|ceiling, count, locked: [dk ids], excluded: [dk ids], max_exposure}.
    Pro (it builds optimal lineups); more than one lineup is also multiple_lineups."""
    from app.optimizer import build_many
    try:
        season, week, _ = _slate_args({**body, "slate_id": slate_id})
        metric = str(body.get("metric") or "proj_points")
        if metric not in ("proj_points", "ceiling"):
            raise ValueError("metric must be proj_points or ceiling")
        count = max(1, min(5, int(body.get("count") or 1)))
        exposure = max(0.2, min(1.0, float(body.get("max_exposure") or 1.0)))
        locked = {int(x) for x in (body.get("locked") or [])[:9]}
        excluded = {int(x) for x in (body.get("excluded") or [])[:200]}
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _require_feature(request, "optimal")          # it builds optimal lineups
    if count > 1:
        await _require_feature(request, "multiple_lineups")
    try:
        _, slate_list = await slates.list_slates(season, week)
        slate = next((s for s in slate_list if s.slate_id == slate_id), None)
        if slate is None or not slate.available:
            raise HTTPException(status_code=404, detail="That slate has no salaries yet.")
        players = (await slates.get_slate_players(season, week, slate_id)).players
        built = await asyncio.to_thread(build_many, players, slate.slate_type, metric, count,
                                        locked=locked, excluded=excluded, max_exposure=exposure)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build lineups: {exc}") from exc
    slots = optimal_module._slots(slate.slate_type)
    return {"lineups": [{
        "players": [{"slot": slot, "dk_draftable_id": p.dk_draftable_id, "name": p.name, "team": p.team} for slot, p in zip(slots, lu)],
        "salary": sum(p.salary for p in lu),
        "proj_points": round(sum(p.proj_points or 0 for p in lu), 2),
        "ceiling": round(sum(p.ceiling or 0 for p in lu), 2),
    } for lu in built], "requested": count}


@app.get("/api/track-record")
async def api_track_record():
    """How the saved optimal lineups scored against their projections, per finished slate (app.optimal)."""
    return {"slates": optimal_module.track_record()}


@memoize_async(ttl_seconds=60)
async def _optimal(season: int, week: int, slate_id: str) -> dict:
    return await optimal_module.get_optimal(season, week, slate_id)


@app.get("/api/slates/{slate_id}/optimal")
async def api_slate_optimal(request: Request, slate_id: str, season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    """The slate's projected optimal lineups (Pro)."""
    await _require_feature(request, "optimal")
    try:
        return await _optimal(season, week, slate_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build optimal lineups: {exc}") from exc


@app.get("/classic/breakdown", response_class=HTMLResponse)
async def breakdown_page(request: Request, season: str | None = None, week: str | None = None):
    return await _page(request, "breakdown.html", "/classic/breakdown", season, week)


@app.get("/classic/dfs-model", response_class=HTMLResponse)
async def dfs_model_page(request: Request, season: str | None = None, week: str | None = None):
    return await _page(request, "dfs_model.html", "/classic/dfs-model", season, week)


@app.get("/breakdown", include_in_schema=False)
async def old_breakdown_page():
    return RedirectResponse("/classic/breakdown")


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


# Stale while revalidate: after the first build, visitors get the model at once while a fresh copy
# builds in the background (it takes seconds), for up to a day past its two minutes.
@memoize_async(ttl_seconds=120, stale_seconds=86400)
async def _dfs_model(season: int, week: int, slate_id: str | None, contest: str, contest_size: int | None,
                     version: tuple) -> bytes:
    """The model, serialized once: repeat requests reuse the bytes."""
    result = await dfs_model.build(season, week, slate_id, contest, contest_size)
    return json.dumps(result, separators=(",", ":"), default=_json_default).encode()


@memoize_async(ttl_seconds=120, stale_seconds=86400)
async def _dfs_model_without_props(season: int, week: int, slate_id: str | None, contest: str, contest_size: int | None,
                                   version: tuple) -> bytes:
    """The model for accounts without Pro: every player's props (a Pro feature) left out."""
    model = json.loads(await _dfs_model(season, week, slate_id, contest, contest_size, version))
    for row in model.get("table") or []:
        row.pop("props", None)
    return json.dumps(model, separators=(",", ":"), default=_json_default).encode()


@memoize_async(ttl_seconds=120, stale_seconds=86400)
async def _plays(season: int, week: int, slate_id: str | None, contest: str, version: tuple) -> bytes:
    model = json.loads(await _dfs_model(season, week, slate_id, "gpp", None, version))
    if not model.get("available"):
        return json.dumps({"available": False, "reason": model.get("reason") or "The DFS model isn't available for this slate."}).encode()
    try:
        profiles = await trenches_module.week_profiles(season, week)
        efficiency = leverage_module.efficiency_context(profiles, await matchups.defense_vs_position(season, week))
    except Exception:
        profiles, efficiency = None, None        # leverage falls back to the plain odds
    # What a DST faces: each offense's sack rate and giveaways per game (the DST game environment).
    offense: dict[str, dict] = {}
    try:
        units = await team_units.unit_table(season, week)
        for t, u in units["teams"].items():
            offense.setdefault(t, {})["giveaways"] = ((u.get("offense") or {}).get("giveaways") or {}).get("value")
    except Exception:
        pass
    for t, p in ((profiles or {}).get("teams") or {}).items():
        offense.setdefault(t, {})["sack_rate"] = (p.get("off") or {}).get("sack_rate")
    store = ownership_store.load(season, week, model["slate"]["slate_id"])
    actuals = play_rankings.actual_ownership(store.get("observations", []))
    result = await asyncio.to_thread(play_rankings.build, model["table"], model["strategy"]["games"], contest,
                                     season, week, model["slate"]["slate_id"], efficiency, actuals, offense)
    result["available"] = True
    result["slate"] = model["slate"]
    result["slates"] = model["slates"]
    return json.dumps(result, separators=(",", ":"), default=_json_default).encode()


@app.get("/api/plays")
async def api_plays(season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK, slate_id: str | None = None,
                    contest: str = "cash"):
    """Cash or GPP play rankings (top QB/RB/WR/TE by strength of play) and every player's expected field
    ownership for that contest type -- cash, or small- and large-field GPP (app.play_rankings,
    app.field_ownership) -- with prioritize / neutral / fade tags."""
    if contest not in ("cash", "gpp"):
        raise HTTPException(status_code=400, detail="contest must be cash or gpp")
    try:
        body = await _plays(season, week, slate_id, contest, _model_version())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build {contest} plays: {exc}") from exc
    return Response(body, media_type="application/json")


def _model_version() -> tuple:
    """The DFS model's cache key: changes with new ownership information or breaking news (app.news_overrides)."""
    return ownership_store.data_version() + news_overrides.data_version()


async def _user(authorization: str | None) -> str:
    try:
        return await accounts.verify(authorization)
    except accounts.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


async def _entitled(request: Request, feature: str) -> bool:
    """Whether this request may see a Pro feature (accounts.PRO_FEATURES); always, with PRO_GATING off."""
    if not accounts.pro_gating() or not sign_in_required():
        return True
    claims = getattr(request.state, "claims", None) or {}
    return accounts.entitled(await accounts.plan(claims.get("sub", ""), claims), feature)


async def _require_feature(request: Request, feature: str) -> None:
    """A Pro feature: with PRO_GATING on, free accounts get a 402."""
    if not await _entitled(request, feature):
        raise HTTPException(status_code=402, detail="This is a Riches Analytics Pro feature.")


async def _require_master(authorization: str | None) -> str:
    """Shared ownership data (projections, actuals) is written by master accounts only."""
    user_id = await _user(authorization)
    if not await accounts.is_master(user_id):
        raise HTTPException(status_code=403, detail="Master account required")
    return user_id


@app.get("/api/me")
async def api_me(authorization: Annotated[str | None, Header()] = None):
    """The signed-in user's synced data (app.accounts): saved lineups, contest entries, pool tags and settings,
    plus whether the account is a master account and where data is stored."""
    user_id = await _user(authorization)
    try:
        return await accounts.load(user_id, await accounts.verify_claims(authorization))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load account data: {exc}") from exc


@app.delete("/api/me")
async def api_me_delete(authorization: Annotated[str | None, Header()] = None):
    """Deletes the signed-in user's account and everything stored for it (Settings > Delete account)."""
    user_id = await _user(authorization)
    try:
        return await accounts.delete_account(user_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not delete the account: {exc}") from exc


@app.put("/api/me/data/{key}")
async def api_me_save(key: str, body: dict = Body(...), authorization: Annotated[str | None, Header()] = None):
    """Store one of the user's synced documents ({"value": ..., "updated_at": ISO}); last write wins."""
    user_id = await _user(authorization)
    try:
        return await accounts.save(user_id, key, body.get("value"), body.get("updated_at"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not save: {exc}") from exc


@memoize_async(ttl_seconds=60, max_entries=64)    # short: a slate that kicks off drops out within a minute
async def _best_contests(entries: frozenset[str], fees: frozenset[str], exclude: frozenset[str],
                         weights: tuple[tuple[str, int], ...], slate: int | None = None) -> dict:
    return await contests.best_contests(entries, fees, exclude, dict(weights), slate)


def _weights(value: str) -> tuple[tuple[str, int], ...]:
    """"rake:4,paid:3,payout:3,field:2" -> sorted (factor, points) pairs; empty = the defaults."""
    out: dict[str, int] = {}
    for part in filter(None, (p.strip() for p in value.split(","))):
        name, _, points = part.partition(":")
        if name not in contests.WEIGHTS or not points.isdigit() or int(points) > contests.MAX_WEIGHT:
            raise HTTPException(status_code=400, detail=f"Bad weight {part!r}: use factor:0-{contests.MAX_WEIGHT} "
                                                        f"with factors {', '.join(contests.WEIGHTS)}")
        out[name] = int(points)
    return tuple(sorted(out.items()))


def _id_set(value: str, allowed: list[str], what: str) -> frozenset[str]:
    ids = frozenset(v.strip() for v in value.split(",") if v.strip())
    if unknown := ids - set(allowed):
        raise HTTPException(status_code=400, detail=f"Unknown {what}: {', '.join(sorted(unknown))}")
    return ids


@app.get("/api/contests/best")
async def api_best_contests(entries: str = "", fees: str = "", exclude: str = "", weights: str = "",
                            slate: Annotated[int | None, Query(ge=1)] = None):
    """The 15 best NFL GPPs in DraftKings' lobby (app.contests): low rake, a big share of the field paid and
    a big first-place prize for the fee. entries / fees: comma-separated max-entries and fee group ids (empty =
    all); exclude: comma-separated contest kinds to leave out, e.g. "Qualifier,League"; weights: points (0-10)
    per factor, e.g. "rake:4,paid:3,payout:3,field:2" (factors left out count 0; none = the defaults); slate: the
    selected slate's DraftKings draft group id, whose contests are listed first. Started slates are left out."""
    chosen = (_id_set(entries, [g[0] for g in contests.ENTRY_GROUPS], "entry groups"),
              _id_set(fees, [g[0] for g in contests.FEE_GROUPS], "fee groups"),
              _id_set(exclude, contests.CONTEST_KINDS, "contest kinds"),
              _weights(weights), slate)
    try:
        return await _best_contests(*chosen)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load DraftKings contests: {exc}") from exc


@app.get("/api/contests/free")
async def api_free_contests():
    """Free NFL contests in DraftKings' lobby that pay cash (app.contests)."""
    try:
        return await contests.free_contests()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load DraftKings contests: {exc}") from exc


@app.get("/api/defense-vs-position")
async def api_defense_vs_position(season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    """Every defense's rank against each position (DK points and efficiency allowed, last 8 games), raw and
    strength-of-schedule adjusted (app.matchups). Rank 32 = allows the most (softest)."""
    try:
        return await matchups.defense_vs_position(season, week)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build matchup ranks: {exc}") from exc


@app.get("/api/player-games")
async def api_player_games(name: str, position: str, team: str, season: Season = DEFAULT_SEASON,
                           week: Week = DEFAULT_WEEK, games: Annotated[int, Query(ge=1, le=17)] = player_games.DEFAULT_GAMES):
    """A player's last few games before this week: snap share, DK points, and the passing / rushing /
    receiving (or team defense) lines relevant to the position (app.player_games)."""
    try:
        return await player_games.player_games(season, week, name=name, position=position, team=team, n=games)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load game logs: {exc}") from exc


def _check_contest(contest: str) -> str:
    if contest not in ownership_store.CLASSIC_CONTESTS:
        raise HTTPException(status_code=400, detail=f"Unknown contest type: {contest}")
    return contest


@memoize_async(ttl_seconds=120)
async def _slate_ownership(season: int, week: int, slate_id: str, version: tuple) -> dict:
    """Posterior ownership for one slate's players, by DraftKings id. Runs the
    DFS Model (memoized) so both pages show the same numbers: Classic slates
    use the large-field GPP posterior, Showdown slates their CPT/FLEX posteriors."""
    _schedule, slate_list = await slates.list_slates(season, week)
    slate = next((s for s in slate_list if s.slate_id == slate_id), None)
    if slate is None:
        raise HTTPException(status_code=404, detail=f"Unknown slate_id: {slate_id}")
    classic = [s for s in slate_list if s.slate_type == "classic" and s.available]
    if not classic or not slate.available:
        return {"available": False, "players": {}, "reason": "Ownership needs a DraftKings Classic slate with salaries."}
    model_slate = slate if slate.slate_type == "classic" else classic[0]
    await _dfs_model(season, week, model_slate.slate_id, "gpp", None, version)
    state = dfs_model._STATE.get((season, week, model_slate.slate_id, "gpp"))
    if state is None:
        return {"available": False, "players": {}, "reason": "The ownership model isn't available for this slate."}
    if slate.slate_type == "classic":
        players = ownership_report.summary_by_id(state, "gpp")
        note = "Large-field GPP posterior (Bayesian ownership model, DFS Model > Ownership)"
    else:
        players = {i: v for i, v in (state.get("showdown_ids") or {}).items()}
        note = "Showdown posterior: Captain and Flex ownership are separate contests"
    return {"available": True, "players": {str(k): v for k, v in players.items()}, "note": note}


@app.get("/api/slates/{slate_id}/ownership")
async def api_slate_ownership(request: Request, slate_id: str, season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    """Projected ownership % for a slate's players, keyed by DraftKings draftable id (Pro)."""
    await _require_feature(request, "ownership")
    try:
        return await _slate_ownership(season, week, slate_id, _model_version())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build ownership: {exc}") from exc


@app.get("/api/dfs-model")
async def api_dfs_model(request: Request, season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK,
                        slate_id: str | None = None, contest: str = "gpp", contest_size: int | None = None):
    """Weekly projection, ownership & lineup analysis for a Classic slate (app.dfs_model). Players' props
    (a Pro feature) are left out for free accounts."""
    _check_contest(contest)
    if contest_size is not None and not 2 <= contest_size <= 2_000_000:
        raise HTTPException(status_code=400, detail="contest_size must be between 2 and 2,000,000")
    build = _dfs_model if await _entitled(request, "props") else _dfs_model_without_props
    try:
        body = await build(season, week, slate_id, contest, contest_size, _model_version())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not build the DFS model: {exc}") from exc
    return Response(body, media_type="application/json")


AUTO_SLATE = "auto"        # an actual-ownership upload's slate, detected from its data


def _slate_args(body: dict) -> tuple[int, int, str]:
    season, week, slate_id = int(body["season"]), int(body["week"]), str(body["slate_id"])
    if not (2000 <= season <= 2100 and 1 <= week <= 22 and re.fullmatch(r"[a-z_]{1,40}", slate_id)):
        raise ValueError("Invalid season, week or slate_id")
    return season, week, slate_id


async def _resolver_players(season: int, week: int, slate_id: str) -> list[dict]:
    return (await ownership_slate.players_for(season, week, slate_id))[0]


async def _upload_slate(season: int, week: int, slate_id: str, detect) -> tuple[int, int, str, list[dict], dict | None]:
    """The slate an actual-ownership upload goes to: the one named, or with slate_id "auto" the one the upload's own
    data points to (app.ownership_slate; `detect` runs it), searching this week and last from (season, week)."""
    if slate_id != AUTO_SLATE:
        return season, week, slate_id, await _resolver_players(season, week, slate_id), None
    found = await detect()
    if not found:
        raise HTTPException(status_code=400, detail="Couldn't tell which slate this contest is from: too few of its players "
                                                    "are on this week's or last week's slates")
    players, _ = await ownership_slate.players_for(found["season"], found["week"], found["slate_id"])
    applied = {k: found[k] for k in ("season", "week", "slate_id", "label", "slate_type", "score")}
    return found["season"], found["week"], found["slate_id"], players, applied


@app.post("/api/ownership/source")
async def api_ownership_source(body: dict = Body(...), authorization: Annotated[str | None, Header()] = None):
    """Ownership projections pasted from a named source: {season, week, slate_id, contest, source, text}."""
    await _require_master(authorization)
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
async def api_ownership_crowd(body: dict = Body(...), authorization: Annotated[str | None, Header()] = None):
    """A crowdsourced submission: {season, week, slate_id, contest, user_id, display_name, confidence (1-5), text}."""
    await _require_master(authorization)
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
async def api_ownership_actual(body: dict = Body(...), authorization: Annotated[str | None, Header()] = None):
    """Actual contest ownership: a DraftKings contest-standings CSV (preferred: also carries every
    field lineup) or "Name, pct" lines. {season, week, slate_id, contest, text}. Triggers relearning."""
    await _require_master(authorization)
    try:
        season, week, slate_id = _slate_args({**body, "slate_id": body.get("slate_id") or AUTO_SLATE})
        contest = str(body.get("contest") or "gpp")
        text = str(body.get("text") or "")[:30_000_000]
        standings = "%Drafted" in text[:5000]
        if standings:
            parsed = ownership_store.parse_dk_standings(text)
            entries = [{"name": name, "pct": pct, "slot": slot if slot in ("CPT",) else "", "fpts": parsed["fpts"].get((name, slot))}
                       for (name, slot), pct in parsed["ownership"].items()]
        else:
            entries = ownership_store.parse_lines(text)
        season, week, slate_id, players, applied = await _upload_slate(
            season, week, slate_id, lambda: ownership_slate.for_names(entries, season, week))
        if standings:
            result = ownership_store.add_observations(season, week, slate_id, "actual", contest, entries, players,
                                                      source="dk_standings")
            result["players_with_ownership"] = len(entries)
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
            result = ownership_store.add_observations(season, week, slate_id, "actual", contest, entries, players,
                                                      source="pasted")
        result["slate"] = applied
        return await _save_actual(result, season, week, slate_id, contest)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _save_actual(result: dict, season: int, week: int, slate_id: str, contest: str) -> dict:
    """After an actual-ownership upload: keep it across redeploys (the disk store is wiped on deploy) and relearn."""
    batch_obs = [o for o in ownership_store.load(season, week, slate_id)["observations"] if o.get("batch") == result.get("batch")]
    result["persisted"] = await asyncio.to_thread(ownership_persist.save_upload, season, week, slate_id, contest,
                                                  result.get("batch", ""), result.get("timestamp", ""),
                                                  result.get("entries"), batch_obs)
    learning = await asyncio.to_thread(ownership_learning.relearn)
    result["learned"] = {"slates_with_actuals": learning.get("slates_with_actuals")}
    return result


MAX_VIDEO_BYTES = 400_000_000      # a few minutes of phone screen recording


@app.post("/api/ownership/actual/video")
async def api_ownership_actual_video(request: Request, season: int, week: int, slate_id: str = AUTO_SLATE,
                                     contest: str = "gpp", authorization: Annotated[str | None, Header()] = None):
    """Actual contest ownership read from a screen recording (or screenshot) of DraftKings' GameCenter Players tab
    (app.ownership_video): ownership, salary and fantasy points per player. The file is the raw request body.
    slate_id "auto" (the default) applies it to the slate its games and salaries match."""
    await _require_master(authorization)
    try:
        season, week, slate_id = _slate_args({"season": season, "week": week, "slate_id": slate_id})
        if contest not in ownership_store.CONTESTS:
            raise ValueError(f"Unknown contest type: {contest}")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ownership_video.available():
        raise HTTPException(status_code=503, detail="Video reading isn't available on this server (ffmpeg / tesseract missing)")
    with tempfile.NamedTemporaryFile(suffix=".upload") as tmp:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_VIDEO_BYTES:
                raise HTTPException(status_code=413, detail=f"Recording over {MAX_VIDEO_BYTES // 1_000_000} MB -- trim it")
            tmp.write(chunk)
        tmp.flush()
        if not size:
            raise HTTPException(status_code=400, detail="Empty upload")
        try:
            read = await asyncio.to_thread(ownership_video.read_video, Path(tmp.name))
        except (subprocess.SubprocessError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Couldn't read that recording: {exc}") from exc
    season, week, slate_id, players, applied = await _upload_slate(
        season, week, slate_id, lambda: ownership_slate.for_rows(read["rows"], season, week))
    if players and players[0]["slate_type"] == "showdown":
        raise HTTPException(status_code=400, detail="Screen recordings are read for Classic slates only")
    matched, unmatched = ownership_video.match(read["rows"], players)
    if not matched:
        raise HTTPException(status_code=400, detail="No players on this slate were read from that recording -- record the "
                                                    "contest's Players tab (GameCenter) and scroll the whole list")
    entries = [{"name": m["player"]["name"], "team": m["player"]["team"], "pct": m["pct"],
                "salary": m["salary"], "fpts": m["points"]} for m in matched]
    result = ownership_store.add_observations(season, week, slate_id, "actual", contest, entries, players,
                                              source="dk_gamecenter_video")
    result["unmatched"] = (result["unmatched"] + unmatched)[:50]
    result["frames"] = read["frames"]
    result["slate"] = applied
    result["players"] = [{"name": m["player"]["name"], "team": m["player"]["team"], "position": m["player"]["position"],
                          "pct": m["pct"], "salary": m["salary"], "points": m["points"],
                          "salary_mismatch": bool(m["salary"] and m["player"].get("salary") and m["salary"] != m["player"]["salary"])}
                         for m in sorted(matched, key=lambda m: -m["pct"])]
    return await _save_actual(result, season, week, slate_id, contest)


@app.post("/api/ownership/duplication")
async def api_ownership_duplication(request: Request, body: dict = Body(...)):
    """Duplication + exposure leverage for your own Lineup Builder lineups (Pro):
    {season, week, slate_id, contest, contest_size, lineups: [[dk_draftable_id, ...], ...]}."""
    await _require_feature(request, "leverage")
    try:
        season, week, slate_id = _slate_args(body)
        contest = _check_contest(str(body.get("contest") or "gpp"))
        size = int(body.get("contest_size") or ownership_report.DEFAULT_CONTEST_SIZE[contest])
        lineups = [[int(x) for x in lu] for lu in (body.get("lineups") or [])[:5] if isinstance(lu, list) and len(lu) == 9]
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _dfs_model(season, week, slate_id, contest, None, _model_version())
    state = dfs_model._STATE.get((season, week, slate_id, contest))
    if state is None:
        raise HTTPException(status_code=404, detail="Build the DFS model for this slate first")
    rep = await asyncio.to_thread(ownership_report.report, state, contest=contest, contest_size=size,
                                  model_lineups={f"Your lineup {i + 1}": lu for i, lu in enumerate(lineups)},
                                  exposure_lineups=lineups)
    return {"duplication": rep["duplication"], "leverage": rep["leverage"], "contest_size": size}


# ------------------------------------------------------------------ Big Picture (master-only pilot)
BIG_PICTURE_WORKFLOW = "big-picture.yml"


@app.get("/api/odds")
async def api_odds(season: Annotated[int | None, Query(ge=2000, le=2100)] = None,
                   week: Annotated[int | None, Query(ge=1, le=22)] = None, summary: bool = False):
    """DraftKings Sportsbook lines for a week (default: the upcoming one) (app.big_picture.odds): opening
    (first captured) and current quotes per game and market. Each call may take a fresh snapshot (at most
    every 10 minutes; for the upcoming week it also stores the next week's lookahead lines); summary=1 returns
    only the capture status."""
    from app.big_picture import dossier as bp_dossier
    from app.big_picture import odds as odds_module
    from app.big_picture import store as bp_store
    try:
        upcoming = season is None or week is None
        if upcoming:
            season, week = await bp_dossier.target_week()
        schedule, _ = await slates.list_slates(season, week)
        games = [(g.away, g.home) for g in schedule.games + schedule.isolated_games]
        # The upcoming week's pull also stores the next week's lookahead lines (their openers).
        next_games = None
        if upcoming and week < 18:
            try:
                nxt, _ = await slates.list_slates(season, week + 1)
                next_games = [(g.away, g.home) for g in nxt.games + nxt.isolated_games]
            except Exception:
                next_games = None
        snap = await odds_module.snapshot(season, week, games, next_games=next_games)
        matchups = {"games": games, "next_games": next_games or []}
        history = await asyncio.to_thread(bp_store.odds_history, season, week)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load odds: {exc}") from exc
    out = {"source": odds_module.SOURCE, "season": season, "week": week, "available": bool(history),
           "status": snap.get("status"), "captured_at": snap.get("fetched_at"), "stored": snap.get("stored"),
           "via": snap.get("via"), "credits_remaining": (snap.get("credits") or {}).get("remaining"),
           "quotes_total": len(history), "next_week_quotes": snap.get("next_week_quotes"),
           "next_week_stored": snap.get("next_week_stored")}
    if summary:
        out["matchups"] = matchups     # the runner's fallback stores these weeks' quotes itself
    else:
        out["games"] = odds_module.summarize(history)
    return out


async def _workflow_status() -> dict | None:
    token = os.environ.get("GITHUB_DISPATCH_TOKEN")
    if not token:
        return None
    import httpx
    repo = os.environ.get("GITHUB_REPO", "hgkf7y4kn6-droid/DFS-Riches")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.github.com/repos/{repo}/actions/workflows/{BIG_PICTURE_WORKFLOW}/runs",
                                 params={"per_page": 1}, headers={"Authorization": f"Bearer {token}",
                                                                  "Accept": "application/vnd.github+json"})
            runs = r.json().get("workflow_runs") or [] if r.status_code == 200 else []
    except Exception:
        return None
    if not runs:
        return {"status": None}
    run = runs[0]
    return {"status": run.get("status"), "conclusion": run.get("conclusion"), "started_at": run.get("run_started_at"),
            "updated_at": run.get("updated_at")}


@app.get("/api/big-picture")
async def api_big_picture(id: int | None = None, authorization: Annotated[str | None, Header()] = None):
    """The NFL Intelligence Desk report (master accounts only): the newest version, or one by id, plus the
    version list and whether a new run can be started from the app."""
    await _require_master(authorization)
    from app.big_picture import store as bp_store
    try:
        report = await asyncio.to_thread(bp_store.get_report, id, with_dossier=True)
        versions = await asyncio.to_thread(bp_store.list_reports, None, 40)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load the Big Picture: {exc}") from exc
    return {"report": report, "versions": versions, "can_run": bool(os.environ.get("GITHUB_DISPATCH_TOKEN")),
            "run": await _workflow_status()}


@app.get("/api/news-overrides")
async def api_news_overrides(season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK):
    """Breaking news entered by hand for the week (app.news_overrides), newest first."""
    return {"season": season, "week": week, "statuses": news_overrides.STATUSES,
            "entries": list(reversed(await news_overrides.entries(season, week)))}


def _news_changed() -> None:
    """New breaking news: rebuild the slates' players and the game model now, not when their caches expire."""
    slates.get_slate_players.cache_clear()
    from app import game_model
    game_model._week_games_cached.cache_clear()


@app.post("/api/news-overrides")
async def api_news_override_add(body: dict = Body(...), authorization: Annotated[str | None, Header()] = None):
    """Master accounts: {season, week, name, team (optional when the name is on one team's DraftKings roster), status
    (OUT | D | Q | PLAYING), note}. The name is matched to the week's DraftKings players; a player who isn't on one
    (a lineman, a defender) needs his team and counts only toward the game model's starters out."""
    user_id = await _require_master(authorization)
    try:
        season, week = int(body["season"]), int(body["week"])
        name, team = str(body.get("name") or "").strip(), str(body.get("team") or "").strip().upper()
        status = str(body.get("status") or "").strip().upper()
        if not (2000 <= season <= 2100 and 1 <= week <= 22) or not 2 <= len(name) <= 60:
            raise ValueError("Give a season, week and player name")
        if status not in news_overrides.STATUSES:
            raise ValueError(f"status must be one of {', '.join(news_overrides.STATUSES)}")
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    match = await _news_player(season, week, name, team)
    if match is None and not team:
        raise HTTPException(status_code=400, detail=f"{name} isn't on this week's DraftKings slates: add his team")
    if match is None and team not in {t for g in (await slates.list_slates(season, week))[0].games for t in (g.away, g.home)}:
        raise HTTPException(status_code=400, detail=f"{team} doesn't play in week {week}")
    entry = await news_overrides.add(season, week, match[1] if match else team, match[0] if match else name, status,
                                     str(body.get("note") or ""), on_slate=match is not None, by=user_id)
    _news_changed()
    return entry


@app.delete("/api/news-overrides/{entry_id}")
async def api_news_override_remove(entry_id: str, season: Season = DEFAULT_SEASON, week: Week = DEFAULT_WEEK,
                                   authorization: Annotated[str | None, Header()] = None):
    await _require_master(authorization)
    if not re.fullmatch(r"[0-9a-f]{6,32}", entry_id):
        raise HTTPException(status_code=400, detail="Bad id")
    gone = await news_overrides.remove(season, week, entry_id)
    _news_changed()
    return {"removed": gone}


async def _news_player(season: int, week: int, name: str, team: str) -> tuple[str, str] | None:
    """(DraftKings name, team) for a typed name: an exact match, else a unique last-name match (on the team, when
    given); None when there's no single match on the week's slates."""
    from app.matching import normalize_name
    _schedule, week_slates = await slates.list_slates(season, week)
    seen: dict[tuple[str, str], str] = {}
    for s in week_slates:
        if not s.available:
            continue
        try:
            sp = await slates.get_slate_players(season, week, s.slate_id)
        except Exception:
            continue
        for p in sp.players:
            if p.position != "DST":
                seen[(p.team, normalize_name(p.name))] = p.name
    want = normalize_name(name)
    pool = {k: v for k, v in seen.items() if not team or k[0] == team}
    exact = [(v, k[0]) for k, v in pool.items() if k[1] == want]
    if len(exact) == 1:
        return exact[0]
    last = want.split(" ")[-1]
    by_last = [(v, k[0]) for k, v in pool.items() if k[1].split(" ")[-1] == last and (" " not in want or k[1].split(" ")[0][:1] == want[:1])]
    return by_last[0] if len(by_last) == 1 else None


@app.post("/api/big-picture/run")
async def api_big_picture_run(authorization: Annotated[str | None, Header()] = None):
    """Start a research run (GitHub Actions workflow) now. Master accounts only."""
    await _require_master(authorization)
    token = os.environ.get("GITHUB_DISPATCH_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="On-demand runs aren't set up (GITHUB_DISPATCH_TOKEN); reports run on schedule.")
    import httpx
    repo = os.environ.get("GITHUB_REPO", "hgkf7y4kn6-droid/DFS-Riches")
    ref = os.environ.get("GITHUB_REF_NAME", "claude/dfsriches-explorer-t1pdh5")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"https://api.github.com/repos/{repo}/actions/workflows/{BIG_PICTURE_WORKFLOW}/dispatches",
                              json={"ref": ref}, headers={"Authorization": f"Bearer {token}",
                                                          "Accept": "application/vnd.github+json"})
    if r.status_code not in (201, 204):
        raise HTTPException(status_code=502, detail=f"GitHub refused the run (HTTP {r.status_code})")
    return {"started": True}


def _web_file(path: str):
    """The web build's file for a URL path: the file itself, its pre-rendered
    .html route (expo-router static output), or the app shell for anything else."""
    root = WEB_DIR.resolve()
    clean = path.strip("/")
    for candidate in (clean, f"{clean}.html", f"{clean}/index.html" if clean else "index.html"):
        if not candidate:
            continue
        f = (root / candidate).resolve()
        if f.is_file() and f.is_relative_to(root):
            return f
    return root / "index.html"


@app.get("/{path:path}", include_in_schema=False)
async def web_app(path: str):
    """Serve the app (registered last, so every API and /classic route wins)."""
    if path.startswith(("api/", "static/")):
        raise HTTPException(status_code=404)
    if not (WEB_DIR / "index.html").is_file():
        return RedirectResponse("/classic")
    f = _web_file(path)
    hashed = path.startswith(("_expo/", "assets/"))   # content-hashed bundles, fonts and images
    if hashed and f.name == "index.html":              # a missing hashed file: never cache the app shell under it
        raise HTTPException(status_code=404)
    headers = {"Cache-Control": "public, max-age=31536000, immutable" if hashed else "no-cache"}
    return FileResponse(f, headers=headers)


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
