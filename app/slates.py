"""Orchestrates the pieces: real Week N schedule (app.schedule) + real
DraftKings draft groups (app.dk_client) + real Sleeper projections
(app.sleeper_client), merged by name (app.matching) into the table the
frontend renders.

A Classic Sunday Main slate covers the Sunday 1:00 + afternoon games; a Full
Week slate covers every game (Thu-Mon). One Showdown slate is built for each
island game: the lone game in a window outside the Sunday main slate
(weeknight/Sunday night, Sunday-morning international, holiday, Saturday).
"""
from __future__ import annotations

from datetime import datetime

from app import ceiling, ceiling_model, dk_client, dst_model, game_model, injury_news, matching, player_model, nflverse_client, player_games, projections, roles, sleeper_client, weather
from app.cache import memoize_async
from app.config import TTL_PLAYERS
from app.models import Player, Slate, SlatePlayers, WeekSchedule
from app.schedule import get_week_schedule



@memoize_async(TTL_PLAYERS)
async def _get_sleeper_index() -> matching.SleeperNameIndex:
    players = await sleeper_client.get_players()
    return matching.SleeperNameIndex(players)


async def _assign_roles(players: list[Player], season: int, week: int) -> None:
    """Starter / rotation / backup / out per player (app.roles), from projections
    and recent snap share, plus any usage trend (role growing or shrinking).
    Showdown CPT rows share their FLEX row's role."""
    index = await player_games.get_index(season)
    base = {}
    for p in players:
        key = (p.name, p.team, p.position)
        if key not in base or p.roster_slot != "CPT":
            proj = p.proj_points / 1.5 if p.roster_slot == "CPT" else p.proj_points
            snap_pct, opps = roles.recent_usage(index, season, week, p.name, p.position, p.team)
            base[key] = {"name": p.name, "team": p.team, "position": p.position, "proj": proj, "injury": p.injury,
                         "snap_pct": snap_pct, "opps": opps}
    assigned = roles.assign(list(base.values()))
    trends = {}
    for key in base:
        if assigned.get(key) != "out" and (t := roles.usage_trend(index, season, week, key[0], key[2])):
            trends[key] = t
    trends = roles.link_shifts(trends)
    shares = roles.team_shares(index, season, week)
    for p in players:
        key = (p.name, p.team, p.position)
        p.role = assigned.get(key)
        p.snap_pct = base[key]["snap_pct"]
        p.usage_trend = trends.get(key)
        p.team_share = shares.get((nflverse_client.player_key(p.name, p.position), p.team)) if p.position in roles.SKILL else None


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

    for game in sorted(schedule.isolated_games, key=lambda g: g.kickoff_utc):
        day_part = game.day_part
        sd = discovery["showdown"].get(day_part)
        if sd is None:
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


def _recent_points(ctx, name: str, position: str, season: int, week: int) -> list[float]:
    """DK points of a player's regular-season games (last season and this one) before `week`, oldest first."""
    entries = ctx.players.get(nflverse_client.player_key(name, position), [])
    return [e[2] for e in sorted(entries) if (e[0], e[1]) < (season, week) and e[1] <= 18][-ceiling_model.HISTORY_GAMES:]


