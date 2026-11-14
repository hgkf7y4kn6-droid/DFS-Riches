"""Which way a team is headed: its schedule ahead against the one behind (data/schedule_outlook.json).

scripts/backtest_schedule_trends.py (2016-2025, walk-forward) found the next three opponents' strength predicts a
team's next three games -- strongly for defences against the opposing offences (coefficient 0.72, t = 10; 0.41 for rush
defence, t = 4.2), modestly for offences (0.30, t = 3.4; rush 0.23, t = 2.2) and not for pass offences (0.09, t = 1.0, left
out). The last games' results against soft or tough opponents did not carry on (the schedule part of a recent move has
no persistence), and recent form is no stickier than the six-game average, so direction here is the schedule, not momentum.
"""
from __future__ import annotations

import json
from pathlib import Path

N_RATE, K_RATE = 12, 3          # a rating = mean of the last 12 games, shrunk with 3 league-average games (as in the back-test)
AHEAD, BEHIND = 3, 6            # opponents ahead / games behind that are compared
FAMILIES = {                    # unit: (what the team did, which column of its opponent it is judged against)
    "off_total": ("off_y", "def_y"), "off_rush": ("off_rush", "def_rush"), "off_pass": ("off_pass", "def_pass"),
    "def_total": ("def_y", "off_y"), "def_pass": ("def_pass", "off_pass"), "def_rush": ("def_rush", "off_rush")}

FILE = Path(__file__).resolve().parent.parent / "data" / "schedule_outlook.json"
MIN_MOVE = 1.0               # EPA per play x100: smaller moves are not shown
PLAYS = 62
UNITS = (("off_total", "Offense", False), ("off_rush", "Rushing offense", False), ("def_total", "Defense", True),
         ("def_pass", "Pass defense", True), ("def_rush", "Run defense", True))
_CACHE: tuple[float, dict] | None = None


def _team_game(off: dict, de: dict) -> dict[str, float | None]:
    """One team-week from app.game_model's per-game counts: what its offense did and what its defense allowed."""
    def rate(c, num, den):
        return c.get(num, 0.0) / c[den] if c.get(den) else None
    return {"off_y": (c.get("db_epa", 0.0) + c.get("rush_epa", 0.0)) / c["plays"] if (c := off).get("plays") else None,
            "off_pass": rate(off, "db_epa", "db"), "off_rush": rate(off, "rush_epa", "rush"),
            "def_y": (c.get("db_epa", 0.0) + c.get("rush_epa", 0.0)) / c["plays"] if (c := de).get("plays") else None,
            "def_pass": rate(de, "db_epa", "db"), "def_rush": rate(de, "rush_epa", "rush")}


