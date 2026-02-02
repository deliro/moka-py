import threading
from time import sleep

import pytest

import moka_py


def test_decorator_typed_flag():
    calls = []

    @moka_py.cached(typed=True)
    def f(x):
        calls.append(x)
        return x

    f(1)
    f(1.0)
    assert len(calls) == 2


def test_decorator_ttl():
    calls = []

    @moka_py.cached(ttl=0.2)
    def f(x):
        calls.append(x)
        return x

    assert f(1) == 1
    assert f(1) == 1
    sleep(0.22)
    assert f(1) == 1
    assert len(calls) == 2


def test_decorator_tti():
    calls = []

    @moka_py.cached(tti=0.2)
    def f(x):
        calls.append(x)
        return x

    assert f(1) == 1
    sleep(0.1)
    assert f(1) == 1
    sleep(0.1)
    assert f(1) == 1
    sleep(0.25)
    assert f(1) == 1
    assert len(calls) == 2


def test_count_and_clear():
    c = moka_py.Moka(3)
    before = c.count()
    c.set("a", 1)
    c.set("b", 2)
    # Count may be approximate; verify behaviorally
    assert c.get("a") == 1
    assert c.get("b") == 2
    c.set("a", 3)
    assert c.get("a") == 3
    assert c.remove("a") == 3
    assert c.get("a") is None
    c.clear()
    after = c.count()
    assert c.get("b") is None
    assert after <= before


def test_get_with_exception_retry():
    c = moka_py.Moka(16)
    called = {"n": 0}

    def init():
        called["n"] += 1
        if called["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    with pytest.raises(RuntimeError):
        c.get_with("k", init)
    assert c.get("k") is None
    assert c.get_with("k", init) == "ok"
    assert called["n"] == 2


def test_sync_wait_concurrent_exception():
    calls = []

    @moka_py.cached(wait_concurrent=True)
    def f(x):
        calls.append(x)
        sleep(0.1)
        raise ValueError("bad")

    def target():
        with pytest.raises(ValueError):
            f(1)

    threads = [threading.Thread(target=target) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1


@pytest.mark.parametrize(
    "ttl,tti",
    [
        (0.0, None),
        (-1.0, None),
        (None, 0.0),
        (None, -2.0),
    ],
)
def test_invalid_ttl_tti(ttl, tti):
    kwargs = {}
    if ttl is not None:
        kwargs["ttl"] = ttl
    if tti is not None:
        kwargs["tti"] = tti
    with pytest.raises(ValueError):
        moka_py.Moka(4, **kwargs)


def test_unhashable_key():
    c = moka_py.Moka(4)
    with pytest.raises(TypeError):
        c.set(["a"], 1)


def test_concurrent_get_with_different_ttl():
    """When multiple threads call get_with for the same key with different TTL,
    only the winning (first) initializer's TTL is used."""
    cache = moka_py.Moka(16)
    results = {}

    def init_short():
        sleep(0.1)  # slow enough for the other thread to start waiting
        return "short"

    def init_long():
        sleep(0.1)
        return "long"

    def thread_short():
        results["short"] = cache.get_with("k", init_short, ttl=0.2)

    def thread_long():
        results["long"] = cache.get_with("k", init_long, ttl=5.0)

    t1 = threading.Thread(target=thread_short)
    t2 = threading.Thread(target=thread_long)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Both threads get the same value (whichever initializer won the race)
    assert results["short"] == results["long"]

    # The value is cached
    assert cache.get("k") == results["short"]

    # Wait for the shorter TTL to expire
    sleep(0.25)

    # The entry should have expired only if the winning initializer had the short TTL.
    # Regardless of which thread won, the TTL of the winner is what counts —
    # the loser's TTL parameter is ignored entirely.
    winner_value = results["short"]
    after = cache.get("k")

    if winner_value == "short":
        # short-TTL thread won → entry expired
        assert after is None
    else:
        # long-TTL thread won → entry still alive
        assert after == winner_value


@pytest.mark.parametrize("global_ttl", [None, 20.0], ids=["no_global_ttl", "with_global_ttl"])
def test_eviction_listener_per_entry_ttl_expired(global_ttl):
    """Per-entry TTL fires the eviction listener with cause='expired' regardless
    of whether the cache has a global TTL. The notification is delivered lazily
    during subsequent cache operations after the per-entry deadline passes."""
    events = []

    def listener(key, value, cause):
        events.append((key, value, cause))

    kwargs = {"eviction_listener": listener}
    if global_ttl is not None:
        kwargs["ttl"] = global_ttl

    cache = moka_py.Moka(128, **kwargs)
    cache.set("k", "val", ttl=1.0)

    assert cache.get("k") == "val"
    sleep(1.1)
    assert cache.get("k") is None

    # A single cache operation is enough to deliver the pending notification
    cache.set("other", "value")

    expired = [(k, v) for k, v, c in events if c == "expired" and k == "k"]
    assert len(expired) == 1, f"expected 'expired' event for 'k' after per-entry TTL, got: {events}"
    assert expired[0] == ("k", "val")
