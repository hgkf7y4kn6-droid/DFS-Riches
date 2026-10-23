"""Player projection correction: role trends, snap share and game script on top of Sleeper's projection.

For each QB / RB / WR / TE the model predicts (actual DK points - Sleeper's projected DK points) from what the
projection may lag: target share and carry share over the last three games and their change against the
season so far, snap share and its trend, recent production against the projection, the team's implied total
and spread (game script) -- with its own spread term for workhorse pass-catching backs (12+ projected carries and
3.5+ targets), whose scoring swings with game script more than the projection allows -- for running backs the
opponent's front-seven starters out (they beat their projections against a depleted front), for wide receivers the
opponent's starting corners out (they beat their projections against a depleted secondary), for receivers their
average depth of target against the opponent's explosive-play rate allowed (deep threats gain against defenses that
give up big plays, short-area receivers against those that don't), and the projection itself (to correct over- or under-dispersed projections). One
ridge regression per position, fit on 2023-2025 by scripts/train_player_model.py and stored in
data/player_model.json with its out-of-sample record. Every input comes from games before the one projected.
"""
from __future__ import annotations

import asyncio
import json
import statistics
from pathlib import Path

from app import game_model as gm
from app.cache import memoize_async
from app.matching import normalize_name

MODEL_FILE = Path(__file__).resolve().parent.parent / "data" / "player_model.json"
FEATURES = ("proj", "ts_l3", "ts_trend", "cs_l3", "cs_trend", "snap_l3", "snap_trend", "form", "implied", "spread",
            "spread_x_rb", "games", "opp_pressure", "ol_out", "front7_out", "spread_x_wpc",
            "adot_x_opp_explosive", "cb_out_x_wr")
# Also computed but not used: vac_ts / vac_cs / vac_ts_same / vac_cs_rb, the shares vacated by regulars out who played
# the team's last game -- they made held-out errors worse (data/vacated_opportunity_tests.json); app.vacated covers the
# window before Sleeper moves an out player's volume itself.
POSITIONS = ("QB", "RB", "WR", "TE")
MAX_ADJ = 0.35          # never move a projection by more than this share (or 3 points, whichever is larger)
WPC_CARRIES, WPC_TARGETS = 12.0, 3.5     # a workhorse pass-catching back's projected carries and targets
ADOT_CENTER, ADOT_GAMES, ADOT_MIN_GAMES = 10.0, 8, 3     # receivers' air yards per target, over their last 8 games
VAC_TS, VAC_CS = 0.12, 0.25     # a regular: this target or carry share over his last three games
SKILL = ("RB", "WR", "TE")


def team_last_week(hist: dict[str, dict[int, dict]], week: int) -> dict[str, int]:
    """Each team's last game before `week` (any player's history)."""
    out: dict[str, int] = {}
    for h in hist.values():
        for w, x in h.items():
            if w < week and w > out.get(x.get("team"), 0):
                out[x["team"]] = w
    return out


def fresh_regulars(hist: dict[str, dict[int, dict]], week: int) -> dict[str, list[tuple[str, str, float, float]]]:
    """{team: [(player key, position, target share, carry share)]}: RB/WR/TE regulars (VAC_TS / VAC_CS over their
    last three games) who played their team's last game -- the ones whose absence the projections may not have
    caught up with yet."""
    last = team_last_week(hist, week)
    out: dict[str, list] = {}
    for k, h in hist.items():
        pos = k.rsplit("|", 1)[-1]
        if pos not in SKILL:
            continue
        games = sorted(w for w in h if w < week)
        if len(games) < 2:
            continue
        team = h[games[-1]]["team"]
        if games[-1] != last.get(team):
            continue
        l3 = [h[w] for w in games[-3:]]
        ts, cs = statistics.fmean(x["ts"] for x in l3), statistics.fmean(x["cs"] for x in l3)
        if ts >= VAC_TS or cs >= VAC_CS:
            out.setdefault(team, []).append((k, pos, ts, cs))
    return out


