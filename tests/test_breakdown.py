from datetime import datetime, timezone

from app.breakdown import (
    _efficiency_takeaway,
    _funnel_takeaways,
    _ordinal,
    _pace_takeaway,
    _vegas_takeaways,
    generate_takeaways,
)
from app.models import Game, GameContext, TeamStatLine
from app.nflverse_client import rank_teams, team_trailing


def _game(**overrides) -> Game:
    defaults = dict(
        game_id="2026_03_ATL_GB",
        season=2026,
        week=3,
        away="ATL",
        home="GB",
        kickoff_utc=datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc),
        kickoff_et="Thu 9/24 8:15 PM ET",
        network="Amazon Prime",
        day_part="THU_NIGHT",
        isolated=True,
    )
    defaults.update(overrides)
    return Game(**defaults)


def _stat_line(team: str, **overrides) -> TeamStatLine:
    defaults = dict(team=team)
    defaults.update(overrides)
    return TeamStatLine(**defaults)


def test_ordinal_handles_regular_and_teen_suffixes():
    assert _ordinal(1) == "1st"
    assert _ordinal(2) == "2nd"
    assert _ordinal(3) == "3rd"
    assert _ordinal(4) == "4th"
    assert _ordinal(11) == "11th"
    assert _ordinal(12) == "12th"
    assert _ordinal(13) == "13th"
    assert _ordinal(21) == "21st"
    assert _ordinal(22) == "22nd"
    assert _ordinal(23) == "23rd"


def test_vegas_takeaways_names_the_favorite_and_ranks():
    game = _game(context=GameContext(home_spread=-5.5, total_line=42.5, away_implied_total=18.5, home_implied_total=24.0))
    bullets = _vegas_takeaways(game, total_rank=9, away_implied_rank=28, home_implied_rank=8)
    assert bullets[0] == "O/U is 42.5 (9th-highest total of the week), with GB favored by 5.5."
    assert bullets[1] == "ATL is implied for 18.5 (28th-highest team total of the week); GB for 24 (8th)."


def test_vegas_takeaways_away_favorite_named_correctly():
    game = _game(context=GameContext(home_spread=6.0, total_line=40.0))
    bullets = _vegas_takeaways(game, total_rank=None, away_implied_rank=None, home_implied_rank=None)
    assert "ATL favored by 6" in bullets[0]


def test_vegas_takeaways_pick_em():
    game = _game(context=GameContext(home_spread=0.0, total_line=45.0))
    bullets = _vegas_takeaways(game, total_rank=None, away_implied_rank=None, home_implied_rank=None)
    assert bullets[0].endswith("a pick'em.")


def test_vegas_takeaways_empty_without_a_line():
    game = _game(context=None)
    assert _vegas_takeaways(game, None, None, None) == []
    assert _vegas_takeaways(_game(context=GameContext()), None, None, None) == []


def test_pace_takeaway_flags_both_fast_offenses():
    game = _game()
    away = _stat_line("ATL", pace_rank=3)
    home = _stat_line("GB", pace_rank=8)
    text = _pace_takeaway(game, away, home)
    assert "top 10 for plays/game" in text
    assert "ATL 3rd" in text and "GB 8th" in text


def test_pace_takeaway_flags_both_slow_offenses():
    game = _game()
    away = _stat_line("ATL", pace_rank=28)
    home = _stat_line("GB", pace_rank=29)
    text = _pace_takeaway(game, away, home)
    assert "bottom 10 for plays/game" in text


def test_pace_takeaway_flags_the_faster_side_when_mixed():
    game = _game()
    away = _stat_line("ATL", pace_rank=5)
    home = _stat_line("GB", pace_rank=20)
    text = _pace_takeaway(game, away, home)
    assert text.startswith("ATL plays at a notably faster pace")


def test_pace_takeaway_none_without_ranks():
    game = _game()
    assert _pace_takeaway(game, _stat_line("ATL"), _stat_line("GB")) is None


def test_funnel_takeaways_prefers_pass_funnel_over_rush_funnel():
    game = _game()
    away = _stat_line("ATL")
    home = _stat_line("GB", opp_pass_pct_allowed_rank=2, opp_rush_pct_allowed_rank=1)
    bullets = _funnel_takeaways(game, away, home)
    assert len(bullets) == 1
    assert "passing game projects for extra volume" in bullets[0]
    assert "GB's defense ranks 2nd" in bullets[0]


