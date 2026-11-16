from app import schedule_outlook as so

ENTRY = {"opponents_ahead": ["LV", "PIT", "MIA"],
         "off_total": {"schedule_past6": -1.5, "schedule_ahead": 4.7, "expected_move": 1.83},
         "off_rush": {"schedule_past6": -1.5, "schedule_ahead": -0.9, "expected_move": 0.13},     # under the 1.0 floor: not shown
         "def_total": {"schedule_past6": 0.2, "schedule_ahead": -3.2, "expected_move": -2.43},
         "def_pass": {"schedule_past6": 0.9, "schedule_ahead": 3.0, "expected_move": 1.6}}


def test_lines_direction_and_floor():
    ls = {l["unit"]: l for l in so.lines(ENTRY)}
    assert set(ls) == {"Offense", "Defense", "Pass defense"}
    assert ls["Offense"]["better"] and ls["Defense"]["better"]            # softer defenses ahead; weaker offenses ahead
    assert not ls["Pass defense"]["better"] and "slipping" in ls["Pass defense"]["text"]
    assert "1.1 points per game better" in ls["Offense"]["text"]


def test_for_week_needs_the_matching_week():
    d = {"season": 2026, "week": 10, "teams": {"DEN": ENTRY, "KC": {"opponents_ahead": []}}}
    assert list(so.for_week(2026, 10, d)) == ["DEN"]
    assert so.for_week(2026, 11, d) == {} and so.for_week(2025, 10, d) == {}


def _synthetic():
    """X plays tough-defense HARD for weeks 1-4 and then weak-defense SOFT for weeks 5-7; SOFT and HARD otherwise play MID."""
    allowed = {"X": 0.0, "MID": 0.0, "SOFT": 0.3, "HARD": -0.3}            # EPA per play each defense allows
    games = {1: [("X", "HARD"), ("SOFT", "MID")], 2: [("X", "HARD"), ("SOFT", "MID")], 3: [("X", "HARD"), ("SOFT", "MID")],
             4: [("X", "HARD"), ("SOFT", "MID")], 5: [("X", "SOFT"), ("HARD", "MID")], 6: [("X", "SOFT"), ("HARD", "MID")],
             7: [("X", "SOFT"), ("HARD", "MID")]}
    off, de, sched = {}, {}, []
    for wk, pairs in games.items():
        for a, b in pairs:
            sched.append({"game_type": "REG", "week": str(wk), "home_team": a, "away_team": b})
            for t, o in ((a, b), (b, a)):
                c = {"plays": 60.0, "db": 36.0, "db_epa": 36.0 * allowed[o], "rush": 24.0, "rush_epa": 24.0 * allowed[o]}
                off[f"{wk}|{t}"] = c
                de[f"{wk}|{o}"] = dict(c)
    return {"off": off, "def": de}, sched


def test_compute_rates_the_schedule_ahead_against_the_one_behind():
    agg, sched = _synthetic()
    coefs = {"off_total": [0.3, 3.4], "def_total": [0.72, 10.0], "off_rush": [0.23, 2.2], "def_pass": [0.6, 7.9], "def_rush": [0.4, 4.2]}
    out = so.compute({2026: agg}, {2026: sched}, 2026, 5, coefs)
    x = out["X"]
    assert x["opponents_ahead"] == ["SOFT", "SOFT", "SOFT"]
    assert x["off_total"]["schedule_past6"] < 0 < x["off_total"]["schedule_ahead"]      # tough defenses behind, weak ones ahead
    assert x["off_total"]["expected_move"] > 1.0                                        # so the offense should look better
    assert abs(x["def_total"]["expected_move"]) < 0.5                                   # the opposing offenses were all average


def test_live_falls_back_to_the_file_when_there_is_no_data(monkeypatch):
    monkeypatch.setattr(so, "for_week", lambda s, w, data=None: {"DEN": ["from file"]})
    assert so.live(2026, 10, {}, {}) == {"DEN": ["from file"]}
