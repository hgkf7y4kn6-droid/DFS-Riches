"""Optimal lineups per slate, and the saved record of them.

Optimal lineups lock player by player, the way a DraftKings contest does:
until a slate's last game kicks off they're recomputed live from the current
data (so news all week -- a QB change on Saturday -- still moves the Full
Week lineups) and written to data/optimal_lineups.json whenever they change.
A player in a lineup whose game has kicked off is locked in that lineup as
it was saved before kickoff (his pre-game numbers, never live ones), and
players from games already underway can't be added -- so in-game results
never leak into a lineup. Once every game has started, only the saved record
is served.

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

# Classic: the Safe lineup (the most projected points: a high floor that cashes often, not a tournament winner) and
# the Tournament lineup (the app's tested tournament construction, app.dfs_strategy: QB + two of his pass catchers +
# an opposing WR, one RB per team, $49,000+ spent, projection with the WR FLEX lean). It replaced the Ceiling lineup:
# on 2026 Weeks 3-6 the Ceiling lineup never beat its own projection. Showdown keeps Proj and Ceiling.
CLASSIC_METRICS = (("proj_points", "Safe lineup (high floor)"), ("tournament", "Tournament lineup (stacked)"))
SHOWDOWN_METRICS = (("proj_points", "Optimal - Proj"), ("ceiling", "Optimal - Ceiling"))
LABELS = {"proj_points": "Safe lineup (high floor)", "tournament": "Tournament lineup (stacked)",
          "ceiling": "Ceiling lineup (retired)"}
METRICS = CLASSIC_METRICS
_FIELDS = (
    "name", "position", "team", "opponent", "roster_slot", "salary", "proj_points",
    "ceiling", "sleeper_proj", "game_info", "injury", "dk_draftable_id", "dk_fppg",
)
STARTER_PROJ = 8.0   # projected at least this many points: expected to have a box-score row
_HINDSIGHT_FIELDS = ("name", "position", "team", "opponent", "roster_slot", "salary", "game_info", "dk_draftable_id")


def _slots(slate_type: str) -> list[str]:
    return ["CPT"] + ["FLEX"] * 5 if slate_type == "showdown" else CLASSIC_SLOTS


def slate_locked(slate, now: datetime) -> bool:
    """Every game has kicked off: nothing left to update."""
    return bool(slate.games) and all(g.kickoff_utc <= now for g in slate.games)


def started_teams(slate, now: datetime) -> set[str]:
    return {t for g in slate.games if g.kickoff_utc <= now for t in (g.away, g.home)}


def slate_complete(slate, actuals: dict) -> bool:
    """Every game final (nflverse games.csv) and both teams' box scores in."""
    reported = set(actuals["teams"])
    return bool(slate.games) and all(
        g.context is not None and g.context.is_final and g.away in reported and g.home in reported
        for g in slate.games
    )


def _tournament(players: list, locked: set) -> list | None:
    """The stacked tournament lineup (app.lineup_builder with the tournament construction rules), loosening the stack
    when the locks or the pool can't support it."""
    from app import dfs_strategy, lineup_builder
    from app.optimizer import ELIGIBLE_STATUSES, MIN_ROLE_PROJ, ROLE_POSITIONS

    pool = []
    for p in players:
        d = {f: _get(p, f) for f in _FIELDS}
        if d["dk_draftable_id"] not in locked and not (
                (d["proj_points"] or 0) > 0 and d["salary"] > 0 and d["injury"] in ELIGIBLE_STATUSES and (d["dk_fppg"] or 0) > 0
                and (d["position"] not in ROLE_POSITIONS or (d["proj_points"] or 0) >= MIN_ROLE_PROJ)):
            continue
        pool.append({**d, "id": d["dk_draftable_id"], "game": d["game_info"], "_src": p})
    if not pool:
        return None
    values = [(r["proj_points"] or 0) + (dfs_strategy.WR_FLEX_BONUS if r["position"] == "WR" else 0) for r in pool]
    for min_salary in (dfs_strategy.GPP_MIN_SALARY, 0):
        base = dict(min_salary=min_salary, one_rb_per_team=True, force=locked or None)
        for kw in (dict(stack=(2, 1), bring_back_pos=("WR",)), dict(stack=(2, 1)), dict(stack=(1, 1)), dict(stack=(1, 0)), {}):
            lu = lineup_builder.build(pool, values, **base, **kw)
            if lu:
                return [r["_src"] for r in lu]
    return None


