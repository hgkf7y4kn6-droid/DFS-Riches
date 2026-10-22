import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import main, ownership_store
from app.cache import memoize_async


@pytest.fixture
def client(monkeypatch):
    return TestClient(main.app)


def _state(monkeypatch, state, statuses=("in_progress",)):
    async def fake():
        if isinstance(state, Exception):
            raise state
        return state

    async def games(season, week):
        return [{"status": st} for st in statuses]
    monkeypatch.setattr(main, "get_nfl_state", fake)
    monkeypatch.setattr(main.sleeper_client, "get_week_games", games)
    return main.current_season_week.__wrapped__   # bypass the 30-minute memo


@pytest.mark.parametrize("state,expected", [
    ({"season": "2026", "season_type": "regular", "display_week": 3, "week": 3}, (2026, 3)),
    ({"season": "2026", "season_type": "pre", "display_week": 0, "week": 0}, (2026, 1)),
    ({"season": "2025", "season_type": "post", "display_week": 20, "week": 20}, (2025, 18)),
    ({"season": "2025", "season_type": "off", "week": 0}, (2025, 18)),
])
def test_current_week_follows_sleeper_state(monkeypatch, state, expected):
    fn = _state(monkeypatch, state)
    assert asyncio.run(fn()) == expected


def test_current_week_moves_on_once_every_game_is_complete(monkeypatch):
    # Sleeper keeps display_week on the finished week until midweek.
    state = {"season": "2026", "season_type": "regular", "display_week": 5, "week": 6}
    assert asyncio.run(_state(monkeypatch, state, ("complete", "complete"))()) == (2026, 6)
    assert asyncio.run(_state(monkeypatch, state, ("complete", "pre_game"))()) == (2026, 5)


def test_current_week_falls_back_to_config_when_sleeper_fails(monkeypatch):
    fn = _state(monkeypatch, RuntimeError("down"))
    assert asyncio.run(fn()) == (main.DEFAULT_SEASON, main.DEFAULT_WEEK)


def test_pages_render_requested_week_and_fall_back_on_bad_params(client, monkeypatch):
    async def fixed():
        return 2026, 4
    monkeypatch.setattr(main, "current_season_week", fixed)
    html = client.get("/classic/breakdown?season=2025&week=7").text
    assert 'id="season-input"' in html and 'value="2025"' in html and 'value="7"' in html
    assert 'href="/classic/dfs-model?season=2025&amp;week=7"' in html
    bad = client.get("/classic/dfs-model?season=abc&week=99")
    assert bad.status_code == 200 and 'value="2026"' in bad.text and 'value="4"' in bad.text
    assert 'aria-current="page"' in bad.text


def test_web_app_serves_routes_files_and_shell(client, monkeypatch, tmp_path):
    (tmp_path / "_expo").mkdir()
    (tmp_path / "index.html").write_text("home")
    (tmp_path / "cash.html").write_text("cash")
    (tmp_path / "_expo" / "app.js").write_text("js")
    monkeypatch.setattr(main, "WEB_DIR", tmp_path)
    assert client.get("/").text == "home"
    assert client.get("/cash").text == "cash"
    r = client.get("/_expo/app.js")
    assert r.text == "js" and "immutable" in r.headers["cache-control"]
    assert client.get("/no/such/route").text == "home"            # client-side routes get the app shell
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "font.abc123.ttf").write_text("ttf")
    r = client.get("/assets/font.abc123.ttf")
    assert r.text == "ttf" and "immutable" in r.headers["cache-control"]
    assert client.get("/assets/gone.def456.ttf").status_code == 404  # never the shell under a hashed path
    assert client.get("/_expo/static/js/old.js").status_code == 404
    assert client.get("/cash").headers["cache-control"] == "no-cache"
    assert client.get("/../app/main.py").text == "home"           # never outside the build
    assert client.get("/api/nope").status_code == 404
    assert client.get("/breakdown", follow_redirects=False).headers["location"] == "/classic/breakdown"


