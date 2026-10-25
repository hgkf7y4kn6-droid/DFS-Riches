from app import advanced_env as ae


def _play(week, off, de, **kw):
    row = {"week": str(week), "posteam": off, "defteam": de, "season_type": "REG", "game_id": f"2026_{week:02d}_{off}_{de}",
           "play_id": "1", "fixed_drive": "1", "drive_time_of_possession": "2:00", "drive_play_count": "6",
           "play_type": "pass", "qb_dropback": "1", "yards_gained": "5", "sack": "0", "qb_hit": "0", "rush": "0",
           "epa": "0", "cpoe": "0", "pass_oe": "0", "qtr": "1", "score_differential": "0", "half_seconds_remaining": "1500",
           "two_point_attempt": "0"}
    row.update({k: str(v) for k, v in kw.items()})
    return row


def test_accumulator_counts_drives_once_and_four_man_pressure():
    acc = ae.EnvAccumulator({"2026_01_KC_BUF|1": (0, 0, 0, 0, 0, 6, 0, 4), "2026_01_KC_BUF|2": (0, 0, 0, 0, 0, 6, 2, 6)})
    acc.add(_play(1, "KC", "BUF", play_id=1, qb_hit=1, yards_gained=25))
    acc.add(_play(1, "KC", "BUF", play_id=2, sack=1))
    acc.add(_play(1, "KC", "BUF", play_id=3, play_type="run", qb_dropback=0, rush=1, epa=-0.5))
    off, de = acc.result()["off"]["1|KC"], acc.result()["def"]["1|BUF"]
    assert off["drives"] == 1 and off["drive_secs"] == 120
    assert off["db"] == 2 and off["expl"] == 1 and off["db4"] == 1 and off["hit4"] == 1   # the six-man rush doesn't count
    assert de["rush"] == 1 and de["rush_epa"] == -0.5


def _feats(**over):
    base = {"sec_per_drive": 150.0, "sec_per_play": 25.0, "explosive_pass": 0.08, "rush_epa": 0.0, "rush_epa_allowed": 0.0,
            "neutral_pass_rate": 0.55, "proe": 0.0, "front4_pressure": 0.2, "pressure_allowed": 0.2, "cpoe": 0.0,
            "charted": True, "pass_rate_rank": 10, "run_defense_rank": 10}
    return {**base, **over}


LG = {k: v for k, v in _feats().items() if k not in ("charted", "pass_rate_rank", "run_defense_rank")}


def test_index_rewards_pace_and_penalizes_front_four_pressure():
    neutral = ae.game_index("A", "B", 45.0, {"A": _feats(), "B": _feats()}, LG)
    fast = ae.game_index("A", "B", 45.0, {"A": _feats(proe=0.06), "B": _feats(proe=0.04)}, LG)
    pressured = ae.game_index("A", "B", 45.0, {"A": _feats(pressure_allowed=0.3), "B": _feats(front4_pressure=0.3)}, LG)
    assert fast["adj"] > neutral["adj"] > pressured["adj"]
    assert neutral["score"] == round(0.7 * 45 + neutral["adj"], 2)
    assert pressured["fragile"] == [{"offense": "A", "defense": "B", "index": 0.2}]
    assert any(n.startswith("Pressure fragility: B") for n in ae.notes(pressured))


def test_pass_funnel_floor_and_slate_leans():
    feats = {"A": _feats(pass_rate_rank=2, rush_epa=-0.2), "B": _feats(run_defense_rank=3, rush_epa_allowed=-0.2)}
    g = ae.game_index("A", "B", 44.0, feats, LG)
    assert g["pass_attempt_floor"] == {"A": 38} and g["parts"]["funnel"] > 0
    games = {"x": {"adj": 1.0}, "y": {"adj": 0.0}, "z": {"adj": -1.0}}
    ae.add_leans(games)
    assert [games[k]["lean"] for k in "xyz"] == ["Over", "Neutral", "Under"]


def test_no_pressure_read_without_charting():
    g = ae.game_index("A", "B", 45.0, {"A": _feats(charted=False, pressure_allowed=0.4), "B": _feats(front4_pressure=0.4)}, LG)
    assert g["parts"]["trench_penalty"] == 0 and not g["fragile"]


def test_pace_card_ranks_drives_and_reads_drive_velocity():
    feats = {"A": _feats(sec_per_drive=130.0, explosive_pass=0.12), "B": _feats(sec_per_drive=140.0, explosive_pass=0.10),
             "C": _feats(sec_per_drive=175.0, explosive_pass=0.05), "D": _feats(sec_per_drive=180.0, explosive_pass=0.04)}
    fast = ae.pace_card("A", "B", feats, LG)
    assert fast["teams"]["A"] == {"sec_per_drive": 130.0, "sec_per_drive_rank": 1, "explosive_pass": 0.12, "explosive_pass_rank": 1}
    assert fast["drive_velocity"] == round(0.22 / 270 * 1000, 3) and fast["vs_league"] > ae.VELOCITY_BAND
    assert "quick, explosive drives" in fast["note"]
    slow = ae.pace_card("C", "D", feats, LG)
    assert slow["teams"]["D"]["sec_per_drive_rank"] == 4 and "long, low-explosive drives" in slow["note"]
    assert ae.pace_card("A", "Z", feats, LG) is None
