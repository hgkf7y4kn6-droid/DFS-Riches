from app import dfs_model, prop_pricer as pp


def test_median_sits_below_the_average_for_receiving_yards():
    p = pp.params("rec_yd", "WR")
    assert p is not None
    assert pp.median(60.0, p) < 60.0
    # a line at the median is a coin flip under the lognormal
    assert abs(pp.p_lognormal(pp.median(60.0, p), 60.0, p) - 0.5) < 1e-6


def test_ladders_fall_as_rungs_rise_and_skip_other_positions():
    priced = pp.price({"rec_yd": 70.0, "rec": 5.5, "pass_yd": 250.0}, "WR")
    assert set(priced) == {"rec_yd", "rec"}
    for stat in priced.values():
        chances = list(stat["ladder"].values())
        assert chances == sorted(chances, reverse=True)
        assert all(0.0 <= c <= 1.0 for c in chances)


def test_props_follow_the_final_projection():
    line = {"rush_yd": 60.0, "rush_att": 14, "rec": 2.0, "rec_yd": 15.0}
    base = dfs_model._props(line, "RB", 11.4)
    up = dfs_model._props(line, "RB", 15.0)
    assert up["rush_yd"]["median"] > base["rush_yd"]["median"]
    assert dfs_model._props(line, "RB", 0.0) is None
    assert dfs_model._props({}, "DST", 8.0) is None
