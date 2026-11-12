"""The Big Picture dossier: every fact the report may use, gathered and
computed in code, with its source and capture time.

The research agents (app.big_picture.agents) read slices of this and nothing
else, and the quality check rejects figures that aren't in it. Built from the
app's own data (schedule and weather, nflverse efficiency, DraftKings DFS
salaries and statuses, the DFS model's projections and ownership), injury
designations and next-man-up cross-checked across Sleeper, ESPN, each team's
own site and DraftKings (app.big_picture.rosters), and DraftKings Sportsbook
odds (app.big_picture.odds).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import httpx

from app import advanced_env, game_model
from app.big_picture import odds as odds_module
from app.big_picture import quant, rosters, store
from app.config import ET

log = logging.getLogger(__name__)

MODEL_VERSION = "bp-1.0"
SITE = os.environ.get("BIG_PICTURE_SITE", "https://dfsriches.richesdigitalventures.com")

SKILL = {"QB", "RB", "WR", "TE"}
OL = {"OL", "OT", "G", "C", "T", "LT", "LG", "RG", "RT"}
DL = {"DL", "DE", "DT", "NT", "EDGE"}
LB = {"LB", "ILB", "OLB", "MLB"}
DB = {"DB", "CB", "S", "FS", "SS"}
STATUS_ORDER = {"Out": 0, "IR": 0, "PUP": 0, "Sus": 0, "Doubtful": 1, "Questionable": 2}
DK_STATUS = {"O": "Out", "OUT": "Out", "IR": "IR", "D": "Doubtful", "Q": "Questionable"}


def _r(x, n=1):
    return round(x, n) if isinstance(x, (int, float)) else None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def et_label(dt: datetime | None = None) -> str:
    d = (dt or datetime.now(timezone.utc)).astimezone(ET)
    return d.strftime("%a %b %-d, %Y %-I:%M %p ET")


# ------------------------------------------------------------------ inputs
async def target_week() -> tuple[int, int]:
    """The week the desk is preparing for: Sleeper's week, or the next one once most of it has kicked off."""
    from app.sleeper_client import get_nfl_state
    from app.slates import list_slates
    state = await get_nfl_state()
    season, week = int(state.get("league_season") or state.get("season")), int(state.get("week") or 1)
    if os.environ.get("BIG_PICTURE_WEEK"):
        return season, int(os.environ["BIG_PICTURE_WEEK"])
    schedule, _ = await list_slates(season, week)
    games = schedule.games + schedule.isolated_games
    started = sum(1 for g in games if g.kickoff_utc <= datetime.now(timezone.utc))
    if games and started / len(games) >= 0.6 and week < 18:
        week += 1
    return season, week


def _unit(position: str | None) -> str:
    p = (position or "").upper()
    if p in SKILL:
        return "skill"
    if p in OL:
        return "offensive line"
    if p in DL:
        return "defensive front"
    if p in LB:
        return "linebackers"
    if p in DB:
        return "secondary"
    return "other"


async def fetch_odds(season: int, week: int) -> dict:
    """DraftKings quotes for the week: from the shared database when this run has DATABASE_URL (the site and the
    odds-snapshot workflow store every capture there), else through the site's API."""
    if store._url():
        try:
            history = await asyncio.to_thread(store.odds_history, season, week)
            return {"available": bool(history), "status": "ok" if history else "no stored quotes",
                    "games": odds_module.summarize(history)}
        except Exception as exc:
            log.warning("stored odds unavailable (%s); trying the site", type(exc).__name__)
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.get(f"{SITE}/api/odds", params={"season": season, "week": week})
            if r.status_code == 200:
                return r.json()
            return {"available": False, "status": f"site answered HTTP {r.status_code}", "games": {}}
    except Exception as exc:
        return {"available": False, "status": f"site unreachable ({type(exc).__name__})", "games": {}}


# ------------------------------------------------------------------ market + model per game
def _quote(mk: dict, market: str, side: str) -> dict | None:
    return ((mk.get(market) or {}).get(side)) or None


