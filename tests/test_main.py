import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main, ownership_store
from app.cache import memoize_async


@pytest.fixture
def client(monkeypatch):
    return TestClient(main.app)


def _state(monkeypatch, state):
    async def fake():
        if isinstance(state, Exception):
            raise state
        return state
    monkeypatch.setattr(main, "get_nfl_state", fake)
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


def test_current_week_falls_back_to_config_when_sleeper_fails(monkeypatch):
    fn = _state(monkeypatch, RuntimeError("down"))
    assert asyncio.run(fn()) == (main.DEFAULT_SEASON, main.DEFAULT_WEEK)


def test_pages_render_requested_week_and_fall_back_on_bad_params(client, monkeypatch):
    async def fixed():
        return 2026, 4
    monkeypatch.setattr(main, "current_season_week", fixed)
    html = client.get("/breakdown?season=2025&week=7").text
    assert 'id="season-input"' in html and 'value="2025"' in html and 'value="7"' in html
    assert 'href="/dfs-model?season=2025&amp;week=7"' in html
    bad = client.get("/dfs-model?season=abc&week=99")
    assert bad.status_code == 200 and 'value="2026"' in bad.text and 'value="4"' in bad.text
    assert 'aria-current="page"' in bad.text


def test_api_rejects_out_of_range_weeks(client):
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
