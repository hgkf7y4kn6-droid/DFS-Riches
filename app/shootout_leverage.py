"""Shootout leverage: games whose odds of producing the slate's top scorers outrun the field's ownership.

Scoring isn't predictable game by game against the line, but where the slate's best DFS scores come from is
predictable on average: a game's expected share of the week's top scorers (top 3 QBs, 6 RBs, 9 WRs, 3 TEs)
rises about 5% per point of Vegas total (a Poisson model fit on 2023-2025 Sunday main slates by
scripts/train_leverage.py). Low totals still produce them -- a 41-44 total game finishes 10+ over its line about
as often as a 47-50 one. The field, though, crowds the highest totals, so

    leverage = expected share of top scorers / projected share of the field's ownership

and the top third of the slate by leverage (when at least 1.0) is flagged: rostering those games buys top-scorer
chances the field isn't paying for. In the backtest (this season's slates with saved projected ownership) that
third produced top scorers at about twice the rate per unit of ownership of the bottom third.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MODEL_FILE = Path(__file__).resolve().parent.parent / "data" / "leverage_model.json"
TOP = {"QB": 3, "RB": 6, "WR": 9, "TE": 3}
BANDS = ((0, 41), (41, 44), (44, 47), (47, 50), (50, 99))
MIN_LEVERAGE = 1.0

_MODEL: dict | None = None


def load() -> dict | None:
    global _MODEL
    if _MODEL is None and MODEL_FILE.exists():
        _MODEL = json.loads(MODEL_FILE.read_text())
    return _MODEL


def features(total: float, spread: float) -> list[float]:
    return [1.0, (total - 45) / 4, (abs(spread) - 4) / 3]


def expected_shares(games: list[tuple[float, float]], coef: list[float]) -> list[float]:
    """Each game's expected share of the slate's top scorers from (total, spread)."""
    mu = [math.exp(sum(c * x for c, x in zip(coef, features(t, s)))) for t, s in games]
    total = sum(mu) or 1.0
    return [m / total for m in mu]


def band(total: float, model: dict | None = None) -> dict | None:
    m = model or load() or {}
    return next((b for b in m.get("bands") or [] if b["lo"] <= total < b["hi"]), None)


def rate(games: list[dict], model: dict | None = None) -> None:
    """In place, for DFS game dicts with "total", "spread_home" and "pop_share": "shootout_leverage" = {expected_share,
    own_share, leverage, rank, flag, over_by_10, points_50}."""
    m = model or load()
    rated = [g for g in games if g.get("total") and g.get("pop_share")]
    if not m or len(rated) < 2:
        return
    shares = expected_shares([(g["total"], g.get("spread_home") or 0.0) for g in rated], m["coef"])
    pop = sum(g["pop_share"] for g in rated) or 1.0
    for g, s in zip(rated, shares):
        own = g["pop_share"] / pop
        b = band(g["total"], m) or {}
        g["shootout_leverage"] = {"expected_share": round(s, 3), "own_share": round(own, 3), "leverage": round(s / own, 2),
                                  "over_by_10": b.get("over_by_10"), "points_50": b.get("points_50")}
    top = math.ceil(len(rated) / 3)
    for i, g in enumerate(sorted(rated, key=lambda g: -g["shootout_leverage"]["leverage"]), 1):
        g["shootout_leverage"]["rank"] = i
        g["shootout_leverage"]["flag"] = i <= top and g["shootout_leverage"]["leverage"] >= MIN_LEVERAGE


def note(g: dict) -> str | None:
    s = g.get("shootout_leverage")
    if not s:
        return None
    text = (f"Shootout leverage {s['leverage']:.2f}x (#{s['rank']}): expected {s['expected_share']:.0%} of the slate's top "
            f"scorers vs {s['own_share']:.0%} of the field")
    if s.get("over_by_10") is not None:
        text += f"; games at this total finish 10+ over {s['over_by_10']:.0%} of the time"
    return text
