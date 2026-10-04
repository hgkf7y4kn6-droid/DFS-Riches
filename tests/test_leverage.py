from app import leverage as lv


def _ctx():
    trench = {"teams": {
        "KC": {"off": {"db_epa": 0.30, "rush_epa": 0.05, "epa_play": 0.20}, "def": {"db_epa": 0.10, "rush_epa": 0.00, "epa_play": 0.05}},
        "NYJ": {"off": {"db_epa": -0.20, "rush_epa": -0.15, "epa_play": -0.18}, "def": {"db_epa": 0.25, "rush_epa": -0.20, "epa_play": 0.10}},
        "BAL": {"off": {"db_epa": 0.05, "rush_epa": 0.20, "epa_play": 0.10}, "def": {"db_epa": -0.15, "rush_epa": -0.10, "epa_play": -0.12}},
    }}
    dvp = {"teams": {
        "NYJ": {"WR": {"games": 3, "adj": {"fp": 12.0}}, "RB": {"games": 3, "adj": {"fp": -8.0}}},
        "KC": {"WR": {"games": 3, "adj": {"fp": -2.0}}, "RB": {"games": 3, "adj": {"fp": 4.0}}},
        "BAL": {"WR": {"games": 3, "adj": {"fp": -10.0}}, "RB": {"games": 3, "adj": {"fp": 4.0}}},
    }}
    return lv.efficiency_context(trench, dvp)


def test_mem_rewards_efficient_offense_into_a_soft_matching_defense():
    ctx = _ctx()
    kc_wr_vs_nyj = lv.mem(ctx, "WR", "KC", "NYJ")       # elite passing offense vs worst pass D that funnels to WRs
    nyj_wr_vs_bal = lv.mem(ctx, "WR", "NYJ", "BAL")      # broken offense vs stingy pass D
    assert kc_wr_vs_nyj["mem"] > 1.0 > nyj_wr_vs_bal["mem"]
    assert kc_wr_vs_nyj["pos_z"] > 0 and nyj_wr_vs_bal["pos_z"] < 0
    assert lv.MEM_MIN <= nyj_wr_vs_bal["mem"] and kc_wr_vs_nyj["mem"] <= lv.MEM_MAX
    assert lv.mem({"off_db": {}, "off_rush": {}, "off_play": {}, "def_db": {}, "def_rush": {}, "def_play": {}, "pos": {}},
                  "RB", "KC", "NYJ")["mem"] == 1.0        # no data: neutral


def test_fair_ownership_redistributes_the_positions_ownership_by_true_odds():
    rows = [
        {"position": "RB", "salary": 8200, "p_eff": 0.10, "own": 0.38},   # public trap: chalky, weak odds
        {"position": "RB", "salary": 5400, "p_eff": 0.22, "own": 0.03},   # efficient secret
        {"position": "RB", "salary": 3200, "p_eff": 0.01, "own": 0.01},   # cheap mirage
        {"position": "RB", "salary": 6500, "p_eff": 0.15, "own": 0.18},
    ]
    lv.fair_ownership(rows, "p_eff", "own")
    assert abs(sum(r["fair_own"] for r in rows) - sum(r["own"] for r in rows)) < 1e-9
    lev = [(r["fair_own"] - r["own"]) * 100 for r in rows]
    assert lev[0] < -15 and lev[1] > 15                  # trap strongly negative, secret strongly positive
    assert abs(lev[2]) < 2                               # the mirage can't float to the top
    assert lv.verdict(lev[1], 0.03, 1.08, 0.22) == "Efficient secret"
    assert lv.verdict(lev[0], 0.38, 0.92, 0.10) == "Public trap"
    assert lv.verdict(lev[2], 0.01, 0.95, 0.01) == "Mirage"
