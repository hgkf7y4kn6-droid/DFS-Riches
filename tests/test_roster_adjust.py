from app import roster_adjust as ra
from app import style_matchup as sm
from tests.test_style_matchup import totals

DATA = {"season": 2026, "week": 10, "teams": {
    "MIN": {"week": 10, "reasons": ["QB Kirk Cousins replaces Carson Wentz"], "d_epa_db": 0.03},
    "PHI": {"week": 11, "reasons": ["Pass rush -0.16"], "d_epa_db": 0.0},      # bye in 10: read for week 11
    "DEN": {"week": 10, "reasons": [], "d_epa_db": 0.0}}}


def test_for_week_matches_the_teams_next_game_and_needs_a_reason():
    assert list(ra.for_week(2026, 10, DATA)) == ["MIN"]
    assert list(ra.for_week(2026, 11, DATA)) == ["PHI"]
    assert ra.for_week(2025, 10, DATA) == {}


def test_adjust_moves_styles_only_when_the_shift_is_real():
    base = sm.classify(totals())
    assert base["RUN"]["off_style"] == "run-first efficient"
    # a lost-receivers sized shift (-2 pts of neutral pass rate, -0.04 EPA) is not enough to cross the line
    none = sm.classify(totals(), {"RUN": {"d_epa_db": -0.01, "d_pass_rate": -0.002}})
    assert none["RUN"]["off_style"] == base["RUN"]["off_style"] and "off_style_raw" not in none["RUN"]
    # a big enough one (a pass-heavy offense losing its passing game) does, and keeps the games-only label
    big = sm.classify(totals(), {"PAS": {"d_epa_db": -0.6, "d_pass_rate": -0.3}})
    assert base["PAS"]["off_style"] == "pass-first efficient"
    assert big["PAS"]["off_style"] != base["PAS"]["off_style"]
    assert big["PAS"]["off_style_raw"] == "pass-first efficient"
    assert big["RUN"]["off_style"] == base["RUN"]["off_style"]          # other teams keep theirs


def test_game_reports_flips():
    c = sm.classify(totals(), {"PAS": {"d_epa_db": -0.6, "d_pass_rate": -0.3}})
    g = sm.game("PAS", "RUN", c)
    assert g[0]["flips"] and "after roster moves" in g[0]["flips"][0] and "was pass-heavy and efficient" in g[0]["flips"][0]
    assert sm.game("PAS", "RUN", sm.classify(totals()))[0]["flips"] == []
