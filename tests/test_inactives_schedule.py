from datetime import datetime, timezone

from app.models import Game
from scripts.inactives_schedule import LEAD_MINUTES, inactive_runs


def _g(away, home, kickoff):
    return Game(game_id=away + home, season=2026, week=4, away=away, home=home, kickoff_utc=kickoff, kickoff_et="", day_part="SUN_EARLY")


def test_one_run_per_distinct_kickoff_after_inactives():
    london = datetime(2026, 10, 4, 13, 30, tzinfo=timezone.utc)      # 9:30 AM ET international game
    early = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
    games = [_g("IND", "WAS", london), _g("NE", "BUF", early), _g("ARI", "NYG", early)]
    runs = inactive_runs(games, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert [r["run_at"] for r in runs] == ["2026-10-04T12:07:00Z", "2026-10-04T15:37:00Z"]
    assert runs[0]["run_at_et"] == "Sun 10/04 08:07 AM ET" and runs[0]["inactives_at_utc"] == "2026-10-04T12:00:00Z"
    assert runs[1]["games"] == ["ARI@NYG", "NE@BUF"]
    assert 60 < LEAD_MINUTES < 90                                    # after inactives (-90), before kickoff


def test_past_runs_are_dropped_unless_asked():
    kick = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
    now = datetime(2026, 10, 4, 16, 0, tzinfo=timezone.utc)
    assert inactive_runs([_g("A", "B", kick)], now=now) == []
    assert len(inactive_runs([_g("A", "B", kick)], now=now, include_past=True)) == 1