@memoize_async(60)
async def get_slate_players(season: int, week: int, slate_id: str) -> SlatePlayers:
    _schedule, slates = await list_slates(season, week)
    slate = next((s for s in slates if s.slate_id == slate_id), None)
    if slate is None:
        raise ValueError(f"Unknown slate_id: {slate_id}")

    if not slate.available or slate.draft_group_id is None:
        return SlatePlayers(slate=slate, players=[], unmatched_dk_names=[], match_count=0, total_count=0)

    raw = await dk_client.fetch_draftables(slate.draft_group_id)
    # Only the slate's own games: a no-op for its own draft group, and how a Sunday
    # Main DraftKings no longer serves is rebuilt from that week's Full Week group
    # (same players, salaries and ids -- data/dk_overrides.json).
    slate_teams = {t for g in slate.games for t in (g.away, g.home)}
    rows = [r for r in dk_client.parse_draftables(raw, slate.slate_type) if r["team"] in slate_teams]

    sleeper_points = await sleeper_client.get_projections(season, week)
    index = await _get_sleeper_index()
    player_trailing_index = await nflverse_client.get_player_trailing_index(season)
    team_dst_trailing_index = await nflverse_client.get_team_dst_trailing_index(season)
    ceiling_ctx = await ceiling.context_for(season, week)
    projection_ctx = await projections.build_context(season, week)
    team_wx = weather.team_weather(_schedule)

    players: list[Player] = []
    unmatched: list[str] = []
    try:
        role_ctx = await player_model.context(season, week)
    except Exception:
        role_ctx = None
    try:
        team_ctx = await game_model.team_context(season, week)
    except Exception:
        team_ctx = {}
    try:
        dst_rates = await dst_model.context(season, week) if dst_model.load() else {}
    except Exception:
        dst_rates = {}
    team_lines = {}         # team -> (implied total, expected margin)
    for g in slate.games:
        c = g.context
        if c and c.home_spread is not None:
            team_lines[g.home] = (c.home_implied_total, -c.home_spread)
            team_lines[g.away] = (c.away_implied_total, c.home_spread)

    for row in rows:
        sleeper_id = index.find(row["name"], row["team"], row["position"])
        if sleeper_id is None:
            unmatched.append(row["name"])

        # Sleeper's own projected line scored with DraftKings' rules (before
        # matchup/weather adjustments); Sleeper's PPR total if there's no line.
        line = projection_ctx.lines.get(sleeper_id) if sleeper_id else None
        sleeper_proj = projections.dk_points_from_line(line["stats"], row["position"]) if line and line.get("stats") else None
        if not sleeper_proj:
            sleeper_proj = sleeper_points.get(sleeper_id) if sleeper_id else None
        base_proj, proj_notes = projections.project(
            projection_ctx, sleeper_id=sleeper_id, position=row["position"], opponent=row["opponent"], fallback=row["dk_fppg"],
            game_weather=team_wx.get(row["team"]))

        role_adj = dst_adj = None
        role_feats = None
        from_model = False
        imp, spr = team_lines.get(row["team"], (None, None))
        line_pts = projections.dk_points_from_line(line["stats"], row["position"]) if line and line.get("stats") else 0.0
        if role_ctx and row["position"] in player_model.POSITIONS and line_pts >= 3:
            k = player_model.key(row["name"], row["position"])
            tc = team_ctx.get(row["team"]) or {}
            role_feats = player_model.features(
                role_ctx["hist"].get(k), week, line_pts, row["position"], imp, spr, role_ctx["proj_hist"].get(k),
                opp_pressure=tc.get("opp_pressure", 0.0), ol_out=tc.get("ol_out", 0),
                front7_out=tc.get("opp_front7_out", 0))
            role_adj = player_model.adjustment(row["position"], role_feats)
            if role_adj:
                base_proj = round(max(0.0, base_proj + role_adj), 2)
                proj_notes = proj_notes + [f"Role & script model: {role_adj:+.1f} (target, carry and snap share trends; "
                                           f"team total and spread)"]

        if row["position"] == "DST" and line_pts > 0 and dst_rates and row["team"] in team_lines and row["opponent"] in team_lines:
            opp_qb = team_ctx.get(row["opponent"]) or {}
            if opp_qb.get("qb_epa") is not None:
                f = dst_model.features(line_pts, team_lines[row["opponent"]][0], team_lines[row["team"]][1], opp_qb["qb_epa"],
                                       opp_qb.get("qb_dropbacks", 0), dst_rates.get(row["team"]), dst_rates.get(row["opponent"]),
                                       dst_model.load()["pa_sd"])
                if (dst_proj := dst_model.project(f)) is not None:
                    weather_factor = base_proj / line_pts if line_pts else 1.0     # the line's weather adjustment
                    base_proj = round(max(0.0, dst_proj * weather_factor), 2)
                    dst_adj = round(dst_proj - line_pts, 2)
                    proj_notes = proj_notes + [dst_model.note(dst_proj, f, row["opponent"])]

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
            trend_args = dict(player_index=player_trailing_index, name=row["name"], position=row["position"], team=row["team"])
            trend_fn = nflverse_client.trailing_dk_fppg
        trend_l3 = trend_fn(season, week, 3, **trend_args)
        trend_l6 = trend_fn(season, week, 6, **trend_args)
        trend_l9 = trend_fn(season, week, 9, **trend_args)
        trend_season = trend_fn(season, week, 0, **trend_args)

        player_ceiling, ceiling_notes = ceiling.player_ceiling(
            ceiling_ctx,
            name=row["name"],
            position=row["position"],
            team=row["team"],
            opponent=row["opponent"],
            fallback_mean=row["dk_fppg"],
            projection=base_proj,
        )
        if row["position"] in player_model.POSITIONS and line_pts >= 3:
            x = ceiling_model.inputs(row["position"], base_proj, _recent_points(ceiling_ctx, row["name"], row["position"], season, week),
                                     line["stats"], imp, spr, (role_feats or {}).get("ts_l3", 0.0), (role_feats or {}).get("snap_l3", 0.0))
            if (model_ceiling := ceiling_model.ceiling(row["position"], x)) is not None:
                player_ceiling, ceiling_notes = model_ceiling, ceiling_model.notes(model_ceiling, x, row["position"])
                from_model = True
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
                trend_season=trend_season,
                ceiling=player_ceiling,
                ceiling_notes=ceiling_notes,
                value_per_1k=value,
                game_info=row["game_info"],
                injury=row["injury"],
                sleeper_player_id=sleeper_id,
                dk_draftable_id=row["draftable_id"],
                role_adj=role_adj,
                dst_adj=dst_adj,
                ceiling_model=from_model,
            )
        )

    injury_news.apply_news(players, await injury_news.espn_statuses())
    injury_news.zero_out(players)
    for rows, starter in injury_news.replacement_qbs(players):
        base = round((starter.trend_season or starter.dk_fppg) * injury_news.REPLACEMENT_SHARE, 2)
        for p in rows:
            captain = p.roster_slot == "CPT"
            p.proj_points = round(base * 1.5, 2) if captain else base
            p.proj_notes = [f"{starter.name} is out and Sleeper hasn't projected the next-up quarterback yet: "
                            f"{injury_news.REPLACEMENT_SHARE:.0%} of {starter.name}'s {base / injury_news.REPLACEMENT_SHARE:.1f} "
                            f"DK points per game = {base:.1f}"] + (["Captain x1.50"] if captain else [])
            p.value_per_1k = round(p.proj_points / (p.salary / 1000.0), 2) if p.salary > 0 else 0.0
            ceil, notes = ceiling.player_ceiling(ceiling_ctx, name=p.name, position=p.position, team=p.team,
                                                 opponent=p.opponent, fallback_mean=base, projection=base)
            if ceil is not None:
                p.ceiling, p.ceiling_notes = (round(ceil * 1.5, 1), notes + ["Captain x1.50"]) if captain else (ceil, notes)

    await _assign_roles(players, season, week)
    players.sort(key=lambda p: p.salary, reverse=True)

    return SlatePlayers(
        slate=slate,
        players=players,
        unmatched_dk_names=sorted(set(unmatched)),
        match_count=sum(1 for p in players if p.sleeper_player_id),
        total_count=len(players),
    )
