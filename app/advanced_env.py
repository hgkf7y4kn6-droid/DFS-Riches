"""Advanced game environment: drive velocity, schematic funnels, front-4 pressure and playcaller pace.

The index follows the weekly-audit formula

    advanced = 0.7 x Vegas total
               + 0.30 x drive velocity            (explosive pass rates / seconds per drive x 1000)
               + 0.25 x funnel boost              (can't run vs a stout run defense x neutral pass rate x 1.5)
               + 0.20 x playcaller pace           (neutral pass rate over expected x 50)
               + 0.15 x separation                (completion % over expected x 25)
               - 0.40 x trench penalty            (front-4 pressure mismatch x 2.5)

built from public play-by-play only, with the closest stand-ins where the named stat is proprietary:

  quick pressure (< 2.5 s) and pass-block win rate  ->  sack + QB-hit rate when the defense rushed four or fewer
                                                        (FTN charting), for the defense and against the offense,
                                                        each above the league rate
  rush DVOA                                         ->  rush EPA per carry relative to the league
  11/10-personnel rate                              ->  neutral-situation pass rate (no 2026 personnel feed)
  WR open rate                                      ->  completion percentage over expected (CPOE)

Every team stat uses only the weeks before the game, so the backtest (backtest()) is out of sample.
"""
from __future__ import annotations

import statistics
from typing import Any

from app import game_model
from app import nflverse_client as nc
from app.cache import memoize_async

PRESSURE_FRAGILE = 0.12      # a Pressure Fragility Index above this penalizes the game's ceiling
PASS_FLOOR_ATTEMPTS = 38     # top-5 neutral pass rate vs a top-5 run defense
TOP_N = 5
LEAN_BAND = 0.25             # |adj - slate median| under this reads as neutral


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _secs(t: str | None) -> int | None:
    if not t or ":" not in t:
        return None
    m, s = t.split(":", 1)
    try:
        return int(m) * 60 + int(s)
    except ValueError:
        return None


class EnvAccumulator:
    """Per team-week counts for the index, fed the same play-by-play rows as app.trenches.TrenchAccumulator.
    ftn maps 'game_id|play_id' to app.trenches.ftn_index tuples (pass rushers is the last field)."""

    def __init__(self, ftn: dict[str, tuple] | None = None):
        self.ftn = ftn or {}
        self.off: dict[str, dict[str, float]] = {}
        self.de: dict[str, dict[str, float]] = {}
        self._drives: set[tuple] = set()

    def _bump(self, side: dict, key: str, **counts: float) -> None:
        d = side.setdefault(key, {})
        for k, v in counts.items():
            d[k] = d.get(k, 0.0) + float(v)

    def add(self, r: dict) -> None:
        week = nc._to_int(r.get("week"))
        team, opp = nc.to_app_team(r.get("posteam", "")), nc.to_app_team(r.get("defteam", ""))
        if week is None or not team or not opp or r.get("season_type", "REG") != "REG":
            return
        ok, dk = f"{week}|{team}", f"{week}|{opp}"
        drive = (r.get("game_id"), team, r.get("fixed_drive"))
        dt = _secs(r.get("drive_time_of_possession"))
        if r.get("fixed_drive") and dt is not None and drive not in self._drives:
            self._drives.add(drive)
            plays = _f(r.get("drive_play_count")) or 0.0
            self._bump(self.off, ok, drives=1, drive_secs=dt, drive_plays=plays)
            self._bump(self.de, dk, drives=1, drive_secs=dt)
        if r.get("play_type") not in ("pass", "run") or r.get("two_point_attempt") == "1":
            return
        if r.get("qb_dropback") == "1":
            expl = r.get("sack") != "1" and (_f(r.get("yards_gained")) or 0) >= 20
            hit = r.get("sack") == "1" or r.get("qb_hit") == "1"
            charted = self.ftn.get(f"{r.get('game_id')}|{nc._to_int(r.get('play_id'))}")
            four = bool(charted) and 0 < charted[-1] <= 4
            cpoe = _f(r.get("cpoe"))
            self._bump(self.off, ok, db=1, expl=expl, db4=four, hit4=four and hit,
                       cpoe=cpoe or 0.0, cpoe_n=cpoe is not None)
            self._bump(self.de, dk, db=1, expl=expl, db4=four, hit4=four and hit)
        elif r.get("rush") == "1":
            epa = _f(r.get("epa")) or 0.0
            self._bump(self.off, ok, rush=1, rush_epa=epa)
            self._bump(self.de, dk, rush=1, rush_epa=epa)
        if nc._is_neutral(_f(r.get("qtr")), _f(r.get("score_differential")), _f(r.get("half_seconds_remaining"))):
            proe = _f(r.get("pass_oe"))
            self._bump(self.off, ok, neutral=1, neutral_db=r.get("qb_dropback") == "1",
                       proe=(proe or 0.0) / 100, proe_n=proe is not None)

    def result(self) -> dict:
        def rnd(side):
            return {k: {m: round(v, 4) for m, v in d.items()} for k, d in side.items()}
        return {"off": rnd(self.off), "def": rnd(self.de)}


