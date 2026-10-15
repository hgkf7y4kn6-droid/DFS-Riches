"""Injury news DraftKings hasn't caught up with, and who starts in place of an
injured quarterback.

DraftKings' draftables feed can list a player "Healthy" for a day or more after
his team rules him out. ESPN's league-wide injury feed (one small request,
cached 15 minutes) updates within the hour, so a player DraftKings still shows
Healthy but ESPN lists Out / IR / Doubtful takes ESPN's designation.

Sleeper zeroes an injured quarterback's projection as soon as he's ruled out,
but can take a day to project his replacement. Until it does, the team's
next-up quarterback (the highest-salaried healthy one: DraftKings prices the
expected starter) is projected at REPLACEMENT_SHARE of the injured starter's
season average.
"""
from __future__ import annotations

import logging

import httpx

from app.cache import memoize_async
from app.matching import normalize_name

log = logging.getLogger(__name__)

# ESPN designation -> DraftKings' code. Questionable isn't applied: it doesn't change
# whether a player is playable, and DraftKings posts it with the official report.
DK_CODE = {"Out": "OUT", "IR": "IR", "PUP": "OUT", "Suspended": "OUT", "Doubtful": "D"}
REPLACEMENT_SHARE = 0.75
NOT_PLAYING = {"OUT", "IR", "D"}


@memoize_async(60 * 15)
async def espn_statuses() -> dict[tuple[str, str], dict]:
    """{(team, normalized name): {"code", "status", "updated"}} for players ESPN lists Out/IR/Doubtful."""
    from app.big_picture import rosters
    try:
        async with httpx.AsyncClient() as client:
            data = await rosters.espn_injuries(client)
    except Exception as exc:                   # news is a bonus: DraftKings' own designations still stand
        log.warning("ESPN injuries unavailable: %s", exc)
        return {}
    out = {}
    for team, players in data.items():
        for p in players.values():
            code = DK_CODE.get(p.get("status"))
            if code and p.get("name"):
                out[(team, normalize_name(p["name"]))] = {"code": code, "status": p["status"], "updated": p.get("updated")}
    return out


def apply_news(players, news: dict) -> None:
    """Players DraftKings lists Healthy but ESPN lists Out/IR/Doubtful take ESPN's designation."""
    for p in players:
        if p.injury not in (None, "", "Healthy"):
            continue
        n = news.get((p.team, normalize_name(p.name)))
        if n:
            p.injury = n["code"]
            p.proj_notes = p.proj_notes + [f"ESPN lists him {n['status']} (DraftKings still shows Healthy)"]


def zero_out(players) -> None:
    """Players who won't play (Out, IR, Doubtful -- the statuses app.roles treats as out) project to zero:
    no points, no ceiling, no value, so neither the optimizer nor the tables count on them."""
    from app.roles import PLAYABLE
    for p in players:
        if p.injury in PLAYABLE:
            continue
        if p.proj_points or p.ceiling or p.value_per_1k:
            p.proj_notes = p.proj_notes + [f"{p.injury}: projection zeroed (was {p.proj_points:.1f})"]
            p.ceiling_notes = p.ceiling_notes + [f"{p.injury}: ceiling zeroed"]
        p.proj_points, p.ceiling, p.value_per_1k = 0.0, 0.0, 0.0


def replacement_qbs(players) -> list[tuple]:
    """(replacement rows, injured starter) for each team whose quarterback is out and whose
    healthy quarterbacks have no projection yet."""
    by_team: dict[str, list] = {}
    for p in players:
        if p.position == "QB":
            by_team.setdefault(p.team, []).append(p)
    out = []
    for team, qbs in by_team.items():
        healthy = [p for p in qbs if p.injury not in NOT_PLAYING]
        if not healthy or any(p.proj_points > 0 for p in healthy):
            continue
        injured = [p for p in qbs if p.injury in NOT_PLAYING and (p.trend_season or p.dk_fppg)]
        if not injured:
            continue
        starter = max(injured, key=lambda p: p.trend_season or p.dk_fppg or 0)
        top = max(healthy, key=lambda p: p.salary)
        rows = [p for p in healthy if p.name == top.name]      # Showdown: his CPT and FLEX rows
        out.append((rows, starter))
    return out
