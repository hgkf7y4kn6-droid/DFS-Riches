from app import team_changes as tc

CH = [
    {"team": "MIN", "season": 2026, "effective_week": 10, "type": "trade_in", "note": "Kirk Cousins (QB) LV -> MIN | 11-10 trade"},
    {"team": "LV", "season": 2026, "effective_week": 10, "type": "trade_out", "note": "Kirk Cousins (QB) LV -> MIN | 11-10 trade"},
    {"team": "DEN", "season": 2026, "effective_week": 5, "type": "playcaller", "note": "Sean Payton took back play-calling. Second sentence."},
    {"team": "NYG", "season": 2026, "effective_week": 4, "type": "trade_in", "note": "J.J. McCarthy (QB) MIN -> NYG"},
    {"team": "DEN", "season": 2026, "effective_week": 11, "type": "trade_in", "note": "Daiyan Henley (LB) LAC -> DEN"},
    {"team": "MIN", "season": 2025, "effective_week": 10, "type": "trade_in", "note": "Old (QB) AAA -> MIN"},
]


def test_labels():
    assert tc.move_label(CH[0]) == "Added QB Kirk Cousins (from LV)"
    assert tc.move_label(CH[1]) == "Traded away QB Kirk Cousins (to MIN)"
    assert tc.move_label(CH[2]) == "Play-calling: Sean Payton took back play-calling"


def test_recent_moves_window():
    r = tc.recent_moves(2026, 10, CH)
    assert [m["label"] for m in r["MIN"]] == ["Added QB Kirk Cousins (from LV)"]      # not last season's
    assert "LV" in r and "NYG" not in r and "DEN" not in r       # week 4 and 5 are past the 3-week window; week 11 hasn't happened
    assert [m["effective_week"] for m in tc.recent_moves(2026, 11, CH)["DEN"]] == [11]