def team_features(env: dict, week: int) -> tuple[dict[str, dict], dict[str, float]]:
    """Each team's season-to-date rates from the weeks before `week`, and the league averages."""
    tot: dict[tuple[str, str], dict[str, float]] = {}
    for side in ("off", "def"):
        for key, counts in (env.get(side) or {}).items():
            wk, team = key.split("|")
            if int(wk) >= week:
                continue
            d = tot.setdefault((team, side), {})
            for k, v in counts.items():
                d[k] = d.get(k, 0.0) + v
    feats = {}
    for team in {t for t, _ in tot}:
        o, d = tot.get((team, "off"), {}), tot.get((team, "def"), {})
        if not o.get("drives") or not o.get("db") or not o.get("rush") or not d.get("rush"):
            continue
        feats[team] = {
            "sec_per_drive": o["drive_secs"] / o["drives"],
            "sec_per_play": o["drive_secs"] / max(o.get("drive_plays", 0), 1),
            "explosive_pass": o.get("expl", 0) / o["db"],
            "rush_epa": o.get("rush_epa", 0) / o["rush"],
            "rush_epa_allowed": d.get("rush_epa", 0) / d["rush"],
            "neutral_pass_rate": o.get("neutral_db", 0) / max(o.get("neutral", 0), 1),
            "proe": o.get("proe", 0) / max(o.get("proe_n", 0), 1),
            "front4_pressure": d.get("hit4", 0) / max(d.get("db4", 0), 1),
            "pressure_allowed": o.get("hit4", 0) / max(o.get("db4", 0), 1),
            "cpoe": o.get("cpoe", 0) / max(o.get("cpoe_n", 0), 1),
            "charted": o.get("db4", 0) > 0 and d.get("db4", 0) > 0,
        }
    if not feats:
        return {}, {}
    league = {k: statistics.fmean(v[k] for v in feats.values()) for k in next(iter(feats.values())) if k != "charted"}
    rank = lambda key, reverse: {t: i + 1 for i, t in enumerate(sorted(feats, key=lambda t: feats[t][key], reverse=reverse))}
    for t, r in rank("neutral_pass_rate", True).items():
        feats[t]["pass_rate_rank"] = r
    for t, r in rank("rush_epa_allowed", False).items():
        feats[t]["run_defense_rank"] = r
    return feats, league


def game_index(away: str, home: str, total: float | None, feats: dict, lg: dict) -> dict | None:
    """The index and its parts for one game (None without both teams' stats)."""
    a, b = feats.get(away), feats.get(home)
    if not a or not b:
        return None
    dv = (a["explosive_pass"] + b["explosive_pass"]) / max(a["sec_per_drive"] + b["sec_per_drive"], 120) * 1000
    fa = max(0.0, (lg["rush_epa"] - a["rush_epa"]) + (lg["rush_epa_allowed"] - b["rush_epa_allowed"])) * a["neutral_pass_rate"]
    fb = max(0.0, (lg["rush_epa"] - b["rush_epa"]) + (lg["rush_epa_allowed"] - a["rush_epa_allowed"])) * b["neutral_pass_rate"]
    pa = max(0.0, (b["front4_pressure"] - lg["front4_pressure"]) + (a["pressure_allowed"] - lg["pressure_allowed"]))
    pb = max(0.0, (a["front4_pressure"] - lg["front4_pressure"]) + (b["pressure_allowed"] - lg["pressure_allowed"]))
    if not (a["charted"] and b["charted"]):
        pa = pb = 0.0                          # no FTN charting yet: no pressure read
    parts = {
        "drive_velocity": dv * 0.30,
        "funnel": (fa + fb) * 1.5 * 0.25,
        "playcaller_pace": (a["proe"] + b["proe"]) * 50 * 0.20,
        "separation": (a["cpoe"] + b["cpoe"]) / 100 * 25 * 0.15,
        "trench_penalty": -(pa + pb) * 2.5 * 0.40,
    }
    adj = sum(parts.values())
    floors = [t for t, opp in ((away, home), (home, away))
              if feats[t]["pass_rate_rank"] <= TOP_N and feats[opp]["run_defense_rank"] <= TOP_N]
    fragile = [{"offense": t, "defense": opp, "index": round(v, 3)}
               for t, opp, v in ((away, home, pa), (home, away, pb)) if v > PRESSURE_FRAGILE]
    return {
        "score": round(0.7 * total + adj, 2) if total is not None else None,
        "adj": round(adj, 3),
        "parts": {k: round(v, 3) for k, v in parts.items()},
        "funnel": {away: round(fa, 4), home: round(fb, 4)},
        "pressure_fragility": {away: round(pa, 4), home: round(pb, 4)},
        "pass_attempt_floor": {t: PASS_FLOOR_ATTEMPTS for t in floors},
        "fragile": fragile,
        "sec_per_drive": {away: round(a["sec_per_drive"], 1), home: round(b["sec_per_drive"], 1)},
        "proe": {away: round(a["proe"], 3), home: round(b["proe"], 3)},
    }


