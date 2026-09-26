"""Game-time weather for every game, and what it does to projections.

Where it comes from:
  forecast   Open-Meteo's forecast API (free, no key, CC BY 4.0; up to 16
             days out, updated hourly), one batched request for every
             stadium in the week. Falls back to the US National Weather
             Service hourly forecast (public domain, 7 days) if Open-Meteo
             is down.
  past games Open-Meteo's historical data for the same hours, so a finished
             week shows the weather the game was actually played in.
  venues     STADIUMS below: coordinates and roof type for every venue in
             nflverse's schedule (keyed by its stadium_id), including
             international games.

The kickoff window is the kickoff hour plus the next two (a game runs
about 3 hours): average temperature and wind, peak gust, highest chance of
precipitation, and total rain/snow.

Domes and fixed roofs get no weather. Retractable roofs show the forecast
but no adjustment: teams close them when it's cold, wet or windy.

What weather does to projections comes from data/weather_effects.json
(scripts/weather_effects.py): a fit of 2016-2025 team-game results on
game-time weather, with team and opponent strength held fixed. Only the
part the projection sources don't already price in is applied.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.cache import cached_fetch

EFFECTS_PATH = Path(__file__).resolve().parent.parent / "data" / "weather_effects.json"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
HOURLY = "temperature_2m,precipitation_probability,precipitation,snowfall,wind_speed_10m,wind_gusts_10m,weather_code"
HEADERS = {"User-Agent": "DFSRiches/1.0 (+https://github.com/)"}
FORECAST_DAYS = 16
FORECAST_PAST_DAYS = 80        # the forecast API keeps ~3 months of past hours; older games use the archive
FULL_WEIGHT_DAYS = 7           # beyond a week out, forecasts are shaky: adjustments at half strength
WINDOW_HOURS = 3
TTL_FUTURE = 60 * 60           # forecasts update hourly
TTL_PAST = 60 * 60 * 24 * 30
ATTRIBUTION = "Weather: Open-Meteo.com (CC BY 4.0) / National Weather Service"

# stadium_id -> (name, lat, lon, roof): roof is "dome", "retractable" or "outdoors"
STADIUMS: dict[str, tuple[str, float, float, str]] = {
    "ATL97": ("Mercedes-Benz Stadium", 33.7554, -84.4008, "retractable"),
    "ATL00": ("Georgia Dome", 33.7577, -84.4008, "dome"),
    "BAL00": ("M&T Bank Stadium", 39.2780, -76.6227, "outdoors"),
    "BOS00": ("Gillette Stadium", 42.0909, -71.2643, "outdoors"),
    "BUF00": ("Highmark Stadium", 42.7738, -78.7870, "outdoors"),
    "CAR00": ("Bank of America Stadium", 35.2258, -80.8528, "outdoors"),
    "CHI98": ("Soldier Field", 41.8623, -87.6167, "outdoors"),
    "CIN00": ("Paycor Stadium", 39.0955, -84.5161, "outdoors"),
    "CLE00": ("Huntington Bank Field", 41.5061, -81.6995, "outdoors"),
    "DAL00": ("AT&T Stadium", 32.7473, -97.0945, "retractable"),
    "DEN00": ("Empower Field at Mile High", 39.7439, -105.0201, "outdoors"),
    "DET00": ("Ford Field", 42.3400, -83.0456, "dome"),
    "GNB00": ("Lambeau Field", 44.5013, -88.0622, "outdoors"),
    "HOU00": ("NRG Stadium", 29.6847, -95.4107, "retractable"),
    "IND00": ("Lucas Oil Stadium", 39.7601, -86.1639, "retractable"),
    "JAX00": ("EverBank Stadium", 30.3239, -81.6373, "outdoors"),
    "KAN00": ("GEHA Field at Arrowhead Stadium", 39.0489, -94.4839, "outdoors"),
    "LAX01": ("SoFi Stadium", 33.9535, -118.3392, "dome"),
    "LAX97": ("StubHub Center", 33.8644, -118.2611, "outdoors"),
    "LAX99": ("Los Angeles Memorial Coliseum", 34.0141, -118.2879, "outdoors"),
    "MIA00": ("Hard Rock Stadium", 25.9580, -80.2389, "outdoors"),
    "MIN01": ("U.S. Bank Stadium", 44.9737, -93.2575, "dome"),
    "NAS00": ("Nissan Stadium", 36.1665, -86.7713, "outdoors"),
    "NOR00": ("Caesars Superdome", 29.9511, -90.0812, "dome"),
    "NYC01": ("MetLife Stadium", 40.8135, -74.0745, "outdoors"),
    "OAK00": ("Oakland Coliseum", 37.7516, -122.2005, "outdoors"),
    "PHI00": ("Lincoln Financial Field", 39.9008, -75.1675, "outdoors"),
    "PHO00": ("State Farm Stadium", 33.5276, -112.2626, "retractable"),
    "PIT00": ("Acrisure Stadium", 40.4468, -80.0158, "outdoors"),
    "SDG00": ("Qualcomm Stadium", 32.7831, -117.1196, "outdoors"),
    "SEA00": ("Lumen Field", 47.5952, -122.3316, "outdoors"),
    "SFO01": ("Levi's Stadium", 37.4030, -121.9700, "outdoors"),
    "TAM00": ("Raymond James Stadium", 27.9759, -82.5033, "outdoors"),
    "VEG00": ("Allegiant Stadium", 36.0909, -115.1833, "dome"),
    "WAS00": ("Northwest Stadium", 38.9078, -76.8645, "outdoors"),
    # international
    "LON00": ("Wembley Stadium", 51.5560, -0.2796, "outdoors"),
    "LON01": ("Twickenham Stadium", 51.4560, -0.3415, "outdoors"),
    "LON02": ("Tottenham Hotspur Stadium", 51.6043, -0.0664, "outdoors"),
    "MEX00": ("Estadio Banorte", 19.3029, -99.1505, "outdoors"),
    "FRA00": ("Deutsche Bank Park", 50.0686, 8.6455, "outdoors"),
    "GER00": ("Allianz Arena", 48.2188, 11.6247, "outdoors"),
    "MUN01": ("Allianz Arena", 48.2188, 11.6247, "outdoors"),
    "SAO00": ("Arena Corinthians", -23.5453, -46.4742, "outdoors"),
    "RIO00": ("Maracana Stadium", -22.9122, -43.2302, "outdoors"),
    "MAD01": ("Santiago Bernabeu", 40.4531, -3.6883, "retractable"),
    "PAR00": ("Stade de France", 48.9245, 2.3602, "outdoors"),
    "MEL00": ("Melbourne Cricket Ground", -37.8200, 144.9834, "outdoors"),
}
# home team -> usual stadium, when nflverse hasn't tagged a game yet
HOME_STADIUM = {
    "ARI": "PHO00", "ATL": "ATL97", "BAL": "BAL00", "BUF": "BUF00", "CAR": "CAR00", "CHI": "CHI98", "CIN": "CIN00",
    "CLE": "CLE00", "DAL": "DAL00", "DEN": "DEN00", "DET": "DET00", "GB": "GNB00", "HOU": "HOU00", "IND": "IND00",
    "JAX": "JAX00", "KC": "KAN00", "LAC": "LAX01", "LAR": "LAX01", "LV": "VEG00", "MIA": "MIA00", "MIN": "MIN01",
    "NE": "BOS00", "NO": "NOR00", "NYG": "NYC01", "NYJ": "NYC01", "PHI": "PHI00", "PIT": "PIT00", "SEA": "SEA00",
    "SF": "SFO01", "TB": "TAM00", "TEN": "NAS00", "WAS": "WAS00",
}

WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog", 51: "Light drizzle",
       53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle", 61: "Light rain", 63: "Rain",
       65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
       77: "Snow grains", 80: "Rain showers", 81: "Rain showers", 82: "Heavy showers", 85: "Snow showers",
       86: "Heavy snow showers", 95: "Thunderstorms", 96: "Thunderstorms, hail", 99: "Thunderstorms, hail"}

# thresholds for labeling (the projection adjustments use the fitted effects, not these)
WINDY, VERY_WINDY = 15.0, 20.0
WET_CHANCE = 50.0
FREEZING, HOT = 32.0, 90.0


def venue(stadium_id: str | None, home: str) -> dict | None:
    sid = stadium_id if stadium_id in STADIUMS else HOME_STADIUM.get(home)
    if sid not in STADIUMS:
        return None
    name, lat, lon, roof = STADIUMS[sid]
    return {"stadium_id": sid, "name": name, "lat": lat, "lon": lon, "roof": roof}


# ------------------------------------------------------------------ fetching
def _parse_open_meteo(payload) -> list[dict]:
    items = payload if isinstance(payload, list) else [payload]
    return [it.get("hourly") or {} for it in items]


async def fetch_open_meteo(points: list[tuple[float, float]], start: str, end: str, *, archive: bool = False) -> list[dict]:
    """Hourly series (UTC) for each (lat, lon), batched into one request."""
    params = {
        "latitude": ",".join(f"{lat:.4f}" for lat, _ in points),
        "longitude": ",".join(f"{lon:.4f}" for _, lon in points),
        "hourly": HOURLY if not archive else HOURLY.replace("precipitation_probability,", ""),
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch",
        "timezone": "UTC", "start_date": start, "end_date": end,
    }
    async with httpx.AsyncClient(headers=HEADERS, timeout=120 if archive else 30) as client:
        for attempt in range(2):          # one retry: the free tier occasionally 429s/5xxs under load
            try:
                resp = await client.get(OPEN_METEO_ARCHIVE if archive else OPEN_METEO_FORECAST, params=params)
                resp.raise_for_status()
                return _parse_open_meteo(resp.json())
            except (httpx.HTTPError, ValueError):
                if attempt:
                    raise
                await asyncio.sleep(1.5)


def _nws_to_hourly(periods: list[dict]) -> dict:
    """NWS hourly periods -> the Open-Meteo hourly shape used here."""
    out: dict[str, list] = {k: [] for k in ("time", "temperature_2m", "precipitation_probability", "precipitation",
                                            "snowfall", "wind_speed_10m", "wind_gusts_10m", "weather_code", "text")}
    for p in periods:
        t = datetime.fromisoformat(p["startTime"]).astimezone(timezone.utc)
        speed = p.get("windSpeed") or "0 mph"
        nums = [float(x) for x in speed.replace("mph", "").replace("to", " ").split() if x.replace(".", "").isdigit()]
        out["time"].append(t.strftime("%Y-%m-%dT%H:00"))
        temp = p.get("temperature")
        out["temperature_2m"].append(temp if p.get("temperatureUnit", "F") == "F" else temp * 9 / 5 + 32)
        out["precipitation_probability"].append((p.get("probabilityOfPrecipitation") or {}).get("value") or 0)
        out["precipitation"].append(None)
        out["snowfall"].append(None)
        out["wind_speed_10m"].append(max(nums) if nums else 0.0)
        out["wind_gusts_10m"].append(None)
        out["weather_code"].append(None)
        out["text"].append(p.get("shortForecast"))
    return out


async def fetch_nws(lat: float, lon: float) -> dict:
    async with httpx.AsyncClient(headers={**HEADERS, "Accept": "application/geo+json"}, timeout=30, follow_redirects=True) as client:
        pt = await client.get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
        pt.raise_for_status()
        fc = await client.get(pt.json()["properties"]["forecastHourly"])
        fc.raise_for_status()
        return _nws_to_hourly(fc.json()["properties"]["periods"])


# --------------------------------------------------------------- summarizing
def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def kickoff_window(hourly: dict, kickoff_utc: datetime) -> dict | None:
    """Average/peak conditions over the kickoff hour and the next two."""
    times = hourly.get("time") or []
    start = kickoff_utc.replace(minute=0, second=0, microsecond=0)
    wanted = {(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:00") for i in range(WINDOW_HOURS)}
    idx = [i for i, t in enumerate(times) if t in wanted]
    if not idx:
        return None

    def col(k):
        vals = hourly.get(k) or []
        return [vals[i] for i in idx if i < len(vals)]

    codes = [c for c in col("weather_code") if c is not None]
    texts = [t for t in col("text") if t]
    precip = [x for x in col("precipitation") if x is not None]
    snow = [x for x in col("snowfall") if x is not None]
    probs = [x for x in col("precipitation_probability") if x is not None]
    gusts = [x for x in col("wind_gusts_10m") if x is not None]
    temp, wind = _mean(col("temperature_2m")), _mean(col("wind_speed_10m"))
    if temp is None or wind is None:
        return None
    return {
        "temp_f": round(temp), "wind_mph": round(wind, 1), "gust_mph": round(max(gusts)) if gusts else None,
        "precip_chance": round(max(probs)) if probs else None,
        "precip_in": round(sum(precip), 2) if precip else None, "snow_in": round(sum(snow), 1) if snow else None,
        "condition": WMO.get(max(codes)) if codes else (texts[0] if texts else None),
    }


def features(w: dict, observed: bool) -> dict[str, float]:
    """The regression's weather features for one kickoff window. Forecast
    precipitation counts by its probability; observed, by whether it fell."""
    temp, wind = w["temp_f"], w["wind_mph"]
    if observed:
        wet = 1.0 if (w.get("precip_in") or 0) >= 0.02 or (w.get("snow_in") or 0) > 0 else 0.0
    else:
        chance = w.get("precip_chance")
        wet = (chance / 100) if chance is not None else (1.0 if (w.get("precip_in") or 0) >= 0.02 else 0.0)
    snowy = temp <= 34 or (w.get("snow_in") or 0) > 0
    return {"wind_over_10": max(0.0, wind - 10), "rain": 0.0 if snowy else wet, "snow": wet if snowy else 0.0,
            "cold_below_40": max(0.0, 40 - temp)}


def label(w: dict) -> tuple[str, list[str]]:
    """(severity, flags): severity is "good", "mild", "poor" or "severe"."""
    flags = []
    if w["wind_mph"] >= VERY_WINDY:
        flags.append("very windy")
    elif w["wind_mph"] >= WINDY or (w.get("gust_mph") or 0) >= 35:
        flags.append("windy")
    chance = w.get("precip_chance")
    wet = (chance is not None and chance >= WET_CHANCE) or (w.get("precip_in") or 0) >= 0.05
    if wet:
        flags.append("snow" if w["temp_f"] <= 34 or (w.get("snow_in") or 0) > 0 else "rain")
    if w["temp_f"] <= FREEZING:
        flags.append("freezing")
    elif w["temp_f"] >= HOT:
        flags.append("hot")
    heavy = "very windy" in flags or "snow" in flags or (w.get("precip_in") or 0) >= 0.3
    severity = "severe" if heavy and len(flags) >= 2 else "poor" if heavy or len(flags) >= 2 or "windy" in flags or "rain" in flags \
        else "mild" if flags else "good"
    return severity, flags


def describe(w: dict) -> str:
    parts = [f"{w['temp_f']}°F"]
    wind = f"wind {w['wind_mph']:.0f} mph"
    if w.get("gust_mph") and w["gust_mph"] >= w["wind_mph"] + 8:
        wind += f" (gusts {w['gust_mph']})"
    parts.append(wind)
    if w.get("precip_chance") is not None and w["precip_chance"] >= 20:
        kind = "snow" if w["temp_f"] <= 34 else "rain"
        parts.append(f"{w['precip_chance']}% chance of {kind}")
    elif (w.get("precip_in") or 0) >= 0.02:
        parts.append(f"{w['precip_in']:.2f} in {'snow' if w['temp_f'] <= 34 else 'rain'}")
    if w.get("condition"):
        parts.insert(0, w["condition"])
    return ", ".join(parts)


# ------------------------------------------------------------------- effects
_EFFECTS: dict | None = None


def load_effects() -> dict:
    global _EFFECTS
    if _EFFECTS is None:
        try:
            _EFFECTS = json.loads(EFFECTS_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            _EFFECTS = {}
    return _EFFECTS


def multipliers(feats: dict[str, float], effects: dict | None = None, weight: float = 1.0) -> dict[str, float]:
    """outcome -> multiplier (pass_yd, pass_td, rush_yd, rush_td, points, dst)
    from the fitted effects, shrunk by their standard errors and scaled by the
    share projections don't already price in."""
    effects = load_effects() if effects is None else effects
    out = {}
    for name, e in (effects.get("outcomes") or {}).items():
        delta = 0.0
        for f, x in feats.items():
            b, se = (e.get("coef") or {}).get(f), (e.get("se") or {}).get(f)
            if b is None or not x:
                continue
            shrink = b * b / (b * b + se * se) if se else 1.0
            delta += b * shrink * x
        applied = effects.get("applied_share", 1.0) * weight
        out[name] = round(max(0.5, 1 + applied * delta / e["mean"]), 4) if e.get("mean") else 1.0
    return out


