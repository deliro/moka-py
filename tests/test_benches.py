import sys
from itertools import cycle, chain
import pytest
import moka_py


print("moka_py version:", moka_py.VERSION, file=sys.stderr)


@pytest.mark.parametrize("policy", ["tiny_lfu", "lru"])
def test_bench_set(benchmark, policy):
    moka = moka_py.Moka(10_000, policy=policy)
    to_set = cycle(iter(range(100_000)))

    def _set():
        k = next(to_set)
        moka.set(k, k)

    benchmark(_set)


def test_bench_set_str_key(benchmark):
    moka = moka_py.Moka(10_000)
    to_set = cycle(iter(map(str, range(100_000))))

    def _set():
        k = next(to_set)
        moka.set(k, k)

    benchmark(_set)


@pytest.mark.parametrize(("policy", "existent"), [
    ("tiny_lfu", True),
    ("tiny_lfu", False),
    ("lru", True),
    ("lru", False),
])
def test_bench_get(benchmark, policy, existent):
    if existent:
        needle = "pretty_long_key_of_index_5432"
    else:
        needle = "hello"

    moka = moka_py.Moka(10_000, policy=policy)
    payload = "hello" * 100_000
    for key in range(10_000):
        moka.set(f"pretty_long_key_of_index_{key}", payload)

    def _bench():
        moka.get(needle)

    benchmark(_bench)


def test_bench_get_with(benchmark):
    moka = moka_py.Moka(10_000)

    def init():
        return 5

    def _bench():
        moka.get_with("hello", init)

    benchmark(_bench)


def test_bench_remove(benchmark):
    moka = moka_py.Moka(10_000)
    non_existent = range(100_000, 100_000 + 10_000)
    keys = cycle(chain(range(10_000), non_existent))
    for key in range(10_000):
        moka.set(key, key)

    def _remove():
        moka.remove(next(keys))

    benchmark(_remove)
