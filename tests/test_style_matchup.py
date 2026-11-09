from app import style_matchup as sm


def _team(neutral_db, neutral, off_epa, d_db_epa, d_rush_epa, plays=400):
    db, rush = plays * 0.6, plays * 0.4
    return {"off": {"neutral_db": neutral_db, "neutral": neutral, "db": db, "rush": rush,
                    "db_epa": off_epa * db, "rush_epa": off_epa * rush},
            "def": {"db": db, "rush": rush, "db_epa": d_db_epa * db, "rush_epa": d_rush_epa * rush}}


def totals():
    return {
        "PAS": _team(180, 260, 0.20, 0.10, -0.20),   # pass-first, efficient; weak vs the pass
        "RUN": _team(120, 260, 0.15, -0.20, 0.10),   # run-first, efficient; weak vs the run
        "BAD": _team(170, 260, -0.20, 0.25, 0.15),   # pass-first, inefficient; porous
        "GRD": _team(125, 260, -0.15, -0.25, -0.20),  # run-first, inefficient; stout
        "TINY": _team(5, 8, 0.5, 0.5, 0.5, plays=20),  # too few plays to classify
    }


def test_classify_styles():
    c = sm.classify(totals())
    assert "TINY" not in c
    assert c["PAS"]["off_style"] == "pass-first efficient"
    assert c["RUN"]["off_style"] == "run-first efficient"
    assert c["BAD"]["off_style"] == "pass-first inefficient"
    assert c["GRD"]["off_style"] == "run-first inefficient"
    assert c["GRD"]["def_style"].startswith("stout")
    assert c["BAD"]["def_style"].startswith("porous")
    assert c["PAS"]["def_style"].endswith("pass-funnel")
    assert c["RUN"]["def_style"].endswith("run-funnel")


def test_describe_leans_only_when_consistent(monkeypatch):
    monkeypatch.setattr(sm, "_CELLS", {
        "run-first efficient vs porous run-funnel": {"pass_att": -2.1, "rush_att": 1.7, "dk_WR": -3.8, "seasons": 11,
                                                      "pass_att_seasons_same_sign": 10},
        "pass-first efficient vs stout run-funnel": {"pass_att": 1.6, "rush_att": -1.2, "seasons": 11,
                                                      "pass_att_seasons_same_sign": 8}})
    a = sm.describe("NYJ", "MIA", "run-first efficient", "porous run-funnel")
    assert a["lean"] == "run" and a["pass_att"] == -2.1 and "10 of 11 seasons" in a["text"]
    b = sm.describe("BUF", "MIA", "pass-first efficient", "stout run-funnel")
    assert b["lean"] is None            # 8 of 11 seasons is under the 75% bar
    assert sm.describe("X", "Y", "unknown", "cell")["pass_att"] is None


def test_game_both_sides():
    c = sm.classify(totals())
    g = sm.game("PAS", "RUN", c, app_team=str.lower)
    assert [x["offense"] for x in g] == ["pas", "run"]
    assert g[0]["def_style"] == c["RUN"]["def_style"]
    assert sm.game("PAS", "TINY", c) is None


def test_cells_file_loads():
    sm._CELLS = None
    cells = sm.cells()
    assert len(cells) == 16
    assert all("pass_att" in v and "seasons" in v for v in cells.values())
