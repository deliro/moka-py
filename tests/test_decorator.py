import asyncio

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
    print(lst, answers)
