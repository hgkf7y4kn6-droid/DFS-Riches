"""Exact DraftKings lineup optimizer (integer program via SciPy's HiGHS).

Classic:  QB, 2-3 RB, 3-4 WR, 1-2 TE, DST (9 total, so FLEX is the extra
          RB/WR/TE), $50,000 cap, players from at least 2 games.
Showdown: 1 CPT + 5 FLEX, $50,000 cap, a player can't be both CPT and FLEX,
          at least one player from each team.

Only Healthy and Questionable players who have played this season (and, at
QB/RB/WR/TE, are projected for at least 3 points -- a real role this week)
are eligible; IR/OUT/Doubtful never make an optimal lineup.
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

SALARY_CAP = 50000
ELIGIBLE_STATUSES = {"Healthy", "Q"}
ROLE_POSITIONS = {"QB", "RB", "WR", "TE"}
MIN_ROLE_PROJ = 3.0   # a QB/RB/WR/TE projected under this has no real role this week
PUNT_SALARY = 4500    # a "punt": a QB/RB/WR/TE priced under this (the safe lineup allows at most one)
CLASSIC_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]


def _value(p, metric: str) -> float | None:
    return p.get(metric) if isinstance(p, dict) else getattr(p, metric)


def _attr(p, name: str):
    return p.get(name) if isinstance(p, dict) else getattr(p, name)


class SolverError(RuntimeError):
    """HiGHS failed for a reason other than infeasibility (time limit, numerical trouble): not "no valid lineup"."""


INFEASIBLE_STATUS = 2    # scipy.optimize.milp: 0 optimal, 1 limit reached, 2 infeasible, 3 unbounded, 4 other


def _solve(values, rows, lows, highs):
    n = len(values)
    args = dict(c=-np.asarray(values, dtype=float),
                constraints=LinearConstraint(np.asarray(rows, dtype=float), lows, highs),
                integrality=np.ones(n), bounds=Bounds(0, 1))
    res = milp(**args)   # presolve on: ~30% faster on Classic models
    if not res.success:
        # HiGHS presolve (SciPy 1.14) wrongly reports some small, feasible
        # Showdown models as infeasible, so "no solution" is always re-checked
        # without it.
        res = milp(**args, options={"presolve": False})
    if not res.success:
        if res.status == INFEASIBLE_STATUS:
            return None
        raise SolverError(f"lineup solver failed (status {res.status}): {res.message}")
    return [i for i, x in enumerate(res.x) if x > 0.5]


def optimize(players: list, slate_type: str, metric: str, *, hindsight: bool = False,
             locked: set | None = None, excluded: set | None = None, avoid: list[set] | None = None,
             min_unique: int = 2, max_punts: int | None = None) -> list | None:
    """Returns the optimal lineup's players in DraftKings slot order (Classic:
    QB, RB, RB, WR, WR, WR, TE, FLEX, DST; Showdown: CPT then FLEX by salary),
    or None if no valid lineup exists (SolverError if the solver itself fails). metric is the player field to maximize,
    e.g. "proj_points" or "ceiling". hindsight=True is for scoring a finished
    slate on actual points: any player with a salary is eligible. `locked`
    (DK draftable ids) must be in the lineup -- players whose games have
    already kicked off -- whatever their numbers now. `excluded` ids are left
    out; each set in `avoid` (an earlier lineup's ids) must differ from this
    lineup by at least `min_unique` players. Classic: `max_punts` caps the
    QB/RB/WR/TE under PUNT_SALARY (locked players count)."""
    locked = locked or set()
    excluded = (excluded or set()) - locked
    # DK season FPPG > 0 means the player has actually played this season --
    # keeps last year's starters who are now backups out of the Ceiling lineup.
    pool = [
        p for p in players
        if _attr(p, "dk_draftable_id") in locked
        or (_attr(p, "dk_draftable_id") not in excluded and (
            (_value(p, metric) or 0) > 0
            and _attr(p, "salary") > 0
            and (hindsight or (
                _attr(p, "injury") in ELIGIBLE_STATUSES
                and (_attr(p, "dk_fppg") or 0) > 0
                and (_attr(p, "position") not in ROLE_POSITIONS or (_attr(p, "proj_points") or 0) >= MIN_ROLE_PROJ)
            ))
        ))
    ]
    if not pool or len({_attr(p, "dk_draftable_id") for p in pool} & locked) < len(locked):
        return None
    values = [_value(p, metric) or 0.0 for p in pool]
    salary = [_attr(p, "salary") for p in pool]
    rows, lows, highs = [salary], [0], [SALARY_CAP]

    def add(indicator, lo, hi):
        rows.append([1.0 if f else 0.0 for f in indicator])
        lows.append(lo)
        highs.append(hi)

    if slate_type == "showdown":
        add([_attr(p, "roster_slot") == "CPT" for p in pool], 1, 1)
        add([_attr(p, "roster_slot") == "FLEX" for p in pool], 5, 5)
        for person in {(_attr(p, "name"), _attr(p, "team")) for p in pool}:
            add([(_attr(p, "name"), _attr(p, "team")) == person for p in pool], 0, 1)
        for team in {_attr(p, "team") for p in pool}:
            add([_attr(p, "team") == team for p in pool], 1, 6)
    else:
        pos = [_attr(p, "position") for p in pool]
        add([True] * len(pool), 9, 9)
        for position, lo, hi in (("QB", 1, 1), ("RB", 2, 3), ("WR", 3, 4), ("TE", 1, 2), ("DST", 1, 1)):
            add([x == position for x in pos], lo, hi)
        for game in {_attr(p, "game_info") for p in pool}:
            add([_attr(p, "game_info") == game for p in pool], 0, 8)
        if max_punts is not None:
            add([x != "DST" and _attr(p, "salary") < PUNT_SALARY for p, x in zip(pool, pos)], 0, max_punts)

    for p in pool:
        if _attr(p, "dk_draftable_id") in locked:
            add([q is p for q in pool], 1, 1)
    size = 6 if slate_type == "showdown" else 9
    for prev in avoid or []:
        add([_attr(p, "dk_draftable_id") in prev for p in pool], 0, size - min_unique)

    chosen = _solve(values, rows, lows, highs)
    if chosen is None:
        return None
    lineup = [pool[i] for i in chosen]

    if slate_type == "showdown":
        cpt = [p for p in lineup if _attr(p, "roster_slot") == "CPT"]
        flex = sorted((p for p in lineup if _attr(p, "roster_slot") == "FLEX"), key=lambda p: -_attr(p, "salary"))
        return cpt + flex

    return classic_order(lineup)


def classic_order(lineup: list) -> list:
    """A valid Classic lineup in DK slot order: QB, RB, RB, WR, WR, WR, TE, FLEX, DST."""
    by_pos: dict[str, list] = {}
    for p in sorted(lineup, key=lambda p: -_attr(p, "salary")):
        by_pos.setdefault(_attr(p, "position"), []).append(p)
    need = {"RB": 2, "WR": 3, "TE": 1}
    flex = next(by_pos[position].pop() for position in ("RB", "WR", "TE") if len(by_pos.get(position, [])) > need[position])
    return by_pos["QB"] + by_pos["RB"] + by_pos["WR"] + by_pos["TE"] + [flex] + by_pos["DST"]


def build_many(players: list, slate_type: str, metric: str, count: int, *, locked: set | None = None,
               excluded: set | None = None, max_exposure: float = 1.0, min_unique: int = 2) -> list[list]:
    """Up to `count` distinct lineups ("Build for me"), best first: each differs from every earlier one by
    at least `min_unique` players, and no player (other than `locked` ones) appears in more than
    max_exposure of them. Fewer come back when the constraints run out of valid lineups."""
    locked = locked or set()
    cap = max(1, math.floor(max_exposure * count + 1e-9))
    used: Counter = Counter()
    out: list[list] = []
    for _ in range(count):
        over = {pid for pid, n in used.items() if n >= cap} - locked
        lineup = optimize(players, slate_type, metric, locked=locked, excluded=(excluded or set()) | over,
                          avoid=[{_attr(p, "dk_draftable_id") for p in lu} for lu in out], min_unique=min_unique)
        if not lineup:
            break
        out.append(lineup)
        used.update(_attr(p, "dk_draftable_id") for p in lineup)
    return out
