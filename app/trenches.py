"""Line play, efficiency and scheme tendencies for every team, from open data.

The kinds of numbers subscription sites publish as "OL/DL stats", "coverage
schemes" and "offensive/defensive tendencies" tools -- computed here from
free public sources instead of copied from anyone:

  nflverse play-by-play   success rate, EPA/play, sack and QB-hit rates,
                          explosive plays, run stuffs (every play)
  FTN charting (nflverse) box counts, blitzers, pass rushers, play-action,
                          motion, screens, RPOs, no-huddle (every play, weekly)
  nflverse participation  man/zone, coverage shell, true pressure and time to
                          throw (NGS-derived; published after the season, so
                          usually last season's -- labeled wherever shown)

Only "competitive" plays count: win probability 10-90%, no kneels/spikes.
A team's numbers entering a week are this season's games so far plus last
season's rates weighted as PRIOR_GAMES games, so Week 1 shows last season
and the current season takes over as games accumulate.

Unit grades are the average league z-score of their parts, ranked 1 = best
for that unit (so pass-rush #1 is the most disruptive front, pass-pro #1 the
cleanest pocket). A matchup "edge" is the offense unit's z minus the
opposing unit's z: positive favors the offense. It is only called a lean or
strong edge when the defense is itself below average (offense edges) or
above average (defense edges).

Late-down monitor (display only, no model uses it): success on 3rd/4th down
above or below what a team's 1st/2nd-down success implies at the league's
late/early ratio, offense minus defense. In 2022-2025 that gap didn't repeat
from one half of a season to the other (odd vs even weeks, r = -0.08), so a
team far from its early-down pace is flagged as running hot or cold;
scripts.late_down_monitor checks whether fading it beats the closing line.
"""
from __future__ import annotations

import asyncio
import csv
import io
import statistics

import httpx

from app import nflverse_client as nc
from app.cache import cached_fetch, memoize_async
from app.config import TTL_NFLVERSE_PBP_PAST, TTL_NFLVERSE_TEAM_STATS

FTN_URL_TMPL = "https://github.com/nflverse/nflverse-data/releases/download/ftn_charting/ftn_charting_{season}.csv"
PARTICIPATION_URL_TMPL = "https://github.com/nflverse/nflverse-data/releases/download/pbp_participation/pbp_participation_{season}.csv"
FTN_FIRST_SEASON = 2022
PRIOR_GAMES = 3            # last season's rates count as this many games
WP_MIN, WP_MAX = 0.10, 0.90
EXPLOSIVE_PASS, EXPLOSIVE_RUN = 20, 10
LIGHT_BOX, HEAVY_BOX = 6, 8
STRONG_EDGE, LEAN_EDGE = 1.0, 0.5

SINGLE_HIGH = {"COVER_0", "COVER_1", "COVER_3"}
TWO_HIGH = {"COVER_2", "COVER_4", "COVER_6", "2_MAN", "COVER_9"}

