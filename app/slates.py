"""Orchestrates the pieces: real Week N schedule (app.schedule) + real
DraftKings draft groups (app.dk_client) + real Sleeper projections
(app.sleeper_client), merged by name (app.matching) into the table the
frontend renders.

One Classic slate always covers every game in the week. One Showdown slate
is built for each isolated Wednesday/Thursday/Sunday/Monday night game.
"""
from __future__ import annotations

import time

from app import dk_client, matching, sleeper_client
from app.config import TTL_PLAYERS
from app.models import Game, Player, Slate, SlatePlayers, WeekSchedule
from app.schedule import get_week_schedule

_ISOLATED_ORDER = ["WED_NIGHT", "THU_NIGHT", "SUN_NIGHT", "MON_NIGHT"]

_sleeper_index_cache: dict = {"index": None, "ts": 0.0}


async def _get_sleeper_index() -> matching.SleeperNameIndex:
    now = time.time()
    if _sleeper_index_cache["index"] is None or now - _sleeper_index_cache["ts"] > TTL_PLAYERS:
        players = await sleeper_client.get_players()
        _sleeper_index_cache["index"] = matching.SleeperNameIndex(players)
        _sleeper_index_cache["ts"] = now
    return _sleeper_index_cache["index"]


async def list_slates(season: int, week: int) -> tuple[WeekSchedule, list[Slate]]:
    schedule = await get_week_schedule(season, week)
    discovery = await dk_client.discover_draft_groups(schedule)

    slates: list[Slate] = []

    classic = discovery["classic"]
    slates.append(
        Slate(
            slate_id="classic",
            label=classic["label"],
            slate_type="classic",
            day_part=None,
            draft_group_id=classic["draft_group_id"],
            games=schedule.games,
            available=classic["draft_group_id"] is not None,
            source=classic["source"],
        )
    )

    games_by_day_part = {g.day_part: g for g in schedule.isolated_games}
    for day_part in _ISOLATED_ORDER:
        game = games_by_day_part.get(day_part)
        sd = discovery["showdown"].get(day_part)
        if game is None or sd is None:
            continue
        slates.append(
            Slate(
                slate_id=f"showdown_{day_part.lower()}",
                label=sd["label"],
                slate_type="showdown",
                day_part=day_part,
                draft_group_id=sd["draft_group_id"],
                games=[game],
                available=sd["draft_group_id"] is not None,
                source=sd["source"],
            )
        )

    return schedule, slates


async def get_slate_players(season: int, week: int, slate_id: str) -> SlatePlayers:
    _schedule, slates = await list_slates(season, week)
    slate = next((s for s in slates if s.slate_id == slate_id), None)
    if slate is None:
        raise ValueError(f"Unknown slate_id: {slate_id}")

    if not slate.available or slate.draft_group_id is None:
        return SlatePlayers(slate=slate, players=[], unmatched_dk_names=[], match_count=0, total_count=0)

    raw = await dk_client.fetch_draftables(slate.draft_group_id)
    rows = dk_client.parse_draftables(raw, slate.slate_type)

    projections = await sleeper_client.get_projections(season, week)
    index = await _get_sleeper_index()

    players: list[Player] = []
    unmatched: list[str] = []

    for row in rows:
        sleeper_id = index.find(row["name"], row["team"], row["position"])
        if sleeper_id is None:
            unmatched.append(row["name"])

        sleeper_proj = projections.get(sleeper_id) if sleeper_id else None
        # DraftKings' own FPPG is the reliably-populated projection source;
        # Sleeper's week-specific projection is merged in as a bonus column
        # when present (see sleeper_client.get_projections for why it's
        # usually unavailable).
        base_proj = row["dk_fppg"] or 0.0

        is_captain = row["roster_slot"] == "CPT"
        effective_proj = round(base_proj * 1.5, 2) if is_captain else base_proj
        salary = row["salary"]
        value = round(effective_proj / (salary / 1000.0), 2) if salary > 0 else 0.0

        players.append(
            Player(
                name=row["name"],
                team=row["team"],
                opponent=row["opponent"],
                position=row["position"],
                roster_slot=row["roster_slot"],
                salary=salary,
                proj_points=effective_proj,
                dk_fppg=row["dk_fppg"],
                sleeper_proj=sleeper_proj,
                value_per_1k=value,
                game_info=row["game_info"],
                injury=row["injury"],
                sleeper_player_id=sleeper_id,
                dk_draftable_id=row["draftable_id"],
            )
        )

    players.sort(key=lambda p: p.salary, reverse=True)

    return SlatePlayers(
        slate=slate,
        players=players,
        unmatched_dk_names=sorted(set(unmatched)),
        match_count=sum(1 for p in players if p.sleeper_player_id),
        total_count=len(players),
    )