def add_leans(games: dict[str, dict]) -> None:
    """Over / Under lean for each game's index against the slate's median, in place."""
    adjs = [g["adj"] for g in games.values() if g]
    if not adjs:
        return
    med = statistics.median(adjs)
    for g in games.values():
        if g:
            d = g["adj"] - med
            g["lean"] = "Over" if d > LEAN_BAND else "Under" if d < -LEAN_BAND else "Neutral"
            g["vs_slate"] = round(d, 3)


def notes(g: dict | None) -> list[str]:
    """Plain-language flags for one game."""
    if not g:
        return []
    out = []
    for t, n in g["pass_attempt_floor"].items():
        out.append(f"Pass funnel: {t} (top-{TOP_N} neutral pass rate) faces a top-{TOP_N} run defense -- {n}+ pass attempts floor")
    for f in g["fragile"]:
        out.append(f"Pressure fragility: {f['defense']}'s four-man rush vs {f['offense']}'s protection "
                   f"(+{f['index']:.0%} over league) -- ceiling penalty")
    if g.get("lean") in ("Over", "Under"):
        out.append(f"Advanced environment leans {g['lean']} ({g['vs_slate']:+.2f} vs the slate)")
    return out


async def _aggregates(season: int) -> dict:
    return (await nc.get_pbp_aggregates(season)).get("environment") or {}


@memoize_async(600)
async def for_games(season: int, week: int, games: tuple[tuple[str, str, float | None], ...]) -> dict[str, dict | None]:
    """{"AWAY@HOME": index} for (away, home, total) games of a week, with slate leans."""
    feats, lg = team_features(await _aggregates(season), week)
    out = {f"{a}@{h}": game_index(a, h, t, feats, lg) for a, h, t in games} if feats else {}
    add_leans(out)
    return out


def _spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 5:
        return None
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for k, i in enumerate(order):
            r[i] = float(k)
        return r
    rx, ry = rank(x), rank(y)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((p - mx) * (q - my) for p, q in zip(rx, ry))
    den = (sum((p - mx) ** 2 for p in rx) * sum((q - my) ** 2 for q in ry)) ** 0.5
    return round(num / den, 3) if den else None


def _z(vals: list[float], v: float) -> float:
    sd = statistics.pstdev(vals) or 1.0
    return (v - statistics.fmean(vals)) / sd


@memoize_async(3600 * 6)
async def backtest(season: int, week: int) -> dict:
    """Out-of-sample record through `week` - 1: does the index call Overs/Unders against the closing total, and
    does adding it to the DFS environment score (total, spread, pace, pass rate) rank games better?"""
    env, games = await _aggregates(season), await nc.get_games(season)
    picks = right = 0
    sig, cur, comb, resid = [], [], [], []
    for w in range(2, week):
        feats, lg = team_features(env, w)
        rows = []
        for (wk, away, home), g in games.items():
            if wk != w or not g["is_final"] or g["total_line"] is None or g["spread_line"] is None:
                continue
            ix = game_index(away, home, g["total_line"], feats, lg)
            if ix:
                rows.append((ix, g, feats[away], feats[home]))
        if len(rows) < 4:
            continue
        med = statistics.median(ix["adj"] for ix, *_ in rows)
        cols = {"total": [g["total_line"] for _, g, *_ in rows], "close": [-abs(g["spread_line"]) for _, g, *_ in rows],
                "pace": [-(a["sec_per_play"] + b["sec_per_play"]) for *_, a, b in rows],
                "pass": [a["neutral_pass_rate"] + b["neutral_pass_rate"] for *_, a, b in rows],
                "adj": [ix["adj"] for ix, *_ in rows]}
        for i, (ix, g, _, _) in enumerate(rows):
            r = g["home_score"] + g["away_score"] - g["total_line"]
            if r == 0:
                continue
            if ix["adj"] != med:
                picks += 1
                right += (ix["adj"] > med) == (r > 0)
            base = (0.40 * _z(cols["total"], cols["total"][i]) + 0.20 * _z(cols["close"], cols["close"][i])
                    + 0.10 * _z(cols["pace"], cols["pace"][i]) + 0.10 * _z(cols["pass"], cols["pass"][i]))
            sig.append(ix["adj"]); cur.append(base); comb.append(base + 0.20 * _z(cols["adj"], cols["adj"][i])); resid.append(r)
    s_ix, s_cur, s_comb = _spearman(sig, resid), _spearman(cur, resid), _spearman(comb, resid)
    helps = s_comb is not None and s_cur is not None and s_comb > s_cur
    return {
        "games": len(resid), "ou_picks": {"right": right, "n": picks, "pct": round(right / picks, 3) if picks else None},
        "spearman_vs_total": {"index": s_ix, "dfs_env_current": s_cur, "dfs_env_with_index": s_comb},
        "weighted_in_dfs_env": helps,
        "history_2023_2025": (game_model.load() or {}).get("advanced_index_record"),
        "note": ("Index picks Over for games above the week's median index, Under below, against the closing total. "
                 "It is weighted into the DFS environment score only while adding it ranks past games better."),
    }
