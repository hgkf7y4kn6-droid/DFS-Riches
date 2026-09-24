from datetime import datetime, timedelta, timezone

import pytest

import app.dk_client as dk_client
from app.models import Game, WeekSchedule

pytestmark = pytest.mark.anyio


def _schedule(n_games: int) -> WeekSchedule:
    kickoff = datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc)
    games = [
        Game(
            game_id=f"g{i}",
            season=2026,
            week=3,
            away=f"A{i}",
            home=f"H{i}",
            kickoff_utc=kickoff + timedelta(days=min(i, 3)),
            kickoff_et="",
            day_part="SUN_EARLY",
        )
        for i in range(n_games)
    ]
    return WeekSchedule(season=2026, week=3, games=games, isolated_games=[])


def _group(group_id: int, contest_type_id: int, n_games: int) -> dict:
    return {
        "draftGroupId": group_id,
        "contestType": {"contestTypeId": contest_type_id},
        "games": [{}] * n_games,
        "minStartTime": "2026-09-25T00:15:00.0000000Z",
        "startTimeSuffix": " (Tournament)",
    }


async def test_classic_ignores_same_size_groups_that_are_not_classic_salary_cap(monkeypatch):
    # Real Week 3 listing: several 16-game groups share the window, but only
    # contestTypeId 21 has per-player salaries. A 145 group listed first must not win.
    groups = [_group(146138, 145, 16), _group(153797, 189, 16), _group(153768, 21, 16)]

    async def fake_fetch():
        return groups

    monkeypatch.setattr(dk_client, "_fetch_all_nfl_draft_groups", fake_fetch)
    monkeypatch.setattr(dk_client, "_load_overrides", lambda: {})
    result = await dk_client.discover_draft_groups(_schedule(16))

    assert result["classic"]["draft_group_id"] == 153768
    assert result["classic"]["source"] == "live"
