"""DFS Model: the weekly projection and lineup analysis for a Classic slate.

Order of operations (each step visible in the output):

1. Consensus. Every source's stat line (app.sources) scored with DraftKings
   rules, combined by app.consensus: mean, median, low/high, SD, source count,
   and which sources are missing the player. Equal weight unless graded
   history shows a real accuracy gap (it doesn't, at any position, in 2025-26:
   every source is within ~3% of the others).
2. Final projection = consensus, then only these adjustments:
     sourced   DraftKings injury status: OUT / Doubtful / IR -> 0 and out of
               the pool; Questionable -> kept, uncertainty raised.
     model     the backtested matchup nudge (app.projections): +-5% max, from
               how the opponent's defense has done vs projections this season.
   Game environment, workload and news are already in the sources' lines; a
   second pass on top double counts (stronger adjustments made the 2025
   backtest worse), so they're shown as context, not multiplied in.
3. Floor / Median / Ceiling. Floor and Median are the 15th and 50th
   percentiles of actual-vs-consensus outcomes by position and projection
   range (scripts/source_accuracy.py, 2025 W4-17 + 2026). Ceiling blends the
   same 85th percentile with the app's matchup Ceiling (app.ceiling).
4. Value = Final / (salary / $1,000).
5. Ownership: the Bayesian ownership engine (app.ownership_report /
   app.ownership_model) -- a Beta posterior per player and contest type from
   a behavioral prior, pasted ownership sources, crowd submissions and news,
   with credible intervals and a labeled confidence. The DFS strategy uses
   the large-field GPP posterior mean as each player's ownership.
6. Uncertainty from source disagreement, source count, injury status and
   the position's outcome spread.
7. Strategy and lineups: app.dfs_strategy -- the Cash/GPP lineup-construction
   framework (slate overview, position pools, chalk and leverage, stacks,
   1 recommended + 4 alternate cash lineups, 10 GPP constructions, 5
   contrarian lineups, each audited and scored).

Everything recomputes on each request from cached data (sources refresh
every 2 hours, DraftKings salaries/injuries every 5 minutes), so late news
flows through on the next load.
"""
from __future__ import annotations

import asyncio
import os
import statistics
import time
from datetime import datetime, timezone

from app import breakdown as breakdown_module
from app import consensus, dfs_strategy, ownership_report, projections, sources, usage
from app import slates as slates_module
from app.cache import _cache_path
from app.sleeper_client import get_nfl_state

POSITIONS = ("QB", "RB", "WR", "TE", "DST")
PLAYABLE = {"Healthy", "Q"}
MIN_SKILL_PROJ = 3.0
POP_TIER_SIZE = {"QB": 2, "RB": 3, "WR": 4, "TE": 2, "DST": 2}
STATUS_LABEL = {"O": "OUT", "D": "Doubtful", "Q": "Questionable", "IR": "on IR"}
DEFAULT_CALIB = {"q15": 0.4, "q50": 0.85, "q85": 1.6}


# ------------------------------------------------------------------ helpers
def _bucket(proj: float) -> str:
    for lo, hi in ((0, 8), (8, 12), (12, 16), (16, 20), (20, 99)):
        if lo <= proj < hi:
            return f"{lo}-{hi}"
    return "20-99"


def calibration(accuracy: dict, position: str, proj: float) -> dict:
    """actual/consensus quantiles for this position and projection range; the
    nearest graded range when this one has too few games."""
    table = (accuracy.get("calibration") or {}).get(position) or {}
    if not table:
        return DEFAULT_CALIB
    want = _bucket(proj)
    if want in table:
        return table[want]
    lo = int(want.split("-")[0])
    return table[min(table, key=lambda b: abs(int(b.split("-")[0]) - lo))]



def _fetched_at(source: str, season: int, week: int) -> str | None:
    path = _cache_path(f"proj_source_{source}_{season}_{week}")
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat(timespec="minutes")
    except OSError:
        return None


async def _is_current(season: int, week: int) -> bool:
    try:
        state = await get_nfl_state()
        return int(state.get("season") or season) == season and int(state.get("week") or week) <= week
    except Exception:
        return True


def _pct_rank(values: list[float], v: float) -> float:
    """0..1, 1 = highest."""
    if len(values) <= 1:
        return 1.0
    return sum(1 for x in values if x < v) / (len(values) - 1)


