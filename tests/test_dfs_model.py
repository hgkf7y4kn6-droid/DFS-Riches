import pytest

from app import consensus, dfs_model, lineup_builder, sources
from app.projections import dk_points_from_line

FP_PAGE = """
<table id="data" class="table"><thead>
<tr><td>&nbsp;</td><td colspan="3" style="x"><small><b>RECEIVING</b></small></td><td colspan="3"><b>RUSHING</b></td><td colspan="2"><b>MISC</b></td></tr>
<tr><th class="player-label">Player</th><th>REC</th><th>YDS</th><th>TDS</th><th>ATT</th><th>YDS</th><th>TDS</th><th>FL</th><th>FPTS</th></tr>
</thead><tbody>
<tr class="mpb-player-1 SEAWAS"><td class="player-label"><a href="/x" class="player-name fp-player-link" fp-player-name="Jaxon Smith-Njigba">Jaxon Smith-Njigba</a> SEA</td>
<td>6.7</td><td>99.9</td><td>0.7</td><td>0.4</td><td>2.2</td><td>0.0</td><td>0.1</td><td>21.0</td></tr>
</tbody></table>
"""

CBS_PAGE = """<title>Week 3 Proj Fantasy Football Stats - TE Points - CBS Sports</title>
<thead><tr><th><a href="?sortcol=player&sortdir=a">Player</a></th><th><a href="?sortcol=gp">gp</a></th>
<th><a href="?sortcol=receiving_tgt">tgt</a></th><th><a href="?sortcol=receiving_rec">rec</a></th>
<th><a href="?sortcol=receiving_yds">yds</a></th><th><a href="?sortcol=receiving_yds">yds/g</a></th>
<th><a href="?sortcol=receiving_td">td</a></th><th><a href="?sortcol=misc_fl">fl</a></th><th><a href="?sortcol=misc_fpts">fpts</a></th></tr></thead>
<tbody><tr class="TableBase-bodyTr"><td class="TableBase-bodyTd "><span class="CellPlayerName--long"><span class=""><a href="/p">Trey McBride</a><span class="CellPlayerName-position"> TE </span><span class="CellPlayerName-team"> ARI </span></span></span></td>
<td> 1 </td><td> 10.0 </td><td> 7.5 </td><td> 65.4 </td><td> 65.4 </td><td> 0.6 </td><td> 0.0 </td><td> 17.6 </td></tr></tbody>"""


def test_fantasypros_parser_maps_grouped_columns():
    rows = sources.parse_fantasypros(FP_PAGE, "WR")
    assert rows == [{"name": "Jaxon Smith-Njigba", "team": "SEA", "position": "WR", "stats": {
        "rec": 6.7, "rec_yd": 99.9, "rec_td": 0.7, "rush_att": 0.4, "rush_yd": 2.2, "rush_td": 0.0, "fum_lost": 0.1}}]


def test_cbs_parser_uses_the_total_not_the_per_game_duplicate_and_checks_week():
    rows = sources.parse_cbs(CBS_PAGE, "TE")
    assert rows[0]["name"] == "Trey McBride" and rows[0]["team"] == "ARI"
    assert rows[0]["stats"]["rec_yd"] == 65.4 and rows[0]["stats"]["rec"] == 7.5
    assert sources.cbs_week(CBS_PAGE) == 3


def test_espn_parser_reads_only_the_weeks_projection():
    payload = {"players": [{"player": {"fullName": "Josh Allen", "proTeamId": 2, "defaultPositionId": 1, "stats": [
        {"id": "01401872932", "statSourceId": 0, "stats": {"3": 248.0}},
        {"id": "1120263", "statSourceId": 1, "stats": {"3": 248.68, "4": 1.72, "20": 0.61, "24": 33.65, "25": 0.8, "72": 0.26}},
    ]}}]}
    rows = sources.parse_espn(payload, 2026, 3)
    assert rows[0]["team"] == "BUF" and rows[0]["stats"]["pass_yd"] == 248.68 and rows[0]["stats"]["rush_td"] == 0.8
    assert sources.parse_espn(payload, 2026, 4) == []


def _src(name, team, pos, **stats):
    return {"name": name, "team": team, "position": pos, "stats": stats}


def test_consensus_marks_missing_sources_and_never_fills_them():
    idx = {
        "a": consensus.index_rows([_src("Joe Back", "KC", "RB", rush_yd=80, rush_td=1)]),   # 14
        "b": consensus.index_rows([_src("Joe Back", "KC", "RB", rush_yd=60)]),              # 6
        "c": consensus.index_rows([_src("Someone Else", "KC", "RB", rush_yd=60)]),
    }
    c = consensus.consensus_for(idx, "Joe Back", "KC", "RB", {"a": 1, "b": 1, "c": 1}, "equal")
    assert c.by_source == {"a": 14.0, "b": 6.0, "c": None}
    assert c.missing == ["c"] and c.n == 2
    assert (c.mean, c.median, c.low, c.high, c.sd) == (10.0, 10.0, 6.0, 14.0, 4.0)
    none = consensus.consensus_for(idx, "Nobody", "KC", "RB", {}, "equal")
    assert none.mean is None and none.n == 0


