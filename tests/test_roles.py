from app import roles


def _p(name, team, pos, proj, snaps=None, injury="Healthy", opps=10.0):
    return {"name": name, "team": team, "position": pos, "proj": proj, "snap_pct": snaps, "injury": injury, "opps": opps}


def test_committee_back_is_rotation_and_deep_backup_is_not():
    r = roles.assign([
        _p("Lead", "LAC", "RB", 10.4, 54), _p("Change", "LAC", "RB", 5.8, 31), _p("Third", "LAC", "RB", 1.6, 17),
    ])
    assert r[("Lead", "LAC", "RB")] == "starter"
    assert r[("Change", "LAC", "RB")] == "rotation"      # 5.8 >= 55% of 10.4
    assert r[("Third", "LAC", "RB")] == "backup"


def test_snap_share_alone_makes_a_rotation_player():
    r = roles.assign([_p("Lead", "SF", "RB", 19.8, 63), _p("Spell", "SF", "RB", 5.0, 38)])
    assert r[("Spell", "SF", "RB")] == "rotation"         # 38% snaps >= 35% bar


def test_blocking_fullback_with_snaps_but_no_touches_is_a_backup():
    r = roles.assign([_p("Lead", "NYG", "RB", 15.0, 66), _p("Fullback", "NYG", "RB", 1.5, 54, opps=1.0)])
    assert r[("Fullback", "NYG", "RB")] == "backup"


def test_injured_starter_hands_the_role_to_the_next_back():
    r = roles.assign([_p("Star", "NYJ", "RB", 0.0, 57, injury="OUT"), _p("Next", "NYJ", "RB", 12.8, 41)])
    assert r[("Star", "NYJ", "RB")] == "out"
    assert r[("Next", "NYJ", "RB")] == "starter"


def test_three_starting_receivers_qb_backups_and_dst():
    wrs = [_p(f"W{i}", "CIN", "WR", 20 - i * 3, 90 - i * 12) for i in range(5)]   # W3 54%, W4 42% snaps
    r = roles.assign(wrs + [_p("QB1", "CIN", "QB", 20, 100), _p("QB2", "CIN", "QB", 15, 0), _p("Bengals", "CIN", "DST", 6)])
    assert [r[(f"W{i}", "CIN", "WR")] for i in range(5)] == ["starter", "starter", "starter", "rotation", "backup"]
    assert r[("QB2", "CIN", "QB")] == "backup"             # no QB committees
    assert r[("Bengals", "CIN", "DST")] == "starter"


def _g(season, week, snaps, car=0, tgt=0, team="ATL"):
    return {"season": season, "week": week, "team": team, "snap_pct": snaps,
            "stats": {"rushing": {"att": car}, "receiving": {"tgt": tgt}}}


def test_recent_usage_prefers_this_season():
    index = {"players": {"bijan robinson|RB": [
        _g(2025, 17, 90.0, 20, 5), _g(2026, 1, 60.0, 10, 2), _g(2026, 2, 70.0, 14, 4), _g(2026, 3, None, 12, 3),
    ]}}
    # weighted 2:3 over the two snap readings, 1:2:3 over the three games' usage
    assert roles.recent_usage(index, 2026, 4, "Bijan Robinson", "RB") == (66.0, 15.5)
    # Week 1: last season carries over for his current team only
    assert roles.recent_usage(index, 2026, 1, "Bijan Robinson", "RB", "ATL") == (90.0, 25.0)
    assert roles.recent_usage(index, 2026, 1, "Bijan Robinson", "RB", "NYJ") == (None, None)
    assert roles.recent_usage(index, 2026, 4, "Bills", "DST") == (None, None)


def _ari():
    """Arizona's backfield: Love 43/40% then 64% (21 carries + 5 targets), Allgeier 59/64% then 36%."""
    return {"players": {
        "jeremiyah love|RB": [_g(2026, 1, 43.0, 11, 4), _g(2026, 2, 40.0, 9, 3), _g(2026, 3, 64.0, 21, 5)],
        "tyler allgeier|RB": [_g(2026, 1, 59.0, 17, 2), _g(2026, 2, 64.0, 5, 2), _g(2026, 3, 36.0, 2, 4)],
        "steady eddie|RB": [_g(2026, 1, 60.0, 15, 3), _g(2026, 2, 62.0, 16, 3), _g(2026, 3, 61.0, 15, 4)],
    }}


