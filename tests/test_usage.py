from app import usage


def test_profile_uses_this_season_or_a_same_team_carryover():
    profiles = {"players": {
        "vet|WR": {"targets": 8.0, "team": "BUF", "this_season_games": 3, "last_season_by_team": {"BUF": {"targets": 6.0}}},
        "rookie_year_two|RB": {"team": None, "this_season_games": 0,
                               "last_season_by_team": {"MIA": {"carries": 12.0, "games": 4}}},
    }}
    assert usage.profile_for(profiles, "vet|WR", "BUF")["targets"] == 8.0           # this season wins
    carried = usage.profile_for(profiles, "rookie_year_two|RB", "MIA")
    assert carried["carries"] == 12.0 and carried["carryover"] and carried["team"] == "MIA"
    assert usage.profile_for(profiles, "rookie_year_two|RB", "NYJ") is None         # changed teams
    assert usage.profile_for(profiles, "nobody|QB", "NYJ") is None