def test_weights_stay_equal_when_sources_are_similar():
    acc = {"relative_mae": {"RB": {"a": {"ratio": 1.0, "games": 500}, "b": {"ratio": 1.03, "games": 500}}}}
    w, note = consensus.position_weights(acc, "RB", ["a", "b", "c"])
    assert w == {"a": 1.0, "b": 1.0, "c": 1.0} and "equal" in note
    acc["relative_mae"]["RB"]["b"]["ratio"] = 1.25
    w, note = consensus.position_weights(acc, "RB", ["a", "b", "c"])
    assert w["a"] > w["c"] > w["b"] and "1/historical MAE" in note


def test_calibration_falls_back_to_nearest_graded_range():
    acc = {"calibration": {"TE": {"8-12": {"q15": 0.3, "q50": 0.9, "q85": 1.7}}}}
    assert dfs_model.calibration(acc, "TE", 21)["q85"] == 1.7
    assert dfs_model.calibration({}, "TE", 10) == dfs_model.DEFAULT_CALIB


def _pool():
    rows = []
    pid = 0

    def add(name, pos, team, opp, salary, ceil):
        nonlocal pid
        pid += 1
        game = "A@B" if team in ("A", "B") else "C@D"
        rows.append({"id": pid, "name": name, "position": pos, "team": team, "opponent": opp, "salary": salary, "game": game, "ceiling": ceil})

    for t, o in (("A", "B"), ("B", "A"), ("C", "D"), ("D", "C")):
        add(f"QB{t}", "QB", t, o, 6000, 25)
        for i in range(3):
            add(f"RB{t}{i}", "RB", t, o, 5000, 18 - i)
            add(f"WR{t}{i}", "WR", t, o, 5000, 20 - i)
        add(f"TE{t}", "TE", t, o, 4000, 12)
        add(f"DST{t}", "DST", t, o, 3000, 10)
    return rows


def test_lineup_builder_enforces_stack_bring_back_and_no_dst_against_own_players():
    pool = _pool()
    lu = lineup_builder.build(pool, [r["ceiling"] for r in pool], stack=(2, 1), stack_game="C@D")
    qb = lu[0]
    assert qb["position"] == "QB" and qb["game"] == "C@D"
    assert sum(1 for p in lu if p["team"] == qb["team"] and p["position"] in ("WR", "TE")) >= 2
    assert any(p["team"] == qb["opponent"] and p["position"] in ("RB", "WR", "TE") for p in lu)
    dst = lu[-1]
    assert not any(p["team"] == dst["opponent"] for p in lu if p["position"] != "DST")
    assert sum(p["salary"] for p in lu) <= 50000


def test_lineup_builder_keeps_lineups_distinct_and_honors_counts():
    pool = _pool()
    first = lineup_builder.build(pool, [r["ceiling"] for r in pool], counts={"RB": 3})
    assert sum(1 for p in first if p["position"] == "RB") == 3
    second = lineup_builder.build(pool, [r["ceiling"] for r in pool], prior=[{p["id"] for p in first}], min_unique=3)
    assert len({p["id"] for p in first} & {p["id"] for p in second}) <= 6


class _P:
    def __init__(self, **kw):
        self.__dict__.update(dict(roster_slot="", ceiling=None, dk_fppg=10.0, injury="Healthy", dk_draftable_id=1), **kw)


def test_player_rows_apply_only_labeled_adjustments():
    idx = {"s1": consensus.index_rows([_src("Out Guy", "A", "WR", rec=5, rec_yd=60), _src("Q Guy", "A", "WR", rec=4, rec_yd=50)]),
           "s2": consensus.index_rows([_src("Q Guy", "A", "WR", rec=6, rec_yd=70)])}
    weights = {pos: ({"s1": 1, "s2": 1}, "equal weight") for pos in dfs_model.POSITIONS}
    players = [
        _P(name="Out Guy", team="A", opponent="B", position="WR", salary=6000, injury="O", game_info="A@B"),
        _P(name="Q Guy", team="A", opponent="B", position="WR", salary=5000, injury="Q", game_info="A@B", dk_draftable_id=2),
    ]
    rows = dfs_model._player_rows(players, idx, {}, weights, {"B|WR": [30.0, 20.0, 3]}, {})
    out, q = rows
    assert out["final"] == 0.0 and out["consensus"] == 11.0 and out["adjustments"][0]["kind"] == "sourced"
    assert q["consensus"] == pytest.approx(11.0) and q["n_sources"] == 2
    model = [a for a in q["adjustments"] if a["kind"] == "model"]
    assert model and q["final"] == pytest.approx(11.0 * model[0]["factor"])
    assert q["floor"] < q["median"] < q["final"] <= q["ceiling"]
    assert "Questionable" in q["uncertainty_reasons"]
    assert dk_points_from_line({"rec": 5, "rec_yd": 60}, "WR") == 11.0
