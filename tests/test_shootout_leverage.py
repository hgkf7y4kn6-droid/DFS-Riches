from app import shootout_leverage as sl

MODEL = {"coef": [0.5, 0.23, 0.0], "bands": [{"lo": 0, "hi": 45, "over_by_10": 0.24, "points_50": 0.28},
                                              {"lo": 45, "hi": 99, "over_by_10": 0.27, "points_50": 0.45}]}


def test_higher_totals_expect_more_top_scorers():
    a, b = sl.expected_shares([(52.0, 3.0), (40.0, 3.0)], MODEL["coef"])
    assert a > b and abs(a + b - 1) < 1e-9


def test_leverage_is_expected_share_over_ownership_and_flags_underowned_low_totals():
    games = [{"game": "HI", "total": 52.0, "spread_home": -3.0, "pop_share": 0.6},
             {"game": "LO", "total": 41.5, "spread_home": 2.5, "pop_share": 0.1},
             {"game": "MID", "total": 46.0, "spread_home": -1.0, "pop_share": 0.3}]
    sl.rate(games, MODEL)
    by = {g["game"]: g["shootout_leverage"] for g in games}
    assert by["LO"]["rank"] == 1 and by["LO"]["flag"] and not by["HI"]["flag"]
    assert abs(by["LO"]["leverage"] - by["LO"]["expected_share"] / by["LO"]["own_share"]) < 0.02
    assert by["LO"]["over_by_10"] == 0.24
    assert "Shootout leverage" in sl.note(games[1])
