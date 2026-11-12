"""Which slate an actual-ownership upload belongs to, from the upload itself.

Candidates are every available slate of the week the app is on and the week before (contests are often reviewed
after the week rolls over). Each is scored on what the upload says:

  players    the share of uploaded players on the slate (a Showdown contest -- CPT slots in a CSV -- only
             considers Showdown slates, and a Classic contest only Classic ones)
  week       evidence the upload is from that week: for a screen recording, games (away @ home pairs) and
             salaries that match the slate's; for a standings CSV, players' fantasy points that match their
             actual DraftKings points that week (once nflverse has the box scores)
  coverage   the share of the slate's teams the upload's players come from: a Sunday Main contest covers the
             Main's teams but only part of the Full Week's

The best slate wins when at least MIN_PLAYERS of the upload is on it; ties go to the week the app is on.
"""
from __future__ import annotations

import asyncio

from app import nflverse_client as nc
from app import dk_client, ownership_store, slates

MIN_PLAYERS = 0.6
FPTS_TOLERANCE = 0.6       # our box-score DK points vs DraftKings' (stat corrections, rounding)


async def players_for(season: int, week: int, slate_id: str) -> tuple[list[dict], dict]:
    """(resolver rows {key, name, team, position, roster_slot, salary}, slate) for one slate, straight from
    DraftKings' draftables (cached) -- matching names needs no projections."""
    _schedule, sl = await slates.list_slates(season, week)
    slate = next((s for s in sl if s.slate_id == slate_id), None)
    if slate is None:
        raise ValueError(f"Unknown slate_id: {slate_id}")
    out = []
    if slate.available and slate.draft_group_id is not None:
        teams = {t for g in slate.games for t in (g.away, g.home)}
        for r in dk_client.parse_draftables(await dk_client.fetch_draftables(slate.draft_group_id), slate.slate_type):
            if r["team"] not in teams:
                continue
            key = ownership_store.player_key(r["name"], r["team"], r["position"])
            if slate.slate_type == "showdown":
                key += "|CPT" if r["roster_slot"] == "CPT" else "|FLEX"
            out.append({"key": key, "name": r["name"], "team": r["team"], "position": r["position"],
                        "roster_slot": r["roster_slot"], "salary": r["salary"], "slate_type": slate.slate_type})
    return out, {"season": season, "week": week, "slate_id": slate_id, "label": slate.label,
                 "slate_type": slate.slate_type, "games": [(g.away, g.home) for g in slate.games]}


async def _candidates(season: int, week: int, slate_type: str | None) -> list[tuple[list[dict], dict]]:
    out = []
    for w in dict.fromkeys((week, week - 1)):
        if w < 1:
            continue
        try:
            _schedule, sl = await slates.list_slates(season, w)
        except Exception:
            continue
        ids = [s.slate_id for s in sl if s.available and (slate_type is None or s.slate_type == slate_type)]
        res = await asyncio.gather(*(players_for(season, w, i) for i in ids), return_exceptions=True)
        out += [r for r in res if not isinstance(r, BaseException) and r[0]]
    return out


def _coverage(teams: set[str], slate: dict) -> float:
    st = {t for g in slate["games"] for t in g}
    return len(teams & st) / len(st) if st else 0.0


def _pick(scored: list[tuple[tuple, dict]], hint_week: int) -> dict | None:
    ok = [(s, slate) for s, slate in scored if s[1] >= MIN_PLAYERS]
    if not ok:
        return None
    best = max(ok, key=lambda x: (x[0], x[1]["week"] == hint_week))
    return best[1] | {"score": {"week_evidence": round(best[0][0], 2), "players": round(best[0][1], 2),
                                "coverage": round(best[0][2], 2)}}


async def for_rows(rows: list[dict], season: int, week: int) -> dict | None:
    """A screen recording's rows (app.ownership_video: name, salary, game) -> the best slate, or None."""
    from app import ownership_video

    pairs = {tuple(g.replace(" ", "").split("@")) for r in rows if r.get("game")
             for g in [" ".join(t for t in r["game"].split() if not t.isdigit())]}
    scored = []
    for players, slate in await _candidates(season, week, "classic"):
        matched, _ = ownership_video.match(rows, players)
        n_sal = sum(1 for m in matched if m.get("salary"))
        sal = sum(1 for m in matched if m.get("salary") and m["salary"] == m["player"]["salary"]) / n_sal if n_sal else 0.0
        games = len(pairs & set(slate["games"])) / len(pairs) if pairs else 0.0
        teams = {m["player"]["team"] for m in matched}
        week_evidence = (sal + games) / 2
        scored.append(((week_evidence, len(matched) / max(len(rows), 1), _coverage(teams, slate)), slate))
    return _pick(scored, week)


async def for_names(entries: list[dict], season: int, week: int) -> dict | None:
    """Standings-CSV players ({name, slot, fpts}) -> the best slate, or None."""
    showdown = any(e.get("slot") == "CPT" for e in entries)
    index = await nc.get_player_trailing_index(season)
    scored = []
    for players, slate in await _candidates(season, week, "showdown" if showdown else "classic"):
        matched = [(e, p) for e in entries if (p := ownership_store.resolve(players, e["name"], slot=e.get("slot", "")))]
        hits = n = 0
        for e, p in matched:
            if e.get("fpts") is None or p["position"] == "DST":
                continue
            actual = next((x[2] for x in index.get(nc.player_key(p["name"], p["position"]), [])
                           if x[0] == season and x[1] == slate["week"]), None)
            if actual is not None:
                n += 1
                hits += abs(actual - e["fpts"] * (2 / 3 if e.get("slot") == "CPT" else 1)) <= FPTS_TOLERANCE
        teams = {p["team"] for _, p in matched}
        week_evidence = hits / n if n >= 5 else 0.0
        scored.append(((week_evidence, len(matched) / max(len(entries), 1), _coverage(teams, slate)), slate))
    return _pick(scored, week)
