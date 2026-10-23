"""Injury news DraftKings hasn't caught up with, and who starts in place of an
injured quarterback.

DraftKings' draftables feed can list a player "Healthy" for a day or more after
his team rules him out. ESPN's league-wide injury feed (one small request,
cached 15 minutes) updates within the hour, so a player DraftKings still shows
Healthy but ESPN lists Out / IR / Doubtful takes ESPN's designation.

Questionable players: the sources project them as if they'll play, but a Questionable QB/RB/WR/TE with a role has
played 72% of the time (2019-2026). Each one's projection becomes his chance of playing times what he scores when
he does: the chance from his last practice day this week (the club site's official report: Wednesday-Friday
participation), whether he's a quarterback and whether he's an established scorer (scripts/test_injury_trends.py,
data/injury_model.json); the week's direction (DNP -> LP and so on) added nothing beyond the last day. Before the
final report (Friday for a Sunday game) the latest day so far counts half, the rest from the no-practice fit. Once his
game's inactives are out (an hour before kickoff, leaving the feeds half an hour to post
them) and he isn't on them, he plays. Out and Doubtful stay zeroed: they played 0.1% and 1.4% of
the time, whatever their practice week.

Sleeper zeroes an injured quarterback's projection as soon as he's ruled out,
but can take a day to project his replacement. Until it does, the team's
next-up quarterback (the highest-salaried healthy one: DraftKings prices the
expected starter) is projected at REPLACEMENT_SHARE of the injured starter's
season average.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.cache import cached_fetch, memoize_async
from app.matching import normalize_name

log = logging.getLogger(__name__)

# ESPN designation -> DraftKings' code. Questionable isn't applied: it doesn't change
# whether a player is playable, and DraftKings posts it with the official report.
DK_CODE = {"Out": "OUT", "IR": "IR", "PUP": "OUT", "Suspended": "OUT", "Doubtful": "D"}
REPLACEMENT_SHARE = 0.75
NOT_PLAYING = {"OUT", "IR", "D"}
MODEL_FILE = Path(__file__).resolve().parent.parent / "data" / "injury_model.json"
INACTIVES_POSTED = timedelta(minutes=60)    # inactives are due 90 minutes before kickoff; 30 minutes for the feeds to show them
REPORT_TTL = 60 * 30
_MODEL: dict | None = None


def load() -> dict:
    global _MODEL
    if _MODEL is None:
        _MODEL = json.loads(MODEL_FILE.read_text()) if MODEL_FILE.exists() else {}
    return _MODEL


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


PRACTICE_LEVEL = {"DNP": 0, "LP": 1, "FP": 2}


def practice_trend(practice: dict[str, str]) -> dict | None:
    """The week's practice log ({day: DNP | LP | FP}, in order) -> {"log", "last", "trend" (up | flat | down: the last
    day against the first), "days_practiced"}; None with no practice day logged."""
    log_ = [c for c in practice.values() if c in PRACTICE_LEVEL]
    if not log_:
        return None
    first, last = PRACTICE_LEVEL[log_[0]], PRACTICE_LEVEL[log_[-1]]
    return {"log": log_, "last": log_[-1], "trend": "up" if last > first else "down" if last < first else "flat",
            "days_practiced": sum(1 for c in log_ if c != "DNP")}


STAR_AVG = 10.0            # DK points per game: established players play through a Questionable tag more often
PRACTICE_FEATURES = ("dnp", "fp", "qb", "star")
NO_PRACTICE_FEATURES = ("qb", "star")


def chance_features(position: str, last_practice: str | None, season_avg: float | None) -> dict[str, float]:
    """Inputs of the play-chance model (scripts/test_injury_trends.py): last practice day (DNP / FP vs LP), quarterback,
    and a STAR_AVG+ season average."""
    return {"dnp": float(last_practice == "DNP"), "fp": float(last_practice == "FP"), "qb": float(position == "QB"),
            "star": float((season_avg or 0.0) >= STAR_AVG)}


def play_chance(model: dict, position: str, last_practice: str | None, season_avg: float | None) -> float | None:
    """Chance a Questionable player plays, from data/injury_model.json; the no-practice fit when his last practice
    day isn't known."""
    fit = model.get("with_practice" if last_practice in PRACTICE_LEVEL else "without_practice")
    if not fit:
        return None
    f = chance_features(position, last_practice, season_avg)
    z = fit["intercept"] + sum(w * f[k] for k, w in fit["coef"].items())
    return 1 / (1 + math.exp(-z))


