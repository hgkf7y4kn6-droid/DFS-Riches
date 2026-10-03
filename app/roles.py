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

Snap share and usage are weighted averages over the player's last 3 games
this season (app.player_games), the latest counting most (3:2:1), so roles
move with the depth chart week to week. With no games yet this season, last
season's games carry over only for a player still on the same team.

Usage trend (RB/WR/TE): the latest game against the up-to-3 games before it
this season. "up" when his snap share rose 12+ points, or rose 5+ points
alongside 8+ more carries + targets; "down" for the mirror image. Only for
players with a real role (30%+ of snaps in either span) -- target swings on
steady snaps are game script, not a role change. A single game's snaps
swing with blowouts, so receivers and tight ends keep a trend only when a
teammate at the position moved the other way (a real rotation change) or
the swing is 20+ points; running backs keep theirs.

Genuine role shifts (the Cash/GPP "Role shifts" card) are the trends whose
latest game is a new high (or low) for the season by 8+ snap points -- not
a bounce back from one odd game -- with more than one game's evidence:
  linked     a teammate at the position moved the other way -- work moved
             from one player to another, not just a blowout
  sustained  the last two games both broke from the games before them
             (8+ snap points, same direction)
  big        a 20+ point snap swing with usage (carries + targets) moving
             the same way by 3+ When
a teammate at the position moved the other way, the note names him -- a
backfield shifting from one back to another.
"""
from __future__ import annotations

from app import nflverse_client as nc

STARTERS = {"QB": 1, "RB": 1, "WR": 3, "TE": 1}
ROTATION_SNAP_PCT = {"RB": 35.0, "WR": 50.0, "TE": 45.0}
ROTATION_PROJ_SHARE = {"RB": 0.55, "WR": 0.60, "TE": 0.60}
ROTATION_OPPS = {"RB": 6.0, "WR": 4.0, "TE": 3.0}       # carries + targets per game
PLAYABLE = {None, "", "Healthy", "Q"}
RECENT_GAMES = 3
WEIGHTS = (1, 2, 3)               # oldest .. latest of the recent games
TREND_SNAP_PTS = 12.0
TREND_SNAP_WITH_OPPS = 5.0
TREND_OPPS = 8.0
TREND_MIN_SNAPS = 30.0
TREND_SOLO_SNAP_PTS = 20.0        # WR/TE trend without a teammate moving the other way
SUSTAINED_SNAP_PTS = 8.0
BIG_OPPS = 3.0


def _opps(g: dict) -> float:
    return (g["stats"].get("rushing") or {}).get("att", 0) + (g["stats"].get("receiving") or {}).get("tgt", 0)


def _weighted(values: list[float]) -> float:
    w = WEIGHTS[-len(values):]
    return sum(v * k for v, k in zip(values, w)) / sum(w)


def _games(index: dict, season: int, week: int, name: str, position: str) -> list[dict]:
    return [g for g in index["players"].get(nc.player_key(name, position), []) if (g["season"], g["week"]) < (season, week)]


def recent_usage(index: dict, season: int, week: int, name: str, position: str,
                 team: str | None = None) -> tuple[float | None, float | None]:
    """(snap %, carries + targets per game) over the player's last 3 games
    this season, weighted toward the latest. With no games yet this season,
    last season's games for his current `team` only."""
    if position not in STARTERS:
        return None, None
    games = _games(index, season, week, name, position)
    this = [g for g in games if g["season"] == season]
    carry = [g for g in games if g["season"] == season - 1 and team and g["team"] == team]
    use = (this or carry)[-RECENT_GAMES:]
    if not use:
        return None, None
    snaps = [g["snap_pct"] for g in use if g.get("snap_pct") is not None]
    return (round(_weighted(snaps), 1) if snaps else None), round(_weighted([_opps(g) for g in use]), 1)


def _weeks(games: list[dict]) -> str:
    ws = [g["week"] for g in games]
    return f"Week {ws[0]}" if len(ws) == 1 else f"Weeks {ws[0]}-{ws[-1]}"