def build_lineups(players: list, slate_type: str, *, saved: list[dict] | None = None,
                  started: set[str] | None = None) -> list[dict]:
    """The optimal lineup per metric. With games underway (`started` teams),
    each lineup keeps its saved players from those games (locked, with their
    saved pre-kickoff rows) and fills the rest from games not yet started."""
    started = started or set()
    prev = {lu.get("metric"): lu for lu in (saved or [])}
    open_players = [p for p in players if _get(p, "team") not in started]
    out = []
    for metric, label in (SHOWDOWN_METRICS if slate_type == "showdown" else CLASSIC_METRICS):
        locked_rows = [r for r in prev[metric]["players"] if r["team"] in started] if metric in prev and started else []
        locks = {r["dk_draftable_id"] for r in locked_rows}
        if metric == "tournament":
            lineup = _tournament(open_players + locked_rows, locks)
        else:
            lineup = optimize(open_players + locked_rows, slate_type, metric, locked=locks)
        if not lineup:
            if locked_rows:          # can't complete around the locks: keep what was saved
                out.append(prev[metric])
            continue
        lock_ids = {r["dk_draftable_id"] for r in locked_rows}
        rows = [{"slot": slot, **{f: _get(p, f) for f in _FIELDS},
                 **({"locked": True} if _get(p, "dk_draftable_id") in lock_ids else {})}
                for slot, p in zip(_slots(slate_type), lineup)]
        out.append({
            "metric": metric,
            "label": label,
            "players": rows,
            "salary": sum(r["salary"] for r in rows),
            "proj_points": round(sum(r["proj_points"] or 0 for r in rows), 2),
            "ceiling": round(sum(r["ceiling"] or 0 for r in rows), 2),
        })
    return out


def _get(p, name: str):
    return p.get(name) if isinstance(p, dict) else getattr(p, name)


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
            # Players projected for a real role with no box-score row: inactive, or a name that didn't match.
            # Either way they were scored 0, so a human can check the list before trusting the totals.
            "no_box_score": nc.missing_actuals(
                actuals, [{f: getattr(p, f) for f in ("name", "position", "team")} for p in players if (p.proj_points or 0) >= STARTER_PROJ]),
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
        "Optimal DraftKings lineups per season/week/slate (app/optimal.py): written automatically while any "
        "of the slate's games is still to kick off, each player locked (\"locked\": true) once his game "
        "starts, frozen when the last game starts, then scored with actual points (per player and lineup) "
        "plus a hindsight best-possible lineup once every game is final."
    )
    weeks = data.setdefault(str(season), {})
    weeks.setdefault(str(week), {})[slate_id] = entry
    data[str(season)] = {w: weeks[w] for w in sorted(weeks, key=int)}
    tmp = OPTIMAL_LINEUPS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, OPTIMAL_LINEUPS_PATH)


def _relabel(lineups: list[dict], slate_type: str = "classic") -> list[dict]:
    """Saved Classic lineups under their current names (Proj is the Safe lineup; Ceiling is retired)."""
    if slate_type == "showdown":
        return lineups
    return [{**lu, "label": LABELS.get(lu.get("metric"), lu.get("label"))} for lu in lineups]


def _response(status: str, entry: dict | None, slate_type: str = "classic") -> dict:
    entry = entry or {}
    return {
        "status": status,
        "saved_at": entry.get("saved_at"),
        "results_at": entry.get("results_at"),
        "lineups": _relabel(entry.get("lineups", []), slate_type),
        "hindsight": entry.get("hindsight"),
    }


async def get_optimal(season: int, week: int, slate_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    _schedule, slate_list = await slates_module.list_slates(season, week)
    slate = next((s for s in slate_list if s.slate_id == slate_id), None)
    if slate is None:
        raise ValueError(f"Unknown slate_id: {slate_id}")

    saved = load_saved(season, week, slate_id)
    if not slate_locked(slate, now):
        started = started_teams(slate, now)
        players = (await slates_module.get_slate_players(season, week, slate_id)).players
        lineups = build_lineups(players, slate.slate_type, saved=(saved or {}).get("lineups"), started=started)
        if lineups and (saved is None or saved.get("lineups") != lineups):
            saved = {"saved_at": now.isoformat(timespec="seconds"), "draft_group_id": slate.draft_group_id, "lineups": lineups}
            save(season, week, slate_id, saved)
        locked = sum(1 for lu in lineups for r in lu["players"] if r.get("locked"))
        games = sum(1 for g in slate.games if g.kickoff_utc <= now)
        return _response("live", saved if lineups else None, slate.slate_type) | {"lineups": lineups, "locked_players": locked,
                                                                                 "games_started": games}

    if saved and saved.get("results_at"):
        return _response("final", saved, slate.slate_type)

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
                return _response("final", saved, slate.slate_type)

    return _response("saved" if saved else "none", saved, slate.slate_type)


def track_record() -> list[dict]:
    """How the saved optimal lineups did, newest week first: for each finished slate, each lineup's
    projection and actual score, and the best possible (hindsight) score -- the "How we did" page."""
    out = []
    for season, weeks in _load_all().items():
        if not season.isdigit():
            continue
        for week, slates in weeks.items():
            for slate_id, entry in (slates or {}).items():
                scored = [lu for lu in entry.get("lineups") or [] if lu.get("actual") is not None]
                if not scored:
                    continue
                out.append({
                    "season": int(season), "week": int(week), "slate_id": slate_id,
                    "lineups": [{"label": lu.get("label"), "metric": lu.get("metric"), "proj_points": lu.get("proj_points"),
                                 "ceiling": lu.get("ceiling"), "actual": lu.get("actual"), "note": lu.get("note")}
                                for lu in _relabel(scored, "showdown" if slate_id.startswith("showdown") else "classic")],
                    "best_possible": (entry.get("hindsight") or {}).get("actual"),
                })
    return sorted(out, key=lambda r: (-r["season"], -r["week"], r["slate_id"] != "classic_sunday", r["slate_id"]))
