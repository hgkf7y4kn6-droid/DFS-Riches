"""Kicker projection: the season-to-date average shrunk toward the league average, nudged by the game.

Sleeper projects no stat line for kickers, so a kicker used to be projected at his raw DK season average. Kickers'
week-to-week talent differs very little (a kicker's points are mostly his team's drives and the weather), so a raw
average over a few games mostly carries luck. A fit on 2016-2026 play-by-play (scripts/train_kicker_model.py, stored in
data/kicker_model.json with its record) shrinks that average toward the league mean as if it came with K games of
league-average evidence, then adds a small adjustment for the team's expected margin and implied total. Held out one
season at a time (2019-2026) its mean absolute miss was 3.52 DK points against 3.74 for the raw average; almost all of
that comes from the shrinkage, the game adjustment is worth a few tenths of a point.
"""
from __future__ import annotations

import json
from pathlib import Path

MODEL_FILE = Path(__file__).resolve().parent.parent / "data" / "kicker_model.json"
_MODEL: dict | None = None


def load() -> dict | None:
    global _MODEL
    if _MODEL is None and MODEL_FILE.exists():
        _MODEL = json.loads(MODEL_FILE.read_text())
    return _MODEL


def project(season_avg: float | None, games: int, implied: float | None, spread: float | None,
            model: dict | None = None) -> tuple[float, str] | None:
    """(projected DK points, one-line explanation), or None without a fitted model or any season average.
    games: his games this season so far; implied / spread: his team's implied total and expected margin."""
    m = model if model is not None else load()
    if not m or season_avg is None:
        return None
    games = max(0, games)
    shrunk = (season_avg * games + m["k"] * m["league_mean"]) / (games + m["k"])
    adj = m["intercept"] + m["implied"] * ((implied if implied is not None else m["implied_center"]) - m["implied_center"]) \
        + m["spread"] * (spread or 0.0)
    value = round(max(0.0, shrunk + adj), 2)
    note = (f"Kicker model: {season_avg:.1f} DK points per game over {games} games shrunk toward the league's "
            f"{m['league_mean']:.1f} = {shrunk:.1f}, {adj:+.1f} for his team's game "
            f"(implied total {implied if implied is not None else m['implied_center']:.1f}, margin {spread or 0.0:+.1f}) = {value:.1f}")
    return value, note
