import asyncio

import pytest

import moka_py


def test_run_pending_tasks_converges_count():
    moka = moka_py.Moka(128)
    for i in range(500):
        moka.set(i, i)

    # Without maintenance the count may transiently exceed max_capacity
    # (writes go through an internal buffer). After an explicit
    # run_pending_tasks() the count must have converged.
    moka.run_pending_tasks()

    assert 0 < moka.count() <= 128


def test_weighted_size_without_weigher_counts_entries():
    moka = moka_py.Moka(128)
    for i in range(3):
        moka.set(i, i)

    moka.run_pending_tasks()

    assert moka.weighted_size() == 3


def test_weigher_is_reflected_in_weighted_size():
    moka = moka_py.Moka(1000, weigher=lambda k, v: 5)
    moka.set("a", "x")
    moka.set("b", "y")

    moka.run_pending_tasks()

    assert moka.weighted_size() == 10


def test_eviction_respects_total_weight():
    # capacity means "maximum total weight" once a weigher is set
    moka = moka_py.Moka(10, weigher=lambda k, v: len(v))
    for i in range(5):
        moka.set(i, "abcd")  # weight 4 each, 20 in total

    moka.run_pending_tasks()

    assert moka.weighted_size() <= 10
    assert moka.count() < 5


def test_negative_weight_raises_value_error():
    moka = moka_py.Moka(128, weigher=lambda k, v: -1)
    with pytest.raises(ValueError):
        moka.set("a", "x")


@pytest.mark.parametrize("bad_weight", [1.5, "10", None])
def test_non_int_weight_raises_type_error(bad_weight):
    moka = moka_py.Moka(128, weigher=lambda k, v: bad_weight)
    with pytest.raises(TypeError):
        moka.set("a", "x")


def test_bool_weight_is_accepted_as_int():
    moka = moka_py.Moka(128, weigher=lambda k, v: True)
    moka.set("a", "x")
    moka.run_pending_tasks()
    assert moka.weighted_size() == 1


def test_zero_weight_spends_no_capacity():
    moka = moka_py.Moka(128, weigher=lambda k, v: 0)
    moka.set("a", "x")
    moka.run_pending_tasks()
    assert moka.get("a") == "x"
    assert moka.weighted_size() == 0


@pytest.mark.parametrize("huge", [2**32, 2**40, 10**30])
def test_oversized_weight_clamps_to_u32_max(huge):
    moka = moka_py.Moka(2**40, weigher=lambda k, v: huge)
    moka.set("a", "x")
    moka.run_pending_tasks()
    assert moka.weighted_size() == 2**32 - 1


def test_weigher_exception_fails_set_and_keeps_old_entry():
    def weigh(key, value):
        if value == "bad":
            raise RuntimeError("boom")
        return 1

    moka = moka_py.Moka(128, weigher=weigh)
    moka.set("a", "old")

    with pytest.raises(RuntimeError, match="boom"):
        moka.set("a", "bad")

    # the failed insert must not have touched the existing entry
    assert moka.get("a") == "old"


def test_get_with_applies_weigher_to_initialized_value():
    moka = moka_py.Moka(1000, weigher=lambda k, v: len(v))

    value = moka.get_with("a", lambda: "abcdef")

    assert value == "abcdef"
    moka.run_pending_tasks()
    assert moka.weighted_size() == 6


def test_get_with_weigher_exception_caches_nothing():
    moka = moka_py.Moka(128, weigher=lambda k, v: 1 / 0)

    with pytest.raises(ZeroDivisionError):
        moka.get_with("a", lambda: "value")

    assert moka.get("a") is None


def test_replace_recomputes_weight():
    moka = moka_py.Moka(1000, weigher=lambda k, v: len(v))
    moka.set("a", "xx")
    moka.run_pending_tasks()
    assert moka.weighted_size() == 2

    moka.set("a", "xxxxxxx")

    moka.run_pending_tasks()
    assert moka.weighted_size() == 7


def test_cached_passes_weigher_through():
    @moka_py.cached(maxsize=128, weigher=lambda k, v: -1)
    def double(x):
        return x * 2

    # the negative-weight ValueError can only come from the underlying cache,
    # which proves the weigher reached it
    with pytest.raises(ValueError):
        double(2)


def test_cached_weigher_works_with_sync_wait_concurrent():
    @moka_py.cached(maxsize=128, weigher=lambda k, v: 1, wait_concurrent=True)
    def double(x):
        return x * 2

    assert double(2) == 4
    assert double(2) == 4


async def test_cached_weigher_async_wait_concurrent_coalesces_and_weighs_result():
    calls = []

    @moka_py.cached(maxsize=1000, weigher=lambda k, v: len(v), wait_concurrent=True)
    async def fetch(x):
        calls.append(x)
        await asyncio.sleep(0.01)
        return x * 2

    first, second = await asyncio.gather(fetch("ab"), fetch("ab"))

    assert first == second == "abab"
    assert calls == ["ab"]  # concurrent calls shared one computation

    assert await fetch("ab") == "abab"
    assert calls == ["ab"]  # served from the cache afterwards


async def test_cached_weigher_async_wait_concurrent_weigher_error_fails_insert():
    @moka_py.cached(maxsize=1000, weigher=lambda k, v: -1, wait_concurrent=True)
    async def fetch(x):
        return x

    # the computation succeeds, but caching its result fails
    with pytest.raises(ValueError):
        await fetch("a")