def vacated(regulars: list[tuple[str, str, float, float]], is_out) -> dict:
    """The team's vacated shares from its regulars who are out (is_out(key) -> bool): {"ts", "cs", "ts_by_pos",
    "cs_by_pos", "out": [keys]}."""
    v = {"ts": 0.0, "cs": 0.0, "ts_by_pos": {}, "cs_by_pos": {}, "out": []}
    for k, pos, ts, cs in regulars:
        if is_out(k):
            v["ts"] += ts
            v["cs"] += cs
            v["ts_by_pos"][pos] = v["ts_by_pos"].get(pos, 0.0) + ts
            v["cs_by_pos"][pos] = v["cs_by_pos"].get(pos, 0.0) + cs
            v["out"].append(k)
    return v


def key(name: str, position: str) -> str:
    return f"{normalize_name(name)}|{position}"


def history(player_rows: list[dict], snap_rows: list[dict], team_of=lambda t: t, points=None) -> dict[str, dict[int, dict]]:
    """{player key: {week: {"ts", "cs", "snap", "pts", "team", "air", "tgt"}}} from nflverse weekly player stats and
    snap counts. points(row) gives a row's DK points."""
    carries: dict[tuple[int, str], float] = {}
    for r in player_rows:
        if r.get("season_type", "REG") == "REG" and r.get("week"):
            k = (int(r["week"]), team_of(r.get("team") or ""))
            carries[k] = carries.get(k, 0.0) + (gm._f(r.get("carries")) or 0.0)
    snaps: dict[tuple[str, str, int], float] = {}
    for r in snap_rows:
        if r.get("week") and r.get("player"):
            snaps[(normalize_name(r["player"]), team_of(r.get("team") or ""), int(r["week"]))] = gm._f(r.get("offense_pct")) or 0.0
    out: dict[str, dict[int, dict]] = {}
    for r in player_rows:
        pos = r.get("position")
        if pos not in POSITIONS or r.get("season_type", "REG") != "REG" or not r.get("week"):
            continue
        w, team = int(r["week"]), team_of(r.get("team") or "")
        tc = carries.get((w, team)) or 0.0
        out.setdefault(key(r["player_display_name"], pos), {})[w] = {
            "ts": gm._f(r.get("target_share")) or 0.0,
            "cs": (gm._f(r.get("carries")) or 0.0) / tc if tc else 0.0,
            "snap": snaps.get((normalize_name(r["player_display_name"]), team, w)),
            "pts": points(r) if points else None, "team": team,
            "air": gm._f(r.get("receiving_air_yards")) or 0.0, "tgt": gm._f(r.get("targets")) or 0.0}
    return out


