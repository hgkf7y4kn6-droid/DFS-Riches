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


def _play(**kw):
    base = dict(game_id="g1", week="3", posteam="LA", defteam="SEA", drive="1", qtr="1", play_type="run",
                qb_dropback="0", score_differential="0", half_seconds_remaining="1700", game_seconds_remaining="3500",
                complete_pass="0", out_of_bounds="0", penalty="0", timeout="0", touchdown="0", fumble_lost="0")
    base.update(kw)
    return base


def test_neutral_stats_counts_tied_games_and_maps_team_codes():
    from app.nflverse_client import neutral_stats_from_pbp

    plays = [
        _play(play_type="pass", qb_dropback="1", complete_pass="1", game_seconds_remaining="3500"),
        _play(play_type="run", game_seconds_remaining="3462"),     # 38s after an in-bounds completion
        _play(play_type="pass", qb_dropback="1", game_seconds_remaining="3420"),   # 42s after a run
    ]
    out = neutral_stats_from_pbp(plays)
    off = out["offense"]["3|LAR"]
    assert off["neutral_pass_rate"] == round(2 / 3, 4)   # score_differential 0 (tied) still counts as neutral
    assert off["neutral_secs"] == 40.0
    assert out["defense"]["3|SEA"]["opp_neutral_pass_rate"] == round(2 / 3, 4)


def test_neutral_stats_skip_non_neutral_plays_and_stopped_clocks():
    from app.nflverse_client import neutral_stats_from_pbp

    plays = [
        _play(play_type="pass", qb_dropback="1", complete_pass="0", game_seconds_remaining="3500"),  # incompletion stops clock
        _play(play_type="run", game_seconds_remaining="3495"),
        _play(play_type="run", out_of_bounds="1", game_seconds_remaining="3460"),                   # counted gap: 35s
        _play(play_type="run", game_seconds_remaining="3452"),                                      # after out of bounds: not counted
        _play(play_type="pass", qb_dropback="1", qtr="4", game_seconds_remaining="800"),            # 4th quarter: not neutral
        _play(play_type="pass", qb_dropback="1", score_differential="-21", game_seconds_remaining="3000"),  # blowout: not neutral
        _play(play_type="pass", qb_dropback="1", half_seconds_remaining="90", game_seconds_remaining="1890"),  # 2-minute drill
    ]
    off = neutral_stats_from_pbp(plays)["offense"]["3|LAR"]
    assert off["neutral_pass_rate"] == 0.25   # 1 dropback in the 4 neutral plays
    assert off["neutral_secs"] == 35.0


def test_tendency_metrics_use_season_to_date_once_there_are_two_games():
    from app.nflverse_client import rank_teams, team_trailing

    index = {
        "A": {"neutral_secs": [[2025, w, 42.0] for w in range(10, 18)] + [[2026, 1, 35.0], [2026, 2, 36.0]],
              "plays": [[2025, w, 70.0] for w in range(10, 18)] + [[2026, 1, 60.0], [2026, 2, 60.0]]},
        "B": {"neutral_secs": [[2025, w, 36.0] for w in range(10, 18)] + [[2026, 1, 40.0], [2026, 2, 41.0]]},
    }
    assert team_trailing(index, "A", "neutral_secs", 2026, 3) == 35.5          # this season only
    assert team_trailing(index, "A", "neutral_secs", 2026, 2) == 41.12         # 1 game this season: trailing 8
    assert team_trailing(index, "A", "plays", 2026, 3) == 67.5                 # not a tendency: trailing 8
    assert rank_teams(index, "neutral_secs", 2026, 3, descending=False) == {"A": 1, "B": 2}
