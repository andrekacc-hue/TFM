from __future__ import annotations

import json

from shared.redis_client import NullCache, RedisCache, cache_key, create_cache, create_stream_client


class FakeRedis:
    def __init__(self, fail: bool = False):
        self.store: dict[str, str] = {}
        self.fail = fail
        self.calls = 0

    async def get(self, key):
        self.calls += 1
        if self.fail:
            raise ConnectionError("redis caído")
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.calls += 1
        if self.fail:
            raise ConnectionError("redis caído")
        self.store[key] = value

    async def ping(self):
        if self.fail:
            raise ConnectionError("redis caído")
        return True

    async def aclose(self):
        return None


def test_cache_key_is_stable_and_namespaced():
    assert cache_key("emb", "m", "hola") == cache_key("emb", "m", "hola")
    assert cache_key("emb", "m", "hola") != cache_key("emb", "m", "adios")
    assert cache_key("emb", "x").startswith("emb:")


async def test_null_cache():
    cache = NullCache()
    await cache.set_json("k", [1])
    assert await cache.get_json("k") is None
    assert await cache.ping() is False
    await cache.aclose()


async def test_redis_cache_roundtrip():
    fake = FakeRedis()
    cache = RedisCache(fake)
    await cache.set_json("k", {"v": [1, 2]})
    assert json.loads(fake.store["k"]) == {"v": [1, 2]}
    assert await cache.get_json("k") == {"v": [1, 2]}
    assert await cache.get_json("otra") is None
    assert await cache.ping() is True


async def test_redis_failure_degrades_and_trips_breaker():
    fake = FakeRedis(fail=True)
    cache = RedisCache(fake, cooldown=60)
    assert await cache.get_json("k") is None
    calls_after_trip = fake.calls
    # Con el circuito abierto no se vuelve a llamar a Redis
    assert await cache.get_json("k") is None
    await cache.set_json("k", 1)
    assert fake.calls == calls_after_trip
    assert await cache.ping() is False


async def test_set_failure_trips_breaker():
    fake = FakeRedis(fail=True)
    cache = RedisCache(fake, cooldown=60)
    await cache.set_json("k", 1)
    assert fake.calls == 1
    await cache.set_json("k", 1)
    assert fake.calls == 1


def test_create_cache_without_url_returns_null_cache():
    assert isinstance(create_cache(None), NullCache)
    assert isinstance(create_cache("redis://localhost:6399/0"), RedisCache)


def test_stream_client_timeout_exceeds_block():
    client = create_stream_client("redis://localhost:6399/0", block_ms=5000)
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] > 5
    assert kwargs["decode_responses"] is True
