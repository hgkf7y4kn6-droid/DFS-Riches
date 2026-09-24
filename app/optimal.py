"""Optimal lineups per slate, and the saved pre-kickoff record of them.

Before a slate's first kickoff, optimal lineups are computed live from the
current data and written to data/optimal_lineups.json whenever they change,
so the file always holds the last optimal lineups shown before lock. Once
the slate has started, only that saved record is served: live numbers after
kickoff would already reflect the results.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from app import slates as slates_module
from app.config import OPTIMAL_LINEUPS_PATH
from app.optimizer import CLASSIC_SLOTS, optimize

METRICS = (("proj_points", "Proj"), ("ceiling", "Ceiling"))
_FIELDS = (
    "name", "position", "team", "opponent", "roster_slot", "salary", "proj_points",
    "ceiling", "sleeper_proj", "game_info", "injury", "dk_draftable_id",
)


def slate_started(slate, now: datetime) -> bool:
    return any(g.kickoff_utc <= now for g in slate.games)


def build_lineups(players: list, slate_type: str) -> list[dict]:
    slots = ["CPT"] + ["FLEX"] * 5 if slate_type == "showdown" else CLASSIC_SLOTS
    out = []
    for metric, label in METRICS:
        lineup = optimize(players, slate_type, metric)
        if not lineup:
            continue
        rows = [{"slot": slot, **{f: getattr(p, f) for f in _FIELDS}} for slot, p in zip(slots, lineup)]
        out.append({
            "metric": metric,
            "label": f"Optimal - {label}",
            "players": rows,
            "salary": sum(r["salary"] for r in rows),
            "proj_points": round(sum(r["proj_points"] or 0 for r in rows), 2),
            "ceiling": round(sum(r["ceiling"] or 0 for r in rows), 2),
        })
    return out


def _load_all() -> dict:
    if not OPTIMAL_LINEUPS_PATH.exists():
        return {}
    return json.loads(OPTIMAL_LINEUPS_PATH.read_text())


def load_saved(season: int, week: int, slate_id: str) -> dict | None:
    return _load_all().get(str(season), {}).get(str(week), {}).get(slate_id)


def save(season: int, week: int, slate_id: str, entry: dict) -> None:
    # Synchronous read-modify-write with no awaits, so concurrent requests on
    # the event loop can't interleave; os.replace keeps the file whole.
    data = _load_all()
    data.setdefault("_readme", (
        "Optimal DraftKings lineups per season/week/slate as they stood before that slate's first kickoff "
        "(app/optimal.py). Written automatically while a slate is still open; frozen once it starts."
    ))
    weeks = data.setdefault(str(season), {})
    weeks.setdefault(str(week), {})[slate_id] = entry
    data[str(season)] = {w: weeks[w] for w in sorted(weeks, key=int)}
    tmp = OPTIMAL_LINEUPS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, OPTIMAL_LINEUPS_PATH)


async def get_optimal(season: int, week: int, slate_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    _schedule, slate_list = await slates_module.list_slates(season, week)
    slate = next((s for s in slate_list if s.slate_id == slate_id), None)
    if slate is None:
        raise ValueError(f"Unknown slate_id: {slate_id}")

    saved = load_saved(season, week, slate_id)
    if not slate_started(slate, now):
        players = (await slates_module.get_slate_players(season, week, slate_id)).players
        lineups = build_lineups(players, slate.slate_type)
        if lineups and (saved is None or saved.get("lineups") != lineups):
            saved = {"saved_at": now.isoformat(timespec="seconds"), "draft_group_id": slate.draft_group_id, "lineups": lineups}
            save(season, week, slate_id, saved)
        return {"status": "live", "saved_at": saved["saved_at"] if lineups else None, "lineups": lineups}

    if saved:
        return {"status": "saved", "saved_at": saved["saved_at"], "lineups": saved["lineups"]}
    return {"status": "none", "saved_at": None, "lineups": []}