def scale_line(stats: dict, mult: dict[str, float]) -> dict:
    """A projected stat line with weather multipliers applied per stat."""
    m = lambda k: mult.get(k, 1.0)  # noqa: E731
    table = {"pass_yd": "pass_yd", "rec_yd": "pass_yd", "rec": "pass_yd", "pass_td": "pass_td", "rec_td": "pass_td",
             "rush_yd": "rush_yd", "rush_td": "rush_td"}
    return {k: (v * m(table[k]) if k in table and isinstance(v, (int, float)) else v) for k, v in stats.items()}


def player_factor(w: dict | None, position: str, line: dict | None, points_fn) -> float:
    """Weather multiplier for one player's DK projection: his projected line
    rescored with weather-scaled stats (DST: the fitted DST-points effect)."""
    mult = (w or {}).get("multipliers") or {}
    if not mult:
        return 1.0
    if position in ("DST", "DEF"):
        return mult.get("dst", 1.0)
    if not line:
        return 1.0
    base = points_fn(line, position)
    return round(points_fn(scale_line(line, mult), position) / base, 4) if base > 0 else 1.0


def impact_text(mult: dict[str, float]) -> str | None:
    bits = []
    for key, label_ in (("pass_yd", "passing yards"), ("pass_td", "passing TDs"), ("rush_yd", "rushing yards"), ("points", "team scoring")):
        v = mult.get(key)
        if v is not None and abs(v - 1) >= 0.02:
            bits.append(f"{label_} {v - 1:+.0%}")
    return ", ".join(bits) or None


