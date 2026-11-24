"""Leverage for any slate, keyed by DraftKings player id -- what the app's leverage badge reads.

Classic slates: the large-field GPP leverage the plays page already builds (app.play_rankings, app.leverage), by id.

Showdown slates: the same idea per roster slot. Captain and Flex are separate contests with separate DraftKings ids,
projected ownership and scoring, so fair ownership is redistributed within Captain and within Flex on their own
(app.leverage.fair_ownership grouped by roster slot):

  * ownership is each player's percent of lineups using him in that slot (0-100), from the Showdown posterior
    (app.ownership_report showdown_ids), or uploaded actual ownership where it is known;
  * the hit odds are on each slot's own scoring: a Flex player's projection and ceiling against what a Flex position has to
    score in the best possible Showdown lineups, a Captain's (already x1.5 in the slate pool) against what a Captain has to
    score there (FLEX_TARGET / CPT_TARGET);
  * the efficiency multiplier and the salary tilt are the Classic ones (app.leverage).
"""
from __future__ import annotations

from app import field_ownership as fo
from app import leverage as lv

# What a slot has to score to count as a hit: the median score of that slot in the best possible Showdown lineups of Weeks 7-10
# (data/optimal_lineups.json hindsight, 190 Flex and 38 Captain scores). Flex varies by position; a Captain (scored x1.5 already)
# is the lineup's top scorer, about 40 whoever he is. Small samples: re-fit as more Showdown slates finish.
FLEX_TARGET = {"QB": 22.0, "RB": 17.0, "WR": 15.0, "TE": 14.0, "K": 13.0, "DST": 11.5}
CPT_TARGET = 40.0
SLOTS = ("CPT", "FLEX")
_NEUTRAL = {"off_db": {}, "off_rush": {}, "off_play": {}, "def_db": {}, "def_rush": {}, "def_play": {}, "pos": {}}


def showdown_target(position: str, slot: str) -> float:
    """The score that counts as a hit for this slot (see FLEX_TARGET / CPT_TARGET)."""
    return CPT_TARGET if slot == "CPT" else FLEX_TARGET.get(position, FLEX_TARGET["WR"])


def showdown(rows: list[dict], efficiency: dict | None) -> dict[int, dict]:
    """{draftable id: {"name", "team", "leverage": points, "leverage_detail": {...}, "slot": "CPT"|"FLEX"}} for one Showdown slate.

    rows: one per DraftKings id with id, name, team, opponent, position, salary, slot ("CPT" / "FLEX"), final / floor /
    ceiling (the slot's own scoring: a Captain's are x1.5), own (fraction of lineups using him in that slot), and
    own_is_actual. Anyone without an ownership figure is left out (nothing to compare his odds with)."""
    pool = []
    for src in rows:
        if src.get("own") is None or src.get("slot") not in SLOTS or (src.get("salary") or 0) <= 0:
            continue
        r = dict(src)
        m = lv.mem(efficiency or _NEUTRAL, r["position"], r["team"], r["opponent"])
        k = m["mem"]
        final = r.get("final") or 0.0
        floor, ceiling = r.get("floor"), r.get("ceiling")
        lo, hi = fo.player_sd(final * k, floor * k if floor is not None else None, ceiling * k if ceiling is not None else None)
        r["mem"], r["teap"] = m, final * k
        r["p_eff"] = fo.p_at_least(showdown_target(r["position"], r["slot"]), final * k, lo, hi)
        pool.append(r)
    lv.fair_ownership(pool, "p_eff", "own", group_key="slot")
    out: dict[int, dict] = {}
    for r in pool:
        pts = (r["fair_own"] - r["own"]) * 100
        out[r["id"]] = {
            "name": r["name"], "team": r["team"],
            "leverage": round(pts, 1),
            "slot": r["slot"],
            "leverage_detail": {
                "fair_own": round(r["fair_own"] * 100, 1),
                "own": round(r["own"] * 100, 1),
                "own_is_actual": bool(r.get("own_is_actual")),
                "teap": round(r["teap"], 2),
                "p": round(r["p_eff"], 3),
                **r["mem"],
                "verdict": lv.verdict(pts, r["own"], r["mem"]["mem"], r["p_eff"]),
                "slot": r["slot"],
            },
        }
    return out


def showdown_rows(players: list, ownership: dict[int, dict]) -> list[dict]:
    """The slate's pool (app.models.Player) joined with Showdown ownership by draftable id (percent, from
    ownership_report showdown_ids) as showdown() rows."""
    rows = []
    for p in players:
        o = ownership.get(p.dk_draftable_id)
        if not o or p.roster_slot not in SLOTS:
            continue
        actual = o.get("actual")
        pct = actual if actual is not None else o.get("own")
        if pct is None:
            continue
        rows.append({"id": p.dk_draftable_id, "name": p.name, "team": p.team, "opponent": p.opponent, "position": p.position,
                     "salary": p.salary, "slot": p.roster_slot, "final": p.proj_points or 0.0, "floor": None,
                     "ceiling": p.ceiling, "own": pct / 100, "own_is_actual": actual is not None})
    return rows


def classic(plays: dict) -> dict[int, dict]:
    """The large-field GPP leverage the plays page built (app.play_rankings.build output), by draftable id."""
    return {p["id"]: {"name": p["name"], "team": p["team"], "leverage": p["leverage"], "leverage_detail": p.get("leverage_detail"), "slot": None}
            for p in plays.get("players") or [] if p.get("id") is not None and p.get("leverage") is not None}
