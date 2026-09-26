from datetime import datetime, timedelta, timezone

from app import breakdown, projections, weather
from app.models import Game

KICK = datetime(2026, 12, 13, 18, 0, tzinfo=timezone.utc)
EFFECTS = {"applied_share": 0.5, "outcomes": {
    "pass_yd": {"mean": 240.0, "coef": {"wind_over_10": -3.0, "rain": -14.0, "snow": -22.0, "cold_below_40": -1.0},
                "se": {"wind_over_10": 0.5, "rain": 3.4, "snow": 8.8, "cold_below_40": 0.3}},
    "rush_yd": {"mean": 115.0, "coef": {"wind_over_10": 0.1, "rain": 0.7, "snow": 18.0, "cold_below_40": 0.0},
                "se": {"wind_over_10": 0.4, "rain": 2.4, "snow": 6.1, "cold_below_40": 0.2}},
    "dst": {"mean": 6.0, "coef": {"wind_over_10": 0.04, "rain": 0.64, "snow": -0.3, "cold_below_40": 0.05},
            "se": {"wind_over_10": 0.04, "rain": 0.26, "snow": 0.67, "cold_below_40": 0.02}},
}}


def _hourly(temp=40.0, wind=20.0, prob=80, precip=0.1, snow=0.0, hours=6):
    times = [(KICK + timedelta(hours=i - 1)).strftime("%Y-%m-%dT%H:00") for i in range(hours)]
    return {"time": times, "temperature_2m": [temp] * hours, "wind_speed_10m": [wind - 5, wind, wind, wind, wind + 30, wind][:hours],
            "wind_gusts_10m": [wind + 10] * hours, "precipitation_probability": [prob] * hours,
            "precipitation": [precip] * hours, "snowfall": [snow] * hours, "weather_code": [63] * hours}


def _game(home="BUF", kick=KICK):
    return Game(game_id="g", season=2026, week=15, away="MIA", home=home, kickoff_utc=kick, kickoff_et="Sun", day_part="SUN_EARLY")


def test_kickoff_window_uses_the_kickoff_hour_and_next_two():
    w = weather.kickoff_window(_hourly(wind=20.0), KICK)
    assert w["wind_mph"] == 20.0            # the pre-kickoff hour (15) and 4th hour (50) are outside the window
    assert w["precip_chance"] == 80 and w["precip_in"] == 0.3 and w["condition"] == "Rain"
    assert weather.kickoff_window(_hourly(), KICK + timedelta(days=3)) is None


def test_features_and_labels():
    w = {"temp_f": 30, "wind_mph": 22.0, "gust_mph": 35, "precip_chance": 60, "precip_in": 0.2, "snow_in": 1.0}
    f = weather.features(w, observed=False)
    assert f == {"wind_over_10": 12.0, "rain": 0.0, "snow": 0.6, "cold_below_40": 10}
    assert weather.features(w, observed=True)["snow"] == 1.0
    sev, flags = weather.label(w)
    assert sev == "severe" and {"very windy", "snow", "freezing"} <= set(flags)
    assert weather.label({"temp_f": 70, "wind_mph": 5.0, "precip_chance": 10})[0] == "good"
    assert weather.label({"temp_f": 70, "wind_mph": 16.0, "precip_chance": 10})[0] == "poor"


def test_multipliers_shrink_and_scale_by_applied_share():
    m = weather.multipliers({"wind_over_10": 10.0, "rain": 1.0, "snow": 0.0, "cold_below_40": 0.0}, EFFECTS)
    shrink = lambda b, se: b * b / (b * b + se * se)  # noqa: E731
    expected = 1 + 0.5 * (-3.0 * shrink(3, .5) * 10 - 14.0 * shrink(14, 3.4)) / 240
    assert abs(m["pass_yd"] - round(expected, 4)) < 1e-9
    assert m["pass_yd"] < 1 < m["dst"]
    assert weather.multipliers({"wind_over_10": 0.0, "rain": 0.0, "snow": 0.0, "cold_below_40": 0.0}, EFFECTS)["pass_yd"] == 1.0


