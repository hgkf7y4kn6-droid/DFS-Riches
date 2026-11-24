"""Outside sources' calls for a week, blended into the model where their record earns it.

Files in data/outside/ (written by scripts.import_outside_w11 for Week 11 from the pasted articles):

  {season}_w{week}_footballers.json   The Fantasy Footballers: projections (two sets: the ownership-notes tables "a" and the
                                      optimizer view "b"), ceilings, and projected ownership.
  {season}_w{week}_sharp.json         Sharp Football: calls and role notes (no projections or ownership), kept as text.
  blend_weights.json                  How much of the Footballers' projection to take, by position, from the weeks graded so far
                                      (scripts.outside_blend_weights): one week, so capped at 0.3, and none at a position where
                                      the model was the more accurate.

What changes:
  * Projections. A player the Footballers project gets p.outside_proj (their projection, scaled by the same chance-to-play factor
    as ours if he's Questionable). proj_points in the slate and "final" in the DFS model move that weight of the way to it.
  * Ownership. Their projected ownership goes into the Bayesian ownership model as a "source" observation (ensure_ownership), so
    the ownership posterior, and the leverage and chalk lists built on it, use it.
  * Sharp: informational notes on the player (no numbers move: it publishes no projections to grade).
Only the classic slate the files name is touched. Without files for the week, everything here is a no-op.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from app.config import DATA_DIR
from app.matching import normalize_name

log = logging.getLogger(__name__)

DIR = DATA_DIR / "outside"
FOOTBALLERS = "The Fantasy Footballers"
SHARP = "Sharp Football"
SKILL_AND_QB = ("QB", "RB", "WR", "TE", "DST")


def data_version() -> tuple:
    """Changes when a file in data/outside/ does: part of the DFS model's cache key."""
    try:
        return tuple(int(p.stat().st_mtime) for p in sorted(DIR.glob("*.json")))
    except OSError:
        return ()


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _key(name: str, team: str, pos: str) -> tuple:
    """(position, team, first initial, last name token): 'D. Prescott' and 'Dak Prescott' agree; a DST is just its team."""
    if pos == "DST":
        return ("DST", team, "", "")
    toks = normalize_name(name).split()
    return (pos, team, toks[0][:1] if toks else "", toks[-1] if toks else "")


@lru_cache(maxsize=8)
def _book(season: int, week: int, stamp: tuple) -> dict:
    foot = _read(DIR / f"{season}_w{week}_footballers.json")
    sharp = _read(DIR / f"{season}_w{week}_sharp.json")
    by_key: dict = {}
    for r in foot.get("records", []):
        by_key.setdefault(_key(r["name"], r["team"], r["pos"]), []).append(r)
    notes = {_key(n["name"], n["team"], n["pos"]): n for n in sharp.get("notes", [])}
    return {"foot": by_key, "slate": foot.get("slate") or sharp.get("slate"), "sharp": notes,
            "weights": _read(DIR / "blend_weights.json").get("weights", {})}


def book(season: int, week: int) -> dict:
    return _book(season, week, data_version())


def weight(season: int, week: int, pos: str) -> float:
    return float(book(season, week)["weights"].get(pos, 0.0))


def footballers(season: int, week: int, name: str, team: str, pos: str) -> dict | None:
    """{"proj": mean of the sets' projections, "ceil", "own"} for a player the Footballers list, else None."""
    recs = book(season, week)["foot"].get(_key(name, team, pos))
    if not recs:
        return None
    projs = [r["proj"] for r in recs if r.get("proj") is not None]
    owns = {r["set"]: r["own"] for r in recs if r.get("own") is not None}
    ceils = [r["ceil"] for r in recs if r.get("ceil")]
    return {"proj": sum(projs) / len(projs) if projs else None, "ceil": ceils[0] if ceils else None,
            "own": owns.get("a", owns.get("b"))}


