"""Benchmark matrix agreed in ADR-0003.

~15 cases: get hit/miss x {int, short str, long str, tuple}, set int/str +
replace, get_with hit/miss, remove hit/miss.

Needles for `get` are equal-but-NOT-identical to the stored key objects:
AnyKey::eq short-circuits on object identity, so an identical needle would
never exercise the real hash/eq path that f-string-built keys pay in
production. Note that str objects cache their hash after first use (so
repeated gets with the same needle pay hash once), while tuples recompute
their hash on every call.

Each `get` bench cycles over a pool of needles instead of hammering one key:
a single needle's collision-chain length is a per-process lottery (CPython
hash randomization for str/tuple plus per-instance ahash seeds), which was
measured to swing single-needle results by +-13% between runs of the same
binary. The pool averages bucket luck at the cost of a constant `next()`
overhead. Run under PYTHONHASHSEED=0 (see justfile) and take the median of
>=3 process runs for any merge verdict (ADR-0003).
"""

import sys
from itertools import count, cycle

import moka_py

print("moka_py version:", moka_py.VERSION, file=sys.stderr)

CAPACITY = 10_000
LONG_PREFIX = "x" * 64


NEEDLE_POOL = 100


def _fresh_int(value: int) -> int:
    # Parsing defeats both small-int caching and constant folding.
    return int(str(value))


def _needles(make, start: int):
    return cycle([make(_fresh_int(i)) for i in range(start, start + NEEDLE_POOL)])


def _prefilled(keys) -> moka_py.Moka:
    moka = moka_py.Moka(CAPACITY)
    for key in keys:
        moka.set(key, "value")
    return moka


# --- get hit -----------------------------------------------------------------


def test_bench_get_hit_int(benchmark):
    moka = _prefilled(range(CAPACITY))
    needles = _needles(lambda i: i, 5000)

    def _get():
        moka.get(next(needles))

    benchmark(_get)


def test_bench_get_hit_short_str(benchmark):
    moka = _prefilled(f"k{i}" for i in range(CAPACITY))
    needles = _needles(lambda i: f"k{i}", 5000)

    def _get():
        moka.get(next(needles))

    benchmark(_get)


def test_bench_get_hit_long_str(benchmark):
    moka = _prefilled(f"{LONG_PREFIX}{i}" for i in range(CAPACITY))
    needles = _needles(lambda i: f"{LONG_PREFIX}{i}", 5000)

    def _get():
        moka.get(next(needles))

    benchmark(_get)


def test_bench_get_hit_tuple(benchmark):
    moka = _prefilled(("user", i, True) for i in range(CAPACITY))
    needles = _needles(lambda i: ("user", i, True), 5000)

    def _get():
        moka.get(next(needles))

    benchmark(_get)


# --- get miss ----------------------------------------------------------------


def test_bench_get_miss_int(benchmark):
    moka = _prefilled(range(CAPACITY))
    needles = _needles(lambda i: i, 999_000)

    def _get():
        moka.get(next(needles))

    benchmark(_get)


def test_bench_get_miss_short_str(benchmark):
    moka = _prefilled(f"k{i}" for i in range(CAPACITY))
    needles = _needles(lambda i: f"k{i}", 999_000)

    def _get():
        moka.get(next(needles))

    benchmark(_get)


def test_bench_get_miss_long_str(benchmark):
    moka = _prefilled(f"{LONG_PREFIX}{i}" for i in range(CAPACITY))
    needles = _needles(lambda i: f"{LONG_PREFIX}{i}", 999_000)

    def _get():
        moka.get(next(needles))

    benchmark(_get)


def test_bench_get_miss_tuple(benchmark):
    moka = _prefilled(("user", i, True) for i in range(CAPACITY))
    needles = _needles(lambda i: ("user", i, True), 999_000)

    def _get():
        moka.get(next(needles))

    benchmark(_get)


# --- set ---------------------------------------------------------------------


def test_bench_set_int(benchmark):
    moka = moka_py.Moka(CAPACITY)
    keys = cycle(range(100_000))

    def _set():
        k = next(keys)
        moka.set(k, k)

    benchmark(_set)


def test_bench_set_str(benchmark):
    moka = moka_py.Moka(CAPACITY)
    keys = cycle([str(i) for i in range(100_000)])

    def _set():
        k = next(keys)
        moka.set(k, k)

    benchmark(_set)


def test_bench_set_replace(benchmark):
    moka = moka_py.Moka(CAPACITY)
    moka.set("hot", "value")
    benchmark(moka.set, "hot", "value")


# --- get_with ----------------------------------------------------------------


def test_bench_get_with_hit(benchmark):
    moka = moka_py.Moka(CAPACITY)

    def init():
        return 5

    moka.get_with("hello", init)
    benchmark(moka.get_with, "hello", init)


def test_bench_get_with_miss(benchmark):
    moka = moka_py.Moka(CAPACITY)
    keys = count()

    def init():
        return 5

    def _get_with():
        moka.get_with(next(keys), init)

    benchmark(_get_with)


# --- remove ------------------------------------------------------------------


def test_bench_remove_hit(benchmark):
    """One set() + one remove() per iteration.

    remove() consumes the key, so a pure hit cannot be measured in a steady
    state; subtract set_int's mean to estimate the remove cost alone.
    """
    moka = moka_py.Moka(CAPACITY)

    def _set_and_remove():
        moka.set(1, 1)
        moka.remove(1)

    benchmark(_set_and_remove)


def test_bench_remove_miss(benchmark):
    moka = moka_py.Moka(CAPACITY)
    needle = _fresh_int(999_999)
    benchmark(moka.remove, needle)
