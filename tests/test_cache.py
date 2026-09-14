import asyncio

import pytest

from app import cache

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _clean_cache_state(tmp_path, monkeypatch):
    """Every test gets an empty on-disk cache dir and empty in-memory/
    in-flight state, so tests can't see each other's cached values."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache._memory.clear()
    cache._in_flight.clear()
    yield
    cache._memory.clear()
    cache._in_flight.clear()


async def test_cached_fetch_calls_fetch_fn_once_then_serves_from_memory():
    calls = []

    async def fetch():
        calls.append(1)
        return {"value": 42}

    first = await cache.cached_fetch("k", 60, fetch)
    second = await cache.cached_fetch("k", 60, fetch)

    assert first == second == {"value": 42}
    assert len(calls) == 1  # second call was served from memory, not re-fetched


async def test_cached_fetch_refetches_after_ttl_expires():
    calls = []

    async def fetch():
        calls.append(1)
        return len(calls)

    first = await cache.cached_fetch("k", ttl_seconds=0, fetch_fn=fetch)
    second = await cache.cached_fetch("k", ttl_seconds=0, fetch_fn=fetch)

    assert first == 1
    assert second == 2
    assert len(calls) == 2


async def test_cached_fetch_dedupes_concurrent_calls_for_the_same_key():
    calls = []

    async def fetch():
        calls.append(1)
        await asyncio.sleep(0.02)
        return "value"

    results = await asyncio.gather(*(cache.cached_fetch("k", 60, fetch) for _ in range(10)))

    assert results == ["value"] * 10
    assert len(calls) == 1  # all 10 concurrent callers shared one fetch


async def test_cached_fetch_falls_back_to_stale_disk_cache_on_error():
    async def good_fetch():
        return "fresh"

    await cache.cached_fetch("k", 0, good_fetch)  # populate disk cache
    cache._memory.clear()  # force the next call past the memory layer

    async def failing_fetch():
        raise RuntimeError("upstream is down")

    result = await cache.cached_fetch("k", 0, failing_fetch)
    assert result == "fresh"


async def test_cached_fetch_raises_when_fetch_fails_and_nothing_is_cached():
    async def failing_fetch():
        raise RuntimeError("upstream is down")

    with pytest.raises(RuntimeError):
        await cache.cached_fetch("k", 60, failing_fetch)


async def test_memoize_async_caches_per_argument_combination():
    calls = []

    @cache.memoize_async(60)
    async def compute(x):
        calls.append(x)
        return x * 2

    assert await compute(1) == 2
    assert await compute(1) == 2  # cached, no new call
    assert await compute(2) == 4  # different args, new call

    assert calls == [1, 2]


async def test_memoize_async_dedupes_concurrent_calls_with_the_same_arguments():
    calls = []

    @cache.memoize_async(60)
    async def compute(x):
        calls.append(x)
        await asyncio.sleep(0.02)
        return x * 2

    results = await asyncio.gather(*(compute(5) for _ in range(10)))

    assert results == [10] * 10
    assert calls == [5]
