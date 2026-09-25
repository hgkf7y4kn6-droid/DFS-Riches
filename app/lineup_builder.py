"""Classic lineups with DFS construction rules, as exact integer programs.

On top of DraftKings' roster rules (app.optimizer) a build can require:

  stack       QB plus at least `mates` of his WR/TE, and at least `bring_back`
              RB/WR/TE from the opposing team
  stack_game  the QB must come from this game
  counts      exact position counts (e.g. 3 RBs = RB in the FLEX)
  no DST vs own offense
              a DST never faces any of the lineup's own RB/WR/TE/QB
  unique      at least `min_unique` players different from each earlier
              lineup in the set (so a set of lineups isn't one lineup nine
              ways)

Pool players are dicts with id, name, position, team, opponent, salary, game.
"""
from __future__ import annotations

from app.optimizer import SALARY_CAP, _solve, classic_order

POSITION_RANGE = {"QB": (1, 1), "RB": (2, 3), "WR": (3, 4), "TE": (1, 2), "DST": (1, 1)}
OFFENSE = ("QB", "RB", "WR", "TE")


def build(pool: list[dict], values: list[float], *, prior: list[set] = (), min_unique: int = 3,
          stack: tuple[int, int] | None = None, stack_game: str | None = None,
          counts: dict[str, int] | None = None, max_salary: int = SALARY_CAP) -> list[dict] | None:
    n = len(pool)
    if n == 0:
        return None
    rows, lows, highs = [], [], []

    def add(coefs, lo, hi):
        rows.append(coefs)
        lows.append(lo)
        highs.append(hi)

    add([p["salary"] for p in pool], 0, max_salary)
    add([1] * n, 9, 9)
    for pos, (lo, hi) in POSITION_RANGE.items():
        if counts and pos in counts:
            lo = hi = counts[pos]
        add([1 if p["position"] == pos else 0 for p in pool], lo, hi)
    for game in {p["game"] for p in pool}:
        add([1 if p["game"] == game else 0 for p in pool], 0, 8)

    for i, d in enumerate(pool):
        if d["position"] != "DST":
            continue
        coefs = [1 if (p["team"] == d["opponent"] and p["position"] in OFFENSE) else 0 for p in pool]
        coefs[i] = 8
        add(coefs, 0, 8)

    if stack:
        mates, bring_back = stack
        for i, q in enumerate(pool):
            if q["position"] != "QB":
                continue
            if mates:
                coefs = [1 if (p["team"] == q["team"] and p["position"] in ("WR", "TE")) else 0 for p in pool]
                coefs[i] = -mates
                add(coefs, 0, 9)
            if bring_back:
                coefs = [1 if (p["team"] == q["opponent"] and p["position"] in ("RB", "WR", "TE")) else 0 for p in pool]
                coefs[i] = -bring_back
                add(coefs, 0, 9)
    if stack_game:
        add([1 if (p["position"] == "QB" and p["game"] == stack_game) else 0 for p in pool], 1, 1)

    for earlier in prior:
        add([1 if p["id"] in earlier else 0 for p in pool], 0, 9 - min_unique)

    chosen = _solve(values, rows, lows, highs)
    if chosen is None:
        return None
    return classic_order([pool[i] for i in chosen])
