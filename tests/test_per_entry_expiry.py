import asyncio

import pytest

import moka_py

# ---------------------------------------------------------------------------
# Basic per-entry TTL / TTI
# ---------------------------------------------------------------------------


async def test_per_entry_ttl_basic():
    """Entry with per-entry TTL expires independently of other entries."""
    cache = moka_py.Moka(128)
    cache.set("short", "a", ttl=0.2)
    cache.set("long", "b", ttl=2.0)
    cache.set("forever", "c")

    assert cache.get("short") == "a"
    assert cache.get("long") == "b"
    assert cache.get("forever") == "c"

    await asyncio.sleep(0.3)

    assert cache.get("short") is None
    assert cache.get("long") == "b"
    assert cache.get("forever") == "c"


async def test_per_entry_tti_basic():
    """Entry with per-entry TTI expires after idle period."""
    cache = moka_py.Moka(128)
    cache.set("idle", "val", tti=0.2)

    # keep accessing within TTI
    for _ in range(3):
        assert cache.get("idle") == "val"
        await asyncio.sleep(0.1)

    # now stop accessing and let it expire
    await asyncio.sleep(0.3)
    assert cache.get("idle") is None


async def test_per_entry_ttl_and_tti():
    """Per-entry TTL and TTI work together: earliest wins."""
    cache = moka_py.Moka(128)
    # TTL=0.8s, TTI=0.3s — if we stop accessing, TTI kicks in first
    cache.set("k", "v", ttl=0.8, tti=0.3)

    assert cache.get("k") == "v"
    await asyncio.sleep(0.4)
    # TTI exceeded (0.3s without access)
    assert cache.get("k") is None


async def test_per_entry_ttl_not_extended_by_reads():
    """TTL must not be bypassed by frequent reads (TTI resets must not push past TTL)."""
    cache = moka_py.Moka(128)
    cache.set("k", "v", ttl=0.5, tti=0.3)

    # Keep reading every 0.15s — TTI is 0.3s so it keeps resetting,
    # but TTL is 0.5s and must still expire the entry.
    for _ in range(6):  # 6 * 0.15 = 0.9s, well past TTL=0.5s
        await asyncio.sleep(0.15)
        val = cache.get("k")
        if val is None:
            break

    # Entry MUST be gone by now — TTL=0.5s has passed.
    assert cache.get("k") is None


async def test_per_entry_ttl_only_not_extended_by_reads():
    """TTL-only entry (no TTI) is not extended by reads."""
    cache = moka_py.Moka(128)
    cache.set("k", "v", ttl=0.3)

    for _ in range(4):  # 4 * 0.15 = 0.6s, past TTL=0.3s
        await asyncio.sleep(0.15)
        val = cache.get("k")
        if val is None:
            break

    assert cache.get("k") is None


async def test_different_entries_different_ttls():
    """Multiple entries can have different per-entry TTLs."""
    cache = moka_py.Moka(128)
    cache.set("a", 1, ttl=0.2)
    cache.set("b", 2, ttl=0.5)
    cache.set("c", 3, ttl=1.0)

    await asyncio.sleep(0.3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3

    await asyncio.sleep(0.3)
    assert cache.get("b") is None
    assert cache.get("c") == 3


# ---------------------------------------------------------------------------
# expire_after_update: re-set resets the deadline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first_kwargs", "second_kwargs", "re_set_delay", "alive_after_re_set", "dead_after_re_set"),
    [
        # second TTL same as first, re-set before expiry
        ({"ttl": 0.3}, {"ttl": 0.3}, 0.2, 0.2, 0.4),
        # second TTL longer, re-set before expiry
        ({"ttl": 0.3}, {"ttl": 0.8}, 0.2, 0.4, 0.9),
        # second TTL shorter, re-set before expiry
        ({"ttl": 0.8}, {"ttl": 0.2}, 0.2, 0.1, 0.3),
        # first TTL, second switches to TTI, re-set before expiry
        ({"ttl": 0.3}, {"tti": 0.2}, 0.2, 0.1, 0.3),
        # first TTL, second switches to TTL+TTI, re-set before expiry
        ({"ttl": 0.3}, {"ttl": 0.8, "tti": 0.2}, 0.2, 0.1, 0.3),
        # second TTL same as first, re-set AFTER first expired
        ({"ttl": 0.2}, {"ttl": 0.3}, 0.3, 0.2, 0.4),
        # second TTL shorter, re-set AFTER first expired
        ({"ttl": 0.2}, {"ttl": 0.15}, 0.3, 0.1, 0.2),
        # first TTL, second switches to TTI, re-set AFTER first expired
        ({"ttl": 0.2}, {"tti": 0.2}, 0.3, 0.1, 0.3),
    ],
    ids=[
        "same_ttl_before_expiry",
        "longer_ttl_before_expiry",
        "shorter_ttl_before_expiry",
        "ttl_to_tti_before_expiry",
        "ttl_to_ttl_tti_before_expiry",
        "same_ttl_after_expiry",
        "shorter_ttl_after_expiry",
        "ttl_to_tti_after_expiry",
    ],
)
async def test_re_set_resets_deadline(
    first_kwargs, second_kwargs, re_set_delay, alive_after_re_set, dead_after_re_set
):
    """Re-setting a key resets the expiration deadline from the second set()."""
    cache = moka_py.Moka(128)
    cache.set("k", "v1", **first_kwargs)

    await asyncio.sleep(re_set_delay)
    cache.set("k", "v2", **second_kwargs)

    await asyncio.sleep(alive_after_re_set)
    assert cache.get("k") == "v2", "entry should still be alive"

    await asyncio.sleep(dead_after_re_set - alive_after_re_set)
    assert cache.get("k") is None, "entry should have expired"


