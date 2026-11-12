"""Which way a team is headed: its schedule ahead against the one behind (data/schedule_outlook.json).

scripts/backtest_schedule_trends.py (2016-2025, walk-forward) found the next three opponents' strength predicts a
team's next three games -- strongly for defences against the opposing offences (coefficient 0.72, t = 10; 0.41 for rush
defence, t = 4.2), modestly for offences (0.30, t = 3.4; rush 0.23, t = 2.2) and not for pass offences (0.09, t = 1.0, left
out). The last games' results against soft or tough opponents did not carry on (the schedule part of a recent move has
no persistence), and recent form is no stickier than the six-game average, so direction here is the schedule, not momentum.
"""
from __future__ import annotations

import json
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "data" / "schedule_outlook.json"
MIN_MOVE = 1.0               # EPA per play x100: smaller moves are not shown
PLAYS = 62
UNITS = (("off_total", "Offense", False), ("off_rush", "Rushing offense", False), ("def_total", "Defense", True),
         ("def_pass", "Pass defense", True), ("def_rush", "Run defense", True))
_CACHE: tuple[float, dict] | None = None


def load() -> dict:
    global _CACHE
    if not FILE.exists():
        return {}
    m = FILE.stat().st_mtime
    if _CACHE is None or _CACHE[0] != m:
        _CACHE = (m, json.loads(FILE.read_text()))
    return _CACHE[1]


def lines(entry: dict) -> list[dict]:
    """[{"unit", "better", "text"}] for the parts of a team whose schedule ahead moves it by MIN_MOVE or more."""
    out = []
    opp = ", ".join(entry.get("opponents_ahead") or [])
    for fam, unit, is_def in UNITS:
        f = entry.get(fam)
        if not f or abs(f["expected_move"]) < MIN_MOVE:
            continue
        move = f["expected_move"]
        better = move < 0 if is_def else move > 0
        pts = abs(move) / 100 * PLAYS
        out.append({"unit": unit, "better": better,
                    "text": (f"{unit} {'improving' if better else 'slipping'}: the next 3 {'offenses' if is_def else 'defenses'} ({opp}) rate "
                             f"{f['schedule_ahead']:+.1f} vs {f['schedule_past6']:+.1f} over the last 6 (EPA per play x100 vs an average opponent): "
                             f"about {pts:.1f} points per game {'better' if better else 'worse'}")})
    return out


def for_week(season: int, week: int, data: dict | None = None) -> dict[str, list[dict]]:
    """{app team: lines} when the file is for this slate's week."""
    d = data if data is not None else load()
    if int(d.get("season", 0)) != season or int(d.get("week", 0)) != week:
        return {}
    return {t: ls for t, e in (d.get("teams") or {}).items() if (ls := lines(e))}
