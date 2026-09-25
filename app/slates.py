"""Orchestrates the pieces: real Week N schedule (app.schedule) + real
DraftKings draft groups (app.dk_client) + real Sleeper projections
(app.sleeper_client), merged by name (app.matching) into the table the
frontend renders.

A Classic Sunday Main slate covers the Sunday 1:00 + afternoon games; a Full
Week slate covers every game (Thu-Mon). One Showdown slate is built for each
isolated Wednesday/Thursday/Sunday/Monday night game.
"""
from __future__ import annotations

from datetime import datetime

from app import ceiling, dk_client, matching, nflverse_client, projections, sleeper_client
from app.cache import memoize_async
from app.config import TTL_PLAYERS
from app.models import Player, Slate, SlatePlayers, WeekSchedule
from app.schedule import get_week_schedule

_ISOLATED_ORDER = ["WED_NIGHT", "THU_NIGHT", "SUN_NIGHT", "MON_NIGHT"]


@memoize_async(TTL_PLAYERS)
async def _get_sleeper_index() -> matching.SleeperNameIndex:
    players = await sleeper_client.get_players()
    return matching.SleeperNameIndex(players)


@memoize_async(30)  # just long enough to cover one page load's schedule+slates+players calls
async def list_slates(season: int, week: int) -> tuple[WeekSchedule, list[Slate]]:
    schedule = await get_week_schedule(season, week)
    discovery = await dk_client.discover_draft_groups(schedule)

    slates: list[Slate] = []

    sunday = discovery["classic_sunday"]
    first, last = sunday.get("first_kickoff"), sunday.get("last_kickoff")
    sunday_games = [
        g for g in schedule.games
        if g.day_part in dk_client.SUNDAY_DAY_PARTS
        and (first is None or g.kickoff_utc >= datetime.fromisoformat(first))
        and (last is None or g.kickoff_utc <= datetime.fromisoformat(last))
    ]
    slates.append(
        Slate(
            slate_id="classic_sunday",
            label=sunday["label"],
            slate_type="classic",
            day_part=None,
            draft_group_id=sunday["draft_group_id"],
            games=sunday_games,
            available=sunday["draft_group_id"] is not None,
            source=sunday["source"],
        )
    )

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


@memoize_async(60)
async def get_slate_players(season: int, week: int, slate_id: str) -> SlatePlayers:
    _schedule, slates = await list_slates(season, week)
    slate = next((s for s in slates if s.slate_id == slate_id), None)
    if slate is None:
        raise ValueError(f"Unknown slate_id: {slate_id}")

    if not slate.available or slate.draft_group_id is None:
        return SlatePlayers(slate=slate, players=[], unmatched_dk_names=[], match_count=0, total_count=0)

    raw = await dk_client.fetch_draftables(slate.draft_group_id)
    rows = dk_client.parse_draftables(raw, slate.slate_type)

    sleeper_points = await sleeper_client.get_projections(season, week)
    index = await _get_sleeper_index()
    player_trailing_index = await nflverse_client.get_player_trailing_index(season)
    team_dst_trailing_index = await nflverse_client.get_team_dst_trailing_index(season)
    ceiling_ctx = await ceiling.context_for(season, week)
    projection_ctx = await projections.build_context(season, week)

    players: list[Player] = []
    unmatched: list[str] = []

    for row in rows:
        sleeper_id = index.find(row["name"], row["team"], row["position"])
        if sleeper_id is None:
            unmatched.append(row["name"])

        sleeper_proj = sleeper_points.get(sleeper_id) if sleeper_id else None
        base_proj, proj_notes = projections.project(
            projection_ctx, sleeper_id=sleeper_id, position=row["position"], opponent=row["opponent"], fallback=row["dk_fppg"])

        is_captain = row["roster_slot"] == "CPT"
        if is_captain and sleeper_proj is not None:
            sleeper_proj = round(sleeper_proj * 1.5, 2)
        effective_proj = round(base_proj * 1.5, 2) if is_captain else base_proj
        if is_captain:
            proj_notes = proj_notes + ["Captain x1.50"]
        salary = row["salary"]
        value = round(effective_proj / (salary / 1000.0), 2) if salary > 0 else 0.0

        if row["position"] == "DST":
            trend_args = dict(team_index=team_dst_trailing_index, team=row["team"])
            trend_fn = nflverse_client.trailing_dst_points
        else:
            trend_args = dict(player_index=player_trailing_index, name=row["name"], position=row["position"])
            trend_fn = nflverse_client.trailing_dk_fppg
        trend_l3 = trend_fn(season, week, 3, **trend_args)
        trend_l6 = trend_fn(season, week, 6, **trend_args)
        trend_l9 = trend_fn(season, week, 9, **trend_args)

        player_ceiling, ceiling_notes = ceiling.player_ceiling(
            ceiling_ctx,
            name=row["name"],
            position=row["position"],
            team=row["team"],
            opponent=row["opponent"],
            fallback_mean=row["dk_fppg"],
        )
        if player_ceiling is not None and not projections.has_projected_role(projection_ctx, sleeper_id, row["position"]):
            player_ceiling = round(player_ceiling * 0.5, 1)
            ceiling_notes = ceiling_notes + ["Role x0.50: no meaningful projected stat line this week (backup or inactive)"]
        if is_captain and player_ceiling is not None:
            player_ceiling = round(player_ceiling * 1.5, 1)
            ceiling_notes = ceiling_notes + ["Captain x1.50"]

        players.append(
            Player(
                name=row["name"],
                team=row["team"],
                opponent=row["opponent"],
                position=row["position"],
                roster_slot=row["roster_slot"],
                salary=salary,
                proj_points=effective_proj,
                proj_notes=proj_notes,
                dk_fppg=row["dk_fppg"],
                sleeper_proj=sleeper_proj,
                trend_l3=trend_l3,
                trend_l6=trend_l6,
                trend_l9=trend_l9,
                ceiling=player_ceiling,
                ceiling_notes=ceiling_notes,
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
