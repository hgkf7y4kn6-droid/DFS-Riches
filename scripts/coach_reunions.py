"""Do coaches facing a team they recently coached swing the game against the line?

    python -m scripts.coach_reunions

The idea to test: an offensive play caller who just left a team knows its
defense (personnel, calls, tendencies), so his offense beats that defense more
than the market expects -- the game goes over, or his team beats its implied
total. Likewise a defensive coordinator facing the offense he just left.

1. Coaching staffs: each team-season's head coach, offensive coordinator and
   defensive coordinator, 2006 on, from the infobox (and, where the infobox
   leaves coordinators out, the staff section) of Wikipedia's "<season> <team>
   season" articles (CC BY-SA 4.0), read one page at a time. Cached in
   data/cache/wiki_staffs_<season>.json.
2. Games: nflverse schedules (closing spread and total, final score),
   regular season and playoffs, 2006 on.
3. A team-game is a reunion when one of the team's coaches held a head coach
   or coordinator job with the opponent in any of the previous three seasons:
     offense  -- its OC, or its head coach if he's been an OC in the data
                 (an offensive head coach, usually the play caller)
     defense  -- its DC, or its head coach if he's been a DC in the data
   "First meeting" is the coach's first game against that team after leaving.
   Former division mates: the opponent was in the division of a team the
   coach was with in those three seasons (so he faced it twice a year), it
   isn't that team itself, and it isn't in his current team's division
   (current division games carry that familiarity for both sides).
   Divisions come from nflverse's division-game flags.
4. Against games with no coach connection at all: the game total vs the closing total (signed, the
   over rate, the miss size, how often it misses by 10+), the reunion team's
   points vs its implied total, and its cover rate. p-values from 20,000
   within-season permutations of the reunion label.

Writes data/coach_reunions.json. No proprietary sources.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import random
import re
import statistics
import time
from pathlib import Path

import httpx

from app import nflverse_client as nc
from app.config import NFLVERSE_GAMES_CSV_URL

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "data" / "coach_reunions.json"
FIRST_SEASON = 2006
LOOKBACK = 3
RAW = "https://en.wikipedia.org/w/index.php"
HEADERS = {"User-Agent": "DFSRichesResearch/1.0 (https://dfsriches.richesdigitalventures.com; coach-history study)"}

# Franchise ids across relocations (nflverse's older abbreviations).
FRANCHISE = {"STL": "LA", "SD": "LAC", "OAK": "LV"}
NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
    "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints",
    "NYG": "New York Giants", "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans",
    "STL": "St. Louis Rams", "SD": "San Diego Chargers", "OAK": "Oakland Raiders",
}


def team_name(abbr: str, season: int) -> str:
    if abbr == "LA":
        return "Los Angeles Rams"
    if abbr == "LAC":
        return "Los Angeles Chargers"
    if abbr == "LV":
        return "Las Vegas Raiders"
    if abbr == "WAS":
        return "Washington Redskins" if season <= 2019 else "Washington Football Team" if season <= 2021 else "Washington Commanders"
    return NAMES[abbr]


# ----------------------------------------------------------------- staffs
LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


def people(value: str) -> list[str]:
    """Coach names in an infobox value: link targets, else the plain names (split on line breaks)."""
    value = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", "", value, flags=re.S)
    links = [m.strip() for m in LINK.findall(value)]
    if links:
        return links
    text = re.sub(r"\{\{[^{}]*\}\}|\([^)]*\)|<[^>]+>|'''?", "|", value)
    return [p.strip() for p in re.split(r"[|,;\n]", text) if len(p.strip()) > 3 and not p.strip().lower().startswith(("interim", "week"))]


def infobox_field(text: str, field: str) -> str:
    m = re.search(rf"^\s*\|\s*{field}\s*=(.*?)(?=^\s*\||^\}}\}})", text, flags=re.M | re.S)
    return m.group(1) if m else ""


def staff_line(text: str, role: str) -> list[str]:
    """Names on a staff-section line like "Offensive coordinator – [[Name]]"."""
    out = []
    for m in re.finditer(rf"{role}\s*(?:[–—-]|:|\]\])\s*(.{{0,160}})", text, flags=re.I):
        line = m.group(1).split("\n")[0]
        out += [n for n in LINK.findall(line)][:1] or people(line)[:1]
    return list(dict.fromkeys(n.strip() for n in out if n.strip()))


def parse_staff(text: str) -> dict:
    hc, oc, dc = (people(infobox_field(text, f)) for f in ("coach", "off_coach", "def_coach"))
    if not oc:
        oc = staff_line(text, "offensive coordinator")
    if not dc:
        dc = staff_line(text, "defensive coordinator")
    return {"hc": hc, "oc": oc, "dc": dc}


def wiki_page(title: str) -> str | None:
    """A page's wikitext (index.php?action=raw), following redirects, retrying through rate limits."""
    for _ in range(3):                        # redirect hops
        text = None
        for attempt in range(8):
            r = httpx.get(RAW, params={"title": title, "action": "raw"}, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                text = r.text
                break
            if r.status_code == 404:
                return None
            time.sleep(15 * (attempt + 1))
        time.sleep(1.0)                       # a polite pace
        if text is None:
            raise RuntimeError(f"Wikipedia kept refusing {title!r}")
        m = re.match(r"\s*#REDIRECT\s*\[\[([^\]|#]+)", text, flags=re.I)
        if not m:
            return text
        title = m.group(1).strip()
    return None


def staffs_for(season: int, teams: list[str]) -> dict[str, dict]:
    path = CACHE / f"wiki_staffs_{season}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        if set(teams) <= set(cached):
            return cached
    staffs = {}
    for t in teams:
        text = wiki_page(f"{season} {team_name(t, season)} season")
        if text:
            staffs[t] = parse_staff(text)
    for t in teams:
        staffs.setdefault(t, {"hc": [], "oc": [], "dc": []})
    path.write_text(json.dumps(staffs, indent=1))
    print(f"  {season}: {sum(1 for s in staffs.values() if s['oc'])}/{len(teams)} OCs, "
          f"{sum(1 for s in staffs.values() if s['dc'])}/{len(teams)} DCs")
    return staffs


# ------------------------------------------------------------------ games
def f(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


async def games() -> list[dict]:
    text = await nc._fetch_csv_text(NFLVERSE_GAMES_CSV_URL)
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        s = int(r["season"])
        hs, as_, total, spread = f(r["home_score"]), f(r["away_score"]), f(r["total_line"]), f(r["spread_line"])
        if s < FIRST_SEASON or hs is None or as_ is None or total is None or spread is None:
            continue
        out.append({"season": s, "week": int(r["week"]), "gameday": r["gameday"], "type": r["game_type"], "div": r["div_game"] == "1",
                    "home": r["home_team"], "away": r["away_team"], "hs": hs, "as": as_, "total": total, "spread": spread})
    return sorted(out, key=lambda g: (g["gameday"], g["home"]))


# --------------------------------------------------------------- analysis
def reunions(all_games: list[dict], staffs: dict[int, dict[str, dict]]) -> list[dict]:
    """One row per team-game: outcomes, plus who on the staff (if anyone) recently coached the opponent."""
    def fr(t):
        return FRANCHISE.get(t, t)

    # Every (season, franchise) a coach held each role.
    roles: dict[str, list[tuple[int, str, str]]] = {}
    for season, teams in staffs.items():
        for t, st in teams.items():
            for role in ("hc", "oc", "dc"):
                for name in st[role]:
                    roles.setdefault(name, []).append((season, fr(t), role))

    # Divisions per season: teams joined by division games.
    division: dict[int, dict[str, frozenset]] = {}
    for season in {g["season"] for g in all_games}:
        links: dict[str, set] = {}
        for g in all_games:
            if g["season"] == season and g["div"]:
                a, b = fr(g["home"]), fr(g["away"])
                links.setdefault(a, set()).add(b)
                links.setdefault(b, set()).add(a)
        for t, mates in links.items():
            division.setdefault(season, {})[t] = frozenset(mates | {t})

    def former_division(name: str, team: str, opp: str, season: int) -> bool:
        current = division.get(season, {}).get(team, frozenset())
        if opp in current:
            return False
        return any(season - LOOKBACK <= s < season and t not in (team, opp) and opp in division.get(s, {}).get(t, ())
                   for s, t, _ in roles.get(name, []))

    def been(name: str, role: str, before: int) -> bool:
        return any(s < before and r == role for s, _, r in roles.get(name, []))

    def coached(name: str, opp: str, season: int) -> bool:
        return any(season - LOOKBACK <= s < season and t == opp and r in ("hc", "oc", "dc") for s, t, r in roles.get(name, []))

    seen_meetings: set[tuple[str, str, str]] = set()
    rows = []
    for g in all_games:
        st = staffs.get(g["season"], {})
        for side, opp_side in (("home", "away"), ("away", "home")):
            team, opp = g[side], g[opp_side]
            s = st.get(team)
            if not s:
                continue
            implied = (g["total"] + g["spread"]) / 2 if side == "home" else (g["total"] - g["spread"]) / 2
            pts = g["hs"] if side == "home" else g["as"]
            margin = (g["hs"] - g["as"]) * (1 if side == "home" else -1)
            exp_margin = g["spread"] * (1 if side == "home" else -1)
            offense = list(s["oc"]) + [h for h in s["hc"] if been(h, "oc", g["season"] + 1)]
            defense = list(s["dc"]) + [h for h in s["hc"] if been(h, "dc", g["season"] + 1)]
            off_r = sorted({c for c in offense if coached(c, fr(opp), g["season"])})
            def_r = sorted({c for c in defense if coached(c, fr(opp), g["season"])})
            off_d = sorted({c for c in offense if c not in off_r and former_division(c, fr(team), fr(opp), g["season"])})
            def_d = sorted({c for c in defense if c not in def_r and former_division(c, fr(team), fr(opp), g["season"])})
            first = False
            for c in off_r + def_r:
                key = (c, fr(team), fr(opp))
                if key not in seen_meetings:
                    seen_meetings.add(key)
                    first = True
            rows.append({
                "season": g["season"], "week": g["week"], "type": g["type"], "team": team, "opp": opp,
                "game": f"{g['away']}@{g['home']}", "off_reunion": off_r, "def_reunion": def_r, "first": first,
                "off_division": off_d, "def_division": def_d,
                "resid": g["hs"] + g["as"] - g["total"], "team_vs_implied": pts - implied,
                "cover": margin - exp_margin, "points": pts, "implied": round(implied, 1),
            })
    return rows


def summarize(rows: list[dict]) -> dict:
    res = [r["resid"] for r in rows]
    decided = [x for x in res if x != 0]
    covers = [r["cover"] for r in rows if r["cover"] != 0]
    return {
        "team_games": len(rows),
        "total_resid_mean": round(statistics.fmean(res), 2) if res else None,
        "over_rate": round(sum(x > 0 for x in decided) / len(decided), 3) if decided else None,
        "abs_miss_mean": round(statistics.fmean(abs(x) for x in res), 2) if res else None,
        "miss_10plus_rate": round(sum(abs(x) >= 10 for x in res) / len(res), 3) if res else None,
        "team_vs_implied_mean": round(statistics.fmean(r["team_vs_implied"] for r in rows), 2) if rows else None,
        "team_beat_implied_rate": round(sum(r["team_vs_implied"] > 0 for r in rows) / len(rows), 3) if rows else None,
        "cover_rate": round(sum(c > 0 for c in covers) / len(covers), 3) if covers else None,
    }


STATS = {
    "total_resid_mean": lambda rs: statistics.fmean(r["resid"] for r in rs),
    "over_rate": lambda rs: statistics.fmean(r["resid"] > 0 for r in rs if r["resid"] != 0),
    "abs_miss_mean": lambda rs: statistics.fmean(abs(r["resid"]) for r in rs),
    "miss_10plus_rate": lambda rs: statistics.fmean(abs(r["resid"]) >= 10 for r in rs),
    "team_vs_implied_mean": lambda rs: statistics.fmean(r["team_vs_implied"] for r in rs),
    "cover_rate": lambda rs: statistics.fmean(r["cover"] > 0 for r in rs if r["cover"] != 0),
}


def permutation_p(rows: list[dict], flag, n: int = 20000, seed: int = 7) -> dict:
    """Two-sided p for each stat: shuffle the flag within seasons and compare group differences."""
    rnd = random.Random(seed)
    by_season: dict[int, list[int]] = {}
    for i, r in enumerate(rows):
        by_season.setdefault(r["season"], []).append(i)
    labels = [flag(r) for r in rows]

    def diff(lab, stat):
        a = [r for r, x in zip(rows, lab) if x]
        b = [r for r, x in zip(rows, lab) if not x]
        return STATS[stat](a) - STATS[stat](b)

    observed = {k: diff(labels, k) for k in STATS}
    extreme = {k: 0 for k in STATS}
    for _ in range(n):
        lab = labels[:]
        for idx in by_season.values():
            vals = [lab[i] for i in idx]
            rnd.shuffle(vals)
            for i, v in zip(idx, vals):
                lab[i] = v
        for k in STATS:
            if abs(diff(lab, k)) >= abs(observed[k]) - 1e-12:
                extreme[k] += 1
    return {k: {"diff": round(observed[k], 3), "p": round((extreme[k] + 1) / (n + 1), 4)} for k in STATS}


async def main() -> None:
    all_games = await games()
    seasons = sorted({g["season"] for g in all_games})
    print(f"{len(all_games)} games {seasons[0]}-{seasons[-1]}; staffs from Wikipedia:")
    staffs = {}
    for s in seasons:
        teams = sorted({g["home"] for g in all_games if g["season"] == s} | {g["away"] for g in all_games if g["season"] == s})
        staffs[s] = staffs_for(s, teams)
    rows = reunions(all_games, staffs)

    groups = {
        "offense": lambda r: bool(r["off_reunion"]),
        "offense_first_meeting": lambda r: bool(r["off_reunion"]) and r["first"],
        "defense": lambda r: bool(r["def_reunion"]),
        "any": lambda r: bool(r["off_reunion"] or r["def_reunion"]),
        "offense_former_division": lambda r: bool(r["off_division"]) and not r["off_reunion"],
        "defense_former_division": lambda r: bool(r["def_division"]) and not r["def_reunion"],
        "any_former_division": lambda r: bool(r["off_division"] or r["def_division"]) and not (r["off_reunion"] or r["def_reunion"]),
    }
    baseline = [r for r in rows if not (r["off_reunion"] or r["def_reunion"] or r["off_division"] or r["def_division"])]
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seasons": [seasons[0], seasons[-1]], "lookback_seasons": LOOKBACK,
        "baseline": summarize(baseline),
        "groups": {},
        "source": "Coaching staffs: Wikipedia team-season articles (CC BY-SA 4.0). Games and lines: nflverse.",
    }
    # Each group against the games with no coach connection at all.
    plain = {id(r) for r in baseline}
    for name, flag in groups.items():
        sel = [r for r in rows if flag(r)]
        pool = sel + [r for r in rows if id(r) in plain]
        result["groups"][name] = {"summary": summarize(sel), "vs_baseline": permutation_p(pool, flag, n=10000)}
        print(name, result["groups"][name]["summary"])
        print("   vs baseline", result["groups"][name]["vs_baseline"])
    print("baseline", result["baseline"])
    result["offense_examples"] = [
        {k: r[k] for k in ("season", "week", "team", "opp", "off_reunion", "first", "resid", "team_vs_implied", "points", "implied")}
        for r in rows if r["off_reunion"]
    ]
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