# -------------------------------------------------------------- per player
def _player_rows(players, indexes, accuracy, weights, vs_expectation, game_of=None):
    game_of = game_of or {}
    rows = []
    for p in players:
        if p.position not in POSITIONS or p.roster_slot == "CPT":
            continue
        pos = p.position
        w, w_note = weights[pos]
        c = consensus.consensus_for(indexes, p.name, p.team, pos, w, w_note)
        base = c.weighted if c.weighted is not None and "weighted" in w_note else c.mean
        adjustments: list[dict] = []
        final = None
        if p.injury not in PLAYABLE:
            final = 0.0
            adjustments.append({"kind": "sourced", "text": f"DraftKings lists him {STATUS_LABEL.get(p.injury, p.injury)}: projected 0, out of the pool"})
        elif base is not None:
            final = base
            if pos in projections.SKILL:
                record = vs_expectation.get(f"{p.opponent}|{pos}")
                m = projections.matchup_adjustment(record)
                if record and m != 1.0:
                    actual, projected, games = record
                    adjustments.append({"kind": "model", "factor": m, "text": (
                        f"Matchup: {pos}s vs {p.opponent} have scored {actual / projected - 1:+.0%} vs projections "
                        f"this season ({games} game{'s' if games != 1 else ''}) -> x{m:.2f}")})
                    final = base * m
            if p.injury == "Q":
                adjustments.append({"kind": "sourced", "text": "Questionable (DraftKings): kept, uncertainty raised -- sources may assume he plays"})
            final = round(final, 2)

        cal = calibration(accuracy, pos, final or 0.0)
        floor = median = ceil = None
        if final:
            floor = round(final * cal["q15"], 1)
            median = round(final * cal["q50"], 1)
            proj_ceiling = final * cal["q85"]
            ceil = round((proj_ceiling + p.ceiling) / 2 if p.ceiling else proj_ceiling, 1)
            ceil = max(ceil, round(final, 1))

        unc_reasons: list[str] = []
        unc = None
        if final:
            cv = (c.sd / c.mean) if (c.sd is not None and c.mean) else None
            width = (cal["q85"] - cal["q15"]) / max(cal["q50"], 0.1)
            unc = (cv if cv is not None else 0.30) + 0.25 * width
            if c.n >= 2 and c.low is not None:
                unc_reasons.append(f"Sources range {c.low:.1f}-{c.high:.1f} (SD {c.sd:.1f})")
            if c.n <= 2:
                unc += 0.10
                unc_reasons.append(f"Only {c.n} source{'s' if c.n != 1 else ''} project him")
            if p.injury == "Q":
                unc += 0.25
                unc_reasons.append("Questionable")
            unc = round(unc, 3)

        rows.append({
            "id": p.dk_draftable_id, "name": p.name, "position": pos, "team": p.team, "opponent": p.opponent,
            "salary": p.salary, "game": game_of.get(p.team, p.game_info), "injury": p.injury or "Healthy", "dk_fppg": p.dk_fppg,
            "consensus": c.mean, "weighted": c.weighted, "median_src": c.median, "low": c.low, "high": c.high,
            "sd": c.sd, "n_sources": c.n, "by_source": c.by_source, "missing": c.missing,
            "final": final, "adjustments": adjustments, "floor": floor, "median": median, "ceiling": ceil,
            "app_ceiling": p.ceiling, "value": round(final / (p.salary / 1000), 2) if final and p.salary else None,
            "ownership": None, "uncertainty": unc, "uncertainty_reasons": unc_reasons, "line": c.line,
        })
    return rows


def _eligible(r: dict) -> bool:
    if r["injury"] not in PLAYABLE or not r["final"] or r["salary"] <= 0:
        return False
    return r["position"] == "DST" or r["final"] >= MIN_SKILL_PROJ


