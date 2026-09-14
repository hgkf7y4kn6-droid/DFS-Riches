from app.dk_scoring import dk_dst_points, dk_offense_points
from app.nflverse_client import _trailing_avg, player_key, team_trend, trailing_dk_fppg, trailing_dst_points


def test_trailing_avg_takes_the_most_recent_n_games_before_the_target_week():
    entries = [[2026, 1, 10.0], [2026, 2, 20.0], [2026, 3, 30.0], [2026, 4, 40.0]]
    assert _trailing_avg(entries, season=2026, week=5, n=3) == 30.0  # (20+30+40)/3


def test_trailing_avg_reaches_back_into_prior_season_when_needed():
    entries = [[2025, 17, 10.0], [2025, 18, 20.0], [2026, 1, 30.0]]
    # Week 2 of 2026 with only one 2026 game played: average the last 3
    # games regardless of season, i.e. all three of these.
    assert _trailing_avg(entries, season=2026, week=2, n=3) == 20.0


def test_trailing_avg_excludes_games_from_the_target_week_onward():
    entries = [[2026, 1, 10.0], [2026, 2, 999.0]]
    assert _trailing_avg(entries, season=2026, week=2, n=3) == 10.0


def test_trailing_avg_uses_fewer_than_n_when_not_enough_history_exists():
    entries = [[2026, 1, 10.0]]
    assert _trailing_avg(entries, season=2026, week=2, n=3) == 10.0


def test_trailing_avg_empty_history_returns_none():
    assert _trailing_avg([], season=2026, week=1, n=3) is None


def test_trailing_dk_fppg_looks_up_by_normalized_name_and_position():
    key = player_key("Ja'Marr Chase", "WR")
    index = {key: [[2026, 1, 15.0], [2026, 2, 25.0]]}
    assert trailing_dk_fppg(2026, 3, 2, player_index=index, name="Ja'Marr Chase", position="WR") == 20.0


def test_trailing_dk_fppg_none_when_not_in_index():
    assert trailing_dk_fppg(2026, 3, 2, player_index={}, name="Nobody Fake", position="WR") is None


def test_player_key_ignores_punctuation_and_suffix_differences():
    assert player_key("A.J. Brown", "WR") == player_key("AJ Brown", "WR")
    assert player_key("Michael Pittman Jr.", "WR") == player_key("Michael Pittman", "WR")


def test_player_key_distinguishes_positions_for_the_same_name():
    assert player_key("Josh Allen", "QB") != player_key("Josh Allen", "LB")


def test_player_key_resolves_configured_aliases(monkeypatch):
    import app.nflverse_client as nflverse_client

    monkeypatch.setattr(nflverse_client, "resolve_alias", lambda n: "marquise brown" if n == "hollywood brown" else n)
    assert player_key("Hollywood Brown", "WR") == player_key("Marquise Brown", "WR")


def test_trailing_dst_points_looks_up_by_team():
    index = {"SEA": [[2026, 1, 8.0], [2026, 2, 4.0]]}
    assert trailing_dst_points(2026, 3, 2, team_index=index, team="SEA") == 6.0


def test_team_trend_returns_l3_l6_l9_from_one_series():
    index = {"SEA": {"spread": [[2026, w, float(w)] for w in range(1, 6)]}}
    trend = team_trend(index, "SEA", "spread", season=2026, week=6)
    assert trend == {"l3": 4.0, "l6": 3.0, "l9": 3.0}  # last3=(3+4+5)/3, last5 avail for l6/l9=(1+2+3+4+5)/5


def test_dk_offense_points_applies_yardage_bonuses():
    row = {
        "passing_yards": "320",
        "passing_tds": "2",
        "passing_interceptions": "1",
        "rushing_yards": "10",
        "receptions": "0",
        "receiving_yards": "0",
    }
    # 320*0.04=12.8, +2*4=8, -1 int, +3 (300+ bonus), +10*0.1=1.0 rushing
    assert dk_offense_points(row) == 12.8 + 8 - 1 + 3 + 1.0


def test_dk_offense_points_no_bonus_under_the_yardage_threshold():
    row = {"rushing_yards": "99"}
    assert dk_offense_points(row) == round(99 * 0.1, 2)


def test_dk_dst_points_applies_points_allowed_tiers():
    row = {"def_sacks": "3", "def_interceptions": "1"}
    # 3 sacks=3, 1 int=2, shutout bonus=10
    assert dk_dst_points(row, points_allowed=0) == 3 + 2 + 10


def test_dk_dst_points_penalizes_blowout_losses():
    row = {}
    assert dk_dst_points(row, points_allowed=42) == -4