def sharp_note(season: int, week: int, name: str, team: str, pos: str) -> str | None:
    n = book(season, week)["sharp"].get(_key(name, team, pos))
    if not n:
        return None
    label = {"core": "core play", "tournament": "tournament play", "note": "note"}.get(n["view"], n["view"])
    return f"Sharp Football ({label}): {n['note']}"


def apply_to_players(players: list, season: int, week: int, slate_id: str, *, play_factor) -> None:
    """Sets p.outside_proj / p.outside_notes and moves proj_points toward the Footballers' projection. play_factor(p) is the
    chance-to-play multiplier already in a Questionable player's projection (1.0 for everyone else)."""
    b = book(season, week)
    if not b["foot"] and not b["sharp"] or b["slate"] not in (None, slate_id):
        return
    for p in players:
        if p.roster_slot == "CPT" or p.position not in SKILL_AND_QB:
            continue
        if note := sharp_note(season, week, p.name, p.team, p.position):
            p.outside_notes = p.outside_notes + [note]
        f = footballers(season, week, p.name, p.team, p.position)
        if not f or f["proj"] is None or f["proj"] <= 0 or (p.proj_points or 0) <= 0:
            continue
        theirs = round(f["proj"] * play_factor(p), 2)
        p.outside_proj = theirs
        w = weight(season, week, p.position)
        p.outside_weight = w
        if w <= 0:
            p.proj_notes = p.proj_notes + [f"{FOOTBALLERS} project {theirs:.1f}; not blended (the model was the more accurate at {p.position} in Week 9)"]
            continue
        before = p.proj_points
        p.proj_points = round((1 - w) * before + w * theirs, 2)
        p.value_per_1k = round(p.proj_points / (p.salary / 1000.0), 2) if p.salary > 0 else 0.0
        if p.ceiling and before > 0:
            p.ceiling = round(p.ceiling * p.proj_points / before, 1)
        p.proj_notes = p.proj_notes + [f"{FOOTBALLERS} project {theirs:.1f}; {w:.0%} of the way there (their Week 9 projections beat the "
                                       f"model at {p.position}) -> {before:.1f} to {p.proj_points:.1f}"]


def blend_final(final: float, outside: float | None, w: float) -> tuple[float, float]:
    """(blended final, change) for the DFS model's "final" projection: w of the way to the outside projection."""
    if not outside or outside <= 0 or w <= 0 or not final:
        return final, 0.0
    delta = w * (outside - final)
    return final + delta, delta


async def ensure_ownership(season: int, week: int, slate_id: str) -> int:
    """Puts the Footballers' projected ownership into the slate's ownership store once (idempotent): the Bayesian ownership model
    reads it as a "source". Returns how many observations were added."""
    from app import ownership_slate, ownership_store
    b = book(season, week)
    if not b["foot"] or b["slate"] not in (None, slate_id):
        return 0
    if any(o.get("source") == FOOTBALLERS and o.get("kind") == "source" for o in ownership_store.load(season, week, slate_id)["observations"]):
        return 0
    players, _meta = await ownership_slate.players_for(season, week, slate_id)
    index: dict = {}
    for p in players:
        if p["position"] in SKILL_AND_QB and p.get("roster_slot", "") != "CPT":
            index.setdefault(_key(p["name"], p["team"], p["position"]), []).append(p)
    entries = []
    for k, recs in b["foot"].items():
        owns = {r["set"]: r["own"] for r in recs if r.get("own") is not None}
        cand = index.get(k) or []
        if len(cand) != 1 or not owns:
            continue
        entries.append({"name": cand[0]["name"], "team": cand[0]["team"], "pct": owns.get("a", owns.get("b"))})
    if not entries:
        return 0
    res = ownership_store.add_observations(season, week, slate_id, "source", "gpp", entries, players, source=FOOTBALLERS)
    log.info("outside ownership: %s added, %s unmatched", res["added"], len(res["unmatched"]))
    return res["added"]
