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


def test_team_pair_from_suffix_handles_neutral_site_vs():
    from app.dk_client import _team_pair_from_suffix
    assert _team_pair_from_suffix(" (DET @ CAR)") == ("DET", "CAR")
    assert _team_pair_from_suffix(" (IND vs WAS)") == ("IND", "WAS")   # international game
    assert _team_pair_from_suffix(" (IND vs WAS Snake)") is None


def _sunday_schedule() -> WeekSchedule:
    first = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
    games = [
        Game(game_id=f"s{i}", season=2026, week=4, away=f"A{i}", home=f"H{i}",
             kickoff_utc=first if i < 8 else first + timedelta(hours=3, minutes=25),
             kickoff_et="", day_part="SUN_EARLY" if i < 8 else "SUN_LATE")
        for i in range(12)
    ]
    return WeekSchedule(season=2026, week=4, games=games, isolated_games=[])


def _sunday_group(group_id: int, n_games: int, start: str) -> dict:
    return {"draftGroupId": group_id, "contestType": {"contestTypeId": 21}, "games": [{}] * n_games,
            "minStartTime": start, "maxStartTime": "2026-10-04T20:25:00.0000000Z", "startTimeSuffix": ""}


RECORDED_MAIN = {"2026": {"4": {"classic_sunday": {
    "draft_group_id": 154078, "label": "Classic - Sunday Main (12 games)",
    "first_kickoff": "2026-10-04T17:00:00+00:00", "last_kickoff": "2026-10-04T20:25:00+00:00"}}}}


async def test_recorded_sunday_main_beats_a_later_afternoon_group_after_lock(monkeypatch):
    # After the Main locks, DK's lobby only lists the 4-game Afternoon group.
    groups = [_sunday_group(154081, 4, "2026-10-04T20:05:00.0000000Z")]

    async def fake_fetch():
        return groups

    monkeypatch.setattr(dk_client, "_fetch_all_nfl_draft_groups", fake_fetch)
    monkeypatch.setattr(dk_client, "_load_overrides", lambda: RECORDED_MAIN)
    result = await dk_client.discover_draft_groups(_sunday_schedule())

    assert result["classic_sunday"]["draft_group_id"] == 154078
    assert result["classic_sunday"]["source"] == "override"


async def test_live_sunday_main_starting_at_the_same_kickoff_still_wins(monkeypatch):
    groups = [_sunday_group(160000, 12, "2026-10-04T17:00:00.0000000Z")]

    async def fake_fetch():
        return groups

    monkeypatch.setattr(dk_client, "_fetch_all_nfl_draft_groups", fake_fetch)
    monkeypatch.setattr(dk_client, "_load_overrides", lambda: RECORDED_MAIN)
    result = await dk_client.discover_draft_groups(_sunday_schedule())

    assert result["classic_sunday"]["draft_group_id"] == 160000
    assert result["classic_sunday"]["source"] == "live"


def test_every_recorded_2026_week_has_both_classic_slates():
    # Weeks 1-2 were recovered after the fact; none may lose a Classic slate again.
    import json
    from app.config import DK_OVERRIDES_PATH
    weeks = json.loads(DK_OVERRIDES_PATH.read_text())["2026"]
    for week in ("1", "2", "3", "4"):
        assert weeks[week]["classic_sunday"]["draft_group_id"], week
        assert weeks[week]["classic"]["draft_group_id"], week
        assert weeks[week]["showdown"], week


async def test_afternoon_only_slate_is_the_largest_group_inside_the_late_window(monkeypatch):
    sched = _sunday_schedule()                       # 8 early games, 4 late (4:25 ET)
    late = datetime(2026, 10, 4, 20, 25, tzinfo=timezone.utc)
    early = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)

    def grp(gid, n, start, end):
        g = _group(gid, 21, n)
        g["minStartTime"], g["maxStartTime"] = (t.strftime("%Y-%m-%dT%H:%M:%S.0000000Z") for t in (start, end))
        return g
    groups = [grp(1, 12, early, late), grp(2, 4, late, late), grp(3, 2, late, late)]

    async def fake_fetch():
        return groups
    monkeypatch.setattr(dk_client, "_fetch_all_nfl_draft_groups", fake_fetch)
    monkeypatch.setattr(dk_client, "_load_overrides", lambda: {})
    result = await dk_client.discover_draft_groups(sched)
    assert result["classic_sunday"]["draft_group_id"] == 1
    assert result["classic_afternoon"]["draft_group_id"] == 2
    assert result["classic_afternoon"]["label"] == "Classic - Sunday Afternoon Only (4 games)"

    # no separate afternoon slate when every Sunday game is in the late window
    for g in sched.games:
        g.day_part, g.kickoff_utc = "SUN_LATE", late
    result = await dk_client.discover_draft_groups(sched)
    assert result["classic_afternoon"] is None
