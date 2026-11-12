import pytest

from app import dfs_strategy, trenches


def _play(**kw):
    base = {"play_type": "pass", "week": "2", "posteam": "BUF", "defteam": "MIA", "wp": "0.5", "epa": "0.4",
            "success": "1", "yards_gained": "8", "qb_dropback": "1", "sack": "0", "qb_hit": "0",
            "qb_kneel": "0", "qb_spike": "0", "game_id": "2026_02_BUF_MIA", "play_id": "100"}
    base.update(kw)
    return base


def test_accumulator_counts_both_sides_and_joins_ftn():
    ftn = trenches.ftn_index([{"nflverse_game_id": "2026_02_BUF_MIA", "nflverse_play_id": "101", "is_play_action": "FALSE",
                               "is_motion": "TRUE", "is_screen_pass": "FALSE", "is_rpo": "FALSE", "is_no_huddle": "FALSE",
                               "n_defense_box": "6", "n_blitzers": "0", "n_pass_rushers": "0"},
                              {"nflverse_game_id": "2026_02_BUF_MIA", "nflverse_play_id": "100", "is_play_action": "TRUE",
                               "is_motion": "FALSE", "is_screen_pass": "FALSE", "is_rpo": "FALSE", "is_no_huddle": "FALSE",
                               "n_defense_box": "7", "n_blitzers": "2", "n_pass_rushers": "6"}])
    acc = trenches.TrenchAccumulator(ftn)
    acc.add(_play(sack="1", qb_hit="1", yards_gained="-7", success="0", epa="-1.5"))            # sack, charted
    acc.add(_play(play_type="run", qb_dropback="0", yards_gained="0", success="0", play_id="101.0"))  # stuffed run, light box
    acc.add(_play(yards_gained="25", play_id="102"))                                                          # explosive pass
    acc.add(_play(wp="0.97"))                                                                    # garbage time: ignored
    acc.add(_play(play_type="run", qb_dropback="0", qb_kneel="1"))                               # kneel: ignored
    out = acc.result()
    o, d = out["off"]["2|BUF"], out["def"]["2|MIA"]
    assert o == d
    assert o["plays"] == 3 and o["db"] == 2 and o["sack"] == 1 and o["hit"] == 1 and o["exp_pass"] == 1
    assert o["rush"] == 1 and o["stuff"] == 1
    assert o["pa"] == 1 and o["blitz"] == 1 and o["rushers"] == 6 and o["light_box"] == 1 and o["motion"] == 1


def test_coverage_counts_attributes_the_defense_from_the_game_id():
    rows = [{"nflverse_game_id": "2025_03_KC_NYG", "possession_team": "KC", "defense_man_zone_type": "MAN_COVERAGE",
             "defense_coverage_type": "COVER_1", "was_pressure": "TRUE", "time_to_throw": "2.5"},
            {"nflverse_game_id": "2025_03_KC_NYG", "possession_team": "KC", "defense_man_zone_type": "ZONE_COVERAGE",
             "defense_coverage_type": "COVER_4", "was_pressure": "FALSE", "time_to_throw": "3.1"},
            {"nflverse_game_id": "2025_03_KC_NYG", "possession_team": "KC", "defense_man_zone_type": "",
             "defense_coverage_type": "", "was_pressure": "FALSE", "time_to_throw": ""}]   # a run: not charted
    out = trenches.coverage_counts(rows)
    d, o = out["def"]["3|NYG"], out["off"]["3|KC"]
    assert d["cov"] == 2 and d["man"] == 1 and d["single_high"] == 1 and d["two_high"] == 1 and d["pressure"] == 1
    assert o["ttt_n"] == 2 and abs(o["ttt"] - 5.6) < 1e-9


def test_blend_weights_last_season_as_prior_games():
    cur = {"off": {"1|BUF": {"plays": 60, "succ": 30}, "2|BUF": {"plays": 60, "succ": 30}, "3|BUF": {"plays": 99, "succ": 0}}}
    prev = {"off": {f"{w}|BUF": {"plays": 60, "succ": 18} for w in range(1, 18)}}
    counts, n_now, n_last = trenches.blend(cur, prev, "BUF", "off", week=3)     # week 3 excludes week 3's game
    assert (n_now, n_last) == (2, 17)
    assert counts["plays"] == 120 + trenches.PRIOR_GAMES * 60
    assert abs(counts["succ"] / counts["plays"] - (60 + trenches.PRIOR_GAMES * 18) / counts["plays"]) < 1e-9


def _week(**teams):
    tw = {"teams": {t: {"off": dict(o), "def": dict(d), "cov": {}, "games": 3} for t, (o, d) in teams.items()},
          "league": {}, "coverage_season": 2025}
    trenches.grade_units(tw["teams"])
    return tw


