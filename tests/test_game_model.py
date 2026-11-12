from app import game_model as gm
from app import player_model as pm


def _play(**kw):
    row = {"week": "2", "posteam": "KC", "defteam": "BUF", "season_type": "REG", "game_id": "2026_02_KC_BUF", "play_id": "1",
           "fixed_drive": "1", "drive_time_of_possession": "3:00", "drive_play_count": "8", "play_type": "pass",
           "qb_dropback": "1", "yards_gained": "6", "sack": "0", "qb_hit": "0", "rush": "0", "epa": "0.2", "success": "1",
           "pass_oe": "5", "qtr": "1", "score_differential": "0", "half_seconds_remaining": "1500", "id": "QB1", "name": "P.Mahomes"}
    row.update({k: str(v) for k, v in kw.items()})
    return row


def test_accumulator_counts_quick_pressure_and_quarterback():
    acc = gm.GameAccumulator(ftn={"2026_02_KC_BUF|1": 4}, part={"2026_02_KC_BUF|1": (4, 2.1, True), "2026_02_KC_BUF|2": (6, 2.0, True)})
    acc.add(_play(play_id=1, qb_hit=1))
    acc.add(_play(play_id=2, play_type="run", qb_dropback=0, rush=1, epa=-0.1, success=0))
    out = acc.result()
    off, de = out["off"]["2|KC"], out["def"]["2|BUF"]
    assert off["drives"] == 1 and off["db"] == 1 and off["rush"] == 1 and off["qp"] == 1 and off["qp_db"] == 1
    assert de["hit4"] == 1 and "proe" not in de
    assert out["qb"]["2|KC"]["QB1"][0] == 1


def test_shrinkage_starts_at_last_season_and_moves_with_plays():
    prior = {"teams": {"KC": {"pass_epa": 0.2}}, "league": {"pass_epa": 0.0}}
    none = gm.team_estimates({}, prior)["KC"]["pass_epa"]
    lots = gm.team_estimates({"KC": {"off": {"db": 1600, "db_epa": -160}, "def": {}}}, prior)["KC"]["pass_epa"]
    assert none == 0.2 and -0.1 < lots < 0


def test_unknown_quarterback_starts_below_league():
    est, n = gm.qb_estimate({}, "NEW", 0.05)
    assert n == 0 and est == 0.05 + gm.BACKUP_QB_EPA


def test_ridge_recovers_a_signal():
    X = [[i % 7, (i * 3) % 5] for i in range(60)]
    y = [2.0 * a for a, _ in X]
    w, means, sds, b = gm.fit_ridge(X, y, alpha=0.01)
    model = {"features": ["a", "b"], "weights": w, "means": means, "sds": sds, "intercept": b}
    assert abs(gm.apply(model, {"a": 3, "b": 1}) - 6.0) < 0.1


def test_player_features_use_only_earlier_weeks():
    h = {1: {"ts": 0.1, "cs": 0.0, "snap": 0.5, "pts": 5.0}, 2: {"ts": 0.3, "cs": 0.0, "snap": 0.9, "pts": 15.0},
         3: {"ts": 0.9, "cs": 0.0, "snap": 1.0, "pts": 40.0}}
    f = pm.features(h, 3, 12.0, "WR", 24.0, 3.0, {1: 8.0, 2: 10.0})
    assert f["games"] == 2 and abs(f["ts_l3"] - 0.2) < 1e-9 and abs(f["form"] - 1.0) < 1e-9 and f["spread_x_rb"] == 0.0


def test_adjustment_is_capped():
    model = {"positions": {"WR": {"features": ["proj"], "weights": [100.0], "means": [0.0], "sds": [1.0], "intercept": 0.0}}}
    assert pm.adjustment("WR", {"proj": 10.0}, model) == 3.5
    assert pm.adjustment("QB", {"proj": 10.0}, model) is None
