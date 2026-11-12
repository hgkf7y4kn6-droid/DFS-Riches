from app import ownership_video as ov


def _w(text, left, top, line, height=40):
    return {"text": text, "left": left, "top": top, "width": 20 * len(text), "height": height, "line": ("1", "1", str(line))}


def _row(name, pct, game, salary, top, line):
    first, last = name.split(" ", 1)
    return [_w(first, 230, top, line), _w(last, 280, top, line), _w(pct, 400, top, line),
            *[_w(t, 234 + 60 * i, top + 55, line + 1) for i, t in enumerate(game.split())],
            _w(salary, 234, top + 110, line + 2)]


def test_rows_take_their_salary_game_and_points_and_skip_a_cut_off_salary():
    words = (_row("C. Hubbard", "18.56%", "CAR 25 @ PHI 14 | FINAL", "$6,300", 1000, 10)
             + _row("K. Allen", "16.73%", "TEN 26 @ IND 20 | FINAL", "$4,300", 1256, 20)
             + [_w("T.", 230, 2450, 30), _w("McKee", 270, 2450, 30), _w("14.88%", 400, 2450, 30)])
    points = [_w("22.10", 10, 1080, 1), _w("16.20", 10, 1336, 2), _w("1", 10, 300, 3)]
    rows = ov.parse_frame(words, points, height=2600)
    assert rows[0] == {"name": "C. Hubbard", "pct": 18.56, "salary": 6300, "points": 22.1, "game": "CAR 25 @ PHI 14"}
    assert rows[1]["salary"] == 4300 and rows[1]["points"] == 16.2
    assert rows[2]["name"] == "T. McKee" and rows[2]["pct"] == 14.88 and rows[2]["salary"] is None


def test_a_leading_capital_i_read_as_a_bar_still_starts_a_row():
    rows = ov.parse_frame([_w("|.", 230, 100, 1), _w("Likely", 270, 100, 1), _w("69.26%", 400, 100, 1)], [], height=2600)
    assert rows and rows[0]["name"] == "I. Likely"


def test_merge_takes_each_fields_most_common_reading_across_frames():
    good = {"name": "K. Walker III", "pct": 18.04, "salary": 8500, "points": 30.9, "game": "LAC 6 @ KC 22"}
    merged = ov.merge([[good], [good | {"name": "K. Walker Ill", "points": 3.9}], [good | {"name": "K. Walker IIl", "salary": None}]])
    assert len(merged) == 1
    assert merged[0]["points"] == 30.9 and merged[0]["salary"] == 8500 and merged[0]["frames"] == 3


def test_match_uses_salary_and_team_to_separate_same_last_names():
    players = [{"key": "ja", "name": "Josh Allen", "team": "BUF", "position": "QB", "salary": 7500},
               {"key": "ka", "name": "Keenan Allen", "team": "TEN", "position": "WR", "salary": 4300},
               {"key": "kw", "name": "Kenneth Walker III", "team": "KC", "position": "RB", "salary": 8500},
               {"key": "car", "name": "Panthers", "team": "CAR", "position": "DST", "salary": 2500}]
    rows = [{"name": "K. Allen", "pct": 16.7, "salary": 4300, "points": 16.2, "game": "TEN 26 @ IND 20"},
            {"name": "J. Allen", "pct": 17.2, "salary": None, "points": 18.3, "game": "BUF 33 @ LV 30"},
            {"name": "K. Walker Ill", "pct": 18.0, "salary": 8500, "points": 30.9, "game": None},
            {"name": "Panthers", "pct": 66.9, "salary": 2500, "points": 4.0, "game": "CAR 25 @ PHI 14"},
            {"name": "Z. Nobody", "pct": 1.0, "salary": 3000, "points": 0.0, "game": None}]
    matched, unmatched = ov.match(rows, players)
    assert {m["name"]: m["player"]["key"] for m in matched} == {"K. Allen": "ka", "J. Allen": "ja", "K. Walker Ill": "kw",
                                                                "Panthers": "car"}
    assert unmatched == ["Z. Nobody"]