# --------------------------------------------------------------- per schedule
def build(game, stadium: dict | None, hourly: dict | None, *, source: str | None, now: datetime) -> dict:
    """The weather record attached to one Game."""
    if stadium is None:
        return {"available": False, "summary": "Venue unknown", "indoor": False}
    base = {"venue": stadium["name"], "stadium_id": stadium["stadium_id"], "roof": stadium["roof"]}
    if stadium["roof"] == "dome":
        return {**base, "available": True, "indoor": True, "severity": "good", "flags": [], "summary": "Dome", "multipliers": {}}
    w = kickoff_window(hourly, game.kickoff_utc) if hourly else None
    days_out = (game.kickoff_utc - now).total_seconds() / 86400
    if w is None:
        why = "Forecast not available yet" if days_out > FORECAST_DAYS - 1 else "Weather data unavailable"
        return {**base, "available": False, "indoor": stadium["roof"] == "retractable", "summary": why, "multipliers": {}}
    severity, flags = label(w)
    observed = days_out < 0
    retractable = stadium["roof"] == "retractable"
    weight = 1.0 if days_out <= FULL_WEIGHT_DAYS else 0.5
    mult = {} if retractable else multipliers(features(w, observed), weight=weight)
    mult = {k: v for k, v in mult.items() if abs(v - 1) >= 0.005}
    summary = describe(w)
    if retractable:
        summary = f"Retractable roof ({summary} outside; likely closed if poor)"
    return {**base, **w, "available": True, "indoor": retractable, "observed": observed, "severity": "good" if retractable else severity,
            "flags": [] if retractable else flags, "summary": summary, "multipliers": mult,
            "impact": None if retractable else impact_text(mult), "source": source,
            "long_range": days_out > FULL_WEIGHT_DAYS, "days_out": round(days_out, 1)}