def features(h: dict[int, dict] | None, week: int, proj: float, position: str, implied: float | None,
             spread: float | None, proj_hist: dict[int, float] | None = None, opp_pressure: float = 0.0,
             ol_out: float = 0.0, front7_out: float = 0.0, line: dict | None = None, opp_explosive: float = 0.0,
             opp_cb_out: float = 0.0, vac: dict | None = None) -> dict:
    """spread: the team's expected margin (positive = favored); opp_pressure: the opponent's four-man sack + QB-hit
    rate above the league (app.game_model, shrunk toward last season); ol_out: own offensive-line starters out;
    front7_out: the opponent's front-seven starters out (4 linemen + 2 linebackers), an input for running backs;
    line: Sleeper's projected stat line (a workhorse pass-catching back's carries and targets); opp_explosive: the
    opponent's explosive-play rate allowed above the league (app.game_model), an input for receivers; opp_cb_out: the
    opponent's starting corners out (app.game_model), an input for wide receivers; vac: his team's shares vacated by
    regulars out this week who played its last game (vacated()), inputs for RB/WR/TE."""
    vac = vac or {}
    games = sorted(w for w in (h or {}) if w < week)
    g = [h[w] for w in games]
    l3 = g[-3:]
    mean = lambda xs: statistics.fmean(xs) if xs else 0.0  # noqa: E731
    snaps = [x["snap"] for x in g if x.get("snap") is not None]
    recent = g[-ADOT_GAMES:]
    tgt = sum(x.get("tgt", 0.0) for x in recent)
    adot = sum(x.get("air", 0.0) for x in recent) / tgt if tgt and len(recent) >= ADOT_MIN_GAMES else ADOT_CENTER
    workhorse_catcher = (position == "RB" and float((line or {}).get("rush_att") or 0) >= WPC_CARRIES
                         and float((line or {}).get("rec_tgt") or 0) >= WPC_TARGETS)
    form = 0.0
    if proj_hist:
        diffs = [h[w]["pts"] - proj_hist[w] for w in games[-3:] if w in proj_hist and h[w].get("pts") is not None]
        form = mean(diffs)
    return {
        "proj": proj, "ts_l3": mean([x["ts"] for x in l3]), "ts_trend": mean([x["ts"] for x in l3]) - mean([x["ts"] for x in g]),
        "cs_l3": mean([x["cs"] for x in l3]), "cs_trend": mean([x["cs"] for x in l3]) - mean([x["cs"] for x in g]),
        "snap_l3": mean(snaps[-3:]), "snap_trend": mean(snaps[-3:]) - mean(snaps),
        "form": form, "implied": implied or 22.0, "spread": spread or 0.0,
        "spread_x_rb": (spread or 0.0) if position == "RB" else 0.0, "games": float(len(g)),
        "opp_pressure": opp_pressure or 0.0, "ol_out": float(ol_out or 0),
        "front7_out": float(front7_out or 0) if position == "RB" else 0.0,
        "spread_x_wpc": (spread or 0.0) if workhorse_catcher else 0.0,
        "adot_x_opp_explosive": ((adot - ADOT_CENTER) * (opp_explosive or 0.0) * 100) if position in ("WR", "TE") else 0.0,
        "cb_out_x_wr": float(opp_cb_out or 0) if position == "WR" else 0.0,
        "vac_ts": vac.get("ts", 0.0) if position in SKILL else 0.0,
        "vac_cs": vac.get("cs", 0.0) if position == "RB" else 0.0,
        "vac_ts_same": (vac.get("ts_by_pos") or {}).get(position, 0.0) if position in SKILL else 0.0,
        "vac_cs_rb": (vac.get("cs_by_pos") or {}).get("RB", 0.0) if position == "RB" else 0.0,
    }


_MODEL: dict | None = None


def load() -> dict | None:
    global _MODEL
    if _MODEL is None and MODEL_FILE.exists():
        _MODEL = json.loads(MODEL_FILE.read_text())
    return _MODEL


def adjustment(position: str, feats: dict, model: dict | None = None) -> float | None:
    """Points to add to the projection (capped), or None without a fitted model for the position."""
    m = (model or load() or {}).get("positions", {}).get(position)
    if not m:
        return None
    adj = gm.apply(m, feats)
    cap = max(3.0, MAX_ADJ * feats["proj"])
    return round(max(-cap, min(cap, adj)), 2)


# --------------------------------------------------------------------------- live
@memoize_async(3600 * 6)
async def context(season: int, week: int) -> dict:
    """What features() needs for this week's players: each player's weekly role history (app team codes) and
    their Sleeper projections for the last three weeks."""
    from app import dk_scoring, player_games, projections, sleeper_client
    from app import nflverse_client as nc

    rows = await nc._fetch_player_week_rows(season)
    snaps = await player_games._snap_rows(season)
    hist = history(rows, snaps, team_of=nc.to_app_team, points=dk_scoring.dk_offense_points)
    proj_hist: dict[str, dict[int, float]] = {}
    weeks = list(range(max(1, week - 3), week))
    by_week = await asyncio.gather(*(sleeper_client.get_projection_lines(season, w) for w in weeks), return_exceptions=True)
    for w, lines in zip(weeks, by_week):
        if isinstance(lines, BaseException):
            continue
        for ln in lines.values():
            if ln.get("position") in POSITIONS and ln.get("name"):
                proj_hist.setdefault(key(ln["name"], ln["position"]), {})[w] = projections.dk_points_from_line(ln["stats"], ln["position"])
    return {"hist": hist, "proj_hist": proj_hist}
