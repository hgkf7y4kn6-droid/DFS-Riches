"""Optimal lineups per slate, and the saved record of them.

Before a slate's first kickoff, optimal lineups are computed live from the
current data and written to data/optimal_lineups.json whenever they change,
so the file always holds the last optimal lineups shown before lock. Once
the slate has started, only that saved record is served: live numbers after
kickoff would already reflect the results.

Once every game in the slate is final and its box scores are in, the record
is scored: each saved lineup (and each of its players) gets its actual
DraftKings points, and a hindsight "best possible" lineup -- the optimal
lineup on actual points, from the same salaries -- is added.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from app import nflverse_client as nc
from app import slates as slates_module
from app.config import OPTIMAL_LINEUPS_PATH
from app.optimizer import CLASSIC_SLOTS, optimize

METRICS = (("proj_points", "Proj"), ("ceiling", "Ceiling"))
_FIELDS = (
    "name", "position", "team", "opponent", "roster_slot", "salary", "proj_points",
    "ceiling", "sleeper_proj", "game_info", "injury", "dk_draftable_id",
)
_HINDSIGHT_FIELDS = ("name", "position", "team", "opponent", "roster_slot", "salary", "game_info", "dk_draftable_id")


def _slots(slate_type: str) -> list[str]:
    return ["CPT"] + ["FLEX"] * 5 if slate_type == "showdown" else CLASSIC_SLOTS


def slate_started(slate, now: datetime) -> bool:
    return any(g.kickoff_utc <= now for g in slate.games)


def slate_complete(slate, actuals: dict) -> bool:
    """Every game final (nflverse games.csv) and both teams' box scores in."""
    reported = set(actuals["teams"])
    return bool(slate.games) and all(
        g.context is not None and g.context.is_final and g.away in reported and g.home in reported
        for g in slate.games
    )


def build_lineups(players: list, slate_type: str) -> list[dict]:
    out = []
    for metric, label in METRICS:
        lineup = optimize(players, slate_type, metric)
        if not lineup:
            continue
        rows = [{"slot": slot, **{f: getattr(p, f) for f in _FIELDS}} for slot, p in zip(_slots(slate_type), lineup)]
        out.append({
            "metric": metric,
            "label": f"Optimal - {label}",
            "players": rows,
            "salary": sum(r["salary"] for r in rows),
            "proj_points": round(sum(r["proj_points"] or 0 for r in rows), 2),
            "ceiling": round(sum(r["ceiling"] or 0 for r in rows), 2),
        })
    return out


def score_results(saved_lineups: list[dict], players: list, slate_type: str, actuals: dict) -> tuple[list[dict], dict | None]:
    """Returns (saved lineups with actual points added, hindsight lineup)."""
    def actual(p) -> float:
        get = p.get if isinstance(p, dict) else lambda k: getattr(p, k)
        return nc.actual_points(actuals, name=get("name"), position=get("position"), team=get("team"),
                                roster_slot=get("roster_slot") or "")

    scored = []
    for lu in saved_lineups:
        rows = [{**r, "actual": actual(r)} for r in lu["players"]]
        scored.append({**lu, "players": rows, "actual": round(sum(r["actual"] for r in rows), 2)})

    pool = [{**{f: getattr(p, f) for f in _HINDSIGHT_FIELDS}, "actual": actual(p)} for p in players]
    best = optimize(pool, slate_type, "actual", hindsight=True)
    hindsight = None
    if best:
        rows = [{"slot": slot, **p} for slot, p in zip(_slots(slate_type), best)]
        hindsight = {
            "metric": "actual",
            "label": "Best possible (actual)",
            "players": rows,
            "salary": sum(r["salary"] for r in rows),
            "actual": round(sum(r["actual"] for r in rows), 2),
        }
    return scored, hindsight


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
    data["_readme"] = (
        "Optimal DraftKings lineups per season/week/slate as they stood before that slate's first kickoff "
        "(app/optimal.py): written automatically while a slate is still open, frozen once it starts, then "
        "scored with actual points (per player and lineup) plus a hindsight best-possible lineup once "
        "every game is final."
    )
    weeks = data.setdefault(str(season), {})
    weeks.setdefault(str(week), {})[slate_id] = entry
    data[str(season)] = {w: weeks[w] for w in sorted(weeks, key=int)}
    tmp = OPTIMAL_LINEUPS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, OPTIMAL_LINEUPS_PATH)


def _response(status: str, entry: dict | None) -> dict:
    entry = entry or {}
    return {
        "status": status,
        "saved_at": entry.get("saved_at"),
        "results_at": entry.get("results_at"),
        "lineups": entry.get("lineups", []),
        "hindsight": entry.get("hindsight"),
    }


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
        return _response("live", saved if lineups else None) | {"lineups": lineups}

    if saved and saved.get("results_at"):
        return _response("final", saved)

    if slate.available:
        actuals = await nc.get_week_actuals(season, week)
        if slate_complete(slate, actuals):
            players = (await slates_module.get_slate_players(season, week, slate_id)).players
            scored, hindsight = score_results((saved or {}).get("lineups", []), players, slate.slate_type, actuals)
            if hindsight:
                saved = {
                    "saved_at": (saved or {}).get("saved_at"),
                    "draft_group_id": slate.draft_group_id,
                    "lineups": scored,
                    "hindsight": hindsight,
                    "results_at": now.isoformat(timespec="seconds"),
                }
                save(season, week, slate_id, saved)
                return _response("final", saved)

    return _response("saved" if saved else "none", saved)
