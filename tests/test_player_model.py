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
