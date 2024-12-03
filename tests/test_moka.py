import asyncio
from time import monotonic, sleep
import threading

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


def test_get_with():
    moka = moka_py.Moka(128)
    calls = []

    def init():
        calls.append(1)
        sleep(0.2)
        return "world"

    def target():
        res = moka.get_with("hello", init)
        assert res == "world"

    t1 = threading.Thread(target=target)
    t2 = threading.Thread(target=target)

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    assert len(calls) == 1


def test_default() -> None:
    moka = moka_py.Moka(128)
    moka.set("hello", [1, 2, 3])
    assert moka.get("world") is None
    assert moka.get("world", "foo") == "foo"


def test_threading() -> None:
    moka = moka_py.Moka(128)

    t1_set = threading.Event()
    t2_set = threading.Event()

    def target_1():
        moka.set("hello", "world")
        t1_set.set()
        t2_set.wait(1.0)
        assert moka.get("hello") == "foobar"

    def target_2():
        t1_set.wait(1.0)
        assert moka.get("hello") == "world"
        moka.set("hello", "foobar")
        t2_set.set()

    t1 = threading.Thread(target=target_1)
    t2 = threading.Thread(target=target_2)

    t1.start()
    t2.start()

    t1.join()
    t2.join()
