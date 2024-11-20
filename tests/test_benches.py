from itertools import cycle

import moka_py


def test_bench_set(benchmark):
    moka = moka_py.Moka(100_000)
    to_set = cycle(iter(list(range(100_000))))

    def _set():
        k = next(to_set)
        moka.set(k, k)

    benchmark(_set)


def test_bench_set_huge(benchmark):
    moka = moka_py.Moka(10_000)
    to_set = cycle(iter(list(range(10_000))))
    payload = "hello" * 100_000

    def _set():
        k = next(to_set)
        moka.set(k, payload)

    benchmark(_set)


def test_bench_get(benchmark):
    moka = moka_py.Moka(10_000)
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
