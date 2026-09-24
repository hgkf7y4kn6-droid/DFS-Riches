"""Exact DraftKings lineup optimizer (integer program via SciPy's HiGHS).

Classic:  QB, 2-3 RB, 3-4 WR, 1-2 TE, DST (9 total, so FLEX is the extra
          RB/WR/TE), $50,000 cap, players from at least 2 games.
Showdown: 1 CPT + 5 FLEX, $50,000 cap, a player can't be both CPT and FLEX,
          at least one player from each team.

Only Healthy and Questionable players are eligible; IR/OUT/Doubtful never
make an optimal lineup.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

SALARY_CAP = 50000
ELIGIBLE_STATUSES = {"Healthy", "Q"}
CLASSIC_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]


def _value(p, metric: str) -> float | None:
    return p.get(metric) if isinstance(p, dict) else getattr(p, metric)


def _attr(p, name: str):
    return p.get(name) if isinstance(p, dict) else getattr(p, name)


def _solve(values, rows, lows, highs):
    n = len(values)
    res = milp(
        c=-np.asarray(values, dtype=float),
        constraints=LinearConstraint(np.asarray(rows, dtype=float), lows, highs),
        integrality=np.ones(n),
        bounds=Bounds(0, 1),
        # HiGHS presolve (SciPy 1.14) wrongly reports some small, feasible
        # Showdown models as infeasible; these problems are small enough
        # that solving without it is still fast.
        options={"presolve": False},
    )
    if not res.success:
        return None
    return [i for i, x in enumerate(res.x) if x > 0.5]


def optimize(players: list, slate_type: str, metric: str) -> list | None:
    """Returns the optimal lineup's players in DraftKings slot order (Classic:
    QB, RB, RB, WR, WR, WR, TE, FLEX, DST; Showdown: CPT then FLEX by salary),
    or None if no valid lineup exists. metric is the player field to maximize,
    e.g. "proj_points" or "ceiling"."""
    pool = [
        p for p in players
        if _attr(p, "injury") in ELIGIBLE_STATUSES and (_value(p, metric) or 0) > 0 and _attr(p, "salary") > 0
    ]
    if not pool:
        return None
    values = [_value(p, metric) for p in pool]
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

    chosen = _solve(values, rows, lows, highs)
    if chosen is None:
        return None
    lineup = [pool[i] for i in chosen]

    if slate_type == "showdown":
        cpt = [p for p in lineup if _attr(p, "roster_slot") == "CPT"]
        flex = sorted((p for p in lineup if _attr(p, "roster_slot") == "FLEX"), key=lambda p: -_attr(p, "salary"))
        return cpt + flex

    by_pos: dict[str, list] = {}
    for p in sorted(lineup, key=lambda p: -_attr(p, "salary")):
        by_pos.setdefault(_attr(p, "position"), []).append(p)
    need = {"RB": 2, "WR": 3, "TE": 1}
    flex = next(by_pos[position].pop() for position in ("RB", "WR", "TE") if len(by_pos.get(position, [])) > need[position])
    return by_pos["QB"] + by_pos["RB"] + by_pos["WR"] + by_pos["TE"] + [flex] + by_pos["DST"]