async def test_re_set_without_ttl_clears_expiry():
    """Re-setting a key without ttl/tti removes per-entry expiration."""
    cache = moka_py.Moka(128)
    cache.set("k", "v1", ttl=0.2)

    await asyncio.sleep(0.1)
    # re-set without ttl — no per-entry expiration
    cache.set("k", "v2")

    await asyncio.sleep(0.3)
    # should still be alive (no per-entry or global expiration)
    assert cache.get("k") == "v2"


# ---------------------------------------------------------------------------
# Interaction with cache-wide TTL / TTI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("global_kwargs", "per_entry_kwargs"),
    [
        ({"ttl": 0.2}, {"ttl": 10.0}),
        ({"tti": 0.2}, {"tti": 10.0}),
        ({"tti": 0.2}, {"ttl": 10.0}),
    ],
    ids=[
        "per_entry_ttl_cannot_exceed_global_ttl",
        "per_entry_tti_cannot_exceed_global_tti",
        "per_entry_ttl_cannot_exceed_global_tti",
    ],
)
async def test_per_entry_cannot_exceed_global(global_kwargs, per_entry_kwargs):
    """Per-entry TTL/TTI cannot extend lifetime beyond the cache-wide policy."""
    cache = moka_py.Moka(128, **global_kwargs)
    cache.set("k", "v", **per_entry_kwargs)

    await asyncio.sleep(0.3)
    assert cache.get("k") is None


@pytest.mark.parametrize(
    ("global_kwargs", "per_entry_kwargs"),
    [
        ({"ttl": 2.0}, {"ttl": 0.2}),
        ({"tti": 2.0}, {"tti": 0.2}),
    ],
    ids=[
        "per_entry_ttl_shorter_than_global",
        "per_entry_tti_shorter_than_global",
    ],
)
async def test_per_entry_shortens_global(global_kwargs, per_entry_kwargs):
    """Per-entry TTL/TTI can make an entry expire sooner than the global policy."""
    cache = moka_py.Moka(128, **global_kwargs)
    cache.set("short", "a", **per_entry_kwargs)
    cache.set("default", "b")

    await asyncio.sleep(0.3)

    assert cache.get("short") is None
    assert cache.get("default") == "b"


# ---------------------------------------------------------------------------
# get_with() with per-entry TTL / TTI
# ---------------------------------------------------------------------------


async def test_per_entry_ttl_with_get_with():
    """get_with() supports per-entry TTL."""
    cache = moka_py.Moka(128)
    val = cache.get_with("k", lambda: "computed", ttl=0.2)
    assert val == "computed"

    assert cache.get("k") == "computed"

    await asyncio.sleep(0.3)
    assert cache.get("k") is None


async def test_per_entry_tti_with_get_with():
    """get_with() supports per-entry TTI."""
    cache = moka_py.Moka(128)
    val = cache.get_with("k", lambda: "computed", tti=0.2)
    assert val == "computed"

    await asyncio.sleep(0.1)
    assert cache.get("k") == "computed"

    await asyncio.sleep(0.3)
    assert cache.get("k") is None


async def test_per_entry_ttl_and_tti_with_get_with():
    """get_with() supports per-entry TTL and TTI together."""
    cache = moka_py.Moka(128)
    val = cache.get_with("k", lambda: "computed", ttl=0.5, tti=0.3)
    assert val == "computed"

    # keep alive via reads — TTI resets, but TTL is absolute
    for _ in range(5):
        await asyncio.sleep(0.15)
        v = cache.get("k")
        if v is None:
            break

    # TTL=0.5s must have expired the entry
    assert cache.get("k") is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "kwargs", "match"),
    [
        ("set", {"ttl": 0.0}, "ttl must be positive"),
        ("set", {"tti": 0.0}, "tti must be positive"),
        ("set", {"ttl": -1.0}, "ttl must be positive"),
        ("set", {"tti": -1.0}, "tti must be positive"),
        ("get_with", {"ttl": 0.0}, "ttl must be positive"),
        ("get_with", {"tti": 0.0}, "tti must be positive"),
        ("get_with", {"ttl": -1.0}, "ttl must be positive"),
        ("get_with", {"tti": -1.0}, "tti must be positive"),
    ],
    ids=[
        "set_ttl_zero",
        "set_tti_zero",
        "set_ttl_negative",
        "set_tti_negative",
        "get_with_ttl_zero",
        "get_with_tti_zero",
        "get_with_ttl_negative",
        "get_with_tti_negative",
    ],
)
def test_invalid_per_entry_duration(method, kwargs, match):
    """Zero and negative per-entry TTL/TTI raise ValueError for set() and get_with()."""
    cache = moka_py.Moka(128)
    with pytest.raises(ValueError, match=match):
        if method == "set":
            cache.set("k", "v", **kwargs)
        else:
            cache.get_with("k", lambda: "v", **kwargs)


# ---------------------------------------------------------------------------
# Eviction listener
# ---------------------------------------------------------------------------


def test_eviction_listener_with_per_entry_ttl():
    """Eviction listener fires for per-entry TTL expired entries."""
    from time import sleep

    evicted = []

    def listener(key, value, cause):
        evicted.append((key, value, cause))

    cache = moka_py.Moka(128, eviction_listener=listener, ttl=0.1)
    cache.set("k", "v", ttl=0.1)
    sleep(1)
    # trigger maintenance - same pattern as test_eviction_listener
    assert cache.get("k") is None

    assert any(k == "k" and v == "v" for k, v, _ in evicted)
