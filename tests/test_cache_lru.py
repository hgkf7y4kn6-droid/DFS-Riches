import asyncio

from app import cache


def test_memory_layer_is_lru_capped_and_memory_false_stays_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "MAX_MEMORY_ENTRIES", 3)
    monkeypatch.setattr(cache, "_memory", {})

    async def run():
        for i in range(5):
            async def fetch(i=i):
                return {"v": i}
            await cache.cached_fetch(f"k{i}", 60, fetch)
        assert list(cache._memory) == ["k2", "k3", "k4"]           # oldest evicted
        assert await cache.cached_fetch("k0", 60, lambda: None) == {"v": 0}   # evicted -> re-read from disk

        async def big():
            return {"rows": [1, 2, 3]}
        assert await cache.cached_fetch("raw", 60, big, memory=False) == {"rows": [1, 2, 3]}
        assert "raw" not in cache._memory
        assert await cache.cached_fetch("raw", 60, big, memory=False) == {"rows": [1, 2, 3]}   # from disk

    asyncio.run(run())
