from datetime import datetime

from app.config import ET
from app.models import Game
from app.schedule import classify_day_part, mark_isolated_games


def et(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=ET)


def test_classify_day_part_matches_real_week1_2026_kickoffs():
    # Verified against Sleeper's live schedule feed for 2026 Week 1.
    assert classify_day_part(et(2026, 9, 9, 20, 20)) == "WED_NIGHT"   # NE @ SEA
    assert classify_day_part(et(2026, 9, 10, 20, 35)) == "THU_NIGHT"  # SF @ LAR
    assert classify_day_part(et(2026, 9, 13, 13, 0)) == "SUN_EARLY"
    assert classify_day_part(et(2026, 9, 13, 16, 25)) == "SUN_LATE"
    assert classify_day_part(et(2026, 9, 13, 20, 20)) == "SUN_NIGHT"  # DAL @ NYG
    assert classify_day_part(et(2026, 9, 14, 20, 15)) == "MON_NIGHT"  # DEN @ KC


def _game(game_id, away, home, day_part):
    return Game(
        game_id=game_id,
        season=2026,
        week=1,
        away=away,
        home=home,
        kickoff_utc=datetime(2026, 9, 13, 17, 0, tzinfo=ET),
        kickoff_et="Sun 9/13 1:00 PM ET",
        network="FOX",
        day_part=day_part,
        isolated=False,
    )


def test_isolated_flags_lone_game_per_night_window():
    games = [
        _game("1", "NE", "SEA", "WED_NIGHT"),
        _game("2", "SF", "LAR", "THU_NIGHT"),
        _game("3", "ATL", "PIT", "SUN_EARLY"),
        _game("4", "BAL", "IND", "SUN_EARLY"),
        _game("5", "DAL", "NYG", "SUN_NIGHT"),
        _game("6", "DEN", "KC", "MON_NIGHT"),
    ]
    mark_isolated_games(games)
    isolated_ids = {g.game_id for g in games if g.isolated}
    assert isolated_ids == {"1", "2", "5", "6"}


def test_monday_night_doubleheader_is_not_isolated():
    games = [
        _game("1", "DEN", "KC", "MON_NIGHT"),
        _game("2", "SEA", "SF", "MON_NIGHT"),
    ]
    mark_isolated_games(games)
    assert all(not g.isolated for g in games)


def test_classify_day_part_splits_holiday_international_and_saturday_windows():
    assert classify_day_part(et(2026, 10, 11, 9, 30)) == "SUN_MORNING"   # international (London/Germany)
    assert classify_day_part(et(2026, 11, 26, 12, 30)) == "THU_EARLY"    # Thanksgiving
    assert classify_day_part(et(2026, 11, 26, 16, 30)) == "THU_LATE"
    assert classify_day_part(et(2026, 11, 26, 20, 20)) == "THU_NIGHT"
    assert classify_day_part(et(2026, 11, 27, 15, 0)) == "FRI_LATE"      # Black Friday
    assert classify_day_part(et(2026, 12, 19, 13, 0)) == "SAT_EARLY"


def test_island_games_include_thanksgiving_and_international_but_not_sunday_main():
    games = [
        _game("1", "CHI", "DET", "THU_EARLY"),
        _game("2", "KC", "DAL", "THU_LATE"),
        _game("3", "NYG", "GB", "THU_NIGHT"),
        _game("4", "JAX", "LV", "SUN_MORNING"),
        _game("5", "ATL", "PIT", "SUN_EARLY"),
    ]
    mark_isolated_games(games)
    assert {g.game_id for g in games if g.isolated} == {"1", "2", "3", "4"}
