import asyncio

from app import nflverse_client as nc
from app import player_games as pg

PLAYER_ROWS = [
    {"player_display_name": "Kenny Gainwell", "position": "RB", "week": "1", "team": "TB", "opponent_team": "LA",
     "carries": "12", "rushing_yards": "60", "rushing_tds": "1", "targets": "4", "receptions": "3",
     "receiving_yards": "20", "receiving_tds": "0", "target_share": "0.12"},
    {"player_display_name": "Kenny Gainwell", "position": "RB", "week": "2", "team": "TB", "opponent_team": "NO",
     "carries": "8", "rushing_yards": "30", "rushing_tds": "0", "targets": "0", "receptions": "0"},
    {"player_display_name": "Wide Out", "position": "WR", "week": "1", "team": "LA", "opponent_team": "TB",
     "targets": "9", "receptions": "6", "receiving_yards": "101", "receiving_tds": "1", "carries": "0",
     "target_share": "0.3"},
    {"player_display_name": "Gun Slinger", "position": "QB", "week": "1", "team": "LA", "opponent_team": "TB",
     "completions": "22", "attempts": "33", "passing_yards": "310", "passing_tds": "2", "passing_interceptions": "1",
     "sacks_suffered": "2", "carries": "4", "rushing_yards": "11"},
]
SNAP_ROWS = [
    {"week": "1", "team": "TB", "player": "Kenneth Gainwell", "offense_pct": "0.55", "offense_snaps": "33"},
    {"week": "1", "team": "LA", "player": "Wide Out", "offense_pct": "0.9", "offense_snaps": "60"},
    {"week": "1", "team": "LA", "player": "Gun Slinger", "offense_pct": "1", "offense_snaps": "66"},
]
TEAM_ROWS = [{"team": "TB", "week": "1", "opponent_team": "LA", "def_sacks": "3", "def_interceptions": "1",
              "fumble_recovery_opp": "1", "def_tds": "1"}]


def _patch(monkeypatch):
    async def player_rows(season):
        return PLAYER_ROWS if season == 2026 else []

    async def snap_rows(season):
        return SNAP_ROWS if season == 2026 else []

    async def team_rows(season):
        return TEAM_ROWS if season == 2026 else []

    async def allowed(season):
        return {(1, "TB"): 17.0}

    async def no_cache(key, ttl, fetch):
        return await fetch()

    monkeypatch.setattr(nc, "_fetch_player_week_rows", player_rows)
    monkeypatch.setattr(pg, "_snap_rows", snap_rows)
    monkeypatch.setattr(nc, "_fetch_team_week_rows", team_rows)
    monkeypatch.setattr(nc, "_points_allowed_by_week_team", allowed)
    monkeypatch.setattr(pg, "cached_fetch", no_cache)


def test_stat_lines_only_include_the_positions_groups():
    qb = pg.stat_line(PLAYER_ROWS[3], "QB")
    assert set(qb) == {"passing", "rushing"}
    assert qb["passing"] == {"cmp": 22, "att": 33, "yds": 310, "td": 2, "int": 1, "sacks": 2}
    wr = pg.stat_line(PLAYER_ROWS[2], "WR")
    assert set(wr) == {"receiving"}                      # no carries -> no rushing line
    assert wr["receiving"]["target_share"] == 0.3
    assert set(pg.stat_line(PLAYER_ROWS[0], "RB")) == {"rushing", "receiving"}
    assert set(pg.stat_line(PLAYER_ROWS[2], "TE")) == {"receiving"}


def test_player_games_newest_first_with_snaps_and_dk_points(monkeypatch):
    _patch(monkeypatch)
    res = asyncio.run(pg.player_games(2026, 3, name="Kenny Gainwell", position="RB", team="TB"))
    assert [g["week"] for g in res["games"]] == [2, 1]
    wk1 = res["games"][1]
    assert wk1["snap_pct"] == 55.0 and wk1["offense_snaps"] == 33      # nickname fallback join
    assert wk1["dk_points"] == 6.0 + 6 + 3 + 2.0                       # 60 rush yds, TD, 3 rec, 20 rec yds
    assert res["games"][0]["snap_pct"] is None                         # no snap row for week 2
    assert res["summary"]["games"] == 2 and res["summary"]["avg_snap_pct"] == 55.0


def test_games_before_the_requested_week_only(monkeypatch):
    _patch(monkeypatch)
    res = asyncio.run(pg.player_games(2026, 2, name="Kenny Gainwell", position="RB", team="TB"))
    assert [g["week"] for g in res["games"]] == [1]


def test_dst_game_log(monkeypatch):
    _patch(monkeypatch)
    res = asyncio.run(pg.player_games(2026, 2, name="Buccaneers", position="DST", team="TB"))
    g = res["games"][0]
    assert g["stats"]["defense"] == {"sacks": 3.0, "int": 1, "fum_rec": 1, "td": 1, "pts_allowed": 17}
    assert g["dk_points"] == 3 + 2 + 2 + 6 + 1                      # 14-20 allowed -> +1
    assert g["snap_pct"] is None


def test_slim_rows_keep_what_scoring_and_stat_lines_read():
    full = {**PLAYER_ROWS[3], "headshot_url": "https://x", "passing_epa": "1.2", "fg_made_list": ""}
    slim = nc.slim_rows([full], nc.PLAYER_COLUMNS)[0]
    assert "headshot_url" not in slim and "fg_made_list" not in slim
    assert nc.dk_scoring.dk_offense_points(slim) == nc.dk_scoring.dk_offense_points(full)
    assert pg.stat_line(slim, "QB") == pg.stat_line(full, "QB")


def test_snap_rows_keep_offensive_players_only(monkeypatch):
    csv_text = ("week,team,player,position,offense_snaps,offense_pct,defense_snaps\n"
                "1,TB,Kenneth Gainwell,RB,33,0.55,0\n1,TB,Some Linebacker,LB,0,0,60\n")

    async def text(url):
        return csv_text

    async def no_cache(key, ttl, fetch):
        return await fetch()

    monkeypatch.setattr(nc, "_fetch_csv_text", text)
    monkeypatch.setattr(pg, "cached_fetch", no_cache)
    rows = asyncio.run(pg._snap_rows(2026))
    assert rows == [{"week": "1", "team": "TB", "player": "Kenneth Gainwell", "offense_pct": "0.55", "offense_snaps": "33"}]


def test_game_log_carries_over_last_season_only_for_the_same_team():
    idx = {"players": {"wide out|WR": [
        {"season": 2025, "week": 17, "team": "LAR", "dk_points": 20.0, "snap_pct": 90.0, "stats": {}},
        {"season": 2025, "week": 18, "team": "LAR", "dk_points": 10.0, "snap_pct": 85.0, "stats": {}},
    ]}, "dst": {}}
    week1 = pg.recent_games(idx, season=2026, week=1, name="Wide Out", position="WR", team="LAR")
    assert [g["week"] for g in week1] == [18, 17]
    assert pg.recent_games(idx, season=2026, week=1, name="Wide Out", position="WR", team="KC") == []
    idx["players"]["wide out|WR"].append({"season": 2026, "week": 1, "team": "LAR", "dk_points": 5.0, "snap_pct": 80.0, "stats": {}})
    assert [g["season"] for g in pg.recent_games(idx, season=2026, week=2, name="Wide Out", position="WR", team="LAR")] == [2026]
