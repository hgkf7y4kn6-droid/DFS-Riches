import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main, news_overrides
from app.models import Game, Player, Slate, SlatePlayers


@pytest.fixture(autouse=True)
def disk_store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(news_overrides, "DISK", tmp_path / "news.json")
    news_overrides._read.clear()


def _p(name, team="KC", injury="Healthy", position="WR"):
    return Player(name=name, team=team, opponent="SEA", position=position, roster_slot="", salary=6000, proj_points=12.0,
                  value_per_1k=2.0, game_info="KC @ SEA", injury=injury)


def _add(name, status, team="KC", note=""):
    return asyncio.run(news_overrides.add(2026, 7, team, name, status, note))


def test_out_only_makes_status_worse_and_playing_only_clears_questionable():
    _add("Rashee Rice", "OUT", note="Andy Reid")
    _add("Travis Kelce", "PLAYING")
    _add("Patrick Mahomes", "PLAYING")
    rows = asyncio.run(news_overrides.entries(2026, 7))
    rice, kelce, mahomes, ir = _p("Rashee Rice", injury="Q"), _p("Travis Kelce", injury="Q", position="TE"), _p("Patrick Mahomes"), _p("X")
    news_overrides.apply([rice, kelce, mahomes, ir], rows)
    assert rice.injury == "OUT" and "Breaking news" in rice.proj_notes[-1] and "Andy Reid" in rice.proj_notes[-1]
    assert kelce.injury == "Healthy"
    assert mahomes.injury == "Healthy" and not mahomes.proj_notes          # nothing to clear
    official_out = _p("Rashee Rice", injury="OUT")
    _add("Rashee Rice", "PLAYING")                                          # never overrides an official Out
    news_overrides.apply([official_out], asyncio.run(news_overrides.entries(2026, 7)))
    assert official_out.injury == "OUT"


def test_newest_entry_wins_and_remove_restores():
    first = _add("Rashee Rice", "Q")
    second = _add("Rashee Rice", "OUT")
    assert news_overrides.latest(asyncio.run(news_overrides.entries(2026, 7)))[("KC", "rashee rice")]["id"] == second["id"]
    v = news_overrides.data_version()
    asyncio.run(news_overrides.remove(2026, 7, second["id"]))
    assert news_overrides.data_version() != v
    rows = asyncio.run(news_overrides.entries(2026, 7))
    assert [e["id"] for e in rows] == [first["id"]]
    assert asyncio.run(news_overrides.entries(2026, 8)) == []


def test_linemen_reach_the_game_model_news():
    _add("Jaylon Moore", "OUT")
    _add("Travis Kelce", "Q")
    news = news_overrides.as_news(asyncio.run(news_overrides.entries(2026, 7)))
    assert news == {("KC", "jaylon moore"): {"code": "OUT", "status": "Out", "updated": news[("KC", "jaylon moore")]["updated"]}}


def test_endpoint_matches_names_and_needs_a_team_off_the_slate(monkeypatch):
    async def master(authorization):
        return "user_master"
    game = Game(game_id="g", season=2026, week=7, away="KC", home="SEA", kickoff_utc="2026-10-26T00:20:00Z",
                kickoff_et="Sun 8:20 PM ET", day_part="SUN_NIGHT")
    slate = Slate(slate_id="classic", label="All", slate_type="classic", games=[game], available=True, source="live")

    async def fake_list(season, week):
        return type("S", (), {"games": [game]})(), [slate]

    async def fake_players(season, week, slate_id):
        return SlatePlayers(slate=slate, players=[_p("Rashee Rice", injury="Q"), _p("Brashard Smith", position="RB")],
                            unmatched_dk_names=[], match_count=2, total_count=2)
    monkeypatch.setattr(main, "_require_master", master)
    monkeypatch.setattr(main.slates, "list_slates", fake_list)
    monkeypatch.setattr(main.slates, "get_slate_players", fake_players)
    monkeypatch.setattr(main, "_news_changed", lambda: None)
    client = TestClient(main.app)
    r = client.post("/api/news-overrides", json={"season": 2026, "week": 7, "name": "rashee rice", "status": "out", "note": "Reid"})
    assert r.status_code == 200 and r.json()["name"] == "Rashee Rice" and r.json()["team"] == "KC" and r.json()["on_slate"]
    assert client.post("/api/news-overrides", json={"season": 2026, "week": 7, "name": "B. Smith", "status": "OUT"}).json()["name"] == "Brashard Smith"
    assert client.post("/api/news-overrides", json={"season": 2026, "week": 7, "name": "Jaylon Moore", "status": "OUT"}).status_code == 400
    lineman = client.post("/api/news-overrides", json={"season": 2026, "week": 7, "name": "Jaylon Moore", "team": "KC", "status": "OUT"}).json()
    assert lineman["on_slate"] is False
    assert client.post("/api/news-overrides", json={"season": 2026, "week": 7, "name": "Rice", "status": "MAYBE"}).status_code == 400
    listed = client.get("/api/news-overrides?season=2026&week=7").json()["entries"]
    assert [e["name"] for e in listed] == ["Jaylon Moore", "Brashard Smith", "Rashee Rice"]
    assert client.delete(f"/api/news-overrides/{lineman['id']}?season=2026&week=7").json() == {"removed": True}


def test_playing_clears_a_stale_ir_tag_but_not_out():
    _add("Jordan Mason", "PLAYING")
    _add("Zach Charbonnet", "PLAYING")
    mason, charbonnet = _p("Jordan Mason", injury="IR", position="RB"), _p("Zach Charbonnet", injury="OUT", position="RB")
    news_overrides.apply([mason, charbonnet], asyncio.run(news_overrides.entries(2026, 7)))
    assert mason.injury == "Healthy" and charbonnet.injury == "OUT"