# Sites with comparable (proprietary) tools. Linked for manual comparison only:
# their terms prohibit automated access, so nothing is fetched from them.
REFERENCES = [
    {"label": "Sharp Football NFL stats tools", "url": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-stats-tools/"},
    {"label": "Offensive line stats", "url": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-offensive-line-stats/"},
    {"label": "Defensive line stats", "url": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-defensive-line-stats/"},
    {"label": "Coverage schemes", "url": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-coverage-schemes/"},
    {"label": "Offensive tendencies", "url": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-offensive-tendencies-stats/"},
    {"label": "Defensive tendencies", "url": "https://www.sharpfootballanalysis.com/stats-nfl/nfl-defensive-tendencies/"},
    {"label": "Fantasy tools", "url": "https://www.sharpfootballanalysis.com/fantasy/"},
    {"label": "Betting tools", "url": "https://www.sharpfootballanalysis.com/betting/"},
]
REFERENCE_NOTE = ("Sharp Football Analysis is linked for manual comparison, not ingested or weighted: its terms prohibit "
                  "automated access and copying. The equivalent metrics here are computed from nflverse play-by-play, "
                  "FTN charting and NGS participation data.")


# ------------------------------------------------------------- per-play pass
def _f(v) -> float | None:
    return nc._to_float(v)


def _true(v) -> bool:
    return v in ("TRUE", "1", "True", "true")


def ftn_index(rows) -> dict[str, tuple]:
    """'game_id|play_id' -> (play_action, motion, screen, rpo, no_huddle, box, blitzers, rushers)."""
    out = {}
    for r in rows:
        gid, pid = r.get("nflverse_game_id"), r.get("nflverse_play_id")
        if not gid or not pid:
            continue
        out[f"{gid}|{pid}"] = (
            _true(r.get("is_play_action")), _true(r.get("is_motion")), _true(r.get("is_screen_pass")),
            _true(r.get("is_rpo")), _true(r.get("is_no_huddle")),
            nc._to_int(r.get("n_defense_box")) or 0, nc._to_int(r.get("n_blitzers")) or 0, nc._to_int(r.get("n_pass_rushers")) or 0,
        )
    return out


class TrenchAccumulator:
    """Feed nflverse play-by-play rows (dicts of strings) through add(); result()
    gives per team-game counts {"off": {"week|team": {...}}, "def": {...}}.
    Both sides count the same plays, so a defense's "sacks" are sacks it made.
    "game" holds every scrimmage play of each team's offense (no win-probability
    filter), for postgame summaries of how the whole game went."""

    def __init__(self, ftn: dict[str, tuple] | None = None):
        self.ftn = ftn or {}
        self.off: dict[str, dict[str, float]] = {}
        self.de: dict[str, dict[str, float]] = {}
        self.game: dict[str, dict[str, float]] = {}

    def add(self, r: dict) -> None:
        if r.get("play_type") not in ("pass", "run") or r.get("qb_kneel") == "1" or r.get("qb_spike") == "1":
            return
        wp, week = _f(r.get("wp")), nc._to_int(r.get("week"))
        team, opp = nc.to_app_team(r.get("posteam", "")), nc.to_app_team(r.get("defteam", ""))
        if week is None or not team or not opp:
            return
        epa = _f(r.get("epa"))
        success = r.get("success") == "1"
        yards = _f(r.get("yards_gained")) or 0.0
        dropback = r.get("qb_dropback") == "1"
        sack = r.get("sack") == "1"
        explosive = (not sack and yards >= EXPLOSIVE_PASS) if dropback else yards >= EXPLOSIVE_RUN
        g = self.game.setdefault(f"{week}|{team}", {})
        for k, v in (("plays", 1), ("epa", epa or 0.0), ("succ", success), ("db", dropback), ("sack", sack),
                     ("explosive", explosive), ("db_epa", (epa or 0.0) if dropback else 0.0),
                     ("rush", not dropback), ("rush_epa", 0.0 if dropback else (epa or 0.0))):
            g[k] = g.get(k, 0.0) + float(v)
        if wp is None or not WP_MIN <= wp <= WP_MAX:
            return
        c: dict[str, float] = {"plays": 1, "epa": epa or 0.0, "succ": success}
        down = nc._to_int(r.get("down"))
        if down in (1, 2):
            c.update(ed=1, ed_succ=success)
        elif down in (3, 4):
            c.update(ld=1, ld_succ=success)
        if dropback:
            c.update(db=1, db_epa=epa or 0.0, db_succ=success, sack=sack,
                     hit=sack or r.get("qb_hit") == "1", exp_pass=(not sack and yards >= EXPLOSIVE_PASS))
        else:
            c.update(rush=1, rush_epa=epa or 0.0, rush_succ=success, rush_yds=yards,
                     stuff=yards <= 0, exp_rush=yards >= EXPLOSIVE_RUN)
        charted = self.ftn.get(f"{r.get('game_id')}|{nc._to_int(r.get('play_id'))}")
        if charted:
            pa, motion, screen, rpo, no_huddle, box, blitzers, rushers = charted
            c.update(ftn=1, motion=motion, rpo=rpo, no_huddle=no_huddle)
            if dropback:
                c.update(ftn_db=1, pa=pa, screen=screen, blitz=blitzers > 0, rushers=rushers)
            elif box:
                c.update(ftn_rush=1, box=box, light_box=box <= LIGHT_BOX, heavy_box=box >= HEAVY_BOX)
        for side, key in ((self.off, f"{week}|{team}"), (self.de, f"{week}|{opp}")):
            d = side.setdefault(key, {})
            for k, v in c.items():
                d[k] = d.get(k, 0.0) + float(v)

    def result(self) -> dict:
        def rnd(side):
            return {k: {m: round(v, 3) for m, v in d.items()} for k, d in side.items()}
        return {"off": rnd(self.off), "def": rnd(self.de), "game": rnd(self.game)}


class PenaltyDriveAccumulator:
    """Per offense team-week drive counts for the penalty-drive luck monitor (scripts.late_down_monitor):
    drives (not ending the half), drives on which the defense committed an accepted penalty (not declined or
    offsetting, yards assessed), and how many of those ended in points. Feed every play-by-play row."""

    SCORED = ("Touchdown", "Field goal")

    def __init__(self):
        self.drives: dict[tuple[str, str], dict] = {}

    def add(self, r: dict) -> None:
        if r.get("season_type", "REG") != "REG" or not r.get("fixed_drive") or not r.get("posteam") \
                or r.get("play_type") in ("kickoff", "extra_point", "", None):
            return
        d = self.drives.setdefault((r.get("game_id", ""), r["fixed_drive"]), {
            "week": nc._to_int(r.get("week")), "off": r["posteam"], "def": r.get("defteam"),
            "result": r.get("fixed_drive_result") or "", "flag": False})
        desc = (r.get("desc") or "").lower()
        if (r.get("penalty") == "1" and r["posteam"] == d["off"] and r.get("penalty_team") == d["def"]
                and (_f(r.get("penalty_yards")) or 0) > 0 and "declined" not in desc and "offsetting" not in desc):
            d["flag"] = True

    def result(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for d in self.drives.values():
            team = nc.to_app_team(d["off"])
            if d["week"] is None or not team or d["result"] in ("End of half", ""):
                continue
            c = out.setdefault(f"{d['week']}|{team}", {"drives": 0, "flag_drives": 0, "flag_scored": 0})
            c["drives"] += 1
            if d["flag"]:
                c["flag_drives"] += 1
                c["flag_scored"] += d["result"] in self.SCORED
        return out


def coverage_counts(rows) -> dict:
    """Per team-game counts from nflverse participation rows: the defense's
    man/zone and shell on charted dropbacks, pressure rates, time to throw."""
    off: dict[str, dict[str, float]] = {}
    de: dict[str, dict[str, float]] = {}
    for r in rows:
        gid = r.get("nflverse_game_id") or ""
        parts = gid.split("_")
        team = r.get("possession_team") or ""
        if len(parts) != 4 or team not in (parts[2], parts[3]):
            continue
        week = int(parts[1])
        opp = parts[3] if team == parts[2] else parts[2]
        team, opp = nc.to_app_team(team), nc.to_app_team(opp)
        mz, shell = r.get("defense_man_zone_type") or "", r.get("defense_coverage_type") or ""
        if not mz:           # not a charted dropback
            continue
        pressure = _true(r.get("was_pressure"))
        ttt = _f(r.get("time_to_throw"))
        d = de.setdefault(f"{week}|{opp}", {})
        o = off.setdefault(f"{week}|{team}", {})
        for k, v in (("cov", 1), ("man", mz == "MAN_COVERAGE"), ("single_high", shell in SINGLE_HIGH),
                     ("two_high", shell in TWO_HIGH), ("pressure", pressure), (f"shell_{shell}", 1 if shell else 0)):
            if v:
                d[k] = d.get(k, 0.0) + float(v)
        o["cov"] = o.get("cov", 0.0) + 1
        o["pressure"] = o.get("pressure", 0.0) + pressure
        if ttt is not None and ttt > 0:
            o["ttt_n"] = o.get("ttt_n", 0.0) + 1
            o["ttt"] = round(o.get("ttt", 0.0) + ttt, 3)
    return {"off": off, "def": de}


async def get_ftn_index(season: int) -> dict[str, tuple]:
    """Play-level FTN charting for joining to play-by-play (empty if not published)."""
    if season < FTN_FIRST_SEASON:
        return {}
    try:
        text = await nc._fetch_csv_text(FTN_URL_TMPL.format(season=season))
    except Exception:
        return {}
    return ftn_index(csv.DictReader(io.StringIO(text)))


async def _coverage(season: int, current_season: int) -> dict:
    async def fetch() -> dict:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(PARTICIPATION_URL_TMPL.format(season=season), headers=nc._HEADERS, timeout=120)
        if resp.status_code == 404:
            return {"available": False}
        resp.raise_for_status()
        raw = resp.content      # ~50 MB for a full season: stream-decode rather than copy it into a str
        counts = await asyncio.to_thread(lambda: coverage_counts(csv.DictReader(io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))))
        return {"available": bool(counts["def"]), **counts}

    ttl = TTL_NFLVERSE_TEAM_STATS * 12 if season >= current_season else TTL_NFLVERSE_PBP_PAST
    try:
        return await cached_fetch(f"nflverse_participation_coverage_v1_{season}", ttl, fetch)
    except Exception:
        return {"available": False}


# ------------------------------------------------------------- team profiles
def by_team(side: dict) -> dict[str, list[tuple[int, dict]]]:
    """{"week|team": counts} -> {team: [(week, counts), ...]} for fast windows."""
    out: dict[str, list[tuple[int, dict]]] = {}
    for key, d in side.items():
        wk, t = key.split("|")
        out.setdefault(t, []).append((int(wk), d))
    return out


def _window(games: list[tuple[int, dict]], week: int | None) -> tuple[dict[str, float], int]:
    """Summed counts for one team's games (weeks before `week`; all if None) and the game count."""
    total: dict[str, float] = {}
    n = 0
    for wk, d in games:
        if week is not None and wk >= week:
            continue
        n += 1
        for k, v in d.items():
            total[k] = total.get(k, 0.0) + v
    return total, n


def blend(cur: dict, prev: dict, team: str, side: str, week: int) -> tuple[dict[str, float], int, int]:
    """This season's counts before `week` plus last season's scaled to PRIOR_GAMES games.
    `cur`/`prev` are {side: {"week|team": counts}} or already indexed by by_team."""
    def games(src: dict) -> list:
        data = src.get(side, {})
        if data and "|" in next(iter(data)):
            data = by_team(data)
        return data.get(team, [])

    now, n_now = _window(games(cur), week)
    last, n_last = _window(games(prev), None)
    out = dict(now)
    if n_last:
        scale = PRIOR_GAMES / n_last
        for k, v in last.items():
            out[k] = out.get(k, 0.0) + v * scale
    return out, n_now, n_last


def _rate(c: dict, num: str, den: str, min_den: float = 1.0) -> float | None:
    d = c.get(den, 0.0)
    return round(c.get(num, 0.0) / d, 4) if d >= min_den else None


def offense_metrics(c: dict) -> dict[str, float | None]:
    return {
        "epa_play": _rate(c, "epa", "plays", 20), "success": _rate(c, "succ", "plays", 20),
        "db_epa": _rate(c, "db_epa", "db", 15), "db_success": _rate(c, "db_succ", "db", 15),
        "sack_rate": _rate(c, "sack", "db", 15), "pressure_rate": _rate(c, "hit", "db", 15),
        "explosive_pass": _rate(c, "exp_pass", "db", 15),
        "rush_epa": _rate(c, "rush_epa", "rush", 10), "rush_success": _rate(c, "rush_succ", "rush", 10),
        "stuff_rate": _rate(c, "stuff", "rush", 10), "explosive_run": _rate(c, "exp_rush", "rush", 10),
        "ypc": _rate(c, "rush_yds", "rush", 10),
        "early_down_success": _rate(c, "ed_succ", "ed", 15), "late_down_success": _rate(c, "ld_succ", "ld", 10),
        "play_action": _rate(c, "pa", "ftn_db", 15), "screen": _rate(c, "screen", "ftn_db", 15),
        "motion": _rate(c, "motion", "ftn", 20), "rpo": _rate(c, "rpo", "ftn", 20), "no_huddle": _rate(c, "no_huddle", "ftn", 20),
        "box_faced": _rate(c, "box", "ftn_rush", 10), "light_box": _rate(c, "light_box", "ftn_rush", 10),
    }


def defense_metrics(c: dict) -> dict[str, float | None]:
    m = offense_metrics(c)       # same plays, from the defense's side: "allowed"/"forced"
    return {
        "epa_play": m["epa_play"], "success": m["success"], "db_epa": m["db_epa"], "db_success": m["db_success"],
        "sack_rate": m["sack_rate"], "pressure_rate": m["pressure_rate"], "explosive_pass": m["explosive_pass"],
        "rush_epa": m["rush_epa"], "rush_success": m["rush_success"], "stuff_rate": m["stuff_rate"],
        "explosive_run": m["explosive_run"], "ypc": m["ypc"],
        "early_down_success": m["early_down_success"], "late_down_success": m["late_down_success"],
        "blitz": _rate(c, "blitz", "ftn_db", 15), "rushers": _rate(c, "rushers", "ftn_db", 15),
        "heavy_box": _rate(c, "heavy_box", "ftn_rush", 10), "box": _rate(c, "box", "ftn_rush", 10),
    }


def coverage_metrics(off: dict, de: dict) -> dict[str, float | None]:
    shells = {k[6:]: v for k, v in de.items() if k.startswith("shell_")}
    top = max(shells.items(), key=lambda kv: kv[1])[0] if shells else None
    return {
        "man": _rate(de, "man", "cov", 30), "single_high": _rate(de, "single_high", "cov", 30),
        "two_high": _rate(de, "two_high", "cov", 30), "true_pressure": _rate(de, "pressure", "cov", 30),
        "top_shell": top.replace("_", " ").title().replace("2 Man", "2-Man") if top else None,
        "top_shell_rate": round(shells[top] / de["cov"], 3) if top and de.get("cov") else None,
        "pressure_allowed": _rate(off, "pressure", "cov", 30), "time_to_throw": _rate(off, "ttt", "ttt_n", 30),
    }


# unit -> [(side, metric, sign)]: grade = mean z of sign * metric (higher = better unit)
UNITS = {
    "pass_pro": [("off", "sack_rate", -1), ("off", "pressure_rate", -1)],
    "run_block": [("off", "rush_success", 1), ("off", "stuff_rate", -1), ("off", "rush_epa", 1)],
    "pass_offense": [("off", "db_epa", 1), ("off", "db_success", 1), ("off", "explosive_pass", 1)],
    "offense": [("off", "epa_play", 1), ("off", "success", 1)],
    "pass_rush": [("def", "sack_rate", 1), ("def", "pressure_rate", 1)],
    "run_def": [("def", "rush_success", -1), ("def", "stuff_rate", 1), ("def", "rush_epa", -1)],
    "coverage": [("def", "db_epa", -1), ("def", "db_success", -1), ("def", "explosive_pass", -1)],
    "defense": [("def", "epa_play", -1), ("def", "success", -1)],
}
UNIT_LABELS = {"pass_pro": "Pass protection", "run_block": "Run blocking", "pass_offense": "Dropback efficiency",
               "offense": "Offense (EPA + success)", "pass_rush": "Pass rush", "run_def": "Run defense",
               "coverage": "Pass defense", "defense": "Defense (EPA + success)"}


def grade_units(teams: dict[str, dict]) -> None:
    """Adds profile["grades"][unit] = {"z", "rank"} (rank 1 = best) in place."""
    for unit, parts in UNITS.items():
        zsum: dict[str, list[float]] = {t: [] for t in teams}
        for side, metric, sign in parts:
            vals = {t: p[side][metric] for t, p in teams.items() if p[side].get(metric) is not None}
            if len(vals) < 2:
                continue
            mu, sd = statistics.fmean(vals.values()), statistics.pstdev(vals.values())
            for t, v in vals.items():
                zsum[t].append(sign * (v - mu) / sd if sd else 0.0)
        scored = {t: statistics.fmean(z) for t, z in zsum.items() if z}
        order = sorted(scored, key=lambda t: -scored[t])
        for i, t in enumerate(order):
            teams[t].setdefault("grades", {})[unit] = {"z": round(scored[t], 2), "rank": i + 1}


LATE_DOWN_FLAG_Z = 1.28    # about the top / bottom 10% of teams


def late_downs(teams: dict[str, dict]) -> None:
    """Adds profile["late_downs"] = {"offense", "defense", "net", "z", "flag"} in place: late-down success minus
    what early-down success implies (league late/early ratio), offense minus defense; flag "hot" / "cold" when
    the net is LATE_DOWN_FLAG_Z league standard deviations from the mean."""
    def ratio(side: str) -> float | None:
        ed = [p[side]["early_down_success"] for p in teams.values() if p[side].get("early_down_success")]
        ld = [p[side]["late_down_success"] for p in teams.values() if p[side].get("late_down_success") is not None]
        return statistics.fmean(ld) / statistics.fmean(ed) if ed and ld else None

    r_off, r_def = ratio("off"), ratio("def")
    nets = {}
    for t, p in teams.items():
        o, d = p["off"], p["def"]
        if None in (r_off, r_def, o.get("early_down_success"), o.get("late_down_success"),
                    d.get("early_down_success"), d.get("late_down_success")):
            continue
        off = o["late_down_success"] - r_off * o["early_down_success"]
        de = d["late_down_success"] - r_def * d["early_down_success"]
        p["late_downs"] = {"offense": round(off, 4), "defense": round(de, 4), "net": round(off - de, 4)}
        nets[t] = off - de
    if len(nets) < 2:
        return
    mu, sd = statistics.fmean(nets.values()), statistics.pstdev(nets.values())
    for t, v in nets.items():
        z = (v - mu) / sd if sd else 0.0
        teams[t]["late_downs"].update(z=round(z, 2), flag="hot" if z >= LATE_DOWN_FLAG_Z else "cold" if z <= -LATE_DOWN_FLAG_Z else None)


def late_down_note(team: str, p: dict | None) -> str | None:
    ld = (p or {}).get("late_downs") or {}
    if not ld.get("flag"):
        return None
    pts = ld["net"] * 100
    return (f"{team} is running {'hot' if ld['flag'] == 'hot' else 'cold'} on 3rd/4th downs: {abs(pts):.1f} points of success "
            f"rate {'above' if pts > 0 else 'below'} its early-down pace (offense minus defense). That gap hasn't repeated "
            f"within a season historically -- watched, not used by the model.")


def league_averages(teams: dict[str, dict]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for side in ("off", "def", "cov"):
        keys = {k for p in teams.values() for k, v in p[side].items() if isinstance(v, float)}
        out[side] = {k: round(statistics.fmean(vals), 4) for k in keys
                     if (vals := [p[side][k] for p in teams.values() if isinstance(p[side].get(k), float)])}
    return out


def index_counts(counts: dict) -> dict:
    """Per-season counts ({side: {"week|team": ...}}) indexed by team, for build_teams."""
    return {side: by_team(data) for side, data in (counts or {}).items() if side in ("off", "def")}


def build_teams(week: int, cur_t: dict, prev_t: dict, cov_cur: dict | None = None, cov_prev: dict | None = None) -> dict:
    """Graded team profiles entering `week` from indexed counts (index_counts)."""
    cov_cur, cov_prev = cov_cur or {}, cov_prev or {}
    teams: dict[str, dict] = {}
    names = {t for side in (cur_t, prev_t) for t in side.get("off", {})}
    for team in sorted(names):
        off_c, n_now, n_last = blend(cur_t, prev_t, team, "off", week)
        def_c, _, _ = blend(cur_t, prev_t, team, "def", week)
        if not off_c:
            continue
        cov_off, _, _ = blend(cov_cur, cov_prev, team, "off", week)
        cov_def, _, _ = blend(cov_cur, cov_prev, team, "def", week)
        teams[team] = {"off": offense_metrics(off_c), "def": defense_metrics(def_c),
                       "cov": coverage_metrics(cov_off, cov_def), "games": n_now, "prior_games": PRIOR_GAMES if n_last else 0}
    grade_units(teams)
    late_downs(teams)
    return teams


@memoize_async(300)
async def week_profiles(season: int, week: int) -> dict:
    """{"teams": {team: {"off", "def", "cov", "grades", "games", "prior_games"}},
    "league": {...}, "coverage_season", "sources", "note"} entering (season, week)."""
    cur, prev = await nc.get_pbp_aggregates(season, season), await nc.get_pbp_aggregates(season - 1, season)
    # Participation is usually published only after a season ends; when this
    # season's is missing, last season's alone supplies the coverage rates.
    cov_cur, cov_prev = await _coverage(season, season), await _coverage(season - 1, season)
    cov_season = season if cov_cur.get("available") else season - 1 if cov_prev.get("available") else None
    teams = build_teams(week, index_counts(cur.get("trenches")), index_counts(prev.get("trenches")),
                        index_counts(cov_cur), index_counts(cov_prev))
    has_ftn = any(p["off"].get("motion") is not None for p in teams.values())
    return {
        "teams": teams,
        "league": league_averages(teams) if teams else {},
        "coverage_season": cov_season,
        "has_ftn": has_ftn,
        "window": (f"{season} games before Week {week}, plus {season - 1} rates weighted as {PRIOR_GAMES} games; "
                   f"competitive plays only (win probability 10-90%)"),
        "sources": ["nflverse play-by-play"] + (["FTN charting (via nflverse)"] if has_ftn else [])
                   + ([f"nflverse participation / NGS ({cov_season})"] if cov_season else []),
        "note": REFERENCE_NOTE,
        "references": REFERENCES,
    }


# ------------------------------------------------------------------ matchups
def _ord(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _g(p: dict | None, unit: str) -> dict | None:
    return ((p or {}).get("grades") or {}).get(unit)


def _edge(off_p, off_unit, def_p, def_unit) -> dict | None:
    a, b = _g(off_p, off_unit), _g(def_p, def_unit)
    if not a or not b:
        return None
    e = round(a["z"] - b["z"], 2)
    strength = "strong" if abs(e) >= STRONG_EDGE else "lean" if abs(e) >= LEAN_EDGE else "neutral"
    # An edge only counts when the defense itself points the same way (a bad
    # offense against an average defense is the offense's problem, not the matchup's).
    if (e > 0 and b["z"] > 0) or (e < 0 and b["z"] < 0):
        strength = "neutral"
    return {"edge": e, "strength": strength, "offense_rank": a["rank"], "defense_rank": b["rank"]}


def matchup(tw: dict | None, offense: str, defense: str) -> dict:
    """How `offense` lines up against `defense`: edges (positive = offense
    advantage) for protection vs pass rush, run blocking vs run defense and
    dropback offense vs pass defense, plus original notes for DFS."""
    teams = (tw or {}).get("teams") or {}
    o, d = teams.get(offense), teams.get(defense)
    if not o or not d:
        return {"offense": offense, "defense": defense, "edges": {}, "notes": [], "notes_by": {}, "flags": []}
    league = tw.get("league") or {}
    edges = {k: v for k, v in {
        "protection": _edge(o, "pass_pro", d, "pass_rush"),
        "run": _edge(o, "run_block", d, "run_def"),
        "pass": _edge(o, "pass_offense", d, "coverage"),
    }.items() if v}
    notes: dict[str, str] = {}
    flags: list[str] = []

    pr = edges.get("protection")
    if pr and pr["strength"] != "neutral":
        ranks = f"{defense}'s pass rush {_ord(pr['defense_rank'])}, {offense}'s protection {_ord(pr['offense_rank'])}"
        if pr["edge"] < 0 and pr["strength"] == "strong":
            notes["protection"] = f"Pressure mismatch ({ranks}): expect a muddy pocket -- a QB downgrade and a {defense} DST upgrade."
            flags.append("pressure_mismatch")
        elif pr["edge"] < 0:
            notes["protection"] = f"Slight pressure edge for {defense} ({ranks})."
            flags.append("pressure_lean")
        else:
            notes["protection"] = f"{offense}'s protection should hold up ({ranks}): time for downfield routes to develop."
            flags.append("clean_pocket")
    ru = edges.get("run")
    if ru and ru["strength"] != "neutral":
        ranks = f"{offense}'s run blocking {_ord(ru['offense_rank'])}, {defense}'s run defense {_ord(ru['defense_rank'])}"
        if ru["edge"] > 0:
            what = "a friendly front for its backs" if ru["strength"] == "strong" else "a modest edge on the ground"
            notes["run"] = f"{offense} run game: {what} ({ranks})."
            flags.append("run_edge")
        else:
            what = "rushing efficiency likely suffers" if ru["strength"] == "strong" else "a slightly tougher front than usual"
            notes["run"] = f"{offense} run game: {what} ({ranks})."
            flags.append("run_wall")
    pa = edges.get("pass")
    if pa and pa["strength"] != "neutral":
        ranks = f"{offense}'s dropback efficiency {_ord(pa['offense_rank'])}, {defense}'s pass defense {_ord(pa['defense_rank'])}"
        if pa["edge"] > 0:
            what = "a clear passing-game edge" if pa["strength"] == "strong" else "a slight passing-game edge"
            notes["pass"] = f"{offense} passing game: {what} ({ranks})."
            flags.append("pass_edge")
        else:
            what = "a tough draw" if pa["strength"] == "strong" else "a slightly tougher draw than usual"
            notes["pass"] = f"{offense} passing game: {what} ({ranks})."
            flags.append("pass_wall")

    cov, lg_cov = d.get("cov") or {}, league.get("cov") or {}
    season = tw.get("coverage_season")
    if cov.get("man") is not None and lg_cov.get("man"):
        tag = f" ({season} coverage data)" if season else ""
        if cov["man"] >= lg_cov["man"] * 1.25:
            notes["coverage"] = (f"{defense} plays a lot of man ({cov['man']:.0%} vs {lg_cov['man']:.0%} league){tag}: "
                                 f"favors receivers who win one-on-one and a mobile QB.")
            flags.append("man_heavy")
        elif cov.get("two_high") is not None and lg_cov.get("two_high") and cov["two_high"] >= lg_cov["two_high"] * 1.2:
            notes["coverage"] = (f"{defense} lives in two-high shells ({cov['two_high']:.0%} vs {lg_cov['two_high']:.0%} league){tag}: "
                                 f"deep shots get capped, underneath targets, TEs and RBs gain.")
            flags.append("two_high")
    dd, lg_def = d.get("def") or {}, league.get("def") or {}
    if dd.get("blitz") is not None and lg_def.get("blitz") and dd["blitz"] >= lg_def["blitz"] * 1.3:
        notes["blitz"] = (f"{defense} blitzes on {dd['blitz']:.0%} of dropbacks (league {lg_def['blitz']:.0%}): boom-or-bust "
                          f"for {offense}'s QB -- sacks and turnovers, but also busted coverage.")
        flags.append("blitz_heavy")
    oo, lg_off = o.get("off") or {}, league.get("off") or {}
    if oo.get("light_box") is not None and lg_off.get("light_box") and oo["light_box"] >= lg_off["light_box"] * 1.2:
        notes["box"] = (f"{offense}'s backs see light boxes ({LIGHT_BOX} or fewer) on {oo['light_box']:.0%} of runs "
                        f"(league {lg_off['light_box']:.0%}).")
        flags.append("light_boxes")
    return {"offense": offense, "defense": defense, "edges": edges, "notes": list(notes.values()), "notes_by": notes, "flags": flags}


def game_notes(tw: dict | None, away: str, home: str, limit: int = 2) -> list[str]:
    """The biggest strong line/efficiency mismatches in a game, either side."""
    found = []
    for off, de in ((away, home), (home, away)):
        m = matchup(tw, off, de)
        for key, e in m["edges"].items():
            if e["strength"] == "strong" and key in m["notes_by"] and (key != "protection" or e["edge"] < 0):
                found.append((abs(e["edge"]), m["notes_by"][key]))
    return [n for _e, n in sorted(found, key=lambda x: -x[0])[:limit]]


def team_card(tw: dict | None, team: str) -> dict | None:
    """Unit ranks and scheme rates for one team, for tables."""
    p = ((tw or {}).get("teams") or {}).get(team)
    if not p:
        return None
    g = p.get("grades") or {}
    return {
        "team": team, "games": p["games"],
        "units": {u: {"label": UNIT_LABELS[u], **g[u]} for u in UNITS if u in g},
        "off": p["off"], "def": p["def"], "cov": p["cov"], "late_downs": p.get("late_downs"),
    }
