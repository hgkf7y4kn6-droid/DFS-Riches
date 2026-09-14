"""Client for DraftKings' public (unauthenticated, undocumented) contest and
salary endpoints.

Two endpoints matter:
  - GET /draftgroups/v1/
        Lists every "Upcoming" draft group across all sports. For NFL
        (sportId 1) each entry carries a contestType.contestTypeId, a
        games[] list (their count tells us classic full-slate vs. a
        single-game Showdown), and a start-time window we match against the
        real schedule pulled from Sleeper. contestTypeId 96 is DraftKings'
        standard "Showdown Captain Mode" (CPT slot at 1.5x salary/points +
        5 FLEX slots) -- confirmed by inspecting roster slot ids on a known
        Showdown draft group. This listing only contains contests that
        haven't started yet, so once a slate's games kick off its
        draftGroupId disappears from here.
  - GET /draftgroups/v1/draftgroups/{id}/draftables
        The actual player pool + salaries for one draft group. Keeps
        serving already-started/completed slates by id even after they
        vanish from the listing above, which is why app/config.py and
        data/dk_overrides.json carry a manual id fallback for slates that
        already started before this app's discovery ran.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.cache import cached_fetch
from app.config import (
    DK_BASE,
    DK_OVERRIDES_PATH,
    DK_SHOWDOWN_CPT_SLOT_IDS,
    DK_SHOWDOWN_GAME_TYPE_ID,
    TTL_DK_DISCOVERY,
    TTL_DK_DRAFTABLES,
)
from app.models import WeekSchedule

_HEADERS = {"User-Agent": "DFSRiches/1.0 (+https://github.com/)"}

# DraftKings' public contestType.contestTypeId for Showdown Captain Mode.
DK_SHOWDOWN_CONTEST_TYPE_ID = DK_SHOWDOWN_GAME_TYPE_ID


async def _get_json(url: str) -> Any:
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()


async def _fetch_all_nfl_draft_groups() -> list[dict]:
    async def fetch() -> list[dict]:
        data = await _get_json(f"{DK_BASE}/draftgroups/v1/")
        return [d for d in data.get("draftGroups", []) if d.get("sportId") == 1]

    return await cached_fetch("dk_draft_groups_nfl", TTL_DK_DISCOVERY, fetch)


def _load_overrides() -> dict:
    if not DK_OVERRIDES_PATH.exists():
        return {}
    with DK_OVERRIDES_PATH.open() as f:
        return json.load(f)


def _parse_dk_timestamp(value: str) -> datetime | None:
    """DraftKings timestamps look like '2026-09-15T00:15:00.0000000Z' -- 7
    fractional-second digits, which datetime.fromisoformat can't parse
    (it accepts at most 6). Truncate before parsing."""
    try:
        if "." in value:
            head, _, frac_and_zone = value.partition(".")
            frac = frac_and_zone.rstrip("Z")[:6]
            value = f"{head}.{frac}+00:00" if frac else f"{head}+00:00"
        else:
            value = value.rstrip("Z") + "+00:00"
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _team_pair_from_suffix(suffix: str | None) -> tuple[str, str] | None:
    if not suffix:
        return None
    text = suffix.strip(" ()")
    if "@" not in text:
        return None
    away, _, home = text.partition("@")
    return away.strip().upper(), home.strip().upper()


async def discover_draft_groups(schedule: WeekSchedule) -> dict[str, Any]:
    """Returns {"classic": {...}, "showdown": {day_part: {...}}} where each
    leaf is {"draft_group_id": int, "label": str, "source": "live"|"override"} or
    {"draft_group_id": None, "label": str, "source": "unavailable"}.
    """
    result: dict[str, Any] = {"classic": None, "showdown": {}}

    try:
        nfl_groups = await _fetch_all_nfl_draft_groups()
    except Exception:
        nfl_groups = []

    total_games = len(schedule.games)

    # Restrict candidates to draft groups whose window actually overlaps
    # this week's kickoffs -- game-count alone can coincidentally match an
    # unrelated future slate (e.g. a multi-week "Sit & Go" contest).
    if schedule.games:
        week_start = min(g.kickoff_utc for g in schedule.games) - timedelta(hours=12)
        week_end = max(g.kickoff_utc for g in schedule.games) + timedelta(hours=12)
    else:
        week_start = week_end = None

    def _in_week_window(group: dict) -> bool:
        if week_start is None:
            return False
        start = _parse_dk_timestamp(group.get("minStartTime", ""))
        return start is not None and week_start <= start <= week_end

    # --- Classic: the live "Upcoming" full-slate group whose game count
    # matches the number of games we know about this week from Sleeper.
    classic_candidates = [
        g for g in nfl_groups
        if total_games > 0 and len(g.get("games") or []) == total_games and _in_week_window(g)
    ]
    if classic_candidates:
        best = max(classic_candidates, key=lambda g: len(g.get("games") or []))
        result["classic"] = {
            "draft_group_id": best["draftGroupId"],
            "label": f"Classic - Full Week {schedule.week} Slate ({total_games} games)",
            "source": "live",
        }

    # --- Showdown: one live "Upcoming" Showdown Captain Mode group per
    # isolated game, matched by team pair.
    showdown_by_pair: dict[tuple[str, str], dict] = {}
    for g in nfl_groups:
        contest_type_id = (g.get("contestType") or {}).get("contestTypeId")
        if contest_type_id != DK_SHOWDOWN_CONTEST_TYPE_ID:
            continue
        if len(g.get("games") or []) != 1:
            continue
        if not _in_week_window(g):
            continue
        pair = _team_pair_from_suffix(g.get("startTimeSuffix"))
        if pair:
            showdown_by_pair[pair] = g

    for game in schedule.isolated_games:
        pair = (game.away.upper(), game.home.upper())
        match = showdown_by_pair.get(pair)
        if match:
            result["showdown"][game.day_part] = {
                "draft_group_id": match["draftGroupId"],
                "label": f"Showdown - {game.day_part.replace('_', ' ').title()} ({game.away} @ {game.home})",
                "source": "live",
            }

    # --- Fill gaps from the manual override file (already-started/completed
    # slates that no longer appear in the live "Upcoming" listing).
    overrides = _load_overrides()
    season_overrides = overrides.get(str(schedule.season), {}).get(str(schedule.week), {})

    if result["classic"] is None and "classic" in season_overrides:
        ov = season_overrides["classic"]
        result["classic"] = {
            "draft_group_id": ov["draft_group_id"],
            "label": ov.get("label", "Classic"),
            "source": "override",
        }

    for game in schedule.isolated_games:
        if game.day_part in result["showdown"]:
            continue
        ov = season_overrides.get("showdown", {}).get(game.day_part)
        if ov:
            result["showdown"][game.day_part] = {
                "draft_group_id": ov["draft_group_id"],
                "label": ov.get("label", f"Showdown - {game.day_part}"),
                "source": "override",
            }
        else:
            result["showdown"][game.day_part] = {
                "draft_group_id": None,
                "label": f"Showdown - {game.day_part.replace('_', ' ').title()} ({game.away} @ {game.home})",
                "source": "unavailable",
            }

    if result["classic"] is None:
        result["classic"] = {
            "draft_group_id": None,
            "label": f"Classic - Full Week {schedule.week} Slate",
            "source": "unavailable",
        }

    return result


async def fetch_draftables(draft_group_id: int) -> dict:
    async def fetch() -> dict:
        url = f"{DK_BASE}/draftgroups/v1/draftgroups/{draft_group_id}/draftables"
        return await _get_json(url)

    key = f"dk_draftables_{draft_group_id}"
    return await cached_fetch(key, TTL_DK_DRAFTABLES, fetch)


def parse_draftables(raw: dict, slate_type: str) -> list[dict]:
    """Normalize DraftKings draftables into flat rows regardless of slate
    type. For "showdown" slates, only the standard CPT/FLEX roster slots are
    kept (In-Game H2/Q4 and Snake-draft variants use different slot ids and
    are ignored). Classic slates list every player twice -- once under their
    own position slot and once under the shared FLEX slot, both with
    identical salary/stats -- so those are de-duplicated by playerDkId."""
    rows: list[dict] = []
    seen_player_dk_ids: set[int] = set()
    for d in raw.get("draftables", []):
        salary = d.get("salary")
        if salary is None:
            continue  # snake-draft / no-salary variants

        roster_slot_id = d.get("rosterSlotId")
        if slate_type == "showdown":
            # DraftKings' Showdown Captain Mode uses exactly two roster slot
            # ids per draft group (CPT at 1.5x salary/points, FLEX at base).
            roster_slot = "CPT" if roster_slot_id in DK_SHOWDOWN_CPT_SLOT_IDS else "FLEX"
        else:
            roster_slot = ""
            player_dk_id = d.get("playerDkId")
            if player_dk_id in seen_player_dk_ids:
                continue
            seen_player_dk_ids.add(player_dk_id)

        competition = d.get("competition") or {}
        game_info = competition.get("name", "")
        team = (d.get("teamAbbreviation") or "").upper()
        opponent = ""
        if "@" in game_info:
            away, _, home = game_info.partition("@")
            away, home = away.strip().upper(), home.strip().upper()
            opponent = home if team == away else away if team == home else ""

        dk_fppg = None
        for attr in d.get("draftStatAttributes") or []:
            if attr.get("id") == 90:  # FPPG
                try:
                    dk_fppg = float(attr.get("value"))
                except (TypeError, ValueError):
                    dk_fppg = None

        status = (d.get("status") or "None").strip()
        injury = "Healthy" if status in ("", "None") else status

        rows.append(
            {
                "draftable_id": d.get("draftableId"),
                "player_dk_id": d.get("playerDkId"),
                "name": d.get("displayName", "").strip(),
                "team": team,
                "opponent": opponent,
                "position": d.get("position", ""),
                "roster_slot": roster_slot,
                "salary": int(salary),
                "game_info": game_info,
                "injury": injury,
                "dk_fppg": dk_fppg,
            }
        )
    return rows
