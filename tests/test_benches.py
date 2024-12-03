from itertools import cycle
import pytest
import moka_py


def test_bench_set(benchmark):
    moka = moka_py.Moka(10_000)
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


def test_bench_set_huge(benchmark):
    moka = moka_py.Moka(10_000)
    to_set = cycle(iter(range(100_000)))
    payload = "hello" * 100_000

    def _set():
        k = next(to_set)
        moka.set(k, payload)

    benchmark(_set)


@pytest.mark.parametrize("ttl", [None, 10.0])
def test_bench_get(benchmark, ttl):
    moka = moka_py.Moka(10_000, ttl=ttl)
    payload = "hello" * 100_000
    for key in range(10_000):
        moka.set(f"pretty_long_key_of_index_{key}", payload)

    def _bench():
        moka.get("pretty_long_key_of_index_5432")

    benchmark(_bench)


def test_bench_get_non_existent(benchmark):
    moka = moka_py.Moka(10_000)
    payload = "hello" * 100_000
    for key in range(10_000):
        moka.set(f"pretty_long_key_of_index_{key}", payload)

    def _bench():
        moka.get("hello")

    benchmark(_bench)


def test_bench_get_with(benchmark):
    moka = moka_py.Moka(10_000)

    def init():
        return 5

    def _bench():
        moka.get_with("hello", init)

    benchmark(_bench)