def _unit(sack, hit, rsucc, stuff, repa, dbepa, dbsucc, exp):
    return {"sack_rate": sack, "pressure_rate": hit, "rush_success": rsucc, "stuff_rate": stuff, "rush_epa": repa,
            "db_epa": dbepa, "db_success": dbsucc, "explosive_pass": exp, "epa_play": dbepa, "success": dbsucc}


def test_matchup_edges_require_the_defense_to_point_the_same_way():
    good_off, bad_off = _unit(.04, .10, .50, .12, .10, .30, .52, .12), _unit(.10, .22, .36, .24, -.15, -.20, .40, .05)
    good_def, bad_def = _unit(.10, .22, .36, .24, -.15, -.20, .40, .05), _unit(.04, .10, .50, .12, .10, .30, .52, .12)
    avg = _unit(.07, .16, .43, .18, -.02, .05, .46, .085)
    tw = _week(GOOD=(good_off, bad_def), BAD=(bad_off, good_def), AVG=(avg, avg))
    assert tw["teams"]["GOOD"]["grades"]["pass_pro"]["rank"] == 1
    assert tw["teams"]["BAD"]["grades"]["pass_rush"]["rank"] == 1

    m = trenches.matchup(tw, "BAD", "GOOD")          # bad offense vs a bad defense -> no "wall" can be claimed
    assert all(e["edge"] > 0 or e["strength"] == "neutral" for e in m["edges"].values())
    m = trenches.matchup(tw, "BAD", "BAD")           # bad offense vs the good defense
    assert m["edges"]["protection"]["strength"] == "strong" and "pressure_mismatch" in m["flags"]
    assert "run_wall" in m["flags"] and m["notes_by"]["protection"].startswith("Pressure mismatch")
    m = trenches.matchup(tw, "AVG", "GOOD")          # average offense vs the bad defense -> real edges
    assert "run_edge" in m["flags"] and "pass_edge" in m["flags"]
    assert trenches.matchup(tw, "AVG", "NOPE") == {"offense": "AVG", "defense": "NOPE", "edges": {}, "notes": [], "notes_by": {}, "flags": []}
    notes = trenches.game_notes(tw, "AVG", "GOOD")
    assert 1 <= len(notes) <= 2


def test_strategy_uses_trench_edges_for_scores_and_failure_modes():
    r = {"position": "QB", "opponent": "BUF", "trench": {"edges": {
        "protection": {"edge": -3.1, "strength": "strong", "offense_rank": 30, "defense_rank": 2},
        "pass": {"edge": 0.3, "strength": "neutral", "offense_rank": 12, "defense_rank": 14}}, "notes_by": {}, "flags": []}}
    assert dfs_strategy._edge(r, "protection") == -2.0      # clipped
    assert dfs_strategy._edge(r, "pass") == 0.0             # neutral edges don't move scores
    assert "pressure mismatch" in dfs_strategy._tough_trenches(r)
    assert dfs_strategy._tough_trenches({**r, "position": "WR"}) is None
    assert dfs_strategy._trench_gaps(None, 2026)[0]["item"].startswith("Line play")
    gaps = dfs_strategy._trench_gaps({"has_ftn": True, "coverage_season": 2025}, 2026)
    assert gaps and "2025" in gaps[0]["why"]


def test_accumulator_splits_early_and_late_downs():
    acc = trenches.TrenchAccumulator()
    acc.add(_play(down="1"))
    acc.add(_play(down="2", success="0", epa="-0.3"))
    acc.add(_play(down="3"))
    acc.add(_play(down="4", success="0", epa="-1.0"))
    acc.add(_play(down=""))                                   # no down (two-point try): counted in neither
    o = acc.result()["off"]["2|BUF"]
    assert (o["ed"], o["ed_succ"], o["ld"], o["ld_succ"]) == (2, 1, 2, 1)


def _profile(ed, ld, d_ed, d_ld):
    return {"off": {"early_down_success": ed, "late_down_success": ld},
            "def": {"early_down_success": d_ed, "late_down_success": d_ld}}


def test_late_down_gap_is_measured_against_the_early_down_pace_and_flags_outliers():
    teams = {f"T{i}": _profile(0.45, 0.36, 0.45, 0.36) for i in range(9)}
    teams["HOT"] = _profile(0.45, 0.50, 0.45, 0.30)            # converts far above its early-down pace, allows few
    trenches.late_downs(teams)
    hot, avg = teams["HOT"]["late_downs"], teams["T0"]["late_downs"]
    assert hot["net"] > 0.15 and hot["flag"] == "hot" and hot["z"] > trenches.LATE_DOWN_FLAG_Z
    assert avg["flag"] is None and avg["net"] < 0
    assert "running hot" in trenches.late_down_note("HOT", teams["HOT"])
    assert trenches.late_down_note("T0", teams["T0"]) is None
    # A team missing a rate gets no gap rather than a made-up one.
    teams["NEW"] = _profile(None, 0.4, 0.45, 0.36)
    trenches.late_downs(teams)
    assert "late_downs" not in teams["NEW"]


