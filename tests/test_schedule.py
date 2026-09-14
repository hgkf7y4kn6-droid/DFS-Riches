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
