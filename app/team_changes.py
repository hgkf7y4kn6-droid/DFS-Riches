"""Detects players who changed teams (trades, waiver claims, signings) from week-by-week team snapshots.

Pure functions on plain rows so the same logic runs on nflverse's weekly rosters (history back to 2016) and, when the
network allows, on the DraftKings player pool saved for each week (`from_pools`). Nothing here fetches data.

An event is {player, name, position, from_team, to_team, last_week_old, first_week, season, offseason}. `first_week`
is the first week the player appears on the new team (the first game the new team could use him in); a player who is
inactive that week still counts, because the roster snapshot is what changed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SKILL = ("QB", "RB", "WR", "TE")
ROSTERED = ("ACT", "INA", "RES")      # on the 53, not practice-squad (DEV) or released (CUT)


def detect(rows, positions=SKILL, statuses=ROSTERED, include_offseason: bool = False, relevant=None) -> list[dict]:
    """rows: dicts with season, week, team, player (a stable id), name, position, status (None = don't filter).
    relevant: optional set of player ids to keep (e.g. players who actually played). Returns events, oldest first."""
    by_player: dict[str, list[dict]] = {}
    for r in rows:
        if positions and r.get("position") not in positions:
            continue
        if statuses and r.get("status") not in statuses:
            continue
        if relevant is not None and r["player"] not in relevant:
            continue
        by_player.setdefault(r["player"], []).append(r)
    events = []
    for pid, snaps in by_player.items():
        snaps.sort(key=lambda s: (int(s["season"]), int(s["week"])))
        for a, b in zip(snaps, snaps[1:]):
            if a["team"] == b["team"]:
                continue
            offseason = int(a["season"]) != int(b["season"])
            if offseason and not include_offseason:
                continue
            events.append({"player": pid, "name": b["name"], "position": b["position"], "from_team": a["team"],
                           "to_team": b["team"], "last_week_old": int(a["week"]), "first_week": int(b["week"]),
                           "season": int(b["season"]), "offseason": offseason})
    events.sort(key=lambda e: (e["season"], e["first_week"], e["name"]))
    return events


def from_pools(pools: dict[int, list[dict]], season: int, positions=SKILL) -> list[dict]:
    """Same detection on saved DraftKings pools: {week: [{name, team, position}, ...]}. A player is keyed by name and
    position; a name that is on two teams in the same week's pool (two players, one name) is skipped."""
    rows = []
    for week, players in pools.items():
        seen: dict[tuple[str, str], set[str]] = {}
        for p in players:
            seen.setdefault((p["name"], p["position"]), set()).add(p["team"])
        for (name, pos), teams in seen.items():
            if len(teams) == 1:
                rows.append({"season": season, "week": week, "team": next(iter(teams)), "player": f"{name}|{pos}",
                             "name": name, "position": pos, "status": None})
    return detect(rows, positions=positions, statuses=None)


def context_rows(events: list[dict], source: str) -> list[dict]:
    """Events as data/context_changes.json entries: a trade_out for the old team and a trade_in for the new one."""
    out = []
    for e in events:
        note = f"{e['name']} ({e['position']}) {e['from_team']} -> {e['to_team']}"
        out.append({"team": e["to_team"], "season": e["season"], "effective_week": e["first_week"], "type": "trade_in",
                    "note": note, "source": source})
        out.append({"team": e["from_team"], "season": e["season"], "effective_week": e["first_week"], "type": "trade_out",
                    "note": note, "source": source})
    return out


CONTEXT_FILE = Path(__file__).resolve().parent.parent / "data" / "context_changes.json"
MOVE_LOOKBACK = 3          # weeks a change stays on a game card (a style is read from games played before it)
_MOVE = re.compile(r"^(?P<name>.+?) \((?P<pos>[A-Z]+)\) (?P<old>[A-Z]+) -> (?P<new>[A-Z]+)")
_KIND = {"playcaller": "Play-calling", "coordinator": "Coordinator", "head_coach": "Head coach",
         "front_office": "Front office", "other": "Change"}


def move_label(change: dict) -> str:
    """One short line for a data/context_changes.json row ("Added QB Kirk Cousins (from LV)")."""
    note = str(change.get("note") or "")
    m = _MOVE.match(note)
    if change.get("type") in ("trade_in", "trade_out") and m:
        if change["type"] == "trade_in":
            return f"Added {m['pos']} {m['name']} (from {m['old']})"
        return f"Traded away {m['pos']} {m['name']} (to {m['new']})"
    first = re.split(r"(?<=[a-z0-9)])[.;]\s", note, maxsplit=1)[0].rstrip(".;")
    kind = _KIND.get(change.get("type"), "Change")
    return f"{kind}: {first[:117] + '...' if len(first) > 120 else first}"


def recent_moves(season: int, week: int, changes: list[dict] | None = None, lookback: int = MOVE_LOOKBACK) -> dict[str, list[dict]]:
    """{team: [{"label", "type", "effective_week"}, ...]} for changes that took effect in the last `lookback` weeks
    through `week` (newest first). Archetypes come from games already played, so these are what they cannot see."""
    if changes is None:
        changes = json.loads(CONTEXT_FILE.read_text()).get("changes", []) if CONTEXT_FILE.exists() else []
    out: dict[str, list[dict]] = {}
    for c in changes:
        wk = c.get("effective_week")
        if int(c.get("season", 0)) != season or wk is None or not (week - lookback < int(wk) <= week):
            continue
        out.setdefault(c["team"], []).append({"label": move_label(c), "type": c["type"], "effective_week": int(wk)})
    for rows in out.values():
        rows.sort(key=lambda r: -r["effective_week"])
    return out
