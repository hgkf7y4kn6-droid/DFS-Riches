from app import matchups as m


def _rec(week, producer, allower, fp, num=0.0, vol=0.0, season=2026):
    return {"season": season, "week": week, "producer": producer, "allower": allower, "fp": fp, "num": num, "vol": vol}


def _records():
    """WR games: GOOD is a strong offense (30/game elsewhere), BAD a weak one (10/game).
    Defense SOFTSKED only faced BAD and allowed 14 (more than BAD's usual 10);
    defense TOUGHSKED only faced GOOD and allowed 26 (less than GOOD's usual 30)."""
    wr = [
        _rec(1, "GOOD", "X1", 30, 300, 30), _rec(2, "GOOD", "X2", 30, 300, 30),
        _rec(1, "BAD", "X3", 10, 100, 20), _rec(2, "BAD", "X4", 10, 100, 20),
        _rec(3, "BAD", "SOFTSKED", 14, 160, 20),
        _rec(3, "GOOD", "TOUGHSKED", 26, 240, 30),
    ]
    return {"WR": wr}


def test_raw_ranks_reward_the_soft_schedule_and_adjusted_ranks_correct_it():
    t = m.table(_records(), 2026, 4)
    soft, tough = t["teams"]["SOFTSKED"]["WR"], t["teams"]["TOUGHSKED"]["WR"]
    # Raw: TOUGHSKED allowed more points (26 vs 14) so it looks like the softer matchup.
    assert tough["raw"]["fp"] == 26 and soft["raw"]["fp"] == 14
    assert tough["raw"]["fp_rank"] > soft["raw"]["fp_rank"]
    # Adjusted: SOFTSKED allowed 4 more than BAD's usual; TOUGHSKED held GOOD 4 under.
    assert soft["adj"]["fp"] == 4.0 and tough["adj"]["fp"] == -4.0
    assert soft["adj"]["fp_rank"] > tough["adj"]["fp_rank"]
    # Efficiency: 8.0 yds/target allowed vs BAD's usual 5.0 -> +3.0; 8.0 vs GOOD's usual 10.0 -> -2.0.
    assert soft["raw"]["eff"] == 8.0 and soft["adj"]["eff"] == 3.0
    assert tough["adj"]["eff"] == -2.0


def test_window_uses_games_before_the_week_only():
    t = m.table(_records(), 2026, 3)
    assert "SOFTSKED" not in t["teams"] and "TOUGHSKED" not in t["teams"]
    assert t["teams"]["X1"]["WR"]["games"] == 1


def test_window_caps_at_recent_games():
    recs = {"RB": [_rec(w, "O", "D", float(w), w, 1) for w in range(1, 13)]}
    t = m.table(recs, 2026, 13)
    d = t["teams"]["D"]["RB"]
    assert d["games"] == m.WINDOW
    assert d["raw"]["fp"] == sum(range(5, 13)) / 8


def test_highest_rank_is_the_most_allowed():
    assert m._ranks({"A": 1.0, "B": 3.0, "C": 2.0}) == {"A": 1, "C": 2, "B": 3}


def test_rb_efficiency_counts_rushing_and_receiving():
    row = {"rushing_yards": "50", "receiving_yards": "30", "carries": "12", "receptions": "4", "targets": "6"}
    assert m._skill_numbers(row, "RB") == (80.0, 16.0)
    assert m._skill_numbers(row, "WR") == (30.0, 6.0)
