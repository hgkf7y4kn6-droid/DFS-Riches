from types import SimpleNamespace

from app import team_changes, vacated
from app.player_model import key


def _player(name, team, pos, proj, injury="Healthy", slot="", vac=None):
    return SimpleNamespace(name=name, team=team, position=pos, injury=injury, proj_points=proj, ceiling=proj * 1.6, salary=5000,
                           value_per_1k=0.0, roster_slot=slot, proj_notes=[], vacated_adj=vac)


def _hist(rows):
    """rows: {(name, pos): (target share, carry share)} for the team's last three games (weeks 7-9, all with team T)."""
    return {key(n, p): {w: {"ts": ts, "cs": cs, "team": "T"} for w in (7, 8, 9)} for (n, p), (ts, cs) in rows.items()}


HIST = _hist({("Alpha", "WR"): (0.22, 0), ("Bravo", "WR"): (0.16, 0), ("Charlie", "WR"): (0.06, 0), ("Delta", "RB"): (0.05, 0.60),
              ("Echo", "RB"): (0.04, 0.30)})


def test_regular_teammate_of_an_out_regular_gets_the_halved_slope():
    ps = [_player("Alpha", "T", "WR", 0.0, injury="OUT"), _player("Bravo", "T", "WR", 10.0), _player("Charlie", "T", "WR", 6.0)]
    vacated.top_up(ps, HIST, 10)
    assert abs(ps[1].proj_points - (10.0 + 0.5 * 4.65 * 0.22)) < 0.01       # a regular: half of 4.65 per 100% of the 22% vacated
    assert ps[2].proj_points == 6.0 and not ps[2].proj_notes                # a backup: Sleeper already prices him, so nothing
    assert "Alpha" in ps[1].proj_notes[0] and ps[1].ceiling > 16.0


def test_a_player_traded_away_counts_as_out():
    ps = [_player("Bravo", "T", "WR", 10.0)]                                # Alpha is on another team now: not in this team's pool
    vacated.top_up(ps, HIST, 10, traded={"T": [("Alpha", "WR")]})
    assert ps[0].proj_points > 10.0
    vacated.top_up([_player("Bravo", "T", "WR", 10.0)], HIST, 10, traded={})   # nothing out, nothing traded: untouched


def test_small_vacancies_and_already_redistributed_players_are_left_alone():
    small = _hist({("Alpha", "WR"): (0.13, 0), ("Bravo", "WR"): (0.16, 0)})        # 13% vacated: under the 15% the test used
    p = _player("Bravo", "T", "WR", 10.0)
    vacated.top_up([_player("Alpha", "T", "WR", 0.0, injury="OUT"), p], small, 10)
    assert p.proj_points == 10.0
    q = _player("Bravo", "T", "WR", 10.0, vac=1.2)                                  # the Sleeper-lag path already added his share
    vacated.top_up([_player("Alpha", "T", "WR", 0.0, injury="OUT"), q], HIST, 10)
    assert q.proj_points == 10.0


def test_running_backs_use_carries_and_the_cap():
    ps = [_player("Delta", "T", "RB", 0.0, injury="OUT"), _player("Echo", "T", "RB", 9.0)]      # Delta had 60% of the carries
    vacated.top_up(ps, HIST, 10)
    assert abs(ps[1].proj_points - (9.0 + 0.5 * 5.69 * 0.6)) < 0.01                             # 1.7 points, under the 2.0 cap
    big = _hist({("Delta", "RB"): (0.05, 0.95), ("Echo", "RB"): (0.04, 0.30)})
    ps = [_player("Delta", "T", "RB", 0.0, injury="OUT"), _player("Echo", "T", "RB", 9.0)]
    vacated.top_up(ps, big, 10)
    assert ps[1].proj_points == 9.0 + vacated.MAX_TOP_UP["RB"]                                  # 0.5 x 5.69 x 0.95 = 2.7: capped at 2.0


def test_captain_rows_get_the_multiplier():
    cpt = _player("Bravo", "T", "WR", 15.0, slot="CPT")
    vacated.top_up([_player("Alpha", "T", "WR", 0.0, injury="OUT"), cpt], HIST, 10)
    assert abs(cpt.proj_points - (15.0 + 1.5 * 0.5 * 4.65 * 0.22)) < 0.01


def test_traded_away_parses_trade_out_rows_by_effective_week():
    ch = [{"team": "IND", "season": 2026, "effective_week": 10, "type": "trade_out", "note": "Josh Downs (WR) IND -> KC | x"},
          {"team": "IND", "season": 2026, "effective_week": 11, "type": "trade_out", "note": "Late Guy (WR) IND -> KC"},
          {"team": "IND", "season": 2026, "effective_week": 10, "type": "trade_out", "note": "Line Man (OL) IND -> KC"},
          {"team": "KC", "season": 2026, "effective_week": 10, "type": "trade_in", "note": "Josh Downs (WR) IND -> KC"}]
    assert team_changes.traded_away(2026, 10, ch) == {"IND": [("Josh Downs", "WR")]}
