import pytest

from app import vacated
from app.models import Player


def _p(name, pos, injury="Healthy", proj=10.0, sid=None, slot="", chance=None):
    p = Player(name=name, team="SF", opponent="ATL", position=pos, roster_slot=slot, salary=5000, proj_points=proj,
               value_per_1k=2.0, game_info="ATL @ SF", injury=injury, sleeper_player_id=sid or name, ceiling=proj * 2)
    p.play_chance = chance
    return p


WR_LINE = {"rec_tgt": 8.0, "rec": 5.0, "rec_yd": 70.0, "rec_td": 0.5}       # 15 DK points
LINES = {"Evans": WR_LINE, "Cooks": {"rec_tgt": 4.0, "rec": 2.5, "rec_yd": 30.0, "rec_td": 0.2},
         "Kittle": {"rec_tgt": 6.0, "rec": 4.5, "rec_yd": 50.0, "rec_td": 0.4},
         "Watkins": {"rec_tgt": 1.5, "rec": 1.0, "rec_yd": 12.0},
         "CMC": {"rush_att": 18.0, "rush_yd": 80.0, "rush_td": 0.7, "rec_tgt": 5.0, "rec": 4.0, "rec_yd": 30.0, "rec_td": 0.2},
         "Black": {"rush_att": 4.0, "rush_yd": 16.0, "rec_tgt": 0.5}}


def test_wr_out_still_projected_feeds_receivers():
    evans, cooks, kittle, watkins = _p("Evans", "WR", "OUT", 0.0), _p("Cooks", "WR"), _p("Kittle", "TE"), _p("Watkins", "WR")
    vacated.redistribute([evans, cooks, kittle, watkins], LINES)
    cooks_pt = (2.5 + 3.0 + 1.2) / 4.0
    assert cooks.vacated_adj == pytest.approx(0.20 * 8.0 * cooks_pt, abs=0.01)          # top remaining WR by targets
    assert watkins.vacated_adj == pytest.approx(0.20 * 8.0 * (1.0 + 1.2) / 1.5, abs=0.01)
    assert kittle.vacated_adj == pytest.approx(0.036 * 8.0 * (4.5 + 5.0 + 2.4) / 6.0, abs=0.01)
    assert cooks.proj_points == pytest.approx(10.0 + cooks.vacated_adj, abs=0.01)
    assert cooks.ceiling == pytest.approx(20.0 * cooks.proj_points / 10.0, abs=0.1)
    assert "Evans (out), still in Sleeper's projections" in cooks.proj_notes[-1]


def test_nothing_once_sleeper_zeroed_him():
    cooks = _p("Cooks", "WR")
    vacated.redistribute([_p("Evans", "WR", "OUT", 0.0), cooks], {**LINES, "Evans": {}})
    assert cooks.vacated_adj is None and cooks.proj_points == 10.0


def test_questionable_counts_by_chance_of_sitting_and_captain_rows():
    cpt, flex = _p("Cooks", "WR", slot="CPT", proj=15.0), _p("Cooks", "WR", slot="FLEX")
    vacated.redistribute([_p("Evans", "WR", "Q", 9.0, chance=0.75), cpt, flex], LINES)
    full = 0.20 * 8.0 * (2.5 + 3.0 + 1.2) / 4.0
    assert flex.vacated_adj == pytest.approx(0.25 * full, abs=0.01)
    assert cpt.proj_points == pytest.approx(15.0 + 1.5 * 0.25 * full, abs=0.01)


def test_rb_out_carries_go_to_the_next_back():
    black = _p("Black", "RB", proj=4.0)
    vacated.redistribute([_p("CMC", "RB", "D", 0.0), black], LINES)
    # his own 0.4 points a carry; the position's 1.55 a target (he's projected too few to use his own)
    assert black.vacated_adj == pytest.approx(0.42 * 18.0 * 0.4 + 0.36 * 5.0 * 1.55, abs=0.02)