def market_view(game_key: str, dk: dict, ctx) -> dict:
    """Opening/current DraftKings quotes, else the nflverse consensus line (no prices)."""
    mk = (dk.get("games") or {}).get(game_key) or {}
    if mk:
        out = {"source": odds_module.SOURCE, "prices": True}
        for market, sides in (("spread", ("home", "away")), ("total", ("over", "under")), ("moneyline", ("home", "away")),
                              ("team_total_home", ("over", "under")), ("team_total_away", ("over", "under"))):
            got = {s: q for s in sides if (q := _quote(mk, market, s))}
            if got:
                out[market] = {s: {"opening": q["opening"], "current": q["current"], "moves": len(q.get("moves") or [])}
                               for s, q in got.items()}
        return out
    if ctx is not None and ctx.home_spread is not None:
        return {"source": "nflverse consensus line (DraftKings prices unavailable)", "prices": False,
                "spread": {"home": {"current": {"line": ctx.home_spread, "price": None}},
                           "away": {"current": {"line": ctx.away_spread, "price": None}}},
                "total": {"over": {"current": {"line": ctx.total_line, "price": None}},
                          "under": {"current": {"line": ctx.total_line, "price": None}}}}
    return {"source": "none", "prices": False}


def _cur(m: dict, market: str, side: str) -> dict:
    return (((m.get(market) or {}).get(side) or {}).get("current")) or {}


def candidates(model: dict, market: dict, unresolved: bool, trust: dict | None = None) -> list[dict]:
    """Every listed side of spread, total and team totals, evaluated against the model and classified."""
    out = []
    mh, ma = model["home_points"], model["away_points"]
    mdist, tdist = quant.margin_dist(mh - ma), quant.total_dist(mh + ma)
    hdist, adist = quant.team_dist(mh), quant.team_dist(ma)
    specs = [
        ("spread", "home", "away", +1, mdist, "spread", model["fair_home_spread"]),
        ("spread", "away", "home", -1, mdist, "spread", -model["fair_home_spread"]),
        ("total", "over", "under", +1, tdist, "total", model["fair_total"]),
        ("total", "under", "over", -1, tdist, "total", model["fair_total"]),
        ("team_total_home", "over", "under", +1, hdist, "team_total", mh),
        ("team_total_home", "under", "over", -1, hdist, "team_total", mh),
        ("team_total_away", "over", "under", +1, adist, "team_total", ma),
        ("team_total_away", "under", "over", -1, adist, "team_total", ma),
    ]
    for mkey, side, other, sign, dist, kind, fair in specs:
        q = _cur(market, mkey, side)
        line = q.get("line")
        if line is None:
            continue
        res = quant.evaluate(kind, dist, float(line), sign, q.get("price"), _cur(market, mkey, other).get("price"))
        # Points of value for this side: the posted number against the model's.
        if kind == "spread":
            edge = line - fair                     # home +3 with a fair +1 -> 2 points of value
        else:
            edge = (fair - line) if sign > 0 else (line - fair)
        res.update(market=mkey, side=side, kind=kind, fair=_r(fair), points_edge=_r(edge))
        trusted = (trust or {}).get("spread" if kind == "spread" else "total", True)
        res["class"] = quant.classify(res, kind, edge, unresolved, trusted)
        if not trusted:
            res["class_note"] = "capped at watchlist: the model trails the market on this market type in the backtest"
        out.append(res)
    return out


def line_movement(market: dict, fair: float | None, mkey: str, side: str) -> dict | None:
    """Opening -> current for one side, and whether it moved toward or away from the model's number."""
    q = (market.get(mkey) or {}).get(side) or {}
    op, cur = (q.get("opening") or {}), (q.get("current") or {})
    if op.get("line") is None or cur.get("line") is None:
        return None
    out = {"opening": op.get("line"), "opening_price": op.get("price"), "current": cur.get("line"),
           "current_price": cur.get("price"), "opened_at": op.get("at"), "updated_at": cur.get("at"),
           "line_move": _r(cur["line"] - op["line"]), "quotes": q.get("moves")}
    if fair is not None and cur["line"] != op["line"]:
        out["vs_model"] = "toward model" if abs(cur["line"] - fair) < abs(op["line"] - fair) else "away from model"
    elif cur.get("price") != op.get("price"):
        out["vs_model"] = "price (juice) moved, number unchanged"
    return out


# ------------------------------------------------------------------ injuries
def team_injuries(team: str, roster_data: dict, dk_rows: list[dict]) -> tuple[list[dict], dict]:
    """Designated players who matter, each cross-checked across Sleeper, ESPN, the team's site and DraftKings
    (app.big_picture.rosters), plus the team's source coverage."""
    rows, coverage = rosters.team_injuries(team, roster_data, dk_rows)
    for row in rows:
        row["unit"] = _unit(row["position"])
    return rows, coverage


