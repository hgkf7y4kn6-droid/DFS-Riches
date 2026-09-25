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
5. Ownership. No projected-ownership source is connected, so ownership is
   "not available" unless the user pastes numbers (sourced "User-provided").
   Without it, chalk/leverage use a clearly labeled popularity *estimate*
   (value + projection rank at the position) -- a tier, never a percentage.
6. Uncertainty from source disagreement, source count, injury status and
   the position's outcome spread.
7. Player pool, stacks, game environments, and lineups: 5 high-floor, 10 GPP
   (5 constructions x 2), 5 contrarian GPP. Lineup objectives count a
   Questionable player at 90% (the risk he sits) without changing his
   projection; any player is capped at 6 of the 10 GPP lineups and 8 of the
   15 tournament lineups.

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
from app import consensus, lineup_builder, projections, sources
from app import slates as slates_module
from app.cache import _cache_path
from app.matching import normalize_name, resolve_alias
from app.sleeper_client import get_nfl_state

POSITIONS = ("QB", "RB", "WR", "TE", "DST")
PLAYABLE = {"Healthy", "Q"}
MIN_SKILL_PROJ = 3.0
POP_TIER_SIZE = {"QB": 2, "RB": 3, "WR": 4, "TE": 2, "DST": 2}
POP_PENALTY = {"High": 0.30, "Medium": 0.12, "Low": 0.0}
SAVER_MAX_SALARY = {"QB": 5200, "RB": 4800, "WR": 4200, "TE": 3600, "DST": 2800}
GPP_EXPOSURE_CAP = 6          # of 10 GPP lineups
TOURNAMENT_EXPOSURE_CAP = 8   # of all 15 GPP + contrarian lineups
Q_LINEUP_DISCOUNT = 0.90      # a Questionable player's value in lineup objectives (risk he sits)
STATUS_LABEL = {"O": "OUT", "D": "Doubtful", "Q": "Questionable", "IR": "on IR"}
STACK_TARGET_X = 3.5          # a stack's ceiling is judged against 3.5x its salary (in $1k)
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


def own_key(name: str, team: str, position: str) -> str:
    return f"DST|{team}" if position == "DST" else resolve_alias(normalize_name(name))


