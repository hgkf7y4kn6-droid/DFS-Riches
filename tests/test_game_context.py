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


def test_pace_stat_computes_signed_delta():
    stat = _pace_stat(actual=67.0, baseline=62.0)
    assert stat.actual_plays == 67.0
    assert stat.baseline_plays == 62.0
    assert stat.delta == 5.0


def test_pace_stat_negative_delta_means_slower_than_baseline():
    stat = _pace_stat(actual=48.0, baseline=60.1)
    assert stat.delta == -12.1


def test_pace_stat_missing_baseline_has_no_delta_but_keeps_actual():
    stat = _pace_stat(actual=67.0, baseline=None)
    assert stat.actual_plays == 67.0
    assert stat.delta is None


def test_pace_stat_both_missing_returns_none():
    assert _pace_stat(None, None) is None
