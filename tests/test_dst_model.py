from app import dst_model as dm


def _row(team, opp, week, att=30, sacks=2, ints=1, carries=25, fl=0):
    return {"season_type": "REG", "week": str(week), "team": team, "opponent_team": opp, "attempts": str(att),
            "sacks_suffered": str(sacks), "passing_interceptions": str(ints), "carries": str(carries),
            "rushing_fumbles_lost": str(fl)}


def test_expected_bonus_averages_the_tiers_over_likely_scores():
    low, high = dm.expected_pa_bonus(14.0, 9.0), dm.expected_pa_bonus(28.0, 9.0)
    assert low > high
    assert 0 < low < 4          # not the +1 at exactly 14, nor the +4 tier: an average over the spread
    assert high < 0.5


def test_team_rates_shrink_this_season_toward_last_seasons_regressed_rate():
    prev = [_row("A", "B", w, sacks=1) for w in range(1, 18)] + [_row("B", "A", w, sacks=5) for w in range(1, 18)]
    cur = [_row("A", "B", 1, sacks=6), _row("B", "A", 1, sacks=6)]
    r = dm.team_rates(cur, prev, week=2)
    lg = (17 * 1 + 17 * 5) / (17 * 31 + 17 * 35)
    a_prior = lg + 0.5 * (1 / 31 - lg)
    assert a_prior < r["A"]["o_sack"] < 6 / 36            # moved toward this week's 6 sacks, but mostly the prior
    assert r["B"]["o_sack"] > r["A"]["o_sack"]
    assert abs(r["A"]["d_sack"] - r["B"]["o_sack"]) < 1e-9  # A's defense faced B's offense
    assert dm.team_rates(cur, prev, week=1)["A"]["o_sack"] == a_prior   # nothing played yet this season


def test_features_and_projection():
    f = dm.features(7.0, 17.0, 6.5, -0.15, 40, {"d_sack": 0.08, "d_give": 0.025}, {"o_sack": 0.09, "o_give": 0.03}, 9.0)
    assert f["opp_qb_unknown"] == 1.0 and f["opp_sack_rate"] == 0.09 and f["own_take_rate"] == 0.025
    model = {"model": {"features": ["exp_pa_bonus", "opp_qb_unknown"], "weights": [1.5, 0.5], "means": [1.0, 0.1],
                       "sds": [1.0, 0.3], "intercept": 6.0}}
    assert dm.project(f, model) > 6.0
    assert dm.project(f, {"model": None}) is None
    assert "DST model" in dm.note(8.1, f, "NYG")
