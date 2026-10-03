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


def _g(season, week, snaps, car=0, tgt=0):
    return {"season": season, "week": week, "snap_pct": snaps, "stats": {"rushing": {"att": car}, "receiving": {"tgt": tgt}}}


def test_recent_usage_prefers_this_season():
    index = {"players": {"bijan robinson|RB": [
        _g(2025, 17, 90.0, 20, 5), _g(2026, 1, 60.0, 10, 2), _g(2026, 2, 70.0, 14, 4), _g(2026, 3, None, 12, 3),
    ]}}
    assert roles.recent_usage(index, 2026, 4, "Bijan Robinson", "RB") == (65.0, 15.0)
    assert roles.recent_usage(index, 2026, 1, "Bijan Robinson", "RB") == (90.0, 25.0)
    assert roles.recent_usage(index, 2026, 4, "Bills", "DST") == (None, None)
