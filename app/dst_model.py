"""DST projection: Sleeper's defense line, re-weighted with Vegas, the opposing quarterback and turnover/sack rates.

A ridge regression of actual DK DST points, fit on 2023-2025 by scripts/train_dst_model.py and stored in
data/dst_model.json with its out-of-sample record. Inputs, all known before the game:

  sleeper        Sleeper's projected defense line scored with DK rules
  exp_pa_bonus   the points-allowed bonus averaged over the opponent's likely scores (its implied total, normal
                 spread ~9 points) -- not the bonus at the average score, which is what a projected line gives
  margin         the defense's team's expected margin (a trailing opponent drops back more)
  opp_qb_epa     the opposing starter's dropback EPA (app.game_model: his own history, shrunk; a quarterback
                 without 100 dropbacks starts at backup level), opp_qb_unknown flags that case
  opp_sack_rate  sacks the opposing offense takes per dropback; opp_give_rate its interceptions + lost fumbles
                 per play; own_sack_rate / own_take_rate the same against this defense -- each this season's
                 count shrunk toward last season's rate (regressed halfway to the league)

DSTs are the noisiest position: no model gets far below a 3.8-point average miss. What the model improves is the
ranking that picks a DST: on 2026 Weeks 1-6 its top three per week averaged 8.5 DK points vs 7.6 for Sleeper's
line, and its within-week rank correlation was 0.25 vs 0.22 (2023-2025 seasons held out one at a time: 0.33 vs
0.30, top three tied at 8.8).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from app import dk_scoring

MODEL_FILE = Path(__file__).resolve().parent.parent / "data" / "dst_model.json"
FEATURES = ("sleeper", "exp_pa_bonus", "margin", "opp_qb_epa", "opp_qb_unknown", "opp_sack_rate", "opp_give_rate",
            "own_sack_rate", "own_take_rate")
K_DB, K_PLAYS = 200, 400      # dropbacks / plays of evidence last season's rate is worth
REGRESS = 0.5
MIN_QB_DROPBACKS = 100

_MODEL: dict | None = None


def load() -> dict | None:
    global _MODEL
    if _MODEL is None and MODEL_FILE.exists():
        _MODEL = json.loads(MODEL_FILE.read_text())
    return _MODEL


def expected_pa_bonus(opp_implied: float, sd: float) -> float:
    """DK's points-allowed bonus averaged over a normal spread of opponent scores around its implied total."""
    ps = [math.exp(-0.5 * ((s - opp_implied) / sd) ** 2) for s in range(0, 71)]
    z = sum(ps)
    return sum(p / z * dk_scoring._points_allowed_bonus(s) for s, p in enumerate(ps))