def test_funnel_takeaways_falls_back_to_rush_funnel():
    game = _game()
    away = _stat_line("ATL")
    home = _stat_line("GB", opp_pass_pct_allowed_rank=25, opp_rush_pct_allowed_rank=1)
    bullets = _funnel_takeaways(game, away, home)
    assert len(bullets) == 1
    assert "ground game gets a runway" in bullets[0]


def test_funnel_takeaways_checks_both_sides():
    game = _game()
    away = _stat_line("ATL", opp_rush_pct_allowed_rank=3)
    home = _stat_line("GB", opp_pass_pct_allowed_rank=4)
    bullets = _funnel_takeaways(game, away, home)
    assert len(bullets) == 2


def test_funnel_takeaways_none_outside_threshold():
    game = _game()
    away = _stat_line("ATL", opp_pass_pct_allowed_rank=20, opp_rush_pct_allowed_rank=22)
    home = _stat_line("GB", opp_pass_pct_allowed_rank=18, opp_rush_pct_allowed_rank=19)
    assert _funnel_takeaways(game, away, home) == []


def test_efficiency_takeaway_flags_mismatch():
    game = _game()
    away = _stat_line("ATL", yards_per_play_rank=2)
    home = _stat_line("GB", yards_allowed_per_play_rank=31)
    text = _efficiency_takeaway(game, away, home)
    assert "ATL's offense" in text and "efficiency mismatch" in text


def test_efficiency_takeaway_none_when_no_mismatch():
    game = _game()
    away = _stat_line("ATL", yards_per_play_rank=15)
    home = _stat_line("GB", yards_allowed_per_play_rank=15)
    assert _efficiency_takeaway(game, away, home) is None


def test_generate_takeaways_falls_back_when_nothing_stands_out():
    game = _game(context=None)
    bullets = generate_takeaways(game, _stat_line("ATL"), _stat_line("GB"))
    assert bullets == ["No standout statistical edge for either side yet -- an early-season, projection-neutral matchup."]


def test_generate_takeaways_combines_all_categories():
    game = _game(context=GameContext(home_spread=-3.0, total_line=48.0))
    away = _stat_line("ATL", pace_rank=2, opp_rush_pct_allowed_rank=1, yards_per_play_rank=1)
    home = _stat_line("GB", pace_rank=25, opp_pass_pct_allowed_rank=3, yards_allowed_per_play_rank=32)
    bullets = generate_takeaways(game, away, home, total_rank=1)
    assert len(bullets) >= 4  # vegas + pace + funnel(s) + efficiency


def test_rank_teams_orders_by_descending_value_by_default():
    index = {
        "A": {"points_for": [[2026, 1, 20.0], [2026, 2, 30.0]]},
        "B": {"points_for": [[2026, 1, 10.0], [2026, 2, 10.0]]},
        "C": {"points_for": [[2026, 1, 40.0], [2026, 2, 40.0]]},
    }
    ranks = rank_teams(index, "points_for", season=2026, week=3, n=8, descending=True)
    assert ranks == {"C": 1, "A": 2, "B": 3}


def test_rank_teams_ascending_for_lower_is_better_metrics():
    index = {
        "A": {"points_against": [[2026, 1, 20.0]]},
        "B": {"points_against": [[2026, 1, 10.0]]},
    }
    ranks = rank_teams(index, "points_against", season=2026, week=2, n=8, descending=False)
    assert ranks == {"B": 1, "A": 2}


def test_rank_teams_skips_teams_with_no_data():
    index = {
        "A": {"points_for": [[2026, 1, 20.0]]},
        "B": {"points_for": []},
    }
    ranks = rank_teams(index, "points_for", season=2026, week=2, n=8)
    assert ranks == {"A": 1}
    assert "B" not in ranks


def test_team_trailing_reads_through_to_trailing_avg():
    index = {"A": {"yards_per_play": [[2026, 1, 5.0], [2026, 2, 7.0]]}}
    assert team_trailing(index, "A", "yards_per_play", season=2026, week=3, n=8) == 6.0


def test_team_trailing_none_for_unknown_team_or_metric():
    index = {"A": {"yards_per_play": [[2026, 1, 5.0]]}}
    assert team_trailing(index, "Z", "yards_per_play", season=2026, week=2) is None
    assert team_trailing(index, "A", "unknown_metric", season=2026, week=2) is None
