import asyncio
from threading import Thread
from time import sleep

import pytest

import moka_py
import random


def test_decorator_sync():
    lst = []

    @moka_py.cached()
    def f(x: int, y: int) -> float:
        lst.append((x, y))
        return x / y

    cases = [
        (1, 2), (3, 4), (5, 6), (7, 8)
    ]

    answers = {}

    for _ in range(100):
        copy = cases[:]
        random.shuffle(copy)
        for case in copy:
            result = f(*case)
            if case not in answers:
                answers[case] = result
            else:
                assert answers[case] == result

    # A call with the same arguments occurs only once
    assert len(lst) == len(cases)


@pytest.mark.asyncio
async def test_decorator_async():
    lst = []

    @moka_py.cached()
    async def f(x: int, y: int) -> float:
        lst.append((x, y))
        await asyncio.sleep(0.01)
        return x / y

    cases = [
        (1, 2), (3, 4), (5, 6), (7, 8)
    ]

    answers = {}

    for _ in range(100):
        copy = cases[:]
        random.shuffle(copy)
        for case in copy:
            result = await f(*case)
            if case not in answers:
                answers[case] = result
            else:
                assert answers[case] == result

    # A call with the same arguments occurs only once
    assert len(lst) == len(cases)


def test_cache_clear():
    calls = []

    @moka_py.cached()
    def f(x: int, y: int) -> float:
        calls.append((x, y))
        return x / y

    f(1, 2)
    f(1, 2)
    f.cache_clear()
    f(1, 2)
    assert len(calls) == 2


@pytest.mark.parametrize(("wait", "expected_calls"), [
    (True, 1),
    (False, 5)
])
def test_wait_concurrent(wait, expected_calls):
    calls = []

    @moka_py.cached(wait_concurrent=wait)
    def f(x: int, y: int) -> float:
        calls.append((x, y))
        sleep(0.1)
        return x / y

    def target():
        assert f(12, 3) == 4.0

    threads = [Thread(target=target) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == expected_calls


def test_return_none():
    calls = []

    @moka_py.cached()
    def f(x, y):
        calls.append((x, y))
        if x == 5:
            return None
        return x * y

    assert f(5, 1) is None
    assert f(4, 2) == 8
    assert f(5, 1) is None

    assert calls == [(5, 1), (4, 2)]

@pytest.mark.parametrize(("policy", "must_fail"), [
    (None, False),
    ("tiny_lfu", False),
    ("lru", False),
    ("unknown_policy", True),
])
def test_policy(policy, must_fail):
    if must_fail:
        with pytest.raises(ValueError):
            moka_py.cached(policy=policy)(lambda x, y: x * y)
    else:
        if policy is None:
            f = moka_py.cached()(lambda x, y: x * y)
        else:
            f = moka_py.cached(policy=policy)(lambda x, y: x * y)
        assert f(5, 6) == 30
        assert f(5, 6) == 30