def unresolved(injuries: list[dict]) -> bool:
    """A quarterback, or two or more starters, still questionable/doubtful: prices may not have settled."""
    open_ = [r for r in injuries if r["status"] in ("Questionable", "Doubtful")]
    return any(r["position"] == "QB" for r in open_) or sum(1 for r in open_ if r.get("starter")) >= 2


# ------------------------------------------------------------------ compact records
PROFILE_KEYS = ("epa_play", "success", "db_epa", "rush_epa", "sack_rate", "pressure_rate", "explosive_pass", "explosive_run")


def _profile(p: dict | None) -> dict:
    if not p:
        return {}
    return {"off": {k: p["off"].get(k) for k in PROFILE_KEYS}, "def": {k: p["def"].get(k) for k in PROFILE_KEYS},
            "games": p.get("games"), "prior_games": p.get("prior_games")}


def _player(r: dict, own_key: str | None = None) -> dict:
    own = r.get("ownership")
    if isinstance(own, dict):
        own = own.get(own_key or "large_gpp")
    out = {"name": r.get("name"), "pos": r.get("position"), "team": r.get("team"), "opp": r.get("opponent"),
           "salary": r.get("salary"), "proj": _r(r.get("final")), "floor": _r(r.get("floor")),
           "ceiling": _r(r.get("ceiling")), "own": _r(own), "injury": r.get("injury")}
    for k in ("leverage", "p_hit", "tag", "value", "role"):
        if r.get(k) is not None:
            out[k] = _r(r[k], 3) if k == "p_hit" else (_r(r[k]) if isinstance(r[k], float) else r[k])
    if r.get("tag_reason"):
        out["why"] = r["tag_reason"]
    return out


# ------------------------------------------------------------------ build
def model_game(gb, hp: dict, ap: dict, league: dict, league_points: float, league_plays: float) -> dict:
    """The quant model for one GameBreakdown (also used by the backtest, app.big_picture.history)."""
    def plays(own, opp):
        o, p = own.plays_per_game or league_plays, opp.plays_per_game or league_plays
        return 0.5 * o + 0.25 * p + 0.25 * league_plays

    wx = gb.game.weather or {}
    wmult = 1.0 if wx.get("observed") else float((wx.get("multipliers") or {}).get("points") or 1.0)
    return quant.project_game(hp["off"], hp["def"], ap["off"], ap["def"], league,
                              home_plays=plays(gb.home_stats, gb.away_stats), away_plays=plays(gb.away_stats, gb.home_stats),
                              league_points=league_points, weather_points=wmult,
                              home_games=hp.get("games") or 0, away_games=ap.get("games") or 0,
                              prior_games=hp.get("prior_games") or 3)


def league_baselines(wb) -> tuple[float, float]:
    stats = [s for g in wb.games for s in (g.away_stats, g.home_stats)]
    pts = [s.points_for for s in stats if s.points_for]
    plays = [s.plays_per_game for s in stats if s.plays_per_game]
    return (sum(pts) / len(pts) if pts else 22.5), (sum(plays) / len(plays) if plays else 62.0)


