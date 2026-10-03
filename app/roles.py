"""Each slate player's role on his team: starter, rotation or backup.

Roles let the app sort by matchup without burying starters under a soft
defense's whole depth chart: starters and rotation players first, ordered
by matchup, then everyone else.

Per team and position, among players who can play (not OUT / Doubtful / IR):
  starter   the top N by this week's projection (QB 1, RB 1, WR 3, TE 1;
            every DST). Projection already reflects injuries and depth-chart
            news, so a backup stepping in for an injured starter moves up.
  rotation  anyone else with a real share of the work: recent snap share at
            or above the position's bar (RB 35%, WR 50%, TE 45%) *and* real
            usage on those snaps (RB 6 carries + targets a game, WR 4
            targets, TE 3 -- so a blocking fullback or TE doesn't count), or
            a projection at least RB 55% / WR 60% / TE 60% of the starter's.
            Covers committee backfields (two backs splitting snaps) and
            near-every-down WR4s and TE2s.
  backup    everyone else.
  out       can't play this week.

Snap share is the average offensive snap % over the player's last 3 games
(app.player_games), this season first.
"""
from __future__ import annotations

from app import nflverse_client as nc

STARTERS = {"QB": 1, "RB": 1, "WR": 3, "TE": 1}
ROTATION_SNAP_PCT = {"RB": 35.0, "WR": 50.0, "TE": 45.0}
ROTATION_PROJ_SHARE = {"RB": 0.55, "WR": 0.60, "TE": 0.60}
ROTATION_OPPS = {"RB": 6.0, "WR": 4.0, "TE": 3.0}       # carries + targets per game
PLAYABLE = {None, "", "Healthy", "Q"}
RECENT_GAMES = 3


def recent_usage(index: dict, season: int, week: int, name: str, position: str) -> tuple[float | None, float | None]:
    """(average offensive snap %, average carries + targets per game) over the
    player's last 3 games before the week -- this season's games when he has any."""
    if position not in STARTERS:
        return None, None
    games = [g for g in index["players"].get(nc.player_key(name, position), []) if (g["season"], g["week"]) < (season, week)]
    this = [g for g in games if g["season"] == season]
    use = (this or games)[-RECENT_GAMES:]
    if not use:
        return None, None
    snaps = [g["snap_pct"] for g in use if g.get("snap_pct") is not None]
    opps = [(g["stats"].get("rushing") or {}).get("att", 0) + (g["stats"].get("receiving") or {}).get("tgt", 0) for g in use]
    return (round(sum(snaps) / len(snaps), 1) if snaps else None), round(sum(opps) / len(opps), 1)


def assign(players: list[dict]) -> dict[tuple[str, str, str], str]:
    """players: [{name, team, position, proj, injury, snap_pct, opps}] (one entry per
    player -- Showdown's CPT/FLEX duplicates removed). Returns
    {(name, team, position): role}."""
    roles: dict[tuple[str, str, str], str] = {}
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in players:
        key = (p["name"], p["team"], p["position"])
        if p.get("injury") not in PLAYABLE:
            roles[key] = "out"
        elif p["position"] not in STARTERS:
            roles[key] = "starter"            # DST (and Showdown kickers)
        else:
            groups.setdefault((p["team"], p["position"]), []).append(p)
    for (_team, pos), group in groups.items():
        group.sort(key=lambda p: -(p.get("proj") or 0))
        n = STARTERS[pos]
        starters, rest = group[:n], group[n:]
        bar = (starters[-1].get("proj") or 0) * ROTATION_PROJ_SHARE.get(pos, 1.0)
        for p in starters:
            roles[(p["name"], p["team"], pos)] = "starter"
        for p in rest:
            snaps, opps = p.get("snap_pct"), p.get("opps")
            on_field = snaps is not None and snaps >= ROTATION_SNAP_PCT.get(pos, 101) and (opps or 0) >= ROTATION_OPPS.get(pos, 0)
            involved = pos != "QB" and (on_field or (bar > 0 and (p.get("proj") or 0) >= bar))
            roles[(p["name"], p["team"], pos)] = "rotation" if involved else "backup"
    return roles
