from app import kicker_model

M = {"k": 30, "league_mean": 8.6, "intercept": 0.0, "implied": 0.064, "spread": 0.06, "implied_center": 22.5}


def test_a_hot_average_is_pulled_toward_the_league_mean():
    value, note = kicker_model.project(9.9, 9, 22.5, 0.0, M)
    assert 8.6 < value < 9.9 and abs(value - (9.9 * 9 + 30 * 8.6) / 39) < 0.01
    assert "shrunk toward the league" in note and "9 games" in note


def test_more_games_trust_the_kicker_more():
    early = kicker_model.project(11.0, 2, 22.5, 0.0, M)[0]
    late = kicker_model.project(11.0, 16, 22.5, 0.0, M)[0]
    assert 8.6 < early < late < 11.0


def test_game_environment_moves_the_projection_the_right_way():
    base = kicker_model.project(9.0, 9, 22.5, 0.0, M)[0]
    assert kicker_model.project(9.0, 9, 27.5, 0.0, M)[0] > base          # higher implied total
    assert kicker_model.project(9.0, 9, 22.5, 6.0, M)[0] > base          # favored
    assert kicker_model.project(9.0, 9, 17.5, -6.0, M)[0] < base
    assert kicker_model.project(9.0, 9, None, None, M)[0] == base        # no line: league-average game


def test_no_model_or_no_average_means_no_projection():
    assert kicker_model.project(9.0, 9, 22.0, 1.0, {}) is None or kicker_model.load() is not None
    assert kicker_model.project(None, 9, 22.0, 1.0, M) is None
    assert kicker_model.project(0.0, 0, 22.5, 0.0, M)[0] >= 0           # a kicker with no games yet: the league mean


def test_the_shipped_model_cuts_the_raw_average_toward_the_mean():
    m = kicker_model.load()
    assert m and m["record"]["model"]["mae"] < m["record"]["flat_season_average"]["mae"]
    zvada = kicker_model.project(9.9, 9, 22.0, 2.5)[0]                   # raw DK average 9.9 before this change
    assert 8.5 < zvada < 9.9
