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
