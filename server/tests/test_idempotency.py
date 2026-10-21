from app.idempotency import IdempotencyCache


def test_retry_with_identical_payload_replays_outcome() -> None:
    cache = IdempotencyCache()
    payload = {"window_id": 3, "choice": "pung", "tiles": [1, 2]}
    assert cache.check("c-1", payload) == (False, True, None)
    cache.record("c-1", payload, ok=False, error="illegal")
    assert cache.check("c-1", dict(payload)) == (True, False, "illegal")


def test_same_id_different_payload_conflicts() -> None:
    cache = IdempotencyCache()
    cache.record("c-1", {"tile_id": 1}, ok=True)
    assert cache.check("c-1", {"tile_id": 2}) == (True, False, "id_conflict")


def test_key_order_does_not_change_the_digest() -> None:
    cache = IdempotencyCache()
    cache.record("c-1", {"a": 1, "b": 2}, ok=True)
    assert cache.check("c-1", {"b": 2, "a": 1}) == (True, True, None)


def test_cache_stores_a_fixed_size_digest_not_the_payload() -> None:
    cache = IdempotencyCache()
    payload = {"window_id": 1, "choice": "chow", "tiles": list(range(10_000))}
    cache.record("c-1", payload, ok=True)
    stored = cache._entries["c-1"][0]
    assert isinstance(stored, bytes)
    assert len(stored) == 32
    assert stored is not payload


def test_lru_eviction_keeps_last_maxlen_ids() -> None:
    cache = IdempotencyCache(maxlen=2)
    for i in range(3):
        cache.record(f"c-{i}", {"tile_id": i}, ok=True)
    assert cache.check("c-0", {"tile_id": 0}) == (False, True, None)
    assert cache.check("c-2", {"tile_id": 2}) == (True, True, None)
