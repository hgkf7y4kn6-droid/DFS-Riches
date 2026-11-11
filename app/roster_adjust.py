"""Roster-move adjustments for the week's teams (data/roster_adjust.json, written by scripts.update_roster_adjust).

Each team's entry holds the back-tested effect of who is expected to play against who its recent games came from: the
quarterback (his career dropback EPA vs the last starter's, and the cost of a starter under 300 career dropbacks),
receivers who are out or traded away, and pass-rush arrivals and departures. The coefficients are in
data/roster_adjust_model.json (scripts.backtest_roster_moves: walk-forward 2019-2025; effects that did not hold up out of
sample are listed there as not adopted). An entry applies only to the game its `week` names -- a team on a bye is read
for the game after it -- and only teams with something to report are returned.
"""
from __future__ import annotations

import json
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "data" / "roster_adjust.json"
_CACHE: tuple[float, dict] | None = None


def load() -> dict:
    global _CACHE
    if not FILE.exists():
        return {}
    mtime = FILE.stat().st_mtime
    if _CACHE is None or _CACHE[0] != mtime:
        _CACHE = (mtime, json.loads(FILE.read_text()))
    return _CACHE[1]


def for_week(season: int, week: int, data: dict | None = None) -> dict[str, dict]:
    """{app team: entry} for the teams whose next game is `week` and that have a reason to be adjusted."""
    d = data if data is not None else load()
    if int(d.get("season", 0)) != season:
        return {}
    return {t: e for t, e in (d.get("teams") or {}).items() if int(e.get("week", 0)) == week and e.get("reasons")}