async def practice_report(team: str, week: int) -> dict | None:
    """The club site's injury report for the week ({key: {name, practice, game_status, ...}}), cached 30 minutes;
    None when it isn't published or can't be read."""
    from app.big_picture import rosters

    async def fetch():
        async with httpx.AsyncClient(headers=rosters.UA) as client:
            site = await rosters.team_report(client, team, week)
        if site is None:
            raise RuntimeError("no report")          # not cached: try again next time
        return site
    try:
        return await cached_fetch(f"practice_report_{team}_{week}", REPORT_TTL, fetch)
    except Exception:
        return None


async def practice_reports(teams, week: int, timeout: float = 20.0) -> dict[str, dict]:
    """{team: report} for the teams whose report could be read in time."""
    tasks = {t: asyncio.ensure_future(practice_report(t, week)) for t in sorted(set(teams))}
    if not tasks:
        return {}
    done, pending = await asyncio.wait(tasks.values(), timeout=timeout)
    if pending:            # left running: they cache for the next request
        log.warning("club injury reports: %d of %d not back in %.0fs", len(pending), len(tasks), timeout)
    return {t: f.result() for t, f in tasks.items() if f in done and f.result()}


def _entry(reports: dict, p) -> dict | None:
    return (reports.get(p.team) or {}).get(normalize_name(p.name))


def apply_report_statuses(players, reports: dict) -> None:
    """The club's posted game status rules a player out (Out / Doubtful) when DraftKings hasn't caught up."""
    for p in players:
        e = _entry(reports, p)
        code = DK_CODE.get((e or {}).get("game_status") or "")
        if code and p.injury in (None, "", "Healthy", "Q"):
            was = p.injury or "Healthy"
            p.injury = code
            p.proj_notes = p.proj_notes + [f"The team's injury report lists him {e['game_status']} (DraftKings shows {was})"]


def apply_play_chance(players, reports: dict, kickoff: dict[str, datetime], now: datetime | None = None,
                      model: dict | None = None) -> None:
    """Questionable players: projection x his chance of playing x what a Questionable player scores when he plays;
    the ceiling (what he does if he plays) moves only by the latter. Sets play_chance and practice."""
    model = model if model is not None else load()
    if not model:
        return
    now = now or datetime.now(timezone.utc)
    factor = (model.get("if_played") or {}).get("factor", 1.0)
    for p in players:
        if p.injury != "Q" or p.position == "DST":
            continue
        e = _entry(reports, p)
        if e and e.get("game_status_raw") == "(-)":
            p.proj_notes = p.proj_notes + ["The team's final injury report gives him no game status: no Questionable discount"]
            continue
        trend = practice_trend((e or {}).get("practice") or {})
        p.practice = " · ".join(f"{d} {c}" for d, c in ((e or {}).get("practice") or {}).items() if c in PRACTICE_LEVEL) or None
        ko = kickoff.get(p.team)
        if ko is not None and now >= ko - INACTIVES_POSTED:
            chance, why = 1.0, "active: not on his team's inactives"
        else:
            chance = play_chance(model, p.position, trend["last"] if trend else None, p.trend_season)
            if chance is None:
                continue
            final_report = bool(e and e.get("game_status"))
            if trend and not final_report:
                # Mid-week: a Thursday DNP/LP/FP splits players less sharply than the week's last practice
                # (2026: 60% / 69% / 87% played vs 45% / 64% / 91%), so halfway to the no-practice chance.
                chance = (chance + play_chance(model, p.position, None, p.trend_season)) / 2
            why = (f"last practice {trend['last']}{'' if final_report else ' so far'}" if trend else "no practice report read") + (
                ", a quarterback" if p.position == "QB" else "") + (
                f", {p.trend_season:.1f} DK points per game" if p.trend_season else "")
        p.play_chance = round(chance, 2)
        mult = chance * factor
        before = p.proj_points
        p.proj_points = round(p.proj_points * mult, 2)
        p.value_per_1k = round(p.proj_points / (p.salary / 1000.0), 2) if p.salary > 0 else 0.0
        p.proj_notes = p.proj_notes + [
            f"Questionable: plays {chance:.0%} ({why}) x {factor:.2f} (Questionable players who play score "
            f"{1 - factor:.0%} under projection) -> {before:.1f} to {p.proj_points:.1f}"]
        if p.ceiling and factor != 1.0:
            p.ceiling = round(p.ceiling * factor, 1)
            p.ceiling_notes = p.ceiling_notes + [f"Questionable x{factor:.2f}: his ceiling if he plays"]


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