async def build(season: int | None = None, week: int | None = None) -> dict:
    """The full dossier for (season, week) -- the upcoming week by default."""
    from app import breakdown, game_detail, main, ownership_persist, ownership_store, trenches

    if season is None or week is None:
        season, week = await target_week()
    await asyncio.to_thread(ownership_persist.restore)
    version = ownership_store.data_version()

    wb = await breakdown.build_week_breakdown(season, week)
    profiles = await trenches.week_profiles(season, week)
    sem = asyncio.Semaphore(4)

    async def detail(gid):
        async with sem:
            try:
                return gid, await game_detail.build_game_detail(season, week, gid)
            except Exception as exc:
                log.warning("game detail %s failed: %s", gid, exc)
                return gid, None

    details = dict(await asyncio.gather(*(detail(g.game.game_id) for g in wb.games)))
    model = json.loads(await main._dfs_model(season, week, None, "gpp", None, version))
    gpp = json.loads(await main._plays(season, week, None, "gpp", version))
    cash = json.loads(await main._plays(season, week, None, "cash", version))
    playing = sorted({t for gb in wb.games for t in (gb.game.away, gb.game.home)})
    roster_data = await rosters.gather(playing, week)
    cov = roster_data["coverage"]
    status_note = None if cov["sleeper"] == "ok" and cov["espn_injuries"] == "ok" else \
        f"Injury sources partly unavailable: Sleeper {cov['sleeper']}, ESPN {cov['espn_injuries']}"
    dk = await fetch_odds(season, week)
    from app.big_picture import history
    backtest = await history.backtest(season, week)
    # Game model v2 (app.game_model): the market line plus a correction fit on 2023-2025. A market type is rated
    # beyond watchlist only while the model's out-of-sample picks beat break-even.
    v2_lines = {}
    for gb in wb.games:
        k = f"{gb.game.away}@{gb.game.home}"
        mk = market_view(k, dk, gb.game.context)
        t, sp = _cur(mk, "total", "over").get("line"), _cur(mk, "spread", "home").get("line")
        v2_lines[k] = (t, -sp if sp is not None else None)
    try:
        v2 = await game_model.week_games(season, week, v2_lines,
                                         wind={f"{gb.game.away}@{gb.game.home}": (gb.game.weather or {}).get("wind_mph") for gb in wb.games})
        v2_season = await game_model.season_record(season, week)
    except Exception as exc:
        log.warning("game model v2 failed: %s", exc)
        v2, v2_season = {}, None
    trust = game_model.trusted() if v2 else {
        "spread": backtest.get("games", 0) >= 30 and backtest["spread_mae_model"] <= backtest["spread_mae_market"] + 0.25,
        "total": backtest.get("games", 0) >= 30 and backtest["total_mae_model"] <= backtest["total_mae_market"] + 0.25}

    adv_games = tuple((gb.game.away, gb.game.home,
                       _cur(market_view(f"{gb.game.away}@{gb.game.home}", dk, gb.game.context), "total", "over").get("line"))
                      for gb in wb.games)
    try:
        adv = await advanced_env.for_games(season, week, adv_games)
        adv_bt = await advanced_env.backtest(season, week)
    except Exception as exc:
        log.warning("advanced environment failed: %s", exc)
        adv, adv_bt = {}, None

    table = model.get("table") or []
    strategy = model.get("strategy") or {}
    env_by_game = {g["game"]: g for g in strategy.get("games") or []}
    league_points, league_plays = league_baselines(wb)
    league = profiles.get("league") or {}
    teams = profiles.get("teams") or {}
    now = datetime.now(timezone.utc)

    games = []
    for gb in wb.games:
        g = gb.game
        if g.kickoff_utc <= now:
            continue
        key = f"{g.away}@{g.home}"
        hp, ap = teams.get(g.home), teams.get(g.away)
        if not hp or not ap:
            continue

        wx = g.weather or {}
        mdl = model_game(gb, hp, ap, league, league_points, league_plays)
        mkt = market_view(key, dk, g.context)
        if v2.get(key):
            f = v2[key]
            mdl = quant.from_points((f["fair_total"] + f["fair_home_margin"]) / 2, (f["fair_total"] - f["fair_home_margin"]) / 2,
                                    inputs={"model": "v2: market line + fitted correction", "total_adj": f["total_adj"],
                                            "margin_adj": f["margin_adj"], "qbs": f["qbs"], "ol_out": f["ol_out"],
                                            "epa_model": {k: mdl[k] for k in ("home_points", "away_points", "fair_total", "fair_home_spread")}})
        (home_inj, home_cov), (away_inj, away_cov) = team_injuries(g.home, roster_data, table), team_injuries(g.away, roster_data, table)
        inj = {"home": home_inj, "away": away_inj}
        open_news = unresolved(inj["home"]) or unresolved(inj["away"])
        cands = candidates(mdl, mkt, open_news, trust)
        gd = details.get(g.game_id)
        env = env_by_game.get(key) or {}
        ctx = g.context
        movement = {k: v for k, v in {
            "spread_home": line_movement(mkt, mdl["fair_home_spread"], "spread", "home"),
            "total": line_movement(mkt, mdl["fair_total"], "total", "over"),
            "team_total_home": line_movement(mkt, mdl["home_points"], "team_total_home", "over"),
            "team_total_away": line_movement(mkt, mdl["away_points"], "team_total_away", "over"),
        }.items() if v}
        cur_spread = _cur(mkt, "spread", "home").get("line")
        cur_total = _cur(mkt, "total", "over").get("line")
        games.append({
            "id": f"{season}-W{week:02d}-{key}",
            "game": key, "away": g.away, "home": g.home, "kickoff_et": g.kickoff_et,
            "kickoff_utc": g.kickoff_utc.isoformat(), "network": g.network, "window": g.day_part,
            "market": mkt,
            "market_summary": {"home_spread": cur_spread, "total": cur_total,
                               "home_team_total": _cur(mkt, "team_total_home", "over").get("line"),
                               "away_team_total": _cur(mkt, "team_total_away", "over").get("line"),
                               "implied_home": _r((cur_total - cur_spread) / 2) if cur_total is not None and cur_spread is not None else None,
                               "implied_away": _r((cur_total + cur_spread) / 2) if cur_total is not None and cur_spread is not None else None},
            "movement": movement,
            "model": mdl,
            "advanced_env": {**adv[key], "notes": advanced_env.notes(adv[key])} if adv.get(key) else None,
            "checklist": (v2.get(key) or {}).get("checklist"),
            "model_vs_market": {"spread_gap": _r(cur_spread - mdl["fair_home_spread"]) if cur_spread is not None else None,
                                "total_gap": _r(mdl["fair_total"] - cur_total) if cur_total is not None else None},
            "candidates": cands,
            "unresolved_news": open_news,
            "injuries": inj,
            "injury_sources": {"home": home_cov, "away": away_cov},
            "weather": {k: wx.get(k) for k in ("summary", "roof", "temp_f", "wind_mph", "gust_mph", "precip_chance",
                                                "severity", "flags", "impact", "multipliers", "long_range", "source")},
            "environment": {**{k: env.get(k) for k in ("env_rank", "env_score", "pop_rank", "pop_share", "shootout",
                                                       "negative_script", "favorite", "underdog", "live_dog", "script",
                                                       "ownership_vs_quality", "tempo_ranks", "pass_rate_ranks",
                                                       "top10_ceiling", "shootout_leverage", "shootout_note") if env.get(k) is not None},
                            **{k: mdl[k] for k in ("p_shootout", "p_both_24", "p_one_score", "p_blowout")},
                            "on_main_slate": bool(env)},
            "teams": {
                "home": {"team": g.home, **_profile(hp), "points_for": gb.home_stats.points_for,
                         "points_against": gb.home_stats.points_against, "plays_pg": gb.home_stats.plays_per_game,
                         "tempo_rank": gb.home_stats.tempo_rank, "pass_rate": gb.home_stats.pass_pct},
                "away": {"team": g.away, **_profile(ap), "points_for": gb.away_stats.points_for,
                         "points_against": gb.away_stats.points_against, "plays_pg": gb.away_stats.plays_per_game,
                         "tempo_rank": gb.away_stats.tempo_rank, "pass_rate": gb.away_stats.pass_pct},
            },
            "trenches": (env.get("trench_notes") or []) + ([gd.insights.get("trenches")] if gd and gd.insights.get("trenches") else []),
            "insights": {k: v for k, v in (gd.insights.items() if gd else []) if k in ("vegas", "away_offense", "home_offense", "tempo", "tendency", "positions")},
            "market_trend": {"home_spread_l3": (ctx.home_spread_trend.l3 if ctx and ctx.home_spread_trend else None),
                             "away_spread_l3": (ctx.away_spread_trend.l3 if ctx and ctx.away_spread_trend else None)} if ctx else {},
            "key_players": {side: [_player(r) for r in sorted((r for r in table if r.get("team") == t), key=lambda r: -(r.get("final") or 0))[:5]]
                            for side, t in (("home", g.home), ("away", g.away))},
        })
    games.sort(key=lambda x: x["kickoff_utc"])

    dfs = {
        "slate": model.get("slate"), "slates": [{"id": s.get("slate_id"), "label": s.get("label")} for s in model.get("slates") or []],
        "ownership_note": "Projected ownership from this app's ownership model (not observed contest data) unless marked actual.",
        "actual_ownership_uploaded": bool(gpp.get("actual_ownership")),
        "cash_top": {pos: [_player(r, "cash") for r in (cash.get("rankings") or {}).get(pos, [])[:5]] for pos in ("QB", "RB", "WR", "TE")},
        "gpp_top": {pos: [_player(r, "large_gpp") for r in (gpp.get("rankings") or {}).get(pos, [])[:5]] for pos in ("QB", "RB", "WR", "TE")},
        "leverage": {pos: [_player(r, "large_gpp") for r in rows[:4]] for pos, rows in (gpp.get("leverage_by_position") or {}).items()},
        "chalk": [_player(r, "large_gpp") for r in (strategy.get("chalk") or [])[:10]],
        "chalk_notes": [{"name": r.get("name"), "why_popular": r.get("why_popular"), "risk": r.get("risk"),
                         "classification": r.get("classification")} for r in (strategy.get("chalk") or [])[:10]],
        "stacks": [{"game": s.get("game"), "team": s.get("team"), "type": s.get("type"),
                    "players": [_player(p) for p in s.get("players") or []]} for s in (strategy.get("stacks") or [])[:6]],
        "fades": {k: [{**_player(r), "reason": r.get("reason")} for r in v[:3]] for k, v in (strategy.get("fades") or {}).items()},
        "leverage_pairs": [{**_player(r), "reason": r.get("reason")} for r in ((strategy.get("leverage") or {}).get("same_team") or [])[:5]],
        "role_shifts": [_player(r) for r in (gpp.get("role_shifts") or [])[:6]],
        "dst": [_player(r, "large_gpp") for r in ((gpp.get("leverage_by_position") or {}).get("DST") or [])[:5]],
        "available": bool(model.get("available")),
    }

    gaps = [
        "Betting ticket and handle splits: no source connected -- public-betting sentiment is inferred, not measured.",
        f"Official team injury reports: {cov['team_reports']} of {cov['teams']} teams have posted Week {week} "
        "(reports start Wednesday; until then designations come from Sleeper, ESPN and DraftKings).",
        "Beat-reporter news and coaching comments: not connected.",
        "Sportsbooks other than DraftKings: not used (DraftKings only, by design).",
        "Showdown slates: listed, analyzed in depth only through the main-slate model.",
    ]
    if not dk.get("available"):
        gaps.insert(0, f"DraftKings Sportsbook odds unavailable ({dk.get('status')}): lines are nflverse consensus, without prices -- no expected value can be computed.")
    if status_note:
        gaps.append(status_note)
    gaps += [f"{m['item']}: {m['why']}" for m in (strategy.get("missing_data") or [])[:4]]

    return {
        "meta": {"season": season, "week": week, "generated_at": now_iso(), "generated_et": et_label(),
                 "model_version": MODEL_VERSION, "timezone": "ET",
                 "games_covered": [g["game"] for g in games],
                 "markets": ["spread", "total", "team totals", "moneyline (fair price only)"],
                 "sources": [
                     {"name": odds_module.SOURCE, "use": "odds: spreads, totals, team totals, prices; first capture = opening",
                      "status": dk.get("status"), "captured_at": dk.get("captured_at")},
                     {"name": "nflverse play-by-play", "use": "EPA/play, success, pressure, explosive rates (app.trenches)"},
                     {"name": "nflverse schedules/lines", "use": "consensus lines, results, pace"},
                     {"name": "Sleeper", "use": "injury designations and depth charts (all positions)", "status": cov["sleeper"],
                      "captured_at": now_iso()},
                     {"name": "ESPN", "use": "injury feed and team depth charts", "status": cov["espn_injuries"],
                      "captured_at": now_iso()},
                     {"name": "Team sites", "use": f"official injury reports ({cov['team_reports']}/{cov['teams']} posted) "
                                                   f"and depth charts ({cov['team_depth_charts']}/{cov['teams']} readable)",
                      "captured_at": now_iso()},
                     {"name": "DraftKings DFS", "use": "salaries, DFS player statuses, slates"},
                     {"name": "Riches Analytics DFS model", "use": "projections, floors/ceilings, ownership, leverage"},
                     {"name": "National Weather Service (app.weather)", "use": "kickoff forecasts and projection multipliers"},
                 ],
                 "gaps": gaps,
                 "definitions": {"shootout": f"{quant.SHOOTOUT_POINTS}+ combined points",
                                 "both_teams": f"each team {quant.BOTH_TEAMS_POINTS}+",
                                 "blend": f"blended probability = {quant.BLEND_MODEL:.0%} model + {1 - quant.BLEND_MODEL:.0%} no-vig DraftKings",
                                 "classes": "strongest: blended EV >= 2.5% and a real points gap; price_sensitive: blended EV > 0.5%; "
                                            "watchlist: model likes it but the blend doesn't, or key injury news is unresolved; none."},
                 "league": {"points_per_team": _r(league_points), "plays_per_team": _r(league_plays),
                            "epa_play": league.get("off", {}).get("epa_play")}},
        "calibration": {"backtest": backtest, "trusted": trust, "advanced_env": adv_bt,
                        "game_model": {**(game_model.records_summary() or {}), "this_season": v2_season}},
        "market_status": {"available": bool(dk.get("available")), "status": dk.get("status"), "captured_at": dk.get("captured_at")},
        "games": games,
        "dfs": dfs,
    }
