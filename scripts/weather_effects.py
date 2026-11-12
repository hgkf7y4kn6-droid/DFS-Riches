"""Measure what game-time weather does to NFL offense, and how much of it
the projection sources already price in.

    python -m scripts.weather_effects

1. Every regular-season game 2016-2025. For games played in the open air
   (nflverse roof "outdoors"/"open"), the kickoff-window weather at the
   stadium from Open-Meteo's historical archive -- the same variables and
   the same kickoff-window summary app.weather uses for forecasts, so the
   fit and the forecasts are on one scale.
2. One row per team-game. Outcomes: the offense's passing yards/TDs,
   rushing yards/TDs and points, plus the opposing defense's DraftKings DST
   points. OLS with offense-season and defense-season fixed effects (so a
   bad offense playing in Buffalo in December isn't read as "weather"), an
   indoor dummy, and four weather features:
       wind_over_10   mph of average wind above 10
       rain           measurable precipitation (0.02 in+) above 34°F
       snow           measurable precipitation at 34°F or colder
       cold_below_40  degrees below 40°F
3. Priced-in check: for 2025 and this season's finished weeks, each skill
   player's actual DK points minus Sleeper's projection, regressed on the
   weather delta the fit predicts for his projected line. A slope near 1
   means projections ignore weather (apply it in full); near 0 means they
   already account for it. applied_share = that slope, clipped to [0, 1].

Writes data/weather_effects.json, read by app.weather.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app import dk_scoring, projections, sleeper_client, weather
from app import nflverse_client as nc
from app.cache import cached_fetch
from app.config import ET, NFLVERSE_GAMES_CSV_URL

FIT_SEASONS = range(2016, 2026)
CHECK = [(2025, range(1, 19)), (2026, range(1, 4))]
OUT = Path(__file__).resolve().parent.parent / "data" / "weather_effects.json"
FEATURES = ["wind_over_10", "rain", "snow", "cold_below_40"]
OUTCOMES = ["pass_yd", "pass_td", "rush_yd", "rush_td", "points", "dst"]
TTL = 60 * 60 * 24 * 365


def kickoff(row: dict) -> datetime | None:
    try:
        local = datetime.strptime(f"{row['gameday']} {row['gametime']}", "%Y-%m-%d %H:%M")
    except (KeyError, ValueError):
        return None
    return local.replace(tzinfo=ET).astimezone(timezone.utc)


async def game_rows() -> list[dict]:
    text = await nc._fetch_csv_text(NFLVERSE_GAMES_CSV_URL)
    wanted = set(FIT_SEASONS) | {s for s, _ in CHECK}
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("game_type") != "REG" or int(r["season"]) not in wanted or not r.get("away_score"):
            continue
        k = kickoff(r)
        if k is None:
            continue
        out.append({"season": int(r["season"]), "week": int(r["week"]), "away": nc.to_app_team(r["away_team"]),
                    "home": nc.to_app_team(r["home_team"]), "away_score": int(r["away_score"]), "home_score": int(r["home_score"]),
                    "kickoff": k, "exposed": r.get("roof") in ("outdoors", "open"), "venue": weather.venue(r.get("stadium_id"), nc.to_app_team(r["home_team"]))})
    return out


async def attach_weather(games: list[dict]) -> None:
    """Archive weather for every open-air game: one request per season covering
    all its venues and dates (Open-Meteo drops bursts of small requests)."""
    by_season: dict[int, list[dict]] = {}
    for g in games:
        if g["exposed"] and g["venue"]:
            by_season.setdefault(g["season"], []).append(g)
    for season, items in sorted(by_season.items()):
        points = sorted({(g["venue"]["lat"], g["venue"]["lon"]) for g in items})
        start = min(g["kickoff"] for g in items).strftime("%Y-%m-%d")
        end = (max(g["kickoff"] for g in items) + timedelta(days=1)).strftime("%Y-%m-%d")
        key = f"weather_archive_season_{season}_{len(points)}"
        series = None
        for attempt in range(5):
            try:
                series = dict(zip(points, await cached_fetch(
                    key, TTL, lambda: weather.fetch_open_meteo(points, start, end, archive=True))))
                break
            except Exception as e:  # noqa: BLE001
                print(f"  {season}: archive failed ({type(e).__name__}); retrying")
                await asyncio.sleep(15 * (attempt + 1))
        if series is None:
            print(f"  {season}: skipped")
            continue
        for g in items:
            w = weather.kickoff_window(series.get((g["venue"]["lat"], g["venue"]["lon"])) or {}, g["kickoff"])
            if w:
                g["weather"] = w
                g["features"] = weather.features(w, observed=True)
        print(f"  weather: {season} ({len(items)} open-air games, {len(points)} venues)")
        await asyncio.sleep(3)


async def team_rows(season: int) -> dict[tuple[int, str], dict]:
    return {(int(r["week"]), nc.to_app_team(r["team"])): r for r in await nc._fetch_team_week_rows(season)
            if r.get("season_type", "REG") == "REG" and r.get("week")}


def f(row: dict, k: str) -> float:
    try:
        return float(row.get(k) or 0)
    except ValueError:
        return 0.0


async def build_rows(games: list[dict]) -> list[dict]:
    rows = []
    stats = {s: await team_rows(s) for s in FIT_SEASONS}
    for g in games:
        if g["season"] not in FIT_SEASONS or (g["exposed"] and "features" not in g):
            continue
        for off, de, pts, allowed in ((g["away"], g["home"], g["away_score"], g["away_score"]),
                                      (g["home"], g["away"], g["home_score"], g["home_score"])):
            o, d = stats[g["season"]].get((g["week"], off)), stats[g["season"]].get((g["week"], de))
            if not o or not d:
                continue
            rows.append({
                "off": f"{g['season']}{off}", "def": f"{g['season']}{de}", "indoor": 0.0 if g["exposed"] else 1.0,
                **{k: (g.get("features") or {}).get(k, 0.0) for k in FEATURES},
                "pass_yd": f(o, "passing_yards"), "pass_td": f(o, "passing_tds"), "rush_yd": f(o, "rushing_yards"),
                "rush_td": f(o, "rushing_tds"), "points": float(pts), "dst": dk_scoring.dk_dst_points(d, allowed),
            })
    return rows


def fit(rows: list[dict]) -> dict:
    offs = sorted({r["off"] for r in rows})
    defs = sorted({r["def"] for r in rows})
    oi, di = {k: i for i, k in enumerate(offs)}, {k: i for i, k in enumerate(defs)}
    n, k = len(rows), len(offs) + len(defs) + 1 + len(FEATURES)
    X = np.zeros((n, k))
    for i, r in enumerate(rows):
        X[i, oi[r["off"]]] = 1
        X[i, len(offs) + di[r["def"]]] = 1
        X[i, len(offs) + len(defs)] = r["indoor"]
        for j, feat in enumerate(FEATURES):
            X[i, len(offs) + len(defs) + 1 + j] = r[feat]
    xtx_inv = np.linalg.pinv(X.T @ X)
    out = {}
    for name in OUTCOMES:
        y = np.array([r[name] for r in rows])
        beta = xtx_inv @ X.T @ y
        resid = y - X @ beta
        sigma2 = float(resid @ resid) / max(1, n - np.linalg.matrix_rank(X))
        se = np.sqrt(np.diag(xtx_inv) * sigma2)
        base = len(offs) + len(defs) + 1
        out[name] = {
            "mean": round(float(y.mean()), 4),
            "coef": {feat: round(float(beta[base + j]), 5) for j, feat in enumerate(FEATURES)},
            "se": {feat: round(float(se[base + j]), 5) for j, feat in enumerate(FEATURES)},
            "indoor": round(float(beta[base - 1]), 4),
        }
    return out


async def priced_in(games: list[dict], outcomes: dict) -> dict:
    """Slope of (actual - Sleeper projection) on the fitted weather delta."""
    effects = {"outcomes": outcomes, "applied_share": 1.0}
    by_team = {}
    for g in games:
        for t in (g["away"], g["home"]):
            by_team[(g["season"], g["week"], t)] = g
    xs, ys = [], []
    for season, weeks in CHECK:
        for week in weeks:
            try:
                lines = await sleeper_client.get_projection_lines(season, week)
                actual = await nc.get_week_actuals(season, week)
            except Exception:  # noqa: BLE001
                continue
            if not actual["players"]:
                continue
            for line in lines.values():
                pos = line.get("position")
                if pos not in projections.SKILL or not line.get("name") or not line.get("team"):
                    continue
                proj = projections.dk_points_from_line(line["stats"], pos)
                key = nc.player_key(line["name"], pos)
                if proj < projections.MIN_LINE_POINTS or key not in actual["players"]:
                    continue
                g = by_team.get((season, week, nc.to_app_team(line["team"])))
                if g is None or not g["exposed"] or "features" not in g:
                    continue
                mult = weather.multipliers(g["features"], effects)
                adjusted = projections.dk_points_from_line(weather.scale_line(line["stats"], mult), pos)
                xs.append(adjusted - proj)
                ys.append(actual["players"][key] - proj)
    x, y = np.array(xs), np.array(ys)
    informative = int(np.sum(np.abs(x) >= 0.25))
    if informative < 30:
        return {"slope": None, "se": None, "player_games": len(xs), "informative": informative}
    X = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    cov = np.linalg.inv(X.T @ X) * float(resid @ resid) / (len(y) - 2)
    return {"slope": round(float(beta[1]), 3), "se": round(float(np.sqrt(cov[1, 1])), 3),
            "player_games": len(xs), "informative": informative}


async def main() -> None:
    games = await game_rows()
    print(f"{len(games)} games; fetching archive weather for open-air games...")
    await attach_weather(games)
    rows = await build_rows(games)
    exposed = sum(1 for r in rows if not r["indoor"])
    print(f"fitting on {len(rows)} team-games ({exposed} open-air)")
    outcomes = fit(rows)
    check = await priced_in(games, outcomes)
    share = 1.0 if check["slope"] is None else max(0.0, min(1.0, check["slope"]))
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seasons": [min(FIT_SEASONS), max(FIT_SEASONS)], "team_games": len(rows), "open_air_team_games": exposed,
        "features": FEATURES, "outcomes": outcomes,
        "priced_in_check": {**check, "seasons": [s for s, _ in CHECK]},
        "applied_share": round(share, 3),
        "source": "Open-Meteo historical weather (CC BY 4.0) + nflverse schedules/box scores",
    }
    OUT.write_text(json.dumps(result, indent=1))
    for name, e in outcomes.items():
        print(name, "mean", e["mean"], {k: f"{v:+.3f}±{e['se'][k]:.3f}" for k, v in e["coef"].items()})
    print("priced-in check", check, "-> applied_share", result["applied_share"])


if __name__ == "__main__":
    asyncio.run(main())