def usage_trend(index: dict, season: int, week: int, name: str, position: str) -> dict | None:
    """{"direction": "up" | "down", "text": ...} when the latest game this
    season broke from the games before it; None otherwise."""
    if position not in ROTATION_SNAP_PCT:
        return None
    this = [g for g in _games(index, season, week, name, position) if g["season"] == season]
    if len(this) < 2 or week - this[-1]["week"] > 2:     # no recent game: nothing current to report
        return None
    last, prior = this[-1], this[-4:-1]
    prior_snaps = [g["snap_pct"] for g in prior if g.get("snap_pct") is not None]
    if last.get("snap_pct") is None or not prior_snaps:
        return None
    before = sum(prior_snaps) / len(prior_snaps)
    if max(before, last["snap_pct"]) < TREND_MIN_SNAPS:
        return None
    snap_delta = last["snap_pct"] - before
    prior_opps = sum(_opps(g) for g in prior) / len(prior)
    opp_delta = _opps(last) - prior_opps
    if snap_delta >= TREND_SNAP_PTS or (snap_delta >= TREND_SNAP_WITH_OPPS and opp_delta >= TREND_OPPS):
        direction = "up"
    elif snap_delta <= -TREND_SNAP_PTS or (snap_delta <= -TREND_SNAP_WITH_OPPS and opp_delta <= -TREND_OPPS):
        direction = "down"
    else:
        return None
    unit = "carries + targets" if position == "RB" else ("target" if round(_opps(last)) == 1 else "targets")
    parts = [f"{last['snap_pct']:.0f}% of snaps in Week {last['week']} vs {before:.0f}% in {_weeks(prior)}"]
    parts.append(f"{_opps(last):.0f} {unit} vs {prior_opps:.0f} a game before")
    lead = "Role growing" if direction == "up" else "Role shrinking"
    sign = 1 if direction == "up" else -1
    sustained = False
    if len(this) >= 3:
        base = [g["snap_pct"] for g in this[:-2][-3:] if g.get("snap_pct") is not None]
        prev = this[-2].get("snap_pct")
        if base and prev is not None:
            b = sum(base) / len(base)
            sustained = sign * (prev - b) >= SUSTAINED_SNAP_PTS and sign * (last["snap_pct"] - b) >= SUSTAINED_SNAP_PTS
    return {
        "direction": direction,
        "text": f"{lead}: " + "; ".join(parts) + ".",
        "snap_delta": round(snap_delta, 1),
        "opp_delta": round(opp_delta, 1),
        "sustained": sustained,
        "big": abs(snap_delta) >= TREND_SOLO_SNAP_PTS and sign * opp_delta >= BIG_OPPS,
        # a new season high (up) / low (down), not a return from one odd game
        "new_level": sign * (last["snap_pct"] - (max(prior_snaps) if sign > 0 else min(prior_snaps))) >= SUSTAINED_SNAP_PTS,
        "series": [{"week": g["week"], "snap_pct": g.get("snap_pct"), "opps": _opps(g)} for g in this[-4:]],
        "unit": "carries + targets" if position == "RB" else "targets",
    }


def link_shifts(trends: dict[tuple[str, str, str], dict]) -> dict[tuple[str, str, str], dict]:
    """Name the teammate on the other side of a shift (a back trending up
    "taking work from" one trending down at the same team and position) and
    drop receiver/tight-end trends that are likely just one game's script."""
    kept = {}
    for (name, team, pos), t in trends.items():
        others = [n2 for (n2, t2, p2), o in trends.items()
                  if t2 == team and p2 == pos and n2 != name and o["direction"] != t["direction"]]
        if pos != "RB" and not others and abs(t["snap_delta"]) < TREND_SOLO_SNAP_PTS:
            continue
        t = {**t, "partners": others}
        if others:
            verb = "taking work from" if t["direction"] == "up" else "losing work to"
            t["text"] = t["text"][:-1] + f", {verb} {' and '.join(others)}."
        t["genuine"] = bool(t.get("new_level")) and (bool(others) or bool(t.get("sustained")) or bool(t.get("big")))
        kept[(name, team, pos)] = t
    return kept


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
