# moka-py

**moka-py** is a Python binding to the [Moka](https://github.com/moka-rs/moka) cache written in Rust. It brings Moka’s high-performance, feature‑rich caching to Python.

## Features

- **Synchronous cache:** Thread-safe in-memory caching for Python.
- **TTL:** Evicts entries after a configurable time to live (TTL).
- **TTI:** Evicts entries after a configurable time to idle (TTI).
- **Per-entry TTL / TTI:** Override the cache-wide TTL or TTI on individual entries.
- **Size-based eviction:** Removes items when capacity is exceeded using TinyLFU or LRU.
- **Concurrency:** Optimized for high-throughput, concurrent access.
- **Fully typed:** `mypy` and `pyright` friendly.

## Installation

<p>
  <img
    src="https://thesvg.org/icons/uv/default.svg"
    alt="uv"
    height="14"
  />
  Using <a href="https://github.com/astral-sh/uv">uv</a>:
</p>

```bash
uv add moka-py
```

<p>
  <img
    src="https://thesvg.org/icons/poetry/default.svg"
    alt="Poetry"
    height="14"
  />
  Using <a href="https://github.com/python-poetry/poetry">poetry</a>:
</p>

```bash
poetry add moka-py
```

<p>
  <img
    src="https://thesvg.org/icons/python/default.svg"
    alt="Python"
    height="14"
  />
  Using <a href="https://github.com/pypa/pip">pip</a>:
</p>

```bash
pip install moka-py
```

## Table of Contents

- [Installation](#installation)
- [Features](#features)
- [Usage](#usage)
    - [Using moka_py.Moka](#using-moka_pymoka)
    - [Per-entry TTL / TTI](#per-entry-ttl--tti)
    - [@cached decorator](#as-a-decorator)
    - [Async support](#async-support)
    - [Coalesce concurrent calls (wait_concurrent)](#coalesce-concurrent-calls-wait_concurrent)
    - [Eviction listener](#eviction-listener)
    - [Removing entries](#removing-entries)
- [How it works](#how-it-works)
- [Eviction policies](#eviction-policies)
- [Performance](#performance)
- [License](#license)

## Usage

### Using moka_py.Moka

```python
from time import sleep
from moka_py import Moka


# Create a cache with a capacity of 100 entries, with a TTL of 10.0 seconds
# and a TTI of 0.1 seconds. Entries are always removed after 10 seconds
# and are removed after 0.1 seconds if there are no `get`s happened for this time.
#
# Both TTL and TTI settings are optional. In the absence of an entry,
# the corresponding policy will not expire it.

# The default eviction policy is "tiny_lfu" which is optimal for most workloads,
# but you can choose "lru" as well.
cache: Moka[str, list[int]] = Moka(capacity=100, ttl=10.0, tti=0.1, policy="lru")

# Insert a value.
cache.set("key", [3, 2, 1])

# Retrieve the value.
assert cache.get("key") == [3, 2, 1]

# Wait for 0.1+ seconds, and the entry will be automatically evicted.
sleep(0.12)
assert cache.get("key") is None
```

### Per-entry TTL / TTI

By default, TTL and TTI are set once for the entire cache. You can also set them
per entry by passing `ttl` and/or `tti` to `set()` or `get_with()`:

```python
from time import sleep
from moka_py import Moka


cache = Moka(100)

cache.set("short-lived", "value", ttl=0.5)
cache.set("session", {"user": "alice"}, ttl=3600.0)
cache.set("idle-sensitive", "value", tti=1.0)
cache.set("both", "value", ttl=60.0, tti=5.0)

# Entries without per-entry ttl/tti never expire (unless the cache has global settings).
cache.set("permanent", "value")

sleep(0.6)
assert cache.get("short-lived") is None  # expired after 0.5s
assert cache.get("session") is not None  # still alive
assert cache.get("permanent") is not None
```

`get_with()` accepts the same parameters:

```python
from moka_py import Moka


cache = Moka(100)

value = cache.get_with("key", lambda: "computed", ttl=30.0)
```

#### Concurrent `get_with` with different TTL / TTI

`get_with()` guarantees that only **one** thread executes the initializer for a given key (stampede protection).
When multiple threads call `get_with()` for the same key concurrently with **different** `ttl`/`tti` values,
the thread that wins the race runs its initializer — and its `ttl`/`tti` values are stored with the entry.
All other threads receive the same cached value and their `ttl`/`tti` parameters are **silently ignored**.

```python
import threading
from moka_py import Moka


cache = Moka(100)

# Thread A: get_with("k", compute, ttl=1.0)
# Thread B: get_with("k", compute, ttl=60.0)
#
# If thread A wins, the entry expires in 1 second.
# If thread B wins, the entry expires in 60 seconds.
# The loser's ttl is discarded — it is NOT merged or compared.
```

#### Interaction with cache-wide TTL / TTI

When the cache is constructed with global `ttl` or `tti` **and** an entry specifies its own, the entry
expires at whichever deadline comes **first**.

> **WARNING**
>
> Per-entry TTL / TTI can only make an entry expire **sooner** than the cache-wide
> policy, not later. This is a technical limitation of the underlying
> [Moka](https://github.com/moka-rs/moka) library: global and per-entry expiration
> are evaluated independently, and the earliest deadline wins.
>
> If you need entries with different lifetimes that can **exceed** a common default,
> do not set global `ttl`/`tti` on the cache. Use per-entry values exclusively instead.

```python
from moka_py import Moka

# Do this:
cache = Moka(1000)
cache.set("short", "v", ttl=60.0)
cache.set("long", "v", ttl=300.0)  # works as expected

# NOT this — "long" will still expire in 60 s:
cache = Moka(1000, ttl=60.0)
cache.set("long", "v", ttl=300.0)  # capped at 60 s by the global policy
```

```python
from time import sleep
from moka_py import Moka


# Global TTL of 10 seconds.
cache = Moka(100, ttl=10.0)

# This entry will expire in 0.5 s (per-entry TTL wins, it is shorter).
cache.set("fast", "value", ttl=0.5)

# This entry keeps the global 10 s TTL (per-entry TTL=20 s is longer, so global wins).
cache.set("slow", "value", ttl=20.0)

sleep(0.6)
assert cache.get("fast") is None
assert cache.get("slow") is not None
```

### As a decorator

moka-py can be used as a drop-in replacement for `@lru_cache()` with TTL + TTI support:

```python
from time import sleep
from moka_py import cached


calls = []


@cached(maxsize=1024, ttl=5.0, tti=0.05)
def f(x, y):
    calls.append((x, y))
    return x + y


assert f(1, 2) == 3  # calls computations
assert f(1, 2) == 3  # gets from the cache
assert len(calls) == 1
sleep(0.06)
assert f(1, 2) == 3  # calls computations again (since TTI has passed)
assert len(calls) == 2
```

### Async support

Unlike `@lru_cache()`, `@moka_py.cached()` supports async functions:

```python
import asyncio
from time import perf_counter
from moka_py import cached


calls = []


@cached(maxsize=1024, ttl=5.0, tti=0.1)
async def f(x, y):
    calls.append((x, y))
    await asyncio.sleep(0.05)
    return x + y


start = perf_counter()
assert asyncio.run(f(5, 6)) == 11
assert asyncio.run(f(5, 6)) == 11  # from cache
elapsed = perf_counter() - start
assert elapsed < 0.2
assert len(calls) == 1
```

### Coalesce concurrent calls (wait_concurrent)

`moka-py` can synchronize threads on keys

```python
import moka_py
from typing import Any
from time import sleep
import threading
from decimal import Decimal


calls = []


@moka_py.cached(ttl=5, wait_concurrent=True)
def get_user(id_: int) -> dict[str, Any]:
    calls.append(id_)
    sleep(0.02)  # simulate an HTTP request (short for tests)
    return {
        "id": id_,
        "first_name": "Jack",
        "last_name": "Pot",
    }


def process_request(path: str, user_id: int) -> None:
    user = get_user(user_id)
    ...


def charge_money(from_user_id: int, amount: Decimal) -> None:
    user = get_user(from_user_id)
    ...


if __name__ == '__main__':
    request_processing = threading.Thread(target=process_request, args=("/user/info/123", 123))
    money_charging = threading.Thread(target=charge_money, args=(123, Decimal("3.14")))
    request_processing.start()
    money_charging.start()
    request_processing.join()
    money_charging.join()

    # Only one call occurred. Without `wait_concurrent`, each thread would issue its own HTTP request
    # before the cache entry is set.
    assert len(calls) == 1
```

### Async wait_concurrent

When using `wait_concurrent=True` with async functions, `moka-py` creates a shared `asyncio.Task` per cache key. All
concurrent callers `await` the same task and receive the same result or exception. This eliminates duplicate in-flight
work for identical arguments.

### Eviction listener

`moka-py` supports an eviction listener, called whenever a key is removed.
The listener must be a three-argument function `(key, value, cause)` and uses positional arguments only.

Possible reasons:

1. `"expired"`: The entry's expiration timestamp has passed.
2. `"explicit"`: The entry was manually removed by the user (`.remove()` is called).
3. `"replaced"`: The entry itself was not actually removed, but its value was replaced by the user (`.set()` is
   called for an existing entry).
4. `"size"`: The entry was evicted due to size constraints.

```python
from typing import Literal
from moka_py import Moka
from time import sleep


def key_evicted(
    k: str,
    v: list[int],
    cause: Literal["explicit", "size", "expired", "replaced"]
):
    events.append((k, v, cause))


events: list[tuple[str, list[int], str]] = []


moka: Moka[str, list[int]] = Moka(2, eviction_listener=key_evicted, ttl=0.5)
moka.set("hello", [1, 2, 3])
moka.set("hello", [3, 2, 1])  # replaced
moka.set("foo", [4])  # expired
moka.set("baz", "size")
moka.remove("foo")  # explicit
sleep(1.0)
moka.get("anything")  # this will trigger eviction for expired

causes = {c for _, _, c in events}
assert causes == {"size", "expired", "replaced", "explicit"}, events
```

> IMPORTANT NOTES
> 1) The listener is not called just-in-time. `moka` has no background threads or tasks; it runs only during cache operations.
> 2) The listener must not raise exceptions. If it does, the exception may surface from any `moka-py` method on any thread.
> 3) Keep the listener fast. Heavy work (especially I/O) will slow `.get()`, `.set()`, etc. Offload via `ThreadPoolExecutor.submit()` or `asyncio.create_task()`
> 4) **Per-entry TTL / TTI and the eviction listener.** Per-entry expiry fires the
>    listener with `"expired"` just like global TTL/TTI does. The notification is
>    delivered lazily during subsequent cache operations (e.g. `get`, `set`) after
>    the per-entry deadline passes — it is not instant.

### Removing entries

Remove an entry with `Moka.remove(key)`. It returns the previous value if present; otherwise `None`.

```python
from moka_py import Moka


c = Moka(128)
c.set("hello", "world")
assert c.remove("hello") == "world"
assert c.get("hello") is None
```

If `None` is a valid cached value, distinguish it from absence using `Moka.remove(key, default=...)`:

```python
from moka_py import Moka


c = Moka(128)
c.set("hello", None)
assert c.remove("hello", default="WAS_NOT_SET") is None  # None was set explicitly

# Now the entry "hello" does not exist, so `default` is returned
assert c.remove("hello", default="WAS_NOT_SET") == "WAS_NOT_SET"
```

## How it works

`Moka` stores Python object references
(by [`Py_INCREF`](https://docs.python.org/3/c-api/refcounting.html#c.Py_INCREF)) and does not serialize or deserialize values.
You can use any Python object as a value and any hashable object as a key (`__hash__` is used).
Mutable objects remain mutable:

```python
from moka_py import Moka


c = Moka(128)
my_list = [1, 2, 3]
c.set("hello", my_list)
still_the_same = c.get("hello")
still_the_same.append(4)
assert my_list == [1, 2, 3, 4]
```

## Eviction policies

`moka-py` uses TinyLFU by default, with an LRU option. Learn more in the
[Moka wiki](https://github.com/moka-rs/moka/wiki#admission-and-eviction-policies).

## Performance

*Measured using MacBook Pro 14-inch, Nov 2024 with Apple M4 Pro processor and 24GiB RAM*

```
-------------------------------------------------------------------------------------------- benchmark: 9 tests -------------------------------------------------------------------------------------------
Name (time in ns)                       Min                 Max                Mean            StdDev              Median               IQR            Outliers  OPS (Mops/s)            Rounds  Iterations
-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
test_bench_remove                   68.1140 (1.0)       68.2812 (1.0)       68.1806 (1.0)      0.0671 (1.0)       68.1621 (1.0)      0.1000 (1.0)           1;0       14.6669 (1.0)           5    10000000
test_bench_get[lru-False]           77.5126 (1.14)      78.2797 (1.15)      77.7823 (1.14)     0.2947 (4.39)      77.6792 (1.14)     0.2913 (2.91)          1;0       12.8564 (0.88)          5    10000000
test_bench_get[tiny_lfu-False]      78.0985 (1.15)      78.8168 (1.15)      78.4920 (1.15)     0.2678 (3.99)      78.4868 (1.15)     0.3429 (3.43)          2;0       12.7401 (0.87)          5    10000000
test_bench_get[lru-True]            89.1512 (1.31)      89.6459 (1.31)      89.4480 (1.31)     0.1910 (2.85)      89.5190 (1.31)     0.2458 (2.46)          2;0       11.1797 (0.76)          5    10000000
test_bench_get[tiny_lfu-True]       91.4891 (1.34)      91.9214 (1.35)      91.6827 (1.34)     0.1867 (2.78)      91.7339 (1.35)     0.3141 (3.14)          2;0       10.9072 (0.74)          5    10000000
test_bench_get_with                137.0672 (2.01)     137.8738 (2.02)     137.4143 (2.02)     0.3182 (4.74)     137.2839 (2.01)     0.4530 (4.53)          2;0        7.2773 (0.50)          5    10000000
test_bench_set_str_key             354.1709 (5.20)     355.5768 (5.21)     354.9073 (5.21)     0.5631 (8.39)     355.0415 (5.21)     0.8900 (8.90)          2;0        2.8176 (0.19)          5     1408297
test_bench_set[tiny_lfu]           355.6927 (5.22)     356.9633 (5.23)     356.3647 (5.23)     0.5645 (8.41)     356.4059 (5.23)     1.0390 (10.40)         2;0        2.8061 (0.19)          5     1405450
test_bench_set[lru]                388.7005 (5.71)     389.5825 (5.71)     389.1170 (5.71)     0.3837 (5.72)     389.0796 (5.71)     0.6915 (6.92)          2;0        2.5699 (0.18)          5     1295615
-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
```

## License

`moka-py` is distributed under the [MIT license](LICENSE).