def _label_uncertainty(pool: list[dict]) -> None:
    vals = sorted(r["uncertainty"] for r in pool)
    if not vals:
        return
    lo, hi = vals[len(vals) // 3], vals[2 * len(vals) // 3]
    for r in pool:
        u = r["uncertainty"]
        r["uncertainty_label"] = "High" if u > hi else ("Low" if u <= lo else "Medium")


def _popularity(pool: list[dict]) -> None:
    """Chalk tier from the Bayesian posterior ownership (percent)."""
    for pos in POSITIONS:
        group = [r for r in pool if r["position"] == pos]
        values = [r["value"] for r in group]
        finals = [r["final"] for r in group]
        for r in group:
            r["pop_score"] = r["ownership"] if r["ownership"] is not None else \
                0.6 * _pct_rank(values, r["value"]) + 0.4 * _pct_rank(finals, r["final"])
            o = r["ownership"] or 0
            r["popularity"] = "High" if o >= 15 else ("Medium" if o >= 7 else "Low")
            r["popularity_source"] = "Bayesian posterior"


def _card(r: dict, reason: str) -> dict:
    keys = ("id", "name", "position", "team", "opponent", "salary", "final", "consensus", "floor", "ceiling",
            "value", "ownership", "popularity", "popularity_source", "uncertainty_label", "injury", "n_sources")
    return {**{k: r.get(k) for k in keys}, "reason": reason}


# ------------------------------------------------------------------ sections
def _pos_median(pool, pos, key):
    xs = [r[key] for r in pool if r["position"] == pos and r[key] is not None]
    return statistics.median(xs) if xs else None


def top_plays(pool: list[dict], n: int = 10) -> list[dict]:
    out = []
    for r in pool:
        med = _pos_median(pool, r["position"], "value") or 1
        r["core_score"] = r["final"] * (r["value"] / med) ** 0.5
    for r in sorted(pool, key=lambda r: -r["core_score"])[:n]:
        med = _pos_median(pool, r["position"], "value")
        out.append(_card(r, f"{r['final']:.1f} proj at {r['value']:.2f} pts/$1k ({r['position']} median {med:.2f}); "
                            f"{r['n_sources']} sources"))
    return out


def _relative_value(pool: list[dict], cands: list[dict], n: int, per_position: int, fmt) -> list[dict]:
    """Best value vs the position's median value (QBs always score more per
    dollar, so raw pts/$1k would list only QBs), at most per_position each."""
    med = {pos: _pos_median(pool, pos, "value") or 1 for pos in POSITIONS}
    out, count = [], {}
    for r in sorted(cands, key=lambda r: -r["value"] / med[r["position"]]):
        if count.get(r["position"], 0) >= per_position:
            continue
        count[r["position"]] = count.get(r["position"], 0) + 1
        out.append(_card(r, fmt(r, med[r["position"]])))
        if len(out) >= n:
            break
    return out


def best_values(pool: list[dict], n: int = 10) -> list[dict]:
    cands = [r for r in pool if r["final"] >= (5 if r["position"] == "DST" else 8)]
    return _relative_value(pool, cands, n, 3, lambda r, m: (
        f"{r['value']:.2f} pts per $1k ({r['value'] / m - 1:+.0%} vs {r['position']} median); Final {r['final']:.1f} at ${r['salary']:,}"))


def highest_ceilings(pool: list[dict], n: int = 10) -> list[dict]:
    return [_card(r, f"Ceiling {r['ceiling']:.1f} ({r['ceiling'] / (r['salary'] / 1000):.1f}x salary); Final {r['final']:.1f}")
            for r in sorted(pool, key=lambda r: -r["ceiling"])[:n]]






def most_uncertain(pool: list[dict], n: int = 10) -> list[dict]:
    cands = [r for r in pool if r["final"] >= 8]
    return [_card(r, "; ".join(r["uncertainty_reasons"]) or "Wide outcome range at the position")
            for r in sorted(cands, key=lambda r: -r["uncertainty"])[:n]]







# ----------------------------------------------------------------------- news
def news_changes(rows: list[dict], n: int = 5) -> list[dict]:
    items = []
    by_team = {}
    for r in rows:
        by_team.setdefault(r["team"], []).append(r)
    for r in rows:
        if r["injury"] == "Healthy" or r["position"] == "DST" or not r["dk_fppg"] or r["dk_fppg"] < 8:
            continue
        if r["injury"] == "Q":
            impact = r["dk_fppg"] * 0.5
            text = f"{r['name']} ({r['team']} {r['position']}) is Questionable; consensus {r['consensus'] or 0:.1f} assumes he plays"
        else:
            impact = r["dk_fppg"]
            text = f"{r['name']} ({r['team']} {r['position']}) is {STATUS_LABEL.get(r['injury'], r['injury'])} -- {r['dk_fppg']:.1f} DK pts/game this season off the board"
            still = [s for s, v in (r["by_source"] or {}).items() if v and v >= MIN_SKILL_PROJ]
            if still:
                text += f"; {', '.join(sources.SOURCES[s] for s in still)} still project him (may predate the news)"
            gainers = [m for m in by_team.get(r["team"], []) if m is not r and m["final"] and m["dk_fppg"]
                       and m["position"] in ("RB", "WR", "TE") and m["final"] - m["dk_fppg"] >= 2]
            gainers.sort(key=lambda m: -(m["final"] - m["dk_fppg"]))
            if gainers:
                text += "; teammates projected above their season average: " + ", ".join(f"{m['name']} {m['final']:.1f} (season {m['dk_fppg']:.1f})" for m in gainers[:2])
        items.append({"impact": round(impact, 1), "kind": "sourced", "source": "DraftKings injury status", "text": text})
    for r in rows:
        for adj in r["adjustments"]:
            if adj["kind"] == "model" and r["final"]:
                delta = r["final"] - (r["consensus"] or 0)
                if abs(delta) >= 0.5:
                    items.append({"impact": round(abs(delta), 1), "kind": "model", "source": "Model matchup adjustment",
                                  "text": f"{r['name']} ({r['team']} {r['position']}) {delta:+.1f}: {adj['text']}"})
    items.sort(key=lambda x: -x["impact"])
    return items[:n]


# ---------------------------------------------------------------------- main
_STATE: dict[tuple, dict] = {}   # latest ownership state per (season, week, slate, contest), for user-lineup duplication


async def _showdown_players(season: int, week: int, slate_list: list, ctx: dict) -> list[tuple]:
    """(slate, players) for this week's Showdown slates, for the Showdown ownership column."""
    out = []
    implied = {t: c.get("implied") for t, c in ctx.items()}
    for s in slate_list:
        if s.slate_type != "showdown" or not s.available:
            continue
        try:
            sp = await slates_module.get_slate_players(season, week, s.slate_id)
        except Exception:
            continue
        for g in s.games:
            c = g.context
            if c:
                implied.setdefault(g.away, c.away_implied_total)
                implied.setdefault(g.home, c.home_implied_total)
        out.append((s, ownership_report.showdown_players(sp.players, implied)))
    return out


async def build(season: int, week: int, slate_id: str | None = None, contest: str = "gpp",
                contest_size: int | None = None) -> dict:
    t0 = time.time()
    _schedule, slate_list = await slates_module.list_slates(season, week)
    classic = [s for s in slate_list if s.slate_type == "classic" and s.available]
    if not classic:
        return {"available": False, "reason": "No DraftKings Classic slate with salaries for this week yet.",
                "slates": [], "season": season, "week": week}
    slate = next((s for s in classic if s.slate_id == slate_id), classic[0])
    current = await _is_current(season, week)

    sp, src_rows, proj_ctx, wd, profiles = await asyncio.gather(
        slates_module.get_slate_players(season, week, slate.slate_id),
        sources.get_all(season, week, current=current),
        projections.build_context(season, week),
        breakdown_module.load_week(season, week),
        usage.usage_profiles(season, week),
        return_exceptions=True,
    )
    if isinstance(sp, Exception):
        raise sp
    if isinstance(src_rows, Exception):
        src_rows = {}
    vs_exp = proj_ctx.vs_expectation if not isinstance(proj_ctx, Exception) else {}
    wd = None if isinstance(wd, Exception) else wd
    profiles = {"players": {}, "teams": {}} if isinstance(profiles, Exception) else profiles

    indexes = {s: consensus.index_rows(rows) for s, rows in src_rows.items() if rows}
    accuracy = consensus.load_accuracy()
    weights = {pos: consensus.position_weights(accuracy, pos, list(indexes)) for pos in POSITIONS}

    game_of = {t: f"{g.away}@{g.home}" for g in slate.games for t in (g.away, g.home)}
    rows = _player_rows(sp.players, indexes, accuracy, weights, vs_exp, game_of)
    ctx = dfs_strategy.team_context(slate)
    for r in rows:
        r["implied"] = (ctx.get(r["team"]) or {}).get("implied")
    showdowns = await _showdown_players(season, week, slate_list, ctx)
    own_state = ownership_report.compute(season, week, slate, rows, contest=contest, showdowns=showdowns)
    gpp_own = ownership_report.own_pct_by_id(own_state, "gpp")
    pool = [r for r in rows if _eligible(r)]
    for r in rows:
        r["ownership"] = gpp_own.get(r["id"])
    _label_uncertainty(pool)
    _popularity(pool)

    strategy = dfs_strategy.run(pool, rows, slate, wd, profiles, True, season, week)
    lineup_ids = {lu["label"]: [p["id"] for p in lu["players"]]
                  for grp in ("cash", "gpp", "contrarian") for lu in strategy["lineups"][grp]}
    tournament_ids = {k: v for k, v in lineup_ids.items() if not k.startswith(("Recommended", "Cash"))}
    own_report = ownership_report.report(own_state, contest=contest, contest_size=contest_size,
                                         model_lineups=lineup_ids, exposure_lineups=list(tournament_ids.values()))
    _STATE[(season, week, slate.slate_id, contest)] = own_state

    slate_teams = {t for g in slate.games for t in (g.away, g.home)}
    source_meta = []
    for key, label in sources.SOURCES.items():
        rows_s = src_rows.get(key) or []
        covered = sum(1 for r in rows if r["by_source"].get(key) is not None)
        source_meta.append({"key": key, "label": label, "players_listed": len([x for x in rows_s if x["team"] in slate_teams]),
                            "matched_on_slate": covered, "fetched_at": _fetched_at(key, season, week),
                            "available": bool(rows_s)})

    table = sorted([r for r in rows if r["final"] is not None and (r["final"] > 0 or r["injury"] not in PLAYABLE and r["consensus"])],
                   key=lambda r: -(r["final"] or 0))
    for r in table:
        r.setdefault("popularity", None)
        r.setdefault("uncertainty_label", None)
    no_source = sorted(r["name"] for r in rows if r["n_sources"] == 0 and r["injury"] in PLAYABLE and (r["dk_fppg"] or 0) >= 5)

    return {
        "available": True,
        "season": season, "week": week,
        "slate": {"slate_id": slate.slate_id, "label": slate.label, "games": len(slate.games)},
        "slates": [{"slate_id": s.slate_id, "label": s.label} for s in classic],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": source_meta,
        "unavailable_sources": [{"label": k, "reason": v} for k, v in sources.UNAVAILABLE.items()],
        "weighting": {pos: note for pos, (_w, note) in weights.items()},
        "accuracy": {"consensus": accuracy.get("consensus"), "relative_mae": accuracy.get("relative_mae"),
                     "weeks": accuracy.get("weeks"), "generated_at": accuracy.get("generated_at")},
        "ownership": {"provided": True, "matched": len(gpp_own),
                      "note": "Bayesian posterior ownership (large-field GPP): behavioral prior + pasted sources + crowd "
                              "+ news. See the Ownership tab for intervals and confidence."},
        "ownership_model": own_report,
        "summary": {
            "top_projections": [_card(r, f"Consensus {r['consensus']:.1f} from {r['n_sources']} sources")
                                for r in sorted(pool, key=lambda r: -r["final"])[:10]],
            "best_values": best_values(pool),
            "highest_ceilings": highest_ceilings(pool),
            "leverage": strategy["leverage"]["ownership"][:10],
            "stacks": strategy["stacks"][:5],
            "most_uncertain": most_uncertain(pool),
            "news": news_changes(rows),
            "constructions": strategy["lineups"]["constructions"],
        },
        "top_plays": top_plays(pool),
        "strategy": {k: v for k, v in strategy.items() if k != "lineups"},
        "table": [{k: r.get(k) for k in (
            "id", "name", "position", "team", "opponent", "salary", "injury", "consensus", "median_src", "low", "high", "sd",
            "n_sources", "by_source", "missing", "final", "adjustments", "floor", "median", "ceiling", "app_ceiling", "value",
            "ownership", "popularity", "uncertainty", "uncertainty_label", "uncertainty_reasons")} for r in table],
        "no_source_players": no_source,
        "lineups": strategy["lineups"],
        "elapsed_s": round(time.time() - t0, 2),
    }
