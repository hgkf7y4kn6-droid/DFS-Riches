from app import ceiling_model as cm

MODEL = {"cv_pos": {"WR": 0.65, "QB": 0.42},
         "positions": {"WR": {"features": ["proj", "sd"], "mu": [12.0, 7.0], "sd": [5.0, 3.0], "b": [17.0, 4.5, 1.5]}}}


def test_inputs_shrink_a_short_history_toward_the_positions_spread():
    x = cm.inputs("WR", 15.0, [15.0, 15.0], {"rec_yd": 80, "rec_td": 0.5}, 24.5, -3.0, model=MODEL)
    assert 0 < x["sd"] < 0.65 * 15.0                   # two identical games pull the spread down, the prior holds it up
    assert abs(x["td_share"] - 3.0 / 15.0) < 1e-9 and x["yds"] == 80 and x["abs_spread"] == 3.0
    assert x["p85"] > 15.0                              # under 6 games: mean + 1.04 x typical spread


def test_ceiling_is_the_quantile_fit_and_never_below_the_projection():
    hi = cm.ceiling("WR", cm.inputs("WR", 20.0, [10, 30, 8, 35, 12, 28, 9], None, 25.0, 0.0, model=MODEL), MODEL)
    lo = cm.ceiling("WR", cm.inputs("WR", 20.0, [20, 21, 19, 20, 20, 21, 19], None, 25.0, 0.0, model=MODEL), MODEL)
    assert hi > lo >= 20.0                              # more volatile history -> higher ceiling
    assert cm.ceiling("QB", cm.inputs("QB", 20.0, [], None, 25.0, 0.0, model=MODEL), MODEL) is None   # no fitted QB model
    assert cm.inputs("K", 8.0, [], None, 20.0, 0.0, model=MODEL) is None


def test_notes_name_the_bonus_path_by_position():
    x = cm.inputs("WR", 15.0, [], {"rec_yd": 95}, 24.0, 0.0, model=MODEL)
    assert "100-yard" in cm.notes(25.0, x, "WR")[0]
    q = cm.inputs("QB", 20.0, [], {"pass_yd": 280}, 24.0, 0.0, model=MODEL)
    assert "300-yard" in cm.notes(30.0, q, "QB")[0]