def test_player_factor_hits_passers_harder_than_runners():
    mult = {"pass_yd": 0.9, "pass_td": 0.85, "rush_yd": 1.02, "dst": 1.05}
    w = {"multipliers": mult}
    qb = {"pass_yd": 250, "pass_td": 1.8, "rush_yd": 15}
    rb = {"rush_yd": 80, "rush_td": 0.6, "rec": 2, "rec_yd": 15}
    f_qb = weather.player_factor(w, "QB", qb, projections.dk_points_from_line)
    f_rb = weather.player_factor(w, "RB", rb, projections.dk_points_from_line)
    assert f_qb < 0.92 and f_rb > 0.98 and f_rb > f_qb
    assert weather.player_factor(w, "DST", None, projections.dk_points_from_line) == 1.05
    assert weather.player_factor(None, "QB", qb, projections.dk_points_from_line) == 1.0


def test_build_handles_domes_roofs_range_and_long_range(monkeypatch):
    monkeypatch.setattr(weather, "load_effects", lambda: EFFECTS)
    now = KICK - timedelta(days=2)
    dome = weather.build(_game("DET"), weather.venue(None, "DET"), None, source=None, now=now)
    assert dome["summary"] == "Dome" and dome["indoor"] and not dome["multipliers"]
    roof = weather.build(_game("IND"), weather.venue(None, "IND"), _hourly(), source="x", now=now)
    assert roof["summary"].startswith("Retractable roof") and not roof["multipliers"] and roof["severity"] == "good"
    out = weather.build(_game(), weather.venue("BUF00", "BUF"), _hourly(), source="Open-Meteo forecast", now=now)
    assert out["severity"] in ("poor", "severe") and out["multipliers"]["pass_yd"] < 1 and "passing yards" in out["impact"]
    far = weather.build(_game(), weather.venue("BUF00", "BUF"), _hourly(), source="x", now=KICK - timedelta(days=10))
    assert far["long_range"] and 1 > far["multipliers"]["pass_yd"] > out["multipliers"]["pass_yd"]
    none = weather.build(_game(), weather.venue("BUF00", "BUF"), None, source=None, now=KICK - timedelta(days=20))
    assert none["available"] is False and none["summary"] == "Forecast not available yet"
    assert weather.venue("NOPE", "XXX") is None


def test_nws_periods_convert_to_hourly_shape():
    periods = [{"startTime": "2026-12-13T13:00:00-05:00", "temperature": 31, "temperatureUnit": "F", "windSpeed": "15 to 20 mph",
                "probabilityOfPrecipitation": {"value": 70}, "shortForecast": "Snow Showers"}]
    h = weather._nws_to_hourly(periods)
    assert h["time"] == ["2026-12-13T18:00"] and h["wind_speed_10m"] == [20.0] and h["precipitation_probability"] == [70]
    w = weather.kickoff_window(h, KICK)
    assert w["condition"] == "Snow Showers" and w["temp_f"] == 31


def test_projection_and_breakdown_show_the_weather():
    ctx = projections.ProjectionContext(lines={"1": {"stats": {"pass_yd": 250, "pass_td": 2}}}, vs_expectation={})
    w = {"summary": "Rain, 40°F, wind 22 mph", "multipliers": {"pass_yd": 0.9, "pass_td": 0.85}, "long_range": False}
    pts, notes = projections.project(ctx, sleeper_id="1", position="QB", opponent="X", fallback=None, game_weather=w)
    assert pts < 18 and notes[-1].startswith("Weather (Rain, 40°F, wind 22 mph): x0.")
    g = _game()
    g.weather = {"available": True, "indoor": False, "severity": "poor", "summary": "Rain, 40°F", "venue": "Highmark Stadium",
                 "impact": "passing yards -8%"}
    assert "Projections adjusted: passing yards -8%" in breakdown.weather_takeaway(g)
    g.weather = {"available": True, "indoor": True, "roof": "dome", "severity": "good", "summary": "Dome"}
    assert breakdown.weather_takeaway(g) is None
