# moka-py

**moka-py** is a Python binding to the [Moka](https://github.com/moka-rs/moka) cache written in Rust. It brings Moka’s high-performance, feature‑rich caching to Python.

## Features

- **Synchronous cache:** Thread-safe in-memory caching for Python.
- **TTL:** Evicts entries after a configurable time to live (TTL).
- **TTI:** Evicts entries after a configurable time to idle (TTI).
- **Size-based eviction:** Removes items when capacity is exceeded using TinyLFU or LRU.
- **Concurrency:** Optimized for high-throughput, concurrent access.
- **Fully typed:** `mypy` and `pyright` friendly.

## Installation

Install with `uv`:

```bash
uv add moka-py
```

Or with `poetry`:

```bash
poetry add moka-py
```

Or with `pip`:

```bash
pip install moka-py
```

## Table of Contents

- [Installation](#installation)
- [Features](#features)
- [Usage](#usage)
    - [Using moka_py.Moka](#using-moka_pymoka)
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

*Measured using MacBook Pro 2021 with Apple M1 Pro processor and 16GiB RAM*

```
-------------------------------------------------------------------------------------------- benchmark: 9 tests -------------------------------------------------------------------------------------------
Name (time in ns)                       Min                 Max                Mean            StdDev              Median               IQR            Outliers  OPS (Mops/s)            Rounds  Iterations
-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
test_bench_remove                  100.8775 (1.0)      108.9191 (1.0)      102.6757 (1.0)      3.4992 (34.54)    101.0640 (1.0)      2.4234 (15.49)         1;1        9.7394 (1.0)           5    10000000
test_bench_get[lru-False]          112.8452 (1.12)     113.0924 (1.04)     112.9415 (1.10)     0.1013 (1.0)      112.9176 (1.12)     0.1565 (1.0)           1;0        8.8541 (0.91)          5    10000000
test_bench_get[tiny_lfu-False]     135.0147 (1.34)     135.6069 (1.25)     135.2916 (1.32)     0.2246 (2.22)     135.2849 (1.34)     0.3164 (2.02)          2;0        7.3914 (0.76)          5    10000000
test_bench_get[lru-True]           135.1628 (1.34)     135.7813 (1.25)     135.4712 (1.32)     0.2231 (2.20)     135.4765 (1.34)     0.2477 (1.58)          2;0        7.3816 (0.76)          5    10000000
test_bench_get[tiny_lfu-True]      135.2461 (1.34)     135.6612 (1.25)     135.4463 (1.32)     0.1802 (1.78)     135.4026 (1.34)     0.3192 (2.04)          2;0        7.3830 (0.76)          5    10000000
test_bench_get_with                290.5307 (2.88)     291.0418 (2.67)     290.8393 (2.83)     0.1893 (1.87)     290.8867 (2.88)     0.1873 (1.20)          2;0        3.4383 (0.35)          5    10000000
test_bench_set[tiny_lfu]           515.7514 (5.11)     518.6080 (4.76)     517.4876 (5.04)     1.1196 (11.05)    517.6572 (5.12)     1.5465 (9.88)          2;0        1.9324 (0.20)          5     1912971
test_bench_set_str_key             516.1032 (5.12)     533.7330 (4.90)     525.7461 (5.12)     6.3386 (62.57)    526.8491 (5.21)     6.1052 (39.01)         2;0        1.9021 (0.20)          5     1918471
test_bench_set[lru]                637.3014 (6.32)     644.4533 (5.92)     640.3571 (6.24)     2.8981 (28.61)    639.8821 (6.33)     4.6131 (29.48)         2;0        1.5616 (0.16)          5     1581738
-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
```

## License

`moka-py` is distributed under the [MIT license](LICENSE).