def test_root_falls_back_to_classic_without_a_web_build(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WEB_DIR", tmp_path)
    assert client.get("/", follow_redirects=False).headers["location"] == "/classic"


def test_api_rejects_out_of_range_weeks(client, monkeypatch):
    async def master(authorization):
        return "user_master"
    monkeypatch.setattr(main, "_require_master", master)
    assert client.get("/api/week?season=2026&week=0").status_code == 422
    assert client.get("/api/breakdown?season=1800&week=3").status_code == 422
    assert client.post("/api/ownership/source", json={"season": 2026, "week": 3, "slate_id": "../etc",
                                                      "source": "x", "text": "a, 1"}).status_code == 400


def test_versioned_static_assets_are_immutable(client):
    r = client.get(f"/static/common.js?v={main.ASSET_VERSION}")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
    assert "max-age=300" in client.get("/static/common.js").headers["cache-control"]


def test_memoize_is_bounded_and_expires():
    calls = []

    @memoize_async(ttl_seconds=60, max_entries=3)
    async def f(x):
        calls.append(x)
        return x * 2

    async def run():
        for x in (1, 2, 3, 4):
            await f(x)
        await f(4)           # cached
        await f(1)           # evicted (oldest) -> recomputed
    asyncio.run(run())
    assert calls == [1, 2, 3, 4, 1]


def test_ownership_version_changes_only_on_new_information(monkeypatch, tmp_path):
    monkeypatch.setattr(ownership_store, "OWN_DIR", tmp_path)
    monkeypatch.setattr(ownership_store, "LEARNING_PATH", tmp_path / "learning.json")
    players = [{"key": "josh allen", "name": "Josh Allen", "team": "BUF", "position": "QB", "roster_slot": ""}]
    v0 = ownership_store.data_version()
    ownership_store.append_history(2026, 3, "classic_sunday", {"timestamp": "t"}, {}, None)
    assert ownership_store.data_version() == v0          # history snapshots don't invalidate
    ownership_store.add_observations(2026, 3, "classic_sunday", "source", "gpp",
                                     [{"name": "Josh Allen", "pct": 12.0}], players, source="S")
    assert ownership_store.data_version() != v0


def test_slate_ownership_rejects_unknown_slates(client, monkeypatch):
    async def fake_list(season, week):
        return None, []
    monkeypatch.setattr(main.slates, "list_slates", fake_list)
    assert client.get("/api/slates/nope/ownership?season=2026&week=3").status_code == 404


def test_pages_on_the_render_address_move_to_the_site_domain(client):
    r = client.get("/sign-in?x=1", headers={"host": "dfs-riches.onrender.com"}, follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "https://dfsriches.richesdigitalventures.com/sign-in?x=1"
    # The API and health check stay on any host; the site's own domain isn't redirected.
    assert client.get("/healthz", headers={"host": "dfs-riches.onrender.com"}).status_code == 200
    assert client.get("/api/nope", headers={"host": "dfs-riches.onrender.com"}, follow_redirects=False).status_code != 301
    assert client.get("/healthz", headers={"host": "dfsriches.richesdigitalventures.com"}, follow_redirects=False).status_code == 200


def test_best_contests_rejects_unknown_kinds(client):
    resp = client.get("/api/contests/best?exclude=Qualifier,Bogus")
    assert resp.status_code == 400 and "Bogus" in resp.json()["detail"]
    assert client.get("/api/contests/best?fees=1-5,cheap").status_code == 400
    assert client.get("/api/contests/best?weights=rake:11").status_code == 400
    assert client.get("/api/contests/best?weights=luck:3").status_code == 400


def test_actual_ownership_from_a_screen_recording(client, monkeypatch, tmp_path):
    async def master(authorization):
        return "user_master"

    async def players(season, week, slate_id):
        return [{"key": "Keenan Allen|TEN|WR", "name": "Keenan Allen", "team": "TEN", "position": "WR", "roster_slot": "",
                 "salary": 4300, "slate_type": "classic"},
                {"key": "Josh Allen|BUF|QB", "name": "Josh Allen", "team": "BUF", "position": "QB", "roster_slot": "",
                 "salary": 7500, "slate_type": "classic"}]
    read = {"frames": 12, "rows": [{"name": "K. Allen", "pct": 16.73, "salary": 4300, "points": 16.2, "game": "TEN 26 @ IND 20"},
                                   {"name": "T. Nobody", "pct": 2.0, "salary": None, "points": None, "game": None}]}
    monkeypatch.setattr(main, "_require_master", master)
    monkeypatch.setattr(main, "_resolver_players", players)
    monkeypatch.setattr(main.ownership_video, "available", lambda: True)
    monkeypatch.setattr(main.ownership_video, "read_video", lambda path: read)
    monkeypatch.setattr(main.ownership_persist, "save_upload", lambda *a: False)
    monkeypatch.setattr(main.ownership_learning, "relearn", lambda: {"slates_with_actuals": 1})
    monkeypatch.setattr(ownership_store, "OWN_DIR", tmp_path)
    url = "/api/ownership/actual/video?season=2026&week=6&slate_id=classic_sunday&contest=cash"
    r = client.post(url, content=b"fake video bytes", headers={"Content-Type": "video/mp4"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == 1 and body["unmatched"] == ["T. Nobody"] and body["frames"] == 12
    assert body["players"][0] == {"name": "Keenan Allen", "team": "TEN", "position": "WR", "pct": 16.73, "salary": 4300,
                                  "points": 16.2, "salary_mismatch": False}
    obs = ownership_store.load(2026, 6, "classic_sunday")["observations"]
    assert obs[0]["kind"] == "actual" and obs[0]["contest"] == "cash" and obs[0]["fpts"] == 16.2 and obs[0]["salary"] == 4300
    assert client.post(url, content=b"", headers={"Content-Type": "video/mp4"}).status_code == 400
    assert client.post(url.replace("cash", "bogus"), content=b"x").status_code == 400


def test_an_upload_without_a_slate_goes_to_the_slate_its_data_matches(client, monkeypatch, tmp_path):
    async def master(authorization):
        return "user_master"
    roster = [{"key": "Keenan Allen|IND|WR", "name": "Keenan Allen", "team": "IND", "position": "WR", "roster_slot": "",
               "salary": 4300, "slate_type": "classic"}]

    async def detect(entries, season, week):
        assert (season, week) == (2026, 7) and entries[0]["fpts"] == 16.2
        return {"season": 2026, "week": 6, "slate_id": "classic_sunday", "label": "Main", "slate_type": "classic",
                "score": {"week_evidence": 1.0, "players": 1.0, "coverage": 0.9}}

    async def players_for(season, week, slate_id):
        assert (season, week, slate_id) == (2026, 6, "classic_sunday")
        return roster, {}
    monkeypatch.setattr(main, "_require_master", master)
    monkeypatch.setattr(main.ownership_slate, "for_names", detect)
    monkeypatch.setattr(main.ownership_slate, "players_for", players_for)
    monkeypatch.setattr(main.ownership_persist, "save_upload", lambda *a: False)
    monkeypatch.setattr(main.ownership_learning, "relearn", lambda: {"slates_with_actuals": 1})
    monkeypatch.setattr(ownership_store, "OWN_DIR", tmp_path)
    csv = "Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS\n,,,,,,,Keenan Allen,WR,16.73%,16.2\n"
    r = client.post("/api/ownership/actual", json={"season": 2026, "week": 7, "slate_id": "auto", "contest": "cash", "text": csv})
    assert r.status_code == 200, r.text
    assert r.json()["slate"]["week"] == 6 and r.json()["added"] == 1
    assert ownership_store.load(2026, 6, "classic_sunday")["observations"][0]["pct"] == 16.73


def test_api_needs_a_signed_in_account(client, monkeypatch):
    monkeypatch.setenv("REQUIRE_SIGN_IN", "1")

    async def verify_claims(authorization):
        if authorization != "Bearer good":
            raise main.accounts.AuthError("sign in required")
        return {"sub": "user_1"}
    monkeypatch.setattr(main.accounts, "verify_claims", verify_claims)
    r = client.get("/api/slates/nope/ownership?season=2026&week=3")
    assert r.status_code == 401 and "Sign in" in r.json()["detail"]
    assert client.get("/api/nope", headers={"authorization": "Bearer bad"}).status_code == 401
    assert client.get("/api/nope", headers={"authorization": "Bearer good"}).status_code == 404   # through to routing
    assert client.options("/api/week", headers={"origin": "https://x.example", "access-control-request-method": "GET"}).status_code == 200
    assert client.get("/healthz").status_code == 200                   # pages, health and odds stay open
    assert "/api/odds" in main.OPEN_API_PATHS


def test_classic_pages_load_clerk_when_sign_in_is_required(client, monkeypatch):
    async def week():
        return 2026, 7
    monkeypatch.setattr(main, "current_season_week", week)
    monkeypatch.setenv("REQUIRE_SIGN_IN", "1")
    html = client.get("/classic").text
    assert 'data-require-sign-in="1"' in html and "clerk.browser.js" in html
    assert main.accounts.publishable_key() in html
    monkeypatch.setenv("REQUIRE_SIGN_IN", "0")
    assert "clerk.browser.js" not in client.get("/classic").text


def test_pro_features_need_pro_once_gating_is_on(client, monkeypatch):
    monkeypatch.setenv("REQUIRE_SIGN_IN", "1")
    plans = {"Bearer free": "free", "Bearer pro": "pro"}

    async def verify_claims(authorization):
        return {"sub": "u", "plan": plans[authorization]}

    async def not_master(user_id):
        return False
    monkeypatch.setattr(main.accounts, "verify_claims", verify_claims)
    monkeypatch.setattr(main.accounts, "is_master", not_master)
    url = "/api/slates/nope/ownership?season=2026&week=3"
    monkeypatch.delenv("PRO_GATING", raising=False)                                  # default: optimal lineups and props
    assert client.get(url, headers={"authorization": "Bearer free"}).status_code == 404
    optimal = "/api/slates/nope/optimal?season=2026&week=3"
    assert client.get(optimal, headers={"authorization": "Bearer free"}).status_code == 402
    assert client.post("/api/slates/classic/build", json={"season": 2026, "week": 3},
                       headers={"authorization": "Bearer free"}).status_code == 402      # "Build for me" makes them
    monkeypatch.setenv("PRO_GATING", "1")
    assert client.get(url, headers={"authorization": "Bearer free"}).status_code == 402
    assert client.get(url, headers={"authorization": "Bearer pro"}).status_code == 404


def test_props_are_left_out_of_the_model_for_free_accounts(client, monkeypatch):
    monkeypatch.setenv("REQUIRE_SIGN_IN", "1")
    monkeypatch.delenv("PRO_GATING", raising=False)
    plans = {"Bearer free": "free", "Bearer pro": "pro"}

    async def verify_claims(authorization):
        return {"sub": "u", "plan": plans[authorization]}

    async def not_master(user_id):
        return False

    async def model(*args):
        return json.dumps({"available": True, "table": [{"name": "A", "props": {"rec": {"median": 4.5}}}]}).encode()
    monkeypatch.setattr(main.accounts, "verify_claims", verify_claims)
    monkeypatch.setattr(main.accounts, "is_master", not_master)
    monkeypatch.setattr(main, "_dfs_model", model)
    url = "/api/dfs-model?season=2026&week=3&slate_id=props_test"
    assert "props" not in client.get(url, headers={"authorization": "Bearer free"}).json()["table"][0]
    assert client.get(url, headers={"authorization": "Bearer pro"}).json()["table"][0]["props"]["rec"]["median"] == 4.5


def test_deleting_the_account_removes_its_data(client, monkeypatch):
    deleted = []

    async def verify(authorization):
        return "user_9"

    async def delete_account(user_id):
        deleted.append(user_id)
        return {"deleted_data": True, "deleted_account": True}
    monkeypatch.setattr(main.accounts, "verify", verify)
    monkeypatch.setattr(main.accounts, "delete_account", delete_account)
    assert client.delete("/api/me", headers={"authorization": "Bearer x"}).json()["deleted_account"] is True
    assert deleted == ["user_9"]
