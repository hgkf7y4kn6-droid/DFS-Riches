import pytest

import app.sleeper_client as sleeper_client

pytestmark = pytest.mark.anyio


async def test_get_projections_parses_list_shaped_response_from_api_sleeper_com(monkeypatch):
    captured = {}

    async def fake_cached_fetch(key, ttl, fetch_fn):
        captured["key"] = key
        return [
            {"player_id": "4881", "stats": {"pts_ppr": 24.09, "pts_std": 20.0}},
            {"player_id": "KC", "stats": {"pts_ppr": 9.36}},
            {"player_id": "999", "stats": {}},  # unprojected depth player
            {"player_id": "1000", "stats": {"pts_half_ppr": 7.5}},
        ]

    monkeypatch.setattr(sleeper_client, "cached_fetch", fake_cached_fetch)
    projections = await sleeper_client.get_projections(2026, 3)

    assert projections == {"4881": 24.09, "KC": 9.36, "1000": 7.5}
    assert captured["key"] == "sleeper_projections_v2_2026_regular_3"
