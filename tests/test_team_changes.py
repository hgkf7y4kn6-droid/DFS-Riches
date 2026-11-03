from app import team_changes as tc


def _row(week, team, pid="p1", name="Some Player", pos="QB", status="ACT", season=2026):
    return {"season": season, "week": week, "team": team, "player": pid, "name": name, "position": pos, "status": status}


def test_detects_in_season_move_and_first_week_on_new_team():
    rows = [_row(1, "MIN", status="INA"), _row(2, "MIN"), _row(3, "MIN", status="INA"), _row(4, "NYG"), _row(5, "NYG")]
    ev = tc.detect(rows)
    assert len(ev) == 1
    e = ev[0]
    assert (e["from_team"], e["to_team"], e["last_week_old"], e["first_week"]) == ("MIN", "NYG", 3, 4)


def test_ignores_practice_squad_released_and_non_skill_rows():
    rows = [_row(1, "ARI", status="DEV"), _row(2, "HOU", status="ACT"),           # DEV row is dropped, so no change
            _row(1, "ARI", pid="ol", pos="T"), _row(2, "HOU", pid="ol", pos="T")]  # linemen are not tracked
    assert tc.detect(rows) == []


def test_offseason_moves_are_opt_in():
    rows = [_row(18, "DAL", season=2025), _row(1, "PIT", season=2026)]
    assert tc.detect(rows) == []
    ev = tc.detect(rows, include_offseason=True)
    assert len(ev) == 1 and ev[0]["offseason"] and ev[0]["first_week"] == 1


def test_relevant_filter_and_context_rows():
    rows = [_row(5, "ARI", pid="mh", name="Marvin Harrison Jr.", pos="WR"), _row(6, "HOU", pid="mh", name="Marvin Harrison Jr.", pos="WR"),
            _row(5, "ARI", pid="bench", pos="WR"), _row(6, "KC", pid="bench", pos="WR")]
    ev = tc.detect(rows, relevant={"mh"})
    assert [e["name"] for e in ev] == ["Marvin Harrison Jr."]
    rows_out = tc.context_rows(ev, "auto: test")
    assert {(r["team"], r["type"], r["effective_week"]) for r in rows_out} == {("HOU", "trade_in", 6), ("ARI", "trade_out", 6)}


def test_dk_pool_diff_skips_names_on_two_teams():
    pools = {1: [{"name": "J.J. McCarthy", "team": "MIN", "position": "QB"}, {"name": "Josh Allen", "team": "BUF", "position": "QB"},
                 {"name": "Josh Allen", "team": "JAX", "position": "QB"}],
             2: [{"name": "J.J. McCarthy", "team": "NYG", "position": "QB"}, {"name": "Josh Allen", "team": "BUF", "position": "QB"},
                 {"name": "Josh Allen", "team": "JAX", "position": "QB"}]}
    ev = tc.from_pools(pools, 2026)
    assert [(e["name"], e["from_team"], e["to_team"], e["first_week"]) for e in ev] == [("J.J. McCarthy", "MIN", "NYG", 2)]
