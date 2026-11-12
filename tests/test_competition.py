from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import competition as comp
from app import main


def test_scoring_matches_the_quarterback_example():
    # Ranked Burrow, Love, Mahomes, Mayfield, Young; the top 5 finished Love, Nix, Mayfield, Purdy, Young.
    burrow, love, mahomes, mayfield, young, nix, purdy = range(1, 8)
    actual = {love: 30, nix: 28, mayfield: 26, purdy: 24, young: 22, burrow: 15, mahomes: 12}
    s = comp.score_position([burrow, love, mahomes, mayfield, young], comp.finish_ranges(actual), 5)
    assert (s["hits"], s["exact"]) == (3, 1)
    # Love and Mayfield each finished one spot higher than ranked (-0.25); Young exactly right (+3).
    assert s["points"] == pytest.approx(3 * comp.HIT_POINTS + comp.EXACT_BONUS - 2 * comp.HIGHER_PENALTY)


def test_finishing_lower_costs_more_than_finishing_higher_and_never_a_whole_hit():
    actual = {i: 100 - i for i in range(1, 16)}
    ranges = comp.finish_ranges(actual)
    lower = comp.score_position([2], ranges, 15)["points"]          # ranked 1st, finished 2nd
    higher = comp.score_position([99, 1], ranges, 15)["rows"][1]["points"]   # ranked 2nd, finished 1st (99 missed)
    assert higher > lower
    worst = comp.score_position([15], ranges, 15)                   # ranked 1st, finished 15th: the biggest deduction
    assert 0 < worst["points"] < comp.HIT_POINTS


def test_ties_share_spots_and_count_as_exact_anywhere_inside_them():
    ranges = comp.finish_ranges({1: 20, 2: 18, 3: 18, 4: 10})
    assert ranges[2] == ranges[3] == (2, 3)
    s = comp.score_position([1, 3, 2], ranges, 3)
    assert s["exact"] == 3 and s["points"] == pytest.approx(3 * (comp.HIT_POINTS + comp.EXACT_BONUS))
    # A tie straddling the cut-off puts both players on the list.
    assert comp.score_position([4], comp.finish_ranges({1: 20, 4: 18, 5: 18}), 2)["hits"] == 1


def test_a_ruled_out_pick_scores_zero_and_costs_nothing_else():
    actual = {1: 30, 2: 28, 3: 26, 9: 0}
    ranges = comp.finish_ranges(actual)
    # Ranked a player who didn't play (9) 1st: the picks below him move up, so 1 and 2 are still exact.
    s = comp.score_position([9, 1, 2], ranges, 3, actual, ruled_out={9})
    assert (s["hits"], s["exact"], s["ruled_out"]) == (2, 2, 1)
    assert s["points"] == pytest.approx(2 * (comp.HIT_POINTS + comp.EXACT_BONUS))
    assert s["rows"][0] == {"id": 9, "ranked": 1, "finished": None, "points": 0.0, "dk": 0, "ruled_out": True}
    assert [r["ranked"] for r in s["rows"]] == [1, 2, 3]                    # the spots as the user ranked them
    # Accuracy leaves his spot out: the same hits with one ruled out score higher accuracy, never lower.
    picks, qbs = {"QB": [9, 1, 2]}, {**actual, 4: 25, 5: 24, 6: 23}        # a full top 5 without him
    actual = qbs
    assert comp.score_entry(picks, {"QB": actual}, {9})["accuracy"] == pytest.approx(round(100 * 2 / (comp.SPOTS - 1), 1))
    assert comp.score_entry(picks, {"QB": actual})["accuracy"] == pytest.approx(round(100 * 2 / comp.SPOTS, 1))


def test_did_not_play_needs_no_box_score_line_and_no_snaps(monkeypatch):
    import asyncio
    from app import nflverse_client as nc, player_games

    async def snaps(season):
        return [{"week": "8", "team": "BUF", "player": "Played Nostats"}, {"week": "7", "team": "BUF", "player": "Sat Out"}]
    monkeypatch.setattr(player_games, "_snap_rows", snaps)

    def mk(i, name, pos="WR"):
        return SimpleNamespace(dk_draftable_id=i, name=name, team="BUF", position=pos)
    players = [mk(1, "Box Score"), mk(2, "Played Nostats"), mk(3, "Sat Out"), mk(4, "Bills", "DST")]
    actuals = {"players": {nc.player_key("Box Score", "WR"): 12.0}}
    assert asyncio.run(comp.did_not_play(2026, 8, players, actuals)) == {3}


def test_perfect_and_standings_rank_equal_scores_together():
    actual = {pos: {pos_i * 100 + i: 50 - i for i in range(n)} for pos_i, (pos, n) in enumerate(comp.SIZES.items())}
    perfect = {pos: sorted(actual[pos], key=lambda pid: -actual[pos][pid]) for pos in comp.SIZES}
    entries = [{"user_id": "a", "name": "Ann", "picks": perfect}, {"user_id": "b", "name": "Bo", "picks": perfect},
               {"user_id": "c", "name": "Cy", "picks": {}}]
    rows = comp.standings(entries, actual, me="b")
    assert rows[0]["points"] == comp.PERFECT and rows[0]["pct_of_perfect"] == 100.0 and rows[0]["accuracy"] == 100.0
    assert rows[2]["accuracy"] == 0.0
    assert [r["rank"] for r in rows] == [1, 1, 3] and rows[1]["me"]