async def _hourly_for(games_venues: list[tuple], now: datetime) -> tuple[dict, dict]:
    """(game_id -> hourly series, game_id -> source label) for outdoor/retractable venues."""
    groups: dict[str, list] = {"forecast": [], "archive": []}
    for g, v in games_venues:
        if v is None or v["roof"] == "dome":
            continue
        days = (g.kickoff_utc - now).total_seconds() / 86400
        if days > FORECAST_DAYS - 0.5:
            continue
        groups["archive" if days < -FORECAST_PAST_DAYS else "forecast"].append((g, v))
    hourly, source = {}, {}
    for kind, items in groups.items():
        if not items:
            continue
        points = sorted({(v["lat"], v["lon"]) for _, v in items})
        start = min(g.kickoff_utc for g, _ in items).strftime("%Y-%m-%d")
        end = (max(g.kickoff_utc for g, _ in items) + timedelta(hours=WINDOW_HOURS + 1)).strftime("%Y-%m-%d")
        past = all(g.kickoff_utc < now for g, _ in items)
        key = f"weather_{kind}_{start}_{end}_" + "_".join(f"{la:.2f},{lo:.2f}" for la, lo in points)

        async def fetch(points=points, start=start, end=end, kind=kind):
            return await fetch_open_meteo(points, start, end, archive=kind == "archive")

        try:
            series = await cached_fetch(key, TTL_PAST if past else TTL_FUTURE, fetch)
            by_point = dict(zip(points, series))
            label_ = "Open-Meteo (observed)" if past else "Open-Meteo forecast"
            for g, v in items:
                hourly[g.game_id] = by_point.get((v["lat"], v["lon"]))
                source[g.game_id] = label_
        except Exception:
            if kind != "forecast":
                continue
            for g, v in items:          # NWS fallback: US venues, next 7 days
                if not (-125 < v["lon"] < -66 and 24 < v["lat"] < 50):
                    continue
                try:
                    hourly[g.game_id] = await cached_fetch(f"weather_nws_{v['lat']:.2f},{v['lon']:.2f}", TTL_FUTURE,
                                                           lambda v=v: fetch_nws(v["lat"], v["lon"]))
                    source[g.game_id] = "National Weather Service forecast"
                except Exception:
                    continue
    return hourly, source


async def attach_weather(schedule, lines: dict) -> None:
    """Adds game.weather to every game in the schedule (in place). Failures
    degrade to "Weather data unavailable" rather than breaking the schedule."""
    now = datetime.now(timezone.utc)
    games_venues = []
    for g in schedule.games:
        row = lines.get((g.week, g.away, g.home)) or {}
        games_venues.append((g, venue(row.get("stadium_id"), g.home)))
    try:
        hourly, source = await _hourly_for(games_venues, now)
    except Exception:
        hourly, source = {}, {}
    for g, v in games_venues:
        try:
            g.weather = build(g, v, hourly.get(g.game_id), source=source.get(g.game_id), now=now)
        except Exception:
            g.weather = {"available": False, "summary": "Weather data unavailable", "indoor": False}


def team_weather(schedule) -> dict[str, dict]:
    """team -> its game's weather record, for projections."""
    out = {}
    for g in schedule.games:
        if getattr(g, "weather", None):
            out[g.away] = g.weather
            out[g.home] = g.weather
    return out
