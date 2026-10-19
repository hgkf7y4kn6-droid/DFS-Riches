import asyncio

from app import ownership_slate as osl


def _p(name, team, pos, salary, slot=""):
    return {"key": f"{name}|{team}|{pos}" + (f"|{slot or 'FLEX'}" if slot != "" else ""), "name": name, "team": team,
            "position": pos, "roster_slot": slot, "salary": salary}


MAIN6 = [_p("Keenan Allen", "IND", "WR", 4300), _p("Josh Allen", "BUF", "QB", 7500), _p("Chuba Hubbard", "CAR", "RB", 6300)]
SLATES = [
    (MAIN6, {"season": 2026, "week": 6, "slate_id": "classic_sunday", "label": "Main 6", "slate_type": "classic",
             "games": [("TEN", "IND"), ("BUF", "LV"), ("CAR", "PHI")]}),
    (MAIN6 + [_p("Puka Nacua", "LAR", "WR", 8100)],
     {"season": 2026, "week": 6, "slate_id": "classic", "label": "Full 6", "slate_type": "classic",
      "games": [("TEN", "IND"), ("BUF", "LV"), ("CAR", "PHI"), ("ARI", "LAR"), ("DAL", "GB"), ("NYJ", "NE")]}),
    ([_p("Keenan Allen", "IND", "WR", 4700), _p("Josh Allen", "BUF", "QB", 7800), _p("Chuba Hubbard", "CAR", "RB", 6000)],
     {"season": 2026, "week": 7, "slate_id": "classic_sunday", "label": "Main 7", "slate_type": "classic",
      "games": [("IND", "MIN"), ("BUF", "NYJ"), ("CAR", "TB")]}),
]


def _stub(monkeypatch, points=None):
    async def candidates(season, week, slate_type):
        return [s for s in SLATES if slate_type is None or s[1]["slate_type"] == slate_type]

    async def index(season):
        return points or {}
    monkeypatch.setattr(osl, "_candidates", candidates)
    monkeypatch.setattr(osl.nc, "get_player_trailing_index", index)


def test_a_recording_goes_to_the_week_its_games_and_salaries_match_and_the_slate_it_covers(monkeypatch):
    _stub(monkeypatch)
    rows = [{"name": "K. Allen", "pct": 16.7, "salary": 4300, "points": 16.2, "game": "TEN 26 @ IND 20"},
            {"name": "J. Allen", "pct": 17.2, "salary": 7500, "points": 18.3, "game": "BUF 33 @ LV 30"},
            {"name": "C. Hubbard", "pct": 18.6, "salary": 6300, "points": 22.1, "game": "CAR 25 @ PHI 14"}]
    found = asyncio.run(osl.for_rows(rows, 2026, 7))
    assert (found["week"], found["slate_id"]) == (6, "classic_sunday")      # not week 7, not the full week
    assert found["score"] == {"week_evidence": 1.0, "players": 1.0, "coverage": 0.5}   # 3 of the Main's 6 teams


def test_a_standings_csv_goes_to_the_week_its_fantasy_points_match(monkeypatch):
    from app import nflverse_client as nc
    pts = {nc.player_key("Keenan Allen", "WR"): [[2026, 6, 16.2, "IND"], [2026, 7, 3.0, "IND"]],
           nc.player_key("Josh Allen", "QB"): [[2026, 6, 18.3, "BUF"], [2026, 7, 30.0, "BUF"]],
           nc.player_key("Chuba Hubbard", "RB"): [[2026, 6, 22.1, "CAR"], [2026, 7, 9.0, "CAR"]]}
    _stub(monkeypatch, pts)
    entries = [{"name": n, "pct": 10.0, "slot": "", "fpts": f} for n, f in
               (("Keenan Allen", 16.2), ("Josh Allen", 18.3), ("Chuba Hubbard", 22.1))] * 2
    found = asyncio.run(osl.for_names(entries, 2026, 7))
    assert (found["week"], found["slate_id"]) == (6, "classic_sunday")
    # no points to go on: the week the app is on wins a tie
    found = asyncio.run(osl.for_names([e | {"fpts": None} for e in entries], 2026, 7))
    assert found["week"] == 7


def test_too_few_players_on_any_slate_is_no_match(monkeypatch):
    _stub(monkeypatch)
    assert asyncio.run(osl.for_names([{"name": "Nobody Atall", "pct": 5.0, "slot": ""}], 2026, 7)) is None
