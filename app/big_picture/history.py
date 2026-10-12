"""What changed since the last report, and how the model has done.

* changes(): compares this dossier with the newest stored one for the same
  week -- line moves, fair-line revisions, edges added/removed/downgraded,
  injury status changes, shootout-ranking and ownership shifts -- as change-log
  rows. Nothing material is reported as "no material change", never invented.
* backtest(): the same game model run as of each finished week this season
  (each week's inputs only use games before it), against the nflverse
  consensus closing line and the final score: error vs the actual margin and
  total, for the model and the market, and the model's record where it
  disagreed with the close.
* graded(): stored reports' strongest / price-sensitive calls, once final:
  win/loss/push and closing-line value against the last DraftKings quote
  before kickoff. Original reports are never edited.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.big_picture import dossier as dossier_module
from app.big_picture import quant, store

log = logging.getLogger(__name__)

RANKED = ("strongest", "price_sensitive", "watchlist", "none")


def _cand_key(c: dict) -> str:
    return f"{c['market']}:{c['side']}"


def _label(game: str, c: dict) -> str:
    mk = c["market"].replace("team_total_", "team total (").replace("home", "home)").replace("away", "away)") \
        if c["market"].startswith("team_total") else c["market"]
    return f"{game} {mk} {c['side']} {c['line']:+g}" if c["kind"] == "spread" else f"{game} {mk} {c['side']} {c['line']:g}"


def changes(cur: dict, prev: dict | None) -> dict:
    if not prev:
        return {"first_report": True, "since": None, "rows": [], "unchanged": [],
                "note": "First report of the week: no earlier version to compare."}
    rows: list[dict] = []
    unchanged: list[str] = []
    prev_games = {g["game"]: g for g in prev.get("games") or []}
    for g in cur.get("games") or []:
        p = prev_games.get(g["game"])
        if not p:
            rows.append({"item": g["game"], "previous": "not covered", "current": "added to coverage",
                         "reason": "game now has lines or inputs", "action": "review"})
            continue
        before = len(rows)
        ms, pms = g["market_summary"], p.get("market_summary") or {}
        for k, label, th in (("home_spread", "spread (home)", 0.5), ("total", "total", 0.5),
                             ("home_team_total", f"{g['home']} team total", 0.5), ("away_team_total", f"{g['away']} team total", 0.5)):
            a, b = pms.get(k), ms.get(k)
            if a is not None and b is not None and abs(b - a) >= th:
                rows.append({"item": f"{g['game']} {label}", "previous": f"{a:g}", "current": f"{b:g}",
                             "reason": "DraftKings line moved", "action": "re-priced"})
        m, pm = g["model"], p.get("model") or {}
        for k, label, th in (("fair_home_spread", "fair spread (home)", 0.5), ("fair_total", "fair total", 1.0)):
            a, b = pm.get(k), m.get(k)
            if a is not None and b is not None and abs(b - a) >= th:
                why = []
                if (pm.get("inputs") or {}).get("weather_points") != (m.get("inputs") or {}).get("weather_points"):
                    why.append("weather forecast")
                if (pm.get("inputs") or {}).get("home") != (m.get("inputs") or {}).get("home") or \
                        (pm.get("inputs") or {}).get("away") != (m.get("inputs") or {}).get("away"):
                    why.append("efficiency/pace inputs")
                rows.append({"item": f"{g['game']} {label}", "previous": f"{a:g}", "current": f"{b:g}",
                             "reason": ", ".join(why) or "model inputs updated", "action": "fair line revised"})
        pc = {_cand_key(c): c for c in p.get("candidates") or []}
        for c in g.get("candidates") or []:
            o = pc.get(_cand_key(c))
            if not o or o.get("class") == c.get("class"):
                continue
            up = RANKED.index(c["class"]) < RANKED.index(o["class"])
            rows.append({"item": _label(g["game"], c), "previous": o["class"], "current": c["class"],
                         "reason": f"blended EV {o.get('ev_blend')} -> {c.get('ev_blend')}" if c.get("ev_blend") is not None else "price unavailable",
                         "action": ("added" if o["class"] == "none" else "upgraded") if up else
                                   ("removed -- edge gone" if c["class"] == "none" else "downgraded")})
        for side in ("home", "away"):
            was = {r["name"]: r["status"] for r in (p.get("injuries") or {}).get(side, [])}
            now = {r["name"]: r["status"] for r in (g.get("injuries") or {}).get(side, [])}
            team = g[side]
            for name in sorted(set(was) | set(now)):
                a, b = was.get(name), now.get(name)
                if a != b:
                    rows.append({"item": f"{name} ({team})", "previous": a or "no designation", "current": b or "designation cleared",
                                 "reason": "injury status update (Sleeper/DraftKings)", "action": "personnel re-check"})
        if len(rows) == before:
            unchanged.append(g["game"])
    # shootout ranking moves (by modeled probability of 50+)
    rank = lambda gs: {g["game"]: i for i, g in enumerate(sorted(gs, key=lambda g: -g["model"]["p_shootout"]), 1)}
    rc, rp = rank(cur.get("games") or []), rank(prev.get("games") or [])
    for game, r in rc.items():
        if game in rp and abs(rp[game] - r) >= 3 and min(r, rp[game]) <= 5:
            rows.append({"item": f"{game} shootout rank", "previous": f"#{rp[game]}", "current": f"#{r}",
                         "reason": "modeled 50+ point probability changed", "action": "environment re-ranked"})
    # ownership shifts among the chalk
    po = {c["name"]: c.get("own") for c in (prev.get("dfs") or {}).get("chalk") or []}
    for c in (cur.get("dfs") or {}).get("chalk") or []:
        a, b = po.get(c["name"]), c.get("own")
        if a is not None and b is not None and abs(b - a) >= 3:
            rows.append({"item": f"{c['name']} projected ownership", "previous": f"{a:g}%", "current": f"{b:g}%",
                         "reason": "ownership model update", "action": "re-check leverage"})
    return {"first_report": False, "since": prev.get("meta", {}).get("generated_et") or prev.get("_created_at"),
            "rows": rows, "unchanged": unchanged,
            "note": None if rows else "No material change since the last report."}


# ------------------------------------------------------------------ backtest
async def backtest(season: int, week: int, weeks_back: int = 4) -> dict:
    """The model as of each recent finished week vs the closing consensus line and the result."""
    from app import breakdown, trenches

    rows = []
    for w in range(max(2, week - weeks_back), week):
        try:
            wb = await breakdown.build_week_breakdown(season, w)
            prof = await trenches.week_profiles(season, w)
        except Exception as exc:
            log.warning("backtest week %d failed: %s", w, exc)
            continue
        lp, lpl = dossier_module.league_baselines(wb)
        for gb in wb.games:
            ctx = gb.game.context
            hp, ap = (prof.get("teams") or {}).get(gb.game.home), (prof.get("teams") or {}).get(gb.game.away)
            if not (ctx and ctx.is_final and ctx.home_spread is not None and ctx.total_line is not None and hp and ap):
                continue
            m = dossier_module.model_game(gb, hp, ap, prof.get("league") or {}, lp, lpl)
            margin = ctx.home_score - ctx.away_score
            total = ctx.home_score + ctx.away_score
            rows.append({"week": w, "game": f"{gb.game.away}@{gb.game.home}", "margin": margin, "total": total,
                         "close_spread": ctx.home_spread, "close_total": ctx.total_line,
                         "fair_spread": m["fair_home_spread"], "fair_total": m["fair_total"]})
    return summarize_backtest(rows)


def _record(picks: list[tuple[float, float]]) -> dict:
    """picks: (side result vs line, ...) -> W-L-P where result > 0 wins."""
    w = sum(1 for r in picks if r > 0)
    l = sum(1 for r in picks if r < 0)
    p = sum(1 for r in picks if r == 0)
    return {"w": w, "l": l, "p": p, "n": w + l + p, "win_pct": round(w / (w + l), 3) if w + l else None}


def summarize_backtest(rows: list[dict]) -> dict:
    if not rows:
        return {"games": 0, "note": "No finished games with closing lines to test yet."}
    n = len(rows)
    mae = lambda xs: round(sum(abs(x) for x in xs) / len(xs), 2)
    out = {
        "games": n, "weeks": sorted({r["week"] for r in rows}),
        "spread_mae_model": mae([r["margin"] + r["fair_spread"] for r in rows]),
        "spread_mae_market": mae([r["margin"] + r["close_spread"] for r in rows]),
        "total_mae_model": mae([r["total"] - r["fair_total"] for r in rows]),
        "total_mae_market": mae([r["total"] - r["close_total"] for r in rows]),
    }
    for th in (1.5, 3.0):
        ats, ou = [], []
        for r in rows:
            gap = r["close_spread"] - r["fair_spread"]      # + = model likes home at the close
            if abs(gap) >= th:
                res = r["margin"] + r["close_spread"]       # home result vs line
                ats.append(res if gap > 0 else -res)
            tg = r["fair_total"] - r["close_total"]
            if abs(tg) >= th + 0.5:
                res = r["total"] - r["close_total"]
                ou.append(res if tg > 0 else -res)
        out[f"ats_gap_{th:g}"] = _record(ats)
        out[f"totals_gap_{th + 0.5:g}"] = _record(ou)
    out["note"] = ("Model built only from data available before each week, scored against the nflverse consensus closing line "
                   f"and final scores ({n} games). Small samples: a record over a few weeks is mostly noise.")
    return out


# ------------------------------------------------------------------ graded calls
def graded(season: int, week: int, finals: dict[str, dict]) -> dict:
    """Strongest / price-sensitive calls from the last stored report before each finished game kicked off."""
    calls = []
    for w in range(max(1, week - 4), week + 1):
        reports = store.previous_dossiers(season, w, limit=40)
        latest_before: dict[str, tuple[dict, dict]] = {}
        for d in reports:                      # newest first
            for g in d.get("games") or []:
                if g["game"] in latest_before or g["game"] not in finals.get(w, {}):
                    continue
                if (d.get("meta") or {}).get("generated_at", "") < g["kickoff_utc"]:
                    latest_before[g["game"]] = (d, g)
        try:
            dk_hist = store.odds_history(season, w)
        except Exception:
            dk_hist = []
        for game, (d, g) in latest_before.items():
            fin = finals[w][game]
            for c in g.get("candidates") or []:
                if c.get("class") not in ("strongest", "price_sensitive"):
                    continue
                res = _result(c, fin)
                close = _closing(dk_hist, game, c["market"], c["side"], g["kickoff_utc"])
                # Closing-line value in points, from the bettor's side: more points on a spread or an
                # under, fewer on an over, than the last pre-kickoff DraftKings number.
                clv = None
                if close is not None:
                    clv = round(close - c["line"], 1) if c["side"] == "over" else round(c["line"] - close, 1)
                calls.append({"week": w, "game": game, "market": c["market"], "side": c["side"], "line": c["line"],
                              "price": c.get("price"), "class": c["class"], "result": res, "closing_line": close, "clv_points": clv,
                              "report_at": (d.get("meta") or {}).get("generated_et")})
    rec = _record([1 if c["result"] == "win" else -1 if c["result"] == "loss" else 0 for c in calls])
    clvs = [c["clv_points"] for c in calls if c["clv_points"] is not None]
    return {"calls": calls[-20:], "record": rec,
            "avg_clv_points": round(sum(clvs) / len(clvs), 2) if clvs else None,
            "note": None if calls else "No graded calls yet: the desk's first reports are still pending results."}


def _result(c: dict, fin: dict) -> str:
    h, a = fin["home_score"], fin["away_score"]
    line = c["line"]
    if c["market"] == "spread":
        r = (h - a) + line if c["side"] == "home" else (a - h) + line
    else:
        x = h + a if c["market"] == "total" else h if c["market"] == "team_total_home" else a
        r = (x - line) if c["side"] == "over" else (line - x)
    return "win" if r > 0 else "loss" if r < 0 else "push"


def _closing(hist: list[dict], game: str, market: str, side: str, kickoff: str) -> float | None:
    last = None
    for r in hist:
        if r["game"] == game and r["market"] == market and r["side"] == side and r["captured_at"] < kickoff:
            last = r["line"]
    return last


async def finals_by_week(season: int, week: int) -> dict[int, dict]:
    from app.slates import list_slates
    out: dict[int, dict] = {}
    for w in range(max(1, week - 4), week + 1):
        try:
            schedule, _ = await list_slates(season, w)
        except Exception:
            continue
        for g in schedule.games + schedule.isolated_games:
            c = g.context
            if c and c.is_final and c.home_score is not None:
                out.setdefault(w, {})[f"{g.away}@{g.home}"] = {"home_score": c.home_score, "away_score": c.away_score}
    return out