def parse_ownership(text: str | None) -> dict[str, float]:
    """Pasted ownership, one player per line: "Name, 23.5" or "Name, TEAM, 23.5"
    (tabs work too; a trailing % is fine; DSTs by team code, e.g. "BUF, 8")."""
    out: dict[str, float] = {}
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.replace("\t", ",").split(",") if p.strip()]
        if len(parts) < 2:
            continue
        try:
            pct = float(parts[-1].rstrip("%"))
        except ValueError:
            continue
        name = parts[0]
        if len(name) <= 3 and name.isupper():
            out[f"DST|{sources.team_code(name)}"] = pct
        else:
            out[resolve_alias(normalize_name(name))] = pct
    return out


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
def _player_rows(players, indexes, accuracy, weights, vs_expectation, ownership, game_of=None):
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

        own = ownership.get(own_key(p.name, p.team, pos)) if ownership else None
        rows.append({
            "id": p.dk_draftable_id, "name": p.name, "position": pos, "team": p.team, "opponent": p.opponent,
            "salary": p.salary, "game": game_of.get(p.team, p.game_info), "injury": p.injury or "Healthy", "dk_fppg": p.dk_fppg,
            "consensus": c.mean, "weighted": c.weighted, "median_src": c.median, "low": c.low, "high": c.high,
            "sd": c.sd, "n_sources": c.n, "by_source": c.by_source, "missing": c.missing,
            "final": final, "adjustments": adjustments, "floor": floor, "median": median, "ceiling": ceil,
            "app_ceiling": p.ceiling, "value": round(final / (p.salary / 1000), 2) if final and p.salary else None,
            "ownership": own, "uncertainty": unc, "uncertainty_reasons": unc_reasons,
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


def _popularity(pool: list[dict], has_ownership: bool) -> None:
    """Chalk tier per player: from real ownership when pasted, else a labeled estimate."""
    for pos in POSITIONS:
        group = [r for r in pool if r["position"] == pos]
        values = [r["value"] for r in group]
        finals = [r["final"] for r in group]
        for r in group:
            r["pop_score"] = 0.6 * _pct_rank(values, r["value"]) + 0.4 * _pct_rank(finals, r["final"])
        ranked = sorted(group, key=lambda r: -r["pop_score"])
        n = POP_TIER_SIZE[pos]
        for i, r in enumerate(ranked):
            if has_ownership and r["ownership"] is not None:
                o = r["ownership"]
                r["popularity"] = "High" if o >= 20 else ("Medium" if o >= 8 else "Low")
                r["popularity_source"] = "user-provided ownership"
            else:
                r["popularity"] = "High" if i < n else ("Medium" if i < 2 * n else "Low")
                r["popularity_source"] = "estimate"


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


def leverage_plays(pool: list[dict], n: int = 10) -> list[dict]:
    cands = []
    for r in pool:
        if r["popularity"] == "High":
            continue
        group = [x["ceiling"] for x in pool if x["position"] == r["position"]]
        r["ceiling_pct"] = _pct_rank(group, r["ceiling"])
        if r["ceiling_pct"] >= 0.6:
            cands.append(r)
    cands.sort(key=lambda r: -(r["ceiling_pct"] - (0.5 if r["popularity"] == "Medium" else 0.0) * 0.3
                               + r["ceiling"] / max(r["final"], 1) * 0.1))
    out = []
    for r in cands[:n]:
        pop = (f"{r['ownership']:.0f}% owned (user-provided)" if r["ownership"] is not None
               else f"{r['popularity'].lower()} expected popularity (estimate)")
        rank = 1 + sum(1 for x in pool if x["position"] == r["position"] and x["ceiling"] > r["ceiling"])
        out.append(_card(r, f"#{rank} {r['position']} ceiling ({r['ceiling']:.1f}) with {pop}"))
    return out


def chalk(pool: list[dict], n: int = 10) -> dict:
    high = sorted([r for r in pool if r["popularity"] == "High"], key=lambda r: -r["pop_score"])
    good, over = [], []
    for r in high:
        med_v = _pos_median(high, r["position"], "value") or r["value"]
        risky = r.get("uncertainty_label") == "High" or r["injury"] == "Q" or r["value"] < med_v * 0.9
        why = []
        if r.get("uncertainty_label") == "High":
            why.append("high uncertainty")
        if r["injury"] == "Q":
            why.append("questionable")
        if r["value"] < med_v * 0.9:
            why.append(f"value {r['value']:.2f} trails the other chalk at {r['position']}")
        (over if risky else good).append(_card(r, ("Likely over-owned: " + ", ".join(why)) if risky
                                               else f"Popular for a reason: {r['value']:.2f} pts/$1k, {r['final']:.1f} proj"))
    return {"eat": good[:n], "over_owned": over[:n]}


def salary_savers(pool: list[dict], n: int = 10) -> list[dict]:
    cands = [r for r in pool if r["salary"] <= SAVER_MAX_SALARY[r["position"]]
             and r["final"] >= (4 if r["position"] == "DST" else 6)]
    return _relative_value(pool, cands, n, 3, lambda r, m: (
        f"${r['salary']:,} for {r['final']:.1f} proj ({r['value']:.2f}/$1k), ceiling {r['ceiling']:.1f}"))


def fades(pool: list[dict], rows: list[dict], n: int = 10) -> list[dict]:
    out = []
    for r in pool:
        why = []
        if r["injury"] == "Q" and r["salary"] >= 5000:
            why.append("questionable at a real salary")
        if r["n_sources"] >= 3 and r["sd"] and r["consensus"] and r["sd"] / r["consensus"] >= 0.25:
            why.append(f"sources disagree ({r['low']:.1f}-{r['high']:.1f})")
        pricey = [x for x in pool if x["position"] == r["position"] and x["salary"] >= 6000]
        vals = sorted(x["value"] for x in pricey)
        ceils = sorted((x["ceiling"] for x in pricey), reverse=True)
        top_ceiling = ceils and r["ceiling"] >= ceils[max(0, len(ceils) // 4 - 1)]
        if r["salary"] >= 6500 and vals and r["value"] <= vals[len(vals) // 4] and not top_ceiling:
            why.append(f"bottom-quarter value among $6,000+ {r['position']}s ({r['value']:.2f}/$1k) without a top ceiling")
        if why:
            text = "; ".join(why)
            out.append((r["salary"] * len(why), _card(r, text[0].upper() + text[1:])))
    out.sort(key=lambda x: -x[0])
    return [c for _, c in out[:n]]


def most_uncertain(pool: list[dict], n: int = 10) -> list[dict]:
    cands = [r for r in pool if r["final"] >= 8]
    return [_card(r, "; ".join(r["uncertainty_reasons"]) or "Wide outcome range at the position")
            for r in sorted(cands, key=lambda r: -r["uncertainty"])[:n]]


def game_environments(pool: list[dict], slate, wd) -> list[dict]:
    out = []
    for g in slate.games:
        ctx = g.context
        players = [r for r in pool if r["team"] in (g.away, g.home)]
        top = sorted(players, key=lambda r: -r["final"])[:10]
        tempo = {t: wd.ranks.get("neutral_secs", {}).get(t) for t in (g.away, g.home)} if wd else {}
        notes = []
        if ctx and ctx.total_line is not None:
            notes.append(f"Total {ctx.total_line:g}")
        if ctx and ctx.away_implied_total is not None:
            notes.append(f"{g.away} {ctx.away_implied_total:g} / {g.home} {ctx.home_implied_total:g} implied")
        fast = [t for t, rk in tempo.items() if rk and rk <= 10]
        if fast:
            notes.append(f"top-10 neutral tempo: {', '.join(fast)}")
        out.append({
            "game": f"{g.away}@{g.home}", "away": g.away, "home": g.home, "kickoff": g.kickoff_et,
            "total": ctx.total_line if ctx else None, "spread_home": ctx.home_spread if ctx else None,
            "away_implied": ctx.away_implied_total if ctx else None, "home_implied": ctx.home_implied_total if ctx else None,
            "top10_final": round(sum(r["final"] for r in top), 1), "top10_ceiling": round(sum(r["ceiling"] for r in top), 1),
            "tempo_ranks": tempo, "notes": notes,
        })
    out.sort(key=lambda e: (-(e["total"] or 0), -e["top10_final"]))
    return out


def build_stacks(pool: list[dict], envs: list[dict]) -> list[dict]:
    env_by_team = {}
    for e in envs:
        env_by_team[e["away"]] = e
        env_by_team[e["home"]] = e
    stacks = []
    for qb in [r for r in pool if r["position"] == "QB"]:
        mates = sorted([r for r in pool if r["team"] == qb["team"] and r["position"] in ("WR", "TE")], key=lambda r: -r["ceiling"])
        opp = sorted([r for r in pool if r["team"] == qb["opponent"] and r["position"] in ("RB", "WR", "TE")], key=lambda r: -r["ceiling"])
        if not mates or not opp:
            continue
        for k in (1, 2):
            if len(mates) < k:
                continue
            members = [qb] + mates[:k] + [opp[0]]
            salary = sum(m["salary"] for m in members)
            ceil = sum(m["ceiling"] for m in members)
            e = env_by_team.get(qb["team"], {})
            implied = e.get("away_implied") if e.get("away") == qb["team"] else e.get("home_implied")
            why = [f"{e.get('game', '')} total {e['total']:g}" if e.get("total") else e.get("game", "")]
            if implied is not None:
                why.append(f"{qb['team']} implied {implied:g}")
            why.append(f"stack ceiling {ceil:.1f} vs {STACK_TARGET_X}x salary target {STACK_TARGET_X * salary / 1000:.1f}")
            stacks.append({
                "game": e.get("game"), "team": qb["team"], "type": f"QB + {k} + 1 bring-back",
                "players": [_card(m, "") for m in members], "salary": salary,
                "final": round(sum(m["final"] for m in members), 1), "ceiling": round(ceil, 1),
                "score": round(ceil - STACK_TARGET_X * salary / 1000, 1), "reason": "; ".join(w for w in why if w),
            })
    stacks.sort(key=lambda s: -s["score"])
    return stacks


# ------------------------------------------------------------------- lineups
def _lineup_out(lineup: list[dict], label: str, construction: str, has_ownership: bool, envs: list[dict]) -> dict:
    qb = lineup[0]
    mates = [p for p in lineup if p["team"] == qb["team"] and p["position"] in ("WR", "TE", "RB") and p is not qb]
    bring = [p for p in lineup if p["team"] == qb["opponent"] and p["position"] in ("RB", "WR", "TE")]
    env = next((e for e in envs if qb["team"] in (e["away"], e["home"])), None)
    if mates:
        why = f"{qb['team']} stack: {qb['name']} + " + ", ".join(m["name"] for m in mates)
        if bring:
            why += f"; bring-back {', '.join(b['name'] for b in bring)}"
        if env and env.get("total"):
            why += f" ({env['game']} total {env['total']:g})"
    else:
        why = f"No stack: {qb['name']} for his own projection"
    own_vals = [p["ownership"] for p in lineup if p["ownership"] is not None]
    return {
        "label": label, "construction": construction,
        "players": [{**_card(p, ""), "slot": slot} for p, slot in zip(lineup, ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"])],
        "salary": sum(p["salary"] for p in lineup),
        "final": round(sum(p["final"] for p in lineup), 1),
        "floor": round(sum(p["floor"] for p in lineup), 1),
        "ceiling": round(sum(p["ceiling"] for p in lineup), 1),
        "ownership": round(sum(own_vals), 1) if has_ownership and len(own_vals) == len(lineup) else None,
        "chalk_count": sum(1 for p in lineup if p["popularity"] == "High"),
        "stack": why,
    }


def _q(r: dict) -> float:
    return Q_LINEUP_DISCOUNT if r["injury"] == "Q" else 1.0


def build_lineups(pool: list[dict], envs: list[dict], stacks: list[dict], has_ownership: bool) -> dict:
    cash, gpp, contrarian, constructions = [], [], [], []
    prior: list[set] = []

    for i in range(5):
        lu = lineup_builder.build(pool, [(r["floor"] + r["final"]) * _q(r) for r in pool], prior=prior, min_unique=2)
        if not lu:
            break
        prior.append({p["id"] for p in lu})
        cash.append(_lineup_out(lu, f"High-floor {i + 1}", "Maximizes Floor + Final projection; no stack required", has_ownership, envs))

    games_by_total = [e["game"] for e in envs if e.get("total")] or [e["game"] for e in envs]
    best_stack_game = next((s["game"] for s in stacks if s["game"] not in games_by_total[:2]), None)
    templates = []
    if games_by_total:
        templates.append(("Top-total game stack", f"QB + 2 pass catchers + 1 bring-back from {games_by_total[0]}, the slate's highest total",
                          dict(stack=(2, 1), stack_game=games_by_total[0])))
    if len(games_by_total) > 1:
        templates.append(("Second-game stack", f"QB + 1 + 1 bring-back from {games_by_total[1]} (2nd-highest total)",
                          dict(stack=(1, 1), stack_game=games_by_total[1])))
    if best_stack_game:
        top = next(s for s in stacks if s["game"] == best_stack_game)
        templates.append(("Best stack outside the top games", f"QB + 2 + 1 from {best_stack_game}: {top['reason']}",
                          dict(stack=(2, 1), stack_game=best_stack_game)))
    templates.append(("RB-heavy", "3 RBs (RB in the FLEX) around a QB + 1 + 1 stack -- pays for volume on the ground",
                      dict(stack=(1, 1), counts={"RB": 3})))
    templates.append(("4-WR onslaught", "4 WRs (WR in the FLEX) with a QB + 2 + 1 stack -- max passing-game correlation",
                      dict(stack=(2, 1), counts={"WR": 4})))

    gpp_prior: list[set] = []
    exposure: dict = {}
    for name, desc, kw in templates[:5]:
        built = 0
        for _ in range(2):
            avail = [r for r in pool if exposure.get(r["id"], 0) < GPP_EXPOSURE_CAP]
            lu = lineup_builder.build(avail, [r["ceiling"] * _q(r) for r in avail], prior=gpp_prior, min_unique=3, **kw)
            if not lu:
                break
            built += 1
            gpp_prior.append({p["id"] for p in lu})
            for p in lu:
                exposure[p["id"]] = exposure.get(p["id"], 0) + 1
            gpp.append(_lineup_out(lu, f"GPP {len(gpp) + 1}", name, has_ownership, envs))
        if built:
            constructions.append({"name": name, "description": desc, "lineups": [lu["label"] for lu in gpp[-built:]]})
    filler = 0
    while len(gpp) < 10:   # a construction that couldn't be built (e.g. no playable QB in that game)
        avail = [r for r in pool if exposure.get(r["id"], 0) < GPP_EXPOSURE_CAP]
        lu = lineup_builder.build(avail, [r["ceiling"] * _q(r) for r in avail], prior=gpp_prior, min_unique=3, stack=(1, 1))
        if not lu:
            break
        filler += 1
        gpp_prior.append({p["id"] for p in lu})
        for p in lu:
            exposure[p["id"]] = exposure.get(p["id"], 0) + 1
        gpp.append(_lineup_out(lu, f"GPP {len(gpp) + 1}", "Best-ceiling stack", has_ownership, envs))
    if filler:
        constructions.append({"name": "Best-ceiling stack", "description": "Any QB + 1 + 1 bring-back, highest total ceiling",
                              "lineups": [lu["label"] for lu in gpp[-filler:]]})

    def contrarian_value(r):
        if has_ownership and r["ownership"] is not None:
            return r["ceiling"] * _q(r) * (1 - min(0.6, r["ownership"] / 100 * 0.8))
        return r["ceiling"] * _q(r) * (1 - POP_PENALTY[r["popularity"]])

    top_games = set(games_by_total[:2])
    c_prior = list(gpp_prior)
    used_qbs: set = set()   # a different QB stack in each contrarian lineup
    for i in range(5):
        c_pool = [r for r in pool if not (r["position"] == "QB" and (r["game"] in top_games or r["id"] in used_qbs))
                  and exposure.get(r["id"], 0) < TOURNAMENT_EXPOSURE_CAP]
        lu = lineup_builder.build(c_pool, [contrarian_value(r) for r in c_pool], prior=c_prior, min_unique=3, stack=(1, 1))
        if not lu:
            break
        c_prior.append({p["id"] for p in lu})
        used_qbs.add(lu[0]["id"])
        for p in lu:
            exposure[p["id"]] = exposure.get(p["id"], 0) + 1
        contrarian.append(_lineup_out(
            lu, f"Contrarian {i + 1}",
            "Ceiling discounted by " + ("ownership (user-provided)" if has_ownership else "estimated popularity")
            + "; a different QB stack each, from outside the two highest-total games", has_ownership, envs))
    return {"high_floor": cash, "gpp": gpp, "contrarian": contrarian, "constructions": constructions}


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
async def build(season: int, week: int, slate_id: str | None = None, ownership_text: str | None = None) -> dict:
    t0 = time.time()
    _schedule, slate_list = await slates_module.list_slates(season, week)
    classic = [s for s in slate_list if s.slate_type == "classic" and s.available]
    if not classic:
        return {"available": False, "reason": "No DraftKings Classic slate with salaries for this week yet.",
                "slates": [], "season": season, "week": week}
    slate = next((s for s in classic if s.slate_id == slate_id), classic[0])
    current = await _is_current(season, week)

    sp, src_rows, proj_ctx, wd = await asyncio.gather(
        slates_module.get_slate_players(season, week, slate.slate_id),
        sources.get_all(season, week, current=current),
        projections.build_context(season, week),
        breakdown_module.load_week(season, week),
        return_exceptions=True,
    )
    if isinstance(sp, Exception):
        raise sp
    if isinstance(src_rows, Exception):
        src_rows = {}
    vs_exp = proj_ctx.vs_expectation if not isinstance(proj_ctx, Exception) else {}
    wd = None if isinstance(wd, Exception) else wd

    indexes = {s: consensus.index_rows(rows) for s, rows in src_rows.items() if rows}
    accuracy = consensus.load_accuracy()
    weights = {pos: consensus.position_weights(accuracy, pos, list(indexes)) for pos in POSITIONS}
    ownership = parse_ownership(ownership_text)
    has_own = bool(ownership)

    game_of = {t: f"{g.away}@{g.home}" for g in slate.games for t in (g.away, g.home)}
    rows = _player_rows(sp.players, indexes, accuracy, weights, vs_exp, ownership, game_of)
    pool = [r for r in rows if _eligible(r)]
    _label_uncertainty(pool)
    _popularity(pool, has_own)
    matched_own = sum(1 for r in pool if r["ownership"] is not None)

    envs = game_environments(pool, slate, wd)
    stacks = build_stacks(pool, envs)
    lineups = build_lineups(pool, envs, stacks, has_own)
    chalk_lists = chalk(pool)

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
        "ownership": {"provided": has_own, "matched": matched_own,
                      "note": ("User-provided ownership" if has_own else
                               "No projected-ownership source is connected. Chalk and leverage use a popularity estimate "
                               "(value + projection rank at the position), shown as a tier, not a percentage.")},
        "summary": {
            "top_projections": [_card(r, f"Consensus {r['consensus']:.1f} from {r['n_sources']} sources")
                                for r in sorted(pool, key=lambda r: -r["final"])[:10]],
            "best_values": best_values(pool),
            "highest_ceilings": highest_ceilings(pool),
            "leverage": leverage_plays(pool),
            "stacks": stacks[:5],
            "most_uncertain": most_uncertain(pool),
            "news": news_changes(rows),
            "constructions": lineups["constructions"],
        },
        "top_plays": top_plays(pool),
        "salary_savers": salary_savers(pool),
        "chalk": chalk_lists,
        "fades": fades(pool, rows),
        "environments": envs,
        "stacks_by_game": {e["game"]: [s for s in stacks if s["game"] == e["game"]][:3] for e in envs},
        "table": [{k: r.get(k) for k in (
            "id", "name", "position", "team", "opponent", "salary", "injury", "consensus", "median_src", "low", "high", "sd",
            "n_sources", "by_source", "missing", "final", "adjustments", "floor", "median", "ceiling", "app_ceiling", "value",
            "ownership", "popularity", "uncertainty", "uncertainty_label", "uncertainty_reasons")} for r in table],
        "no_source_players": no_source,
        "lineups": lineups,
        "elapsed_s": round(time.time() - t0, 2),
    }
