"""Leverage: how much better a player's true, efficiency-adjusted shot at a
big game is than the share of the field that will play him -- borrowed from
business leverage, where the question is how far the funding (ownership)
runs ahead of, or behind, what the underlying asset actually earns.

1. Matchup-Efficiency Multiplier (MEM). Each player's projection is scaled
   by the efficiency of his offense, the vulnerability of the defense he
   faces, and that defense's record against his position:

     MEM = exp(0.05 * off_z + 0.05 * def_z + 0.04 * pos_z), clamped 0.80..1.25

   off_z   his offense's EPA per play in the phases he plays, as a league
           z-score (QB 85% dropback / 15% rush; WR, TE dropback; RB 70% rush
           / 30% dropback). DSTs: minus the opposing offense's EPA per play.
   def_z   the opposing defense's EPA allowed in those same phases (higher
           = softer). DSTs: their own defense's EPA allowed, inverted.
   pos_z   DK points the opposing defense allows to his position beyond what
           its opponents usually score (schedule-adjusted, app.matchups) --
           catches funnel defenses -- shrunk toward 0 by games / (games + 4).

   Why z-scores and not "EPA / league average": league EPA per play sits
   near zero (and goes negative), so that ratio explodes or flips sign. Why
   small coefficients and a clamp: the base projection already prices in
   Vegas totals and some matchup, so efficiency nudges rather than replaces
   it. EPA rates come blended with last season (app.trenches), which keeps
   three-game samples from swinging the multiplier.

2. True Efficiency-Adjusted Projection (TEAP) = projection x MEM, with the
   floor and ceiling scaled the same way; the hit odds are recomputed from
   it (GPP: P(the position's tournament-winning score); cash: P(2.5x
   salary)).

3. Fair ownership. The field's total ownership at the position is
   redistributed in proportion to those odds, tilted gently toward cheaper
   salaries (a ceiling at $4k fits more lineups than one at $9k):

     weight_i  = P_i x (mean salary / salary_i) ^ 0.5
     fair_i    = weight_i / sum(weight) x sum(ownership at the position)

4. Leverage = fair ownership - projected ownership, in percentage points.
   It is a difference, not "odds / ownership", so it can't run to infinity
   for a 0.5%-owned dart: a player with no real ceiling odds has almost no
   fair ownership either, and lands near zero (or below). Negative leverage
   means the field is over-exposed to him relative to his true odds.

Verdicts (shown with the number):
  Efficient secret  leverage >= +3 pts with an efficiency edge (MEM >= 1.04)
  Public trap       15%+ owned, leverage <= -3 pts, and a poor matchup (MEM <= 0.97)
  Mirage            under 2% owned with little real upside (adjusted odds under 5%)
"""
from __future__ import annotations

import math
import statistics

PHASES = {"QB": (0.85, 0.15), "RB": (0.30, 0.70), "WR": (1.0, 0.0), "TE": (1.0, 0.0)}   # (dropback, rush)
COEF = {"off": 0.05, "def": 0.05, "pos": 0.04}
MEM_MIN, MEM_MAX = 0.80, 1.25
POS_SHRINK_GAMES = 4
SALARY_ELASTICITY = 0.5


def _zmap(values: dict[str, float]) -> dict[str, float]:
    if len(values) < 2:
        return {k: 0.0 for k in values}
    mu, sd = statistics.fmean(values.values()), statistics.pstdev(values.values())
    return {k: (v - mu) / sd if sd > 1e-12 else 0.0 for k, v in values.items()}


def efficiency_context(trench_profiles: dict | None, dvp: dict | None) -> dict:
    """League z-scores for every team: offense / defense EPA by phase, and
    schedule-adjusted DK points allowed by position (shrunk)."""
    teams = (trench_profiles or {}).get("teams") or {}

    def side(s: str, metric: str) -> dict[str, float]:
        return _zmap({t: p[s][metric] for t, p in teams.items() if (p.get(s) or {}).get(metric) is not None})

    ctx = {
        "off_db": side("off", "db_epa"), "off_rush": side("off", "rush_epa"), "off_play": side("off", "epa_play"),
        "def_db": side("def", "db_epa"), "def_rush": side("def", "rush_epa"), "def_play": side("def", "epa_play"),
        "pos": {},
    }
    for pos in ("QB", "RB", "WR", "TE", "DST"):
        rows = {t: v[pos] for t, v in ((dvp or {}).get("teams") or {}).items() if pos in v}
        z = _zmap({t: r["adj"]["fp"] for t, r in rows.items()})
        ctx["pos"][pos] = {t: z[t] * rows[t]["games"] / (rows[t]["games"] + POS_SHRINK_GAMES) for t in z}
    return ctx


def mem(ctx: dict, position: str, team: str, opponent: str) -> dict:
    """The Matchup-Efficiency Multiplier and its parts for one player."""
    if position == "DST":
        off_z = -ctx["off_play"].get(opponent, 0.0)          # a weak opposing offense helps a DST
        def_z = -ctx["def_play"].get(team, 0.0)              # his own defense allowing little helps too
    else:
        db, rush = PHASES.get(position, (1.0, 0.0))
        off_z = db * ctx["off_db"].get(team, 0.0) + rush * ctx["off_rush"].get(team, 0.0)
        def_z = db * ctx["def_db"].get(opponent, 0.0) + rush * ctx["def_rush"].get(opponent, 0.0)
    pos_z = ctx["pos"].get(position, {}).get(opponent, 0.0)
    m = math.exp(COEF["off"] * off_z + COEF["def"] * def_z + COEF["pos"] * pos_z)
    return {"mem": round(min(MEM_MAX, max(MEM_MIN, m)), 3),
            "off_z": round(off_z, 2), "def_z": round(def_z, 2), "pos_z": round(pos_z, 2)}


def verdict(lev_pts: float, own: float, m: float, p: float) -> str | None:
    if own < 0.02 and p < 0.05:
        return "Mirage"
    if lev_pts >= 3 and m >= 1.04:
        return "Efficient secret"
    if own >= 0.15 and lev_pts <= -3 and m <= 0.97:
        return "Public trap"
    return None


def fair_ownership(rows: list[dict], p_key: str, own_key: str) -> None:
    """Adds r["fair_own"] (fraction) per position: the position's total
    ownership redistributed by efficiency-adjusted odds, salary-tilted."""
    by_pos: dict[str, list[dict]] = {}
    for r in rows:
        by_pos.setdefault(r["position"], []).append(r)
    for grp in by_pos.values():
        mean_sal = statistics.fmean(r["salary"] for r in grp)
        weights = [max(r[p_key], 0.0) * (mean_sal / max(r["salary"], 1)) ** SALARY_ELASTICITY for r in grp]
        total_w, total_own = sum(weights), sum(r[own_key] for r in grp)
        for r, w in zip(grp, weights):
            r["fair_own"] = w / total_w * total_own if total_w > 0 else 0.0
