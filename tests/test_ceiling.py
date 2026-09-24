import pytest

from app.ceiling import CeilingContext, _weighted_stats, player_ceiling
from app.nflverse_client import player_key

RB_KEY = player_key("Test Back", "RB")


def _ctx(**overrides) -> CeilingContext:
    base = dict(
        season=2026,
        week=3,
        players={RB_KEY: [[2025, w, 20.0, 0.30] for w in range(10, 18)] + [[2026, 1, 20.0, 0.30], [2026, 2, 20.0, 0.30]]},
        def_vs_pos={"OPP": {"RB": [[2025, w, 22.0] for w in range(10, 18)]}},
        dst_index={},
        league_allowed={"RB": 22.0},
        cv_by_pos={"RB": 0.5},
        implied={"TM": 22.0, "OPP": 22.0},
        slate_avg_implied=22.0,
        ranks={m: {} for m in ("opp_pass_pct_allowed", "opp_rush_pct_allowed", "neutral_secs", "yards_per_play", "yards_allowed_per_play")},
        points_for={},
        league_points_for=None,
    )
    base.update(overrides)
    return CeilingContext(**base)


def _ceil(ctx, **kw):
    args = dict(name="Test Back", position="RB", team="TM", opponent="OPP", fallback_mean=None)
    args.update(kw)
    return player_ceiling(ctx, **args)


def test_neutral_context_gives_history_only_ceiling_from_positional_spread():
    # Constant 20-pt games: own spread 0, so the spread comes from the position
    # prior (cv 0.5 -> sd 10) blended in with PRIOR_GAMES weight.
    value, notes = _ceil(_ctx())
    assert 20.0 < value < 20.0 + 1.04 * 10.0
    assert notes[0].startswith("History:")
    assert all(n.split(" x")[1].startswith("1.00") for n in notes[1:])


def test_soft_matchup_raises_ceiling_and_is_clamped():
    neutral, _ = _ceil(_ctx())
    soft = _ctx(def_vs_pos={"OPP": {"RB": [[2025, w, 44.0] for w in range(10, 18)]}})
    value, notes = _ceil(soft)
    matchup = next(n for n in notes if n.startswith("Matchup"))
    assert "x1.15" in matchup  # 2x league average, shrunk 0.5 -> 1.5, clamped to 1.15
    assert value == pytest.approx(neutral * 1.15, abs=0.1)


def test_higher_implied_total_raises_ceiling():
    neutral, _ = _ceil(_ctx())
    value, notes = _ceil(_ctx(implied={"TM": 27.5, "OPP": 16.5}))
    assert value > neutral
    assert any(n.startswith("Game env x1.15") for n in notes)


def test_breakdown_rush_funnel_applies_to_rbs_only():
    ranks = {m: {} for m in ("opp_pass_pct_allowed", "neutral_secs", "yards_per_play", "yards_allowed_per_play")}
    ranks["opp_rush_pct_allowed"] = {"OPP": 3}
    ctx = _ctx(ranks=ranks)
    _, rb_notes = _ceil(ctx)
    assert any("rush funnel (#3)" in n for n in rb_notes)


def test_rising_usage_raises_ceiling_and_falling_usage_lowers_it():
    rising = [[2025, w, 20.0, 0.20] for w in range(12, 18)] + [[2026, 1, 20.0, 0.40], [2026, 2, 20.0, 0.40]]
    falling = [[2025, w, 20.0, 0.40] for w in range(12, 18)] + [[2026, 1, 20.0, 0.15], [2026, 2, 20.0, 0.15]]
    up, up_notes = _ceil(_ctx(players={RB_KEY: rising}))
    down, down_notes = _ceil(_ctx(players={RB_KEY: falling}))
    assert up > down
    assert any(n.startswith("Usage x1.") for n in up_notes)
    assert any(n.startswith("Usage x0.9") for n in down_notes)


def test_combined_adjustments_are_capped():
    ranks = {m: {} for m in ("opp_pass_pct_allowed", "neutral_secs", "yards_per_play", "yards_allowed_per_play")}
    ranks["opp_rush_pct_allowed"] = {"OPP": 1}
    ctx = _ctx(
        def_vs_pos={"OPP": {"RB": [[2025, w, 60.0] for w in range(10, 18)]}},
        implied={"TM": 35.0, "OPP": 10.0},
        ranks=ranks,
    )
    neutral, _ = _ceil(_ctx())
    value, notes = _ceil(ctx)
    assert value == pytest.approx(neutral * 1.25, abs=0.1)
    assert notes[-1].startswith("Combined adjustments capped at x1.25")


def test_no_history_falls_back_to_dk_fppg_and_none_without_either():
    value, notes = _ceil(_ctx(players={}), fallback_mean=12.0)
    assert value > 12.0
    assert "from DK FPPG 12.0" in notes[0]
    assert _ceil(_ctx(players={})) == (None, [])


def test_dst_matchup_and_game_env_are_inverted():
    ctx = _ctx(
        dst_index={"TM": [[2026, 1, 8.0], [2026, 2, 8.0]]},
        cv_by_pos={"DST": 0.8},
        points_for={"OPP": 14.0},
        league_points_for=22.0,
        implied={"TM": 26.0, "OPP": 16.0},
    )
    value, notes = player_ceiling(ctx, name="Team", position="DST", team="TM", opponent="OPP", fallback_mean=None)
    assert any(n.startswith("Matchup x1.") and "OPP score 14.0" in n for n in notes)
    assert any(n.startswith("Game env x1.") and "OPP implied 16" in n for n in notes)


def test_player_with_only_past_season_games_is_discounted_after_week_1():
    last_year_only = {RB_KEY: [[2025, w, 20.0, 0.30] for w in range(10, 18)]}
    this_year = {RB_KEY: last_year_only[RB_KEY] + [[2026, 1, 20.0, 0.30]]}
    discounted, notes = _ceil(_ctx(players=last_year_only))
    active, _ = _ceil(_ctx(players=this_year))
    assert discounted < active * 0.6
    assert notes[-1].startswith("Role x0.50: no games played this season")
    week1, week1_notes = _ceil(_ctx(players=last_year_only, week=1))
    assert not any(n.startswith("Role") for n in week1_notes)


def test_recency_weighting_favors_recent_games():
    mean, _sd, n_eff = _weighted_stats([10.0] * 10 + [30.0, 30.0])
    assert mean > 10.0 + (20.0 * 2 / 12)  # above the unweighted mean
    assert n_eff < 12
