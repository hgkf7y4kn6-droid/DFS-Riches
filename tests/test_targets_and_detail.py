from datetime import datetime, timezone

from app import targets
from app.ceiling import CeilingContext
from app.game_detail import offense_insight, positions_insight, tempo_insight, usage_insight, vegas_insight
from app.models import Game, GameContext, LeagueContext, Player, PositionMatchup, TeamStatLine, UsageShare
from app.nflverse_client import player_key

RANK_KEYS = ("opp_pass_pct_allowed", "opp_rush_pct_allowed", "neutral_secs", "yards_per_play", "yards_allowed_per_play")


def _ctx(players, def_vs_pos=None, ranks=None, implied=None):
    return CeilingContext(
        season=2026, week=3, players=players,
        def_vs_pos=def_vs_pos or {}, dst_index={},
        league_allowed={"QB": 18.0, "RB": 22.0, "WR": 30.0, "TE": 13.0},
        cv_by_pos={"QB": 0.45, "RB": 0.65, "WR": 0.75, "TE": 0.7},
        implied=implied or {"TM": 22.0, "OPP": 22.0}, slate_avg_implied=22.0,
        ranks=ranks or {k: {} for k in RANK_KEYS}, points_for={}, league_points_for=None,
    )


def _player(name, pos, salary, proj=15.0, injury="Healthy", team="TM"):
    return Player(name=name, team=team, opponent="OPP", position=pos, roster_slot="", salary=salary,
                  proj_points=proj, dk_fppg=proj, value_per_1k=0.0, game_info="TM@OPP", injury=injury)


def _history(points, share):
    return [[2025, w, points, share] for w in range(12, 18)] + [[2026, 1, points, share], [2026, 2, points, share]]


def test_targets_follow_the_matchup_not_the_salary():
    players = [
        _player("Pricey WR", "WR", 8500, 20.0),
        _player("Soft Spot RB", "RB", 6500, 18.0),
        _player("Cheap TE", "TE", 3800, 10.0),
        _player("Hurt WR", "WR", 7000, 25.0, injury="OUT"),
    ]
    log = {
        player_key("Pricey WR", "WR"): _history(20.0, 0.20),
        player_key("Soft Spot RB", "RB"): _history(19.0, 0.35),
        player_key("Cheap TE", "TE"): _history(12.0, 0.10),
        player_key("Hurt WR", "WR"): _history(25.0, 0.25),
    }
    # OPP gets shredded by RBs and TEs, stingy vs WRs.
    def_vs_pos = {"OPP": {"RB": [[2025, w, 40.0] for w in range(10, 18)], "TE": [[2025, w, 22.0] for w in range(10, 18)],
                          "WR": [[2025, w, 18.0] for w in range(10, 18)]}}
    picks = targets.pick_targets(players, "TM", "OPP", _ctx(log, def_vs_pos), pass_rank=None, pass_rate=None)

    names = [p.name for p in picks]
    assert "Hurt WR" not in names
    assert names[0] == "Soft Spot RB"
    assert any(r.startswith("OPP allow +") and "RBs" in r for r in picks[0].reasons)
    value = [p for p in picks if p.role == "Value"]
    assert value and value[0].name == "Cheap TE" and value[0].salary <= targets.VALUE_MAX_SALARY


def test_pass_leaning_offense_tilts_toward_pass_catchers():
    players = [_player("Even RB", "RB", 6000, 16.0), _player("Even WR", "WR", 6000, 16.0)]
    log = {player_key("Even RB", "RB"): _history(16.0, 0.2), player_key("Even WR", "WR"): _history(16.0, 0.2)}
    ctx = _ctx(log)
    ctx.cv_by_pos = {"RB": 0.7, "WR": 0.7}
    pass_heavy = targets.pick_targets(players, "TM", "OPP", ctx, pass_rank=2, pass_rate=0.66)
    run_heavy = targets.pick_targets(players, "TM", "OPP", ctx, pass_rank=30, pass_rate=0.48)
    assert pass_heavy[0].name == "Even WR" and any("pass-leaning" in r for r in pass_heavy[0].reasons)
    assert run_heavy[0].name == "Even RB" and any("run-leaning" in r for r in run_heavy[0].reasons)


def _game(home_spread=-6.5, total=47.5):
    return Game(game_id="g", season=2026, week=3, away="NYJ", home="DET",
                kickoff_utc=datetime(2026, 9, 27, 17, tzinfo=timezone.utc), kickoff_et="", day_part="SUN_EARLY",
                context=GameContext(home_spread=home_spread, total_line=total, away_implied_total=20.5, home_implied_total=27.0))


def test_vegas_insight_explains_script_and_environment():
    text = vegas_insight(_game(), {}, total_rank=3, n_games=16)
    assert text.startswith("The 3rd-highest total of the week (47.5)")
    assert "DET is favored by 6.5" in text and "NYJ would likely need to throw more" in text
    close = vegas_insight(_game(home_spread=-1.5, total=38.0), {}, total_rank=15, n_games=16)
    assert "lowest totals" in close and "stacking both sides" in close


def test_offense_insight_classifies_the_matchup():
    league = LeagueContext(yards_per_play=5.5)
    edge = offense_insight("DET", "NYJ", TeamStatLine(team="DET", yards_per_play=6.0), TeamStatLine(team="NYJ", yards_allowed_per_play=6.0), league)
    assert "gains 9% more yards per play than average" in edge and "A clear edge" in edge
    tough = offense_insight("NYJ", "DET", TeamStatLine(team="NYJ", yards_per_play=4.4), TeamStatLine(team="DET", yards_allowed_per_play=4.9), league)
    assert "20% fewer" in tough and "tough spot" in tough


def test_tempo_positions_and_usage_insights():
    g = _game()
    league = LeagueContext(plays=61.0)
    fast = tempo_insight(g, TeamStatLine(team="NYJ", tempo_rank=3, tempo_secs=36.0, plays_per_game=64),
                         TeamStatLine(team="DET", tempo_rank=7, tempo_secs=37.0, plays_per_game=66), league)
    assert fast.startswith("Both offenses play fast") and "130 plays per game (league: 122)" in fast

    pos = positions_insight(
        g,
        [PositionMatchup(position="RB", vs_avg=0.42, rank=1), PositionMatchup(position="WR", vs_avg=-0.2, rank=30)],
        [PositionMatchup(position="TE", vs_avg=0.49, rank=2)],
    )
    assert "DET's best matchup: RBs vs NYJ (+42% DK pts allowed); toughest: WRs (-20%)" in pos
    assert "NYJ's best matchup: TEs vs DET (+49% DK pts allowed)" in pos

    use = usage_insight(g, [UsageShare(name="Hall", position="RB", share_l3=0.22, share_l8=0.3)],
                        [UsageShare(name="Gibbs", position="RB", share_l3=0.41, share_l8=0.37)])
    assert "NYJ spreads the ball around (leader: Hall, 22%, down from 30%)" in use
    assert "Gibbs handles 41% of DET's targets + carries, up from 37%" in use
