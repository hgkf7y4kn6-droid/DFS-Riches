import asyncio

from fastapi.testclient import TestClient

from app import cache, main, metrics


def test_cache_keys_group_into_families():
    assert metrics.family("dk_draftables_155197") == "dk_draftables"
    assert metrics.family("sleeper_projections_v2_2026_regular_7") == "sleeper_projections_v2_2026_regular"
    assert metrics.family("weather_nws_41.86,-87.62") == "weather_nws"
    assert metrics.family("nflverse_team_context_trailing_index_v3_2026") == "nflverse_team_context_trailing_index_v3"


def test_cached_fetch_counts_fetches_then_hits(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(metrics, "_cache", type(metrics._cache)(metrics._cache.default_factory))

    async def fetch():
        return {"x": 1}

    async def run():
        for _ in range(3):
            await cache.cached_fetch("audit_probe_2026", 60, fetch)
    asyncio.run(run())
    c = metrics.snapshot()["cache"]["audit_probe"]
    assert (c["fetch"], c["memory"], c["hit_rate"]) == (1, 2, 0.667)


def test_requests_are_timed_by_route_template_and_metrics_need_a_master(monkeypatch):
    monkeypatch.setattr(metrics, "_requests", type(metrics._requests)(metrics._requests.default_factory))
    client = TestClient(main.app)
    assert client.get("/api/metrics").status_code in (401, 403)
    r = metrics.snapshot()["requests"]["GET /api/metrics"]
    assert r["count"] == 1 and r["p50"] is not None

    async def master(authorization):
        return "user_master"
    monkeypatch.setattr(main, "_require_master", master)
    body = client.get("/api/metrics").json()
    assert {"cache", "memo", "requests", "cache_hit_rate", "uptime_seconds"} <= set(body)
    assert "metrics:" in metrics.summary_line()