def compute(game_aggs: dict[int, dict], schedules: dict[int, list[dict]], season: int, week: int, coefs: dict) -> dict[str, dict]:
    """{team: entry} like the file's, from play-by-play the app already pulls: `game_aggs` is {season: agg["game"]}
    (per team-week offense and defense counts), `schedules` {season: nflverse games rows}. Ratings use every game before
    `week` (last season's too); the schedule behind is the last 6 games' opponents as rated when played, the schedule
    ahead the next 3 as rated now. Same arithmetic as scripts/backtest_schedule_trends.py."""
    cols = ("off_y", "off_pass", "off_rush", "def_y", "def_pass", "def_rush")
    series: dict[str, list[tuple[int, dict]]] = {}
    opp_of: dict[tuple[int, int, str], str] = {}
    for s, rows in schedules.items():
        for r in rows:
            if r.get("game_type") == "REG":
                opp_of[(s, int(r["week"]), r["home_team"])] = r["away_team"]
                opp_of[(s, int(r["week"]), r["away_team"])] = r["home_team"]
    for s, agg in game_aggs.items():
        weeks = {}
        for side in ("off", "def"):
            for key, c in (agg.get(side) or {}).items():
                wk, team = key.split("|")
                if s == season and int(wk) >= week:
                    continue
                weeks.setdefault((int(wk), team), {})[side] = c
        rows = {k: _team_game(v.get("off") or {}, v.get("def") or {}) for k, v in weeks.items() if v.get("off") and v.get("def")}
        mean = {c: (sum(v[c] for v in rows.values() if v[c] is not None) / max(1, sum(v[c] is not None for v in rows.values()))) for c in cols}
        for (wk, team), v in rows.items():
            series.setdefault(team, []).append((s * 100 + wk, {c: (v[c] - mean[c]) if v[c] is not None else 0.0 for c in cols}))
    for v in series.values():
        v.sort(key=lambda x: x[0])

    def rate(team: str, col: str, key: int) -> float:
        prior = [x[1][col] for x in series.get(team, []) if x[0] < key][-N_RATE:]
        return sum(prior) / (len(prior) + K_RATE)

    key_now = season * 100 + week
    out: dict[str, dict] = {}
    for team, games in series.items():
        past = [(k, g) for k, g in games if k // 100 == season][-BEHIND:]
        ahead = [opp_of[(season, w, team)] for w in range(week, 23) if (season, w, team) in opp_of][:AHEAD]
        if len(ahead) < 2 or not past:
            continue
        row = {"opponents_ahead": ahead}
        for fam, (own, opp) in FAMILIES.items():
            p = sum(rate(opp_of[(k // 100, k % 100, team)], opp, k) for k, _ in past if (k // 100, k % 100, team) in opp_of) / len(past)
            f = sum(rate(o, opp, key_now) for o in ahead) / len(ahead)
            coef = (coefs.get(fam) or [0.0])[0]
            row[fam] = {"schedule_past6": round(100 * p, 1), "schedule_ahead": round(100 * f, 1), "change": round(100 * (f - p), 1),
                        "expected_move": round(100 * coef * (f - p), 2),
                        "adj_form_6": round(100 * sum(g[own] - rate(opp_of[(k // 100, k % 100, team)], opp, k) for k, g in past
                                                      if (k // 100, k % 100, team) in opp_of) / len(past), 1)}
        out[team] = row
    return out


def load() -> dict:
    global _CACHE
    if not FILE.exists():
        return {}
    m = FILE.stat().st_mtime
    if _CACHE is None or _CACHE[0] != m:
        _CACHE = (m, json.loads(FILE.read_text()))
    return _CACHE[1]


def lines(entry: dict) -> list[dict]:
    """[{"unit", "better", "text"}] for the parts of a team whose schedule ahead moves it by MIN_MOVE or more."""
    out = []
    opp = ", ".join(entry.get("opponents_ahead") or [])
    for fam, unit, is_def in UNITS:
        f = entry.get(fam)
        if not f or abs(f["expected_move"]) < MIN_MOVE:
            continue
        move = f["expected_move"]
        better = move < 0 if is_def else move > 0
        pts = abs(move) / 100 * PLAYS
        out.append({"unit": unit, "better": better,
                    "text": (f"{unit} {'improving' if better else 'slipping'}: the next 3 {'offenses' if is_def else 'defenses'} ({opp}) rate "
                             f"{f['schedule_ahead']:+.1f} vs {f['schedule_past6']:+.1f} over the last 6 (EPA per play x100 vs an average opponent): "
                             f"about {pts:.1f} points per game {'better' if better else 'worse'}")})
    return out


def live(season: int, week: int, game_aggs: dict[int, dict], schedules: dict[int, list[dict]], app_team=lambda t: t) -> dict[str, list[dict]]:
    """{app team: lines} computed now from the play-by-play (no weekly script needed); falls back to the saved file when
    the coefficients, a season's data or enough games are missing."""
    coefs = load().get("coefficients") or {}
    if coefs and season in game_aggs and season in schedules and week >= 4:
        try:
            teams = compute(game_aggs, schedules, season, week, coefs)
            return {app_team(t): ls for t, e in teams.items() if (ls := lines(e))}
        except (KeyError, ValueError, ZeroDivisionError):
            pass
    return for_week(season, week)


def for_week(season: int, week: int, data: dict | None = None) -> dict[str, list[dict]]:
    """{app team: lines} when the file is for this slate's week."""
    d = data if data is not None else load()
    if int(d.get("season", 0)) != season or int(d.get("week", 0)) != week:
        return {}
    return {t: ls for t, e in (d.get("teams") or {}).items() if (ls := lines(e))}