def _drive_play(drive, result, **kw):
    base = {"season_type": "REG", "game_id": "2026_02_BUF_MIA", "week": "2", "posteam": "BUF", "defteam": "MIA",
            "play_type": "pass", "fixed_drive": str(drive), "fixed_drive_result": result, "penalty": "0", "desc": ""}
    base.update(kw)
    return base


def test_penalty_drive_accumulator_counts_accepted_defensive_flags_per_drive():
    acc = trenches.PenaltyDriveAccumulator()
    acc.add(_drive_play(1, "Touchdown", play_type="kickoff", penalty="1", penalty_team="MIA", penalty_yards="5"))  # kickoff: ignored
    acc.add(_drive_play(1, "Touchdown", play_type="no_play", penalty="1", penalty_team="MIA", penalty_yards="5",
                        desc="Defensive Offside"))
    acc.add(_drive_play(1, "Touchdown"))
    acc.add(_drive_play(2, "Punt", penalty="1", penalty_team="MIA", penalty_yards="10", desc="holding, declined"))
    acc.add(_drive_play(3, "Punt", penalty="1", penalty_team="BUF", penalty_yards="10"))               # offense's own flag
    acc.add(_drive_play(4, "Field goal", penalty="1", penalty_team="MIA", penalty_yards="15"))
    acc.add(_drive_play(5, "End of half", penalty="1", penalty_team="MIA", penalty_yards="15"))        # not counted
    acc.add(_drive_play(6, "Touchdown", season_type="POST", penalty="1", penalty_team="MIA", penalty_yards="5"))
    assert acc.result() == {"2|BUF": {"drives": 4, "flag_drives": 2, "flag_scored": 2, "snaps": 6, "ol_pen": 0}}


def test_penalty_drive_accumulator_counts_offensive_line_flags_per_snap():
    acc = trenches.PenaltyDriveAccumulator()
    acc.add(_drive_play(1, "Punt", play_type="no_play", penalty="1", penalty_team="BUF", penalty_type="False Start"))
    acc.add(_drive_play(1, "Punt", penalty="1", penalty_team="BUF", penalty_type="Offensive Holding", desc="declined"))
    acc.add(_drive_play(1, "Punt", penalty="1", penalty_team="BUF", penalty_type="Offensive Pass Interference"))
    acc.add(_drive_play(1, "Punt", penalty="1", penalty_team="MIA", penalty_type="Defensive Holding"))
    acc.add(_drive_play(1, "Punt", play_type="punt"))                                                   # not a snap
    c = acc.result()["2|BUF"]
    assert (c["snaps"], c["ol_pen"]) == (4, 2)


def test_penalty_luck_needs_four_recent_games_and_shrinks_to_the_league():
    from scripts import late_down_monitor as mon
    pen = {f"{w}|BUF": {"drives": 10, "flag_drives": 2, "flag_scored": 2} for w in (1, 2, 3, 5)}
    assert mon.penalty_luck(pen, "BUF", 5, 0.6) is None                     # only 3 games before Week 5
    luck = mon.penalty_luck(pen, "BUF", 6, 0.6)                            # 8 of 8 scored, plus 10 drives at 60%
    assert luck == pytest.approx((8 + 6) / 18 - 0.6)
    assert mon.league_flag_score_rate({2025: pen}) == 1.0


def test_toxic_flag_needs_weak_protection_and_above_average_ol_penalties():
    from scripts import late_down_monitor as mon
    teams = {f"T{i}": {"off": {"pressure_rate": 0.15}, "def": {"blitz": 0.25}} for i in range(11)}
    teams["BAD"] = {"off": {"pressure_rate": 0.30}, "def": {"blitz": 0.25}}       # protection far below the rest
    teams["CLEAN"] = {"off": {"pressure_rate": 0.30}, "def": {"blitz": 0.60}}
    pen = {f"1|{t}": {"snaps": 120, "ol_pen": 2} for t in teams}
    pen["1|BAD"]["ol_pen"] = 9                                                     # flagged far more often
    pen["1|CLEAN"]["ol_pen"] = 1
    assert mon.toxic_offenses(teams, pen, {}, 2) == {"BAD"}
    assert mon.blitz_z(teams)["CLEAN"] > mon.TOXIC_Z
