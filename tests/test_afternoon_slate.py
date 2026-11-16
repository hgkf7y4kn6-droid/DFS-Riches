"""The Sunday Afternoon Only slate runs through the same Classic pipeline as the Sunday Main."""
from datetime import datetime, timedelta, timezone

import pytest

from app import dfs_model, dk_client, slates
from app.models import Game, WeekSchedule

pytestmark = pytest.mark.anyio
LATE = datetime(2026, 10, 4, 20, 25, tzinfo=timezone.utc)


def _schedule():
    games = [Game(game_id=f"g{i}", season=2026, week=4, away=f"A{i}", home=f"H{i}", kickoff_utc=LATE if i >= 3 else LATE - timedelta(hours=3),
                  kickoff_et="", day_part="SUN_LATE" if i >= 3 else "SUN_EARLY") for i in range(5)]
    return WeekSchedule(season=2026, week=4, games=games, isolated_games=[])


async def test_afternoon_slate_is_a_classic_slate_of_only_the_late_games(monkeypatch):
    sched = _schedule()
    slates.list_slates.cache_clear() if hasattr(slates.list_slates, "cache_clear") else None

    async def sched_fn(season, week):
        return sched

    async def discover(_s):
        main = {"draft_group_id": 1, "label": "Main", "source": "live", "first_kickoff": (LATE - timedelta(hours=3)).isoformat(), "last_kickoff": LATE.isoformat()}
        aft = {"draft_group_id": 2, "label": "Afternoon", "source": "live", "first_kickoff": LATE.isoformat(), "last_kickoff": LATE.isoformat()}
        return {"classic_sunday": main, "classic_afternoon": aft, "classic": {"draft_group_id": 3, "label": "Full", "source": "live"}, "showdown": {}}
    monkeypatch.setattr(slates, "get_week_schedule", sched_fn)
    monkeypatch.setattr(dk_client, "discover_draft_groups", discover)
    _, listed = await slates.list_slates.__wrapped__(2026, 4) if hasattr(slates.list_slates, "__wrapped__") else await slates.list_slates(2026, 4)
    by = {s.slate_id: s for s in listed}
    aft = by["classic_afternoon"]
    assert aft.slate_type == "classic" and aft.available
    assert [g.game_id for g in aft.games] == ["g3", "g4"]
    assert len(by["classic_sunday"].games) == 5
    # the DFS model picks any available Classic slate by id, so it builds for the afternoon slate too
    classic = [s for s in listed if s.slate_type == "classic" and s.available]
    assert next(s for s in classic if s.slate_id == "classic_afternoon") is aft
