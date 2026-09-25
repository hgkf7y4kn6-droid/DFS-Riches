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
