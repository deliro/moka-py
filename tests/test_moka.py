import asyncio
from time import monotonic

import moka_py


async def test_tti():
    moka = moka_py.Moka(128, tti=0.2)
    value = {"foo": "bar"}
    moka.set("hello", value)
    assert moka.get("hello") is value
    assert moka.get("hello") is value
    await asyncio.sleep(0.2)
    assert moka.get("hello") is None


async def test_ttl_and_tti():
    ttl = 0.8
    tti = 0.3
    moka = moka_py.Moka(128, ttl=ttl, tti=tti)
    value = {"foo": "bar"}
    moka.set("hello", value)
    start = monotonic()
    while monotonic() - start <= ttl:
        assert moka.get("hello") is value
        # * 0.5 is a making sure that TTI is bumped in time
        # since asyncio.sleep only guarantees it won't be wakened up before
        # the specified time
        await asyncio.sleep(tti * 0.5)
    assert moka.get("hello") is None


def test_eviction():
    size = 128
    moka = moka_py.Moka(size)
    keys = list(range(500))
    assert len(keys) > size

    for key in keys:
        moka.set(key, key)

    got = []
    for key in keys:
        v = moka.get(key)
        if v is not None:
            got.append(v)

    assert len(got) == size


def test_remove():
    moka = moka_py.Moka(128)
    moka.set("hello", "world")
    assert moka.remove("hello") == "world"
    assert moka.get("hello") is None
