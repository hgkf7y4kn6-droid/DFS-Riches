from app import player_model as pm


def test_workhorse_pass_catching_backs_get_their_own_spread_term():
    hist = {1: {"ts": 0.1, "cs": 0.6, "snap": 70.0, "pts": 15.0, "team": "A"}}
    catcher = pm.features(hist, 2, 16.0, "RB", 24.0, 6.5, line={"rush_att": 15, "rec_tgt": 4.2})
    grinder = pm.features(hist, 2, 16.0, "RB", 24.0, 6.5, line={"rush_att": 18, "rec_tgt": 1.5})
    receiver = pm.features(hist, 2, 16.0, "WR", 24.0, 6.5, line={"rush_att": 15, "rec_tgt": 8})
    assert catcher["spread_x_wpc"] == 6.5
    assert grinder["spread_x_wpc"] == 0.0 and receiver["spread_x_wpc"] == 0.0
    assert pm.features(hist, 2, 16.0, "RB", 24.0, 6.5)["spread_x_wpc"] == 0.0      # no line: no term
    assert set(pm.FEATURES) <= set(catcher)


def test_receivers_depth_of_target_meets_the_opponents_big_plays_allowed():
    deep = {w: {"ts": 0.2, "cs": 0.0, "snap": 80.0, "pts": 12.0, "team": "A", "air": 90.0, "tgt": 6.0} for w in (1, 2, 3)}
    short = {w: {**v, "air": 30.0} for w, v in deep.items()}
    f_deep = pm.features(deep, 4, 12.0, "WR", 23.0, 0.0, opp_explosive=0.01)
    f_short = pm.features(short, 4, 12.0, "WR", 23.0, 0.0, opp_explosive=0.01)
    assert f_deep["adot_x_opp_explosive"] == (15.0 - pm.ADOT_CENTER) * 0.01 * 100
    assert f_short["adot_x_opp_explosive"] < 0
    few = {1: deep[1], 2: deep[2]}                       # fewer than 3 games: no read yet
    assert pm.features(few, 4, 12.0, "WR", 23.0, 0.0, opp_explosive=0.01)["adot_x_opp_explosive"] == 0.0
    assert pm.features(deep, 4, 12.0, "RB", 23.0, 0.0, opp_explosive=0.01)["adot_x_opp_explosive"] == 0.0