def test_usage_trend_flags_a_shifting_backfield():
    idx = _ari()
    up = roles.usage_trend(idx, 2026, 4, "Jeremiyah Love", "RB")
    down = roles.usage_trend(idx, 2026, 4, "Tyler Allgeier", "RB")
    assert up["direction"] == "up" and "64% of snaps in Week 3 vs 42% in Weeks 1-2" in up["text"]
    assert down["direction"] == "down" and "36% of snaps in Week 3" in down["text"]
    assert roles.usage_trend(idx, 2026, 4, "Steady Eddie", "RB") is None
    trends = roles.link_shifts({("Jeremiyah Love", "ARI", "RB"): up, ("Tyler Allgeier", "ARI", "RB"): down})
    assert trends[("Jeremiyah Love", "ARI", "RB")]["text"].endswith("taking work from Tyler Allgeier.")
    assert trends[("Tyler Allgeier", "ARI", "RB")]["text"].endswith("losing work to Jeremiyah Love.")


def test_lone_receiver_swing_is_dropped_unless_large():
    small = {"direction": "up", "text": "Role growing: x.", "snap_delta": 13.0}
    big = {"direction": "down", "text": "Role shrinking: y.", "snap_delta": -31.0}
    kept = roles.link_shifts({("A", "SF", "WR"): small, ("B", "DET", "WR"): big, ("C", "PHI", "RB"): small})
    assert set(kept) == {("B", "DET", "WR"), ("C", "PHI", "RB")}


def test_usage_trend_needs_two_games_this_season_and_skips_qbs():
    idx = _ari()
    assert roles.usage_trend(idx, 2026, 2, "Jeremiyah Love", "RB") is None
    assert roles.usage_trend(idx, 2026, 4, "Jeremiyah Love", "QB") is None


def test_genuine_shifts_need_a_new_level_and_more_than_one_game():
    idx = {"players": {
        "jeremiyah love|RB": [_g(2026, 1, 43.0, 11, 4), _g(2026, 2, 40.0, 9, 3), _g(2026, 3, 64.0, 21, 5)],
        "tyler allgeier|RB": [_g(2026, 1, 59.0, 17, 2), _g(2026, 2, 64.0, 5, 2), _g(2026, 3, 36.0, 2, 4)],
        # back from a one-game dip (injured early in Week 2): not a new role
        "saquon barkley|RB": [_g(2026, 1, 71.0, 15, 2), _g(2026, 2, 16.0, 5, 1), _g(2026, 3, 72.0, 15, 2)],
        "lone spike|WR": [_g(2026, 1, 40.0, 0, 4), _g(2026, 2, 41.0, 0, 4), _g(2026, 3, 56.0, 0, 4)],
    }}
    t = {(n, "ARI", "RB"): roles.usage_trend(idx, 2026, 4, n, "RB") for n in ("Jeremiyah Love", "Tyler Allgeier")}
    t[("Saquon Barkley", "PHI", "RB")] = roles.usage_trend(idx, 2026, 4, "Saquon Barkley", "RB")
    t[("Lone Spike", "XYZ", "WR")] = roles.usage_trend(idx, 2026, 4, "Lone Spike", "WR")
    kept = roles.link_shifts(t)
    assert kept[("Jeremiyah Love", "ARI", "RB")]["genuine"] and kept[("Tyler Allgeier", "ARI", "RB")]["genuine"]
    assert not kept[("Saquon Barkley", "PHI", "RB")]["genuine"]     # 72% after 71% / 16%: no new high
    assert ("Lone Spike", "XYZ", "WR") not in kept                   # one-game WR swing under 20 points, no partner
    assert [g["snap_pct"] for g in kept[("Jeremiyah Love", "ARI", "RB")]["series"]] == [43.0, 40.0, 64.0]
