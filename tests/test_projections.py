import pytest

from app import projections as pj
from app.ceiling import CeilingContext
from app.models import Player
from app.targets import pick_dst


def test_offense_line_uses_dk_scoring_without_yardage_bonuses():
    line = {"rush_yd": 98.74, "rush_td": 0.73, "rec": 4.29, "rec_yd": 30.17, "rec_td": 0.27,
            "fum_lost": 0.1, "rush_2pt": 0.06, "rec_2pt": 0.02}
    expected = 9.874 + 4.38 + 4.29 + 3.017 + 1.62 - 0.1 + 0.16
    assert pj.dk_points_from_line(line, "RB") == pytest.approx(expected, abs=0.01)
    qb = {"pass_yd": 256.28, "pass_td": 1.49, "pass_int": 1.12, "rush_yd": 36.64, "rush_td": 0.79}
    assert pj.dk_points_from_line(qb, "QB") == pytest.approx(10.2512 + 5.96 - 1.12 + 3.664 + 4.74, abs=0.01)


def test_dst_line_uses_dk_dst_scoring_and_points_allowed_tier():
    line = {"sack": 2.6, "int": 0.88, "fum_rec": 0.61, "safe": 0.06, "blk_kick": 0.06, "def_td": 0.22, "st_td": 0.06, "pts_allow": 16.5}
    expected = 2.6 + 2 * (0.88 + 0.61 + 0.06 + 0.06) + 6 * 0.28 + 1   # 14-20 allowed = +1
    assert pj.dk_points_from_line(line, "DST") == pytest.approx(expected, abs=0.01)
    assert "2.6 sacks, 1.5 takeaways, 16.5 pts allowed" == pj.describe_line(line, "DST")


def test_matchup_adjustment_is_slight_shrunk_and_capped():
    assert pj.matchup_adjustment(None) == 1.0
    # 2 games, 20% over projection: 0.5 strength * 2/6 shrink * 0.2 = +3.3%
    assert pj.matchup_adjustment([36.0, 30.0, 2]) == pytest.approx(1.033, abs=0.001)
    assert pj.matchup_adjustment([90.0, 30.0, 2]) == 1.05     # capped
    assert pj.matchup_adjustment([3.0, 30.0, 2]) == 0.95      # capped


def test_project_explains_line_and_matchup_and_falls_back_to_fppg():
    ctx = pj.ProjectionContext(
        lines={"123": {"stats": {"rec": 6.0, "rec_yd": 80.0, "rec_td": 0.5}, "position": "WR"}},
        vs_expectation={"NYJ|WR": [21.0, 30.0, 2]},
    )
    value, notes = pj.project(ctx, sleeper_id="123", position="WR", opponent="NYJ", fallback=30.0)
    assert value == pytest.approx(17.0 * pj.matchup_adjustment([21.0, 30.0, 2]), abs=0.01)
    assert notes[0] == "Line: 6.0 rec, 80 rec yds, 0.5 rec TD = 17.0 DK pts"
    assert notes[1].startswith("vs NYJ this season: WRs have scored -30% vs their projections (2 games)")

    value, notes = pj.project(ctx, sleeper_id=None, position="K", opponent="NYJ", fallback=8.5)
    assert value == 8.5 and notes == ["No projected stat line this week; DK season FPPG 8.5"]


def _dst(team, opp, salary):
    return Player(name=f"{team} D", team=team, opponent=opp, position="DST", roster_slot="", salary=salary,
                  proj_points=7.0, dk_fppg=7.0, value_per_1k=0.0, game_info=f"{team}@{opp}", injury="Healthy")


def test_pick_dst_explains_the_spot():
    ctx = CeilingContext(
        season=2026, week=3, players={}, def_vs_pos={},
        dst_index={"SEA": [[2025, w, 9.0] for w in range(10, 18)] + [[2026, 1, 12.0], [2026, 2, 6.0]]},
        league_allowed={}, cv_by_pos={"DST": 0.8}, implied={"WAS": 16.5, "SEA": 24.0}, slate_avg_implied=22.0,
        ranks={k: {} for k in ("opp_pass_pct_allowed", "opp_rush_pct_allowed", "neutral_secs", "yards_per_play", "yards_allowed_per_play")},
        points_for={"WAS": 17.0}, league_points_for=22.0,
    )
    t = pick_dst([_dst("SEA", "WAS", 3800)], "SEA", "WAS", ctx, opp_sacks=3.4, opp_giveaways=1.6,
                 league_sacks=2.4, league_giveaways=1.15, opp_implied_rank=32, n_teams=32, dst_rank=1, n_dst=32)
    assert t.role == "DST" and t.ceiling > 0
    assert t.reasons[0] == "#1 DST ceiling of 32 this week"
    assert "WAS implied for just 16.5 (1st-lowest this week)" in t.reasons
    assert any(r.startswith("WAS takes 3.4 sacks/gm") for r in t.reasons)

    tough = pick_dst([_dst("SEA", "WAS", 3800)], "SEA", "WAS", ctx, opp_sacks=1.5, opp_giveaways=0.7,
                     league_sacks=2.4, league_giveaways=1.15, opp_implied_rank=2, n_teams=32, dst_rank=28, n_dst=32)
    assert any(r.startswith("Tough spot: WAS implied for 16.5 (2nd-highest)") for r in tough.reasons)
