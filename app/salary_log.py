"""A weekly record of DraftKings salaries (and the app's projection for each player), one file per week.

DraftKings' salary history is not published anywhere, and a backtest at true prices needs it: data/salaries/{season}_w{week}.json
holds, per slate, every player's salary, the app's projection and Sleeper's, and DraftKings' season FPPG as they stood the last
time the slate was recorded before its first kickoff. app.optimal calls `record` each time it refreshes a slate that has not
started (the daily and inactives jobs run it), so the file ends as the final pre-lock snapshot; a slate that has started is
never touched again.

Rows are [dk_draftable_id, name, position, team, opponent, roster_slot, salary, dk_fppg, injury, proj_points, sleeper_proj].
Players with no salary or neither a projection nor a season average are left out. Recording is best effort: a failure here
never affects the lineups.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from app.config import DATA_DIR

SALARY_DIR = DATA_DIR / "salaries"
COLUMNS = ["dk_draftable_id", "name", "position", "team", "opponent", "roster_slot", "salary", "dk_fppg", "injury",
           "proj_points", "sleeper_proj"]


def path(season: int, week: int):
    return SALARY_DIR / f"{season}_w{week:02d}.json"


def _rows(players: list) -> list[list]:
    rows = []
    for p in players:
        get = p.get if isinstance(p, dict) else lambda k, p=p: getattr(p, k)
        if not get("salary") or not ((get("proj_points") or 0) > 0 or (get("dk_fppg") or 0) > 0):
            continue
        rows.append([get(c) for c in COLUMNS])
    rows.sort(key=lambda r: (r[6] is None, -(r[6] or 0), r[1] or ""))
    return rows


def load(season: int, week: int) -> dict:
    f = path(season, week)
    return json.loads(f.read_text()) if f.exists() else {}


def record(season: int, week: int, slate_id: str, draft_group_id: int | None, slate_type: str, players: list,
           now: datetime) -> bool:
    """Writes the slate's salary snapshot when it changed; True if the file was written. Never raises."""
    try:
        rows = _rows(players)
        if not rows:
            return False
        data = load(season, week) or {"season": season, "week": week, "columns": COLUMNS, "slates": {}}
        old = data["slates"].get(slate_id)
        if old and old.get("players") == rows and old.get("draft_group_id") == draft_group_id:
            return False
        data["slates"][slate_id] = {"draft_group_id": draft_group_id, "slate_type": slate_type,
                                    "saved_at": now.isoformat(timespec="seconds"), "players": rows}
        data["slates"] = dict(sorted(data["slates"].items()))
        SALARY_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path(season, week).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")) + "\n")
        os.replace(tmp, path(season, week))
        return True
    except Exception:
        return False