def _f(r: dict, k: str) -> float:
    try:
        return float(r.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def _counts(r: dict) -> dict[str, float]:
    """An offense's dropbacks, sacks taken, plays and giveaways in one game (a stats_team_week row)."""
    db = _f(r, "attempts") + _f(r, "sacks_suffered")
    give = (_f(r, "passing_interceptions") + _f(r, "sack_fumbles_lost") + _f(r, "rushing_fumbles_lost")
            + _f(r, "receiving_fumbles_lost"))
    return {"db": db, "sacks": _f(r, "sacks_suffered"), "plays": db + _f(r, "carries"), "give": give}


def _sum(rows: list[dict], week: int | None = None) -> dict[str, dict[str, dict[str, float]]]:
    """{team: {"off": counts, "def": counts against it}} over regular-season games before `week` (all if None)."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for r in rows:
        if r.get("season_type", "REG") != "REG" or not r.get("week"):
            continue
        if week is not None and int(r["week"]) >= week:
            continue
        c = _counts(r)
        for team, side in ((r.get("team"), "off"), (r.get("opponent_team"), "def")):
            if team:
                d = out.setdefault(team, {"off": {}, "def": {}})[side]
                for k, v in c.items():
                    d[k] = d.get(k, 0.0) + v
    return out


def team_rates(cur_rows: list[dict], prev_rows: list[dict], week: int, team_of=lambda t: t) -> dict[str, dict[str, float]]:
    """{team: {"o_sack", "o_give", "d_sack", "d_give"}}: sack and giveaway rates of its offense and against its
    defense, this season's games before `week` shrunk toward last season's rate (itself regressed halfway to
    the league). Rows are nflverse stats_team_week records."""
    prev, cur = _sum(prev_rows), _sum(cur_rows, week)
    lg = {"db": 0.0, "sacks": 0.0, "plays": 0.0, "give": 0.0}
    for t in prev.values():
        for k in lg:
            lg[k] += t["off"].get(k, 0.0)
    lg_sack = lg["sacks"] / lg["db"] if lg["db"] else 0.065
    lg_give = lg["give"] / lg["plays"] if lg["plays"] else 0.02
    out = {}
    for team in set(prev) | set(cur):
        p, c = prev.get(team, {"off": {}, "def": {}}), cur.get(team, {"off": {}, "def": {}})
        rates = {}
        for side in ("off", "def"):
            ps, pc = p[side], c[side]
            pri_sack = lg_sack + REGRESS * (ps["sacks"] / ps["db"] - lg_sack) if ps.get("db") else lg_sack
            pri_give = lg_give + REGRESS * (ps["give"] / ps["plays"] - lg_give) if ps.get("plays") else lg_give
            rates[f"{side[0]}_sack"] = (pri_sack * K_DB + pc.get("sacks", 0.0)) / (K_DB + pc.get("db", 0.0))
            rates[f"{side[0]}_give"] = (pri_give * K_PLAYS + pc.get("give", 0.0)) / (K_PLAYS + pc.get("plays", 0.0))
        out[team_of(team)] = rates
    return out


def features(sleeper: float, opp_implied: float, margin: float, opp_qb_epa: float, opp_qb_dropbacks: float,
             own: dict | None, opp: dict | None, pa_sd: float) -> dict:
    own, opp = own or {}, opp or {}
    return {
        "sleeper": sleeper, "exp_pa_bonus": expected_pa_bonus(opp_implied, pa_sd), "margin": margin,
        "opp_qb_epa": opp_qb_epa, "opp_qb_unknown": 1.0 if opp_qb_dropbacks < MIN_QB_DROPBACKS else 0.0,
        "opp_sack_rate": opp.get("o_sack", 0.065), "opp_give_rate": opp.get("o_give", 0.02),
        "own_sack_rate": own.get("d_sack", 0.065), "own_take_rate": own.get("d_give", 0.02),
    }


def project(feats: dict, model: dict | None = None) -> float | None:
    """Projected DK DST points, or None without a fitted model."""
    m = (model or load() or {}).get("model")
    if not m:
        return None
    return round(m["intercept"] + sum(w * (feats[k] - mu) / sd for k, w, mu, sd in
                                      zip(m["features"], m["weights"], m["means"], m["sds"])), 2)


def note(value: float, f: dict, opp: str) -> str:
    parts = [f"DST model: {value:.1f} (Sleeper line {f['sleeper']:.1f}; points-allowed bonus {f['exp_pa_bonus']:+.1f} "
             f"averaged over {opp}'s likely scores"]
    if f["opp_qb_unknown"]:
        parts.append(f"{opp} starting a quarterback with little NFL history")
    parts.append(f"{opp} take sacks on {f['opp_sack_rate']:.1%} of dropbacks, give it away on {f['opp_give_rate']:.1%} of plays)")
    return "; ".join(parts)


# --------------------------------------------------------------------------- live
async def context(season: int, week: int) -> dict[str, dict[str, float]]:
    """{app team: rates} for this week (see team_rates)."""
    from app import nflverse_client as nc

    cur = await nc._fetch_team_week_rows(season)
    prev = await nc._fetch_team_week_rows(season - 1)
    return team_rates(cur, prev, week, team_of=nc.to_app_team)
