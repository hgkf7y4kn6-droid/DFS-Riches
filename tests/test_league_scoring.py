import pytest

from app import league_scoring as ls
from app import projections as pj

# A subset of The Breakfast Brunch's scoring_settings.
SCORING = {
    "pass_yd": 0.04, "pass_td": 4.0, "pass_int": -1.0, "rush_yd": 0.1, "rush_td": 6.0, "rec": 1.0, "rec_yd": 0.1,
    "rec_td": 6.0, "fum_lost": -2.0, "rec_2pt": 2.0, "sack": 1.0, "int": 2.0, "fum_rec": 2.0, "ff": 1.0,
    "safe": 2.0, "blk_kick": 2.0, "def_td": 6.0, "pts_allow_0": 10.0, "pts_allow_1_6": 7.0, "pts_allow_7_13": 4.0,
    "pts_allow_14_20": 1.0, "pts_allow_21_27": 0.0, "pts_allow_28_34": -1.0, "pts_allow_35p": -4.0,
}


def test_line_points_is_sleepers_weighted_sum():
    stats = {"rec": 6.5, "rec_yd": 98.27, "rec_td": 0.92, "fum_lost": 0.03, "rush_yd": 1.93, "pts_ppr": 22.16}
    assert ls.line_points(stats, SCORING) == pytest.approx(6.5 + 9.827 + 5.52 - 0.06 + 0.193, abs=0.01)


def test_line_points_def_uses_tier_indicator_or_points_allowed():
    with_tier = {"sack": 3.0, "int": 1.0, "ff": 1.0, "pts_allow": 15.5, "pts_allow_14_20": 1.0}
    assert ls.line_points(with_tier, SCORING) == pytest.approx(3 + 2 + 1 + 1)
    assert ls.line_points({"sack": 2.0, "pts_allow": 10.0}, SCORING) == pytest.approx(2 + 4)


def test_box_score_points_use_league_weights_and_only_its_bonuses():
    row = {"receptions": "8", "receiving_yards": "120", "receiving_tds": "1", "fumbles_lost_total": "1"}
    assert ls.offense_points(row, SCORING) == pytest.approx(8 + 12 + 6 - 2)   # no 100-yd bonus in this league
    assert ls.offense_points(row, {**SCORING, "bonus_rec_yd_100": 3.0}) == pytest.approx(27)
    team = {"def_sacks": "4", "def_interceptions": "1", "def_fumbles_forced": "2", "def_punt_blocks": "1"}
    assert ls.dst_points(team, 0, SCORING) == pytest.approx(4 + 2 + 2 + 2 + 10)


def test_projection_context_scores_with_league_when_available():
    lines = {"1": {"stats": {"rec": 5.0, "rec_yd": 60.0, "fum_lost": 1.0}}}
    dk = pj.ProjectionContext(lines=lines, vs_expectation={})
    league = pj.ProjectionContext(lines=lines, vs_expectation={}, scoring=SCORING)
    assert pj.project(dk, sleeper_id="1", position="WR", opponent="NYJ", fallback=None)[0] == pytest.approx(10.0)
    value, notes = pj.project(league, sleeper_id="1", position="WR", opponent="NYJ", fallback=None)
    assert value == pytest.approx(9.0) and notes[0].endswith("= 9.0 league pts")
    assert league.line_points("1", "WR") == pytest.approx(9.0) and league.line_points("2", "WR") is None