def test_validate_picks_checks_positions_sizes_and_repeats():
    eligible = {1: "QB", 2: "QB", 3: "RB"}
    assert comp.validate_picks({"QB": [2, 1]}, eligible) == {"QB": [2, 1], "RB": [], "WR": [], "TE": [], "DST": []}
    for bad in ({"QB": [3]}, {"QB": [1, 1]}, {"TE": [9]}, {"QB": list(range(6))}):
        with pytest.raises(ValueError):
            comp.validate_picks(bad, eligible)
    assert comp.clean_name("  <b>Rags2Riches</b>!!  ", "x") == "bRags2Richesb"
    assert comp.default_name({"first_name": "Zach", "last_name": "Riches"}) == "Zach R."


@pytest.fixture
def picks_api(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(comp, "LOCAL_DIR", tmp_path)
    plans = {"Bearer pro": ("u-pro", "pro"), "Bearer pro2": ("u-pro2", "pro"), "Bearer free": ("u-free", "free")}

    async def verify(authorization):
        return plans[authorization][0]

    async def verify_claims(authorization):
        return {"sub": plans[authorization][0], "plan": plans[authorization][1]}

    async def not_master(user_id):
        return False

    async def clerk_user(user_id):
        return {"first_name": "Pat", "last_name": "Lee"}
    monkeypatch.setattr(main.accounts, "verify", verify)
    monkeypatch.setattr(main.accounts, "verify_claims", verify_claims)
    monkeypatch.setattr(main.accounts, "is_master", not_master)
    monkeypatch.setattr(main.accounts, "clerk_user", clerk_user)
    players = [SimpleNamespace(dk_draftable_id=i, name=f"QB{i}", team="BUF", opponent="MIA", position="QB",
                               salary=6000, proj_points=20 - i, injury=None) for i in range(1, 8)]
    state = {"kickoff": datetime.now(timezone.utc) + timedelta(hours=2), "actual": None}

    async def main_slate(season, week):
        return SimpleNamespace(label="Sunday Main", games=[SimpleNamespace(kickoff_utc=state["kickoff"])]), players

    async def actual_points(season, week, slate, ps):
        return (state["actual"], state.get("out", set())) if state["actual"] is not None else None
    monkeypatch.setattr(comp, "main_slate", main_slate)
    monkeypatch.setattr(comp, "actual_points", actual_points)
    return TestClient(main.app), state


def test_pro_picks_flow_open_then_locked_then_final(picks_api):
    client, state = picks_api
    url = "/api/pro-picks?season=2026&week=8"
    body = {"season": 2026, "week": 8, "picks": {"QB": [1, 2, 3]}}
    assert client.put("/api/pro-picks", json=body, headers={"authorization": "Bearer free"}).status_code == 402
    free = client.get(url, headers={"authorization": "Bearer free"}).json()
    assert free["pro"] is False and free["status"] == "open"
    assert client.put("/api/pro-picks", json={**body, "picks": {"QB": [1, 1]}}, headers={"authorization": "Bearer pro"}).status_code == 400
    saved = client.put("/api/pro-picks", json=body, headers={"authorization": "Bearer pro"}).json()
    assert saved["mine"]["name"] == "Pat L." and saved["mine"]["picks"]["QB"] == [1, 2, 3]
    client.put("/api/pro-picks", json={**body, "picks": {"QB": [3, 2]}, "name": "Rival"}, headers={"authorization": "Bearer pro2"})
    open_ = client.get(url, headers={"authorization": "Bearer pro"}).json()
    assert open_["status"] == "open" and open_["entrants"] == 2
    assert open_["mine"]["picks"]["QB"] == [1, 2, 3] and len(open_["players"]) == 7

    state["kickoff"] = datetime.now(timezone.utc) - timedelta(minutes=1)          # the Main kicked off
    assert client.put("/api/pro-picks", json=body, headers={"authorization": "Bearer pro"}).status_code == 409
    locked = client.get(url, headers={"authorization": "Bearer pro"}).json()
    assert locked["status"] == "locked" and locked["entrants"] == 2

    state["actual"] = {"QB": {1: 30, 2: 28, 3: 26, 4: 5, 5: 4, 6: 3, 7: 2}, "RB": {}, "WR": {}, "TE": {}, "DST": {}}
    final = client.get(url, headers={"authorization": "Bearer pro"}).json()
    assert final["status"] == "final" and final["entrants"] == 2
    mine = final["my_result"]
    assert mine["rank"] == 1 and mine["points"] == pytest.approx(3 * (comp.HIT_POINTS + comp.EXACT_BONUS))
    assert mine["accuracy"] == pytest.approx(round(100 * 3 / comp.SPOTS, 1))
    rival = client.get(url, headers={"authorization": "Bearer pro2"}).json()["my_result"]
    assert rival["rank"] == 2
    # Nobody else's name, picks or place ever leaves the server.
    for body in (open_, locked, final):
        assert "Rival" not in str(body) and "standings" not in body and "entrant_names" not in body
    assert "Pat L." not in str(client.get(url, headers={"authorization": "Bearer pro2"}).json())
    assert [r["id"] for r in final["actual_top"]["QB"]] == [1, 2, 3, 4, 5]
    # Side by side: each pick with his actual DK points, next to who actually finished in that spot.
    assert [(r["ranked"], r["dk"]) for r in mine["positions"]["QB"]["rows"]] == [(1, 30), (2, 28), (3, 26)]
    assert [(r["spot"], r["points"]) for r in final["actual_top"]["QB"][:3]] == [(1, 30), (2, 28), (3, 26)]
