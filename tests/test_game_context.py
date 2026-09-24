from app.game_context import _implied_totals, _pace_stat


def test_implied_totals_split_around_the_total_by_the_spread():
    # Real 2026 Week 1 NE@SEA line: SEA -3 home favorite, total 44.5.
    away, home = _implied_totals(total_line=44.5, home_spread=-3.0)
    assert away == 20.8
    assert home == 23.8
    assert round(home - away, 1) == 3.0  # matches the spread magnitude


def test_implied_totals_pick_em_splits_the_total_evenly():
    away, home = _implied_totals(total_line=44.0, home_spread=0.0)
    assert away == home == 22.0


def test_implied_totals_missing_line_returns_none():
    assert _implied_totals(None, -3.0) == (None, None)
    assert _implied_totals(44.5, None) == (None, None)


_NO_TREND = {"l3": None, "l6": None, "l9": None}


def test_pace_stat_computes_signed_delta():
    stat = _pace_stat(actual=67.0, baseline=62.0, trend=_NO_TREND)
    assert stat.actual_plays == 67.0
    assert stat.baseline_plays == 62.0
    assert stat.delta == 5.0


def test_pace_stat_negative_delta_means_slower_than_baseline():
    stat = _pace_stat(actual=48.0, baseline=60.1, trend=_NO_TREND)
    assert stat.delta == -12.1


def test_pace_stat_missing_baseline_has_no_delta_but_keeps_actual():
    stat = _pace_stat(actual=67.0, baseline=None, trend=_NO_TREND)
    assert stat.actual_plays == 67.0
    assert stat.delta is None


def test_pace_stat_both_missing_returns_none_when_trend_is_also_empty():
    assert _pace_stat(None, None, trend=_NO_TREND) is None


def test_pace_stat_keeps_trend_even_before_the_game_is_final():
    trend = {"l3": 63.0, "l6": 61.5, "l9": 60.0}
    stat = _pace_stat(actual=None, baseline=None, trend=trend)
    assert stat is not None
    assert stat.actual_plays is None
    assert stat.trend.l3 == 63.0
    assert stat.trend.l9 == 60.0


def test_dk_kicker_points_scores_pats_and_field_goals_by_distance():
    from app.dk_scoring import dk_kicker_points

    row = {"pat_made": "1", "fg_made_0_19": "0", "fg_made_20_29": "1", "fg_made_30_39": "0",
           "fg_made_40_49": "1", "fg_made_50_59": "1", "fg_made_60_": "0", "fg_missed": "2"}
    assert dk_kicker_points(row) == 1 + 3 + 4 + 5
