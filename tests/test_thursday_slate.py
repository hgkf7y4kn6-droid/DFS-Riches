"""Thanksgiving: a Thursday with several games has its own Classic slate, discovered from DraftKings' live listing."""
from datetime import datetime, timezone

import pytest

from app import dk_client, slates
from app.models import Game, WeekSchedule

pytestmark = pytest.mark.anyio
EARLY = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)
LATE = datetime(2026, 11, 26, 21, 30, tzinfo=timezone.utc)
NIGHT = datetime(2026, 11, 27, 1, 20, tzinfo=timezone.utc)
SUN = datetime(2026, 11, 29, 18, 0, tzinfo=timezone.utc)


def _game(i, away, home, kickoff, day_part):
    return Game(game_id=f"g{i}", season=2026, week=12, away=away, home=home, kickoff_utc=kickoff, kickoff_et="", day_part=day_part)


def _schedule(thursday=("THU_EARLY", "THU_LATE", "THU_NIGHT")):
    kicks = {"THU_EARLY": EARLY, "THU_LATE": LATE, "THU_NIGHT": NIGHT}
    games = [_game(i, f"A{i}", f"H{i}", kicks[dp], dp) for i, dp in enumerate(thursday)] + [_game(9, "SUNA", "SUNB", SUN, "SUN_EARLY"),
                                                                                         _game(10, "SUNC", "SUND", SUN, "SUN_EARLY")]
    return WeekSchedule(season=2026, week=12, games=games, isolated_games=[])


def _group(gid, start, end, n_games):
    return {"draftGroupId": gid, "contestType": {"contestTypeId": dk_client.DK_CLASSIC_CONTEST_TYPE_ID}, "sportId": 1,
            "minStartTime": start.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"), "maxStartTime": end.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
            "games": [{}] * n_games}


async def _discover(monkeypatch, groups, sched):
    async def fetch():
        return groups
    monkeypatch.setattr(dk_client, "_fetch_all_nfl_draft_groups", fetch)
    monkeypatch.setattr(dk_client, "_load_overrides", lambda: {})
    return await dk_client.discover_draft_groups(sched)


async def test_the_largest_all_thursday_classic_group_is_the_thanksgiving_slate(monkeypatch):
    groups = [_group(1, EARLY, NIGHT, 3), _group(2, LATE, NIGHT, 2),               # the 3-game slate and its late-afternoon subset
              _group(3, NIGHT, datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc), 2),   # Thu-Fri: runs past the Thursday games
              _group(4, EARLY, SUN, 5)]                                              # the full week
    found = (await _discover(monkeypatch, groups, _schedule()))["classic_thursday"]
    assert found["draft_group_id"] == 1 and found["source"] == "live"
    assert found["label"] == "Classic - Thanksgiving (3 games)"


async def test_a_thursday_with_one_game_has_no_classic_slate(monkeypatch):
    groups = [_group(1, NIGHT, NIGHT, 1)]
    assert (await _discover(monkeypatch, groups, _schedule(thursday=("THU_NIGHT",))))["classic_thursday"] is None


async def test_a_non_thanksgiving_thursday_is_just_thursday():
    assert dk_client.thursday_label(2, thanksgiving=False) == "Classic - Thursday (2 games)"
    assert dk_client.is_thanksgiving(EARLY) and not dk_client.is_thanksgiving(datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc))
    assert not dk_client.is_thanksgiving(datetime(2026, 11, 25, 18, 0, tzinfo=timezone.utc))        # not a Thursday


async def test_the_thanksgiving_slate_is_listed_with_only_its_games_and_the_recorded_id_survives_the_lobby(monkeypatch):
    sched = _schedule()

    async def sched_fn(season, week):
        return sched
    monkeypatch.setattr(slates, "get_week_schedule", sched_fn)

    async def discover(_s):
        return {"classic_sunday": {"draft_group_id": 7, "label": "Main", "source": "live", "first_kickoff": SUN.isoformat(), "last_kickoff": SUN.isoformat()},
                "classic_afternoon": None,
                "classic_thursday": {"draft_group_id": 1, "label": "Classic - Thanksgiving (3 games)", "source": "live",
                                     "first_kickoff": EARLY.isoformat(), "last_kickoff": NIGHT.isoformat()},
                "classic": {"draft_group_id": 3, "label": "Full", "source": "live"}, "showdown": {}}
    monkeypatch.setattr(dk_client, "discover_draft_groups", discover)
    _, listed = await (slates.list_slates.__wrapped__(2026, 12) if hasattr(slates.list_slates, "__wrapped__") else slates.list_slates(2026, 12))
    thu = next(s for s in listed if s.slate_id == "classic_thursday")
    assert thu.slate_type == "classic" and thu.available and thu.draft_group_id == 1
    assert [g.game_id for g in thu.games] == ["g0", "g1", "g2"]                   # not the Sunday games
    assert len(next(s for s in listed if s.slate_id == "classic_sunday").games) == 2
