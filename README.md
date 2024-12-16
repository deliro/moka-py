# moka-py

* * * 

**moka-py** is a Python binding for the highly efficient [Moka](https://github.com/moka-rs/moka) caching library written
in Rust. This library allows you to leverage the power of Moka's high-performance, feature-rich cache in your Python
projects.

## Features

- **Synchronous Cache:** Supports thread-safe, in-memory caching for Python applications.
- **TTL Support:** Automatically evicts entries after a configurable time-to-live (TTL).
- **TTI Support:** Automatically evicts entries after a configurable time-to-idle (TTI).
- **Size-based Eviction:** Automatically removes items when the cache exceeds its size limit using TinyLFU or LRU
  policy.
- **Concurrency:** Optimized for high-performance, concurrent access in multithreaded environments.
- **Fully typed:** `mypy` and `pyright` friendly.

## Installation

You can install `moka-py` using `uv`:

```bash
uv add moka-py
```

`poetry`:

```bash
poetry add moka-py
```

Or, if you still stick to `pip` for some reason:

```bash
pip install moka-py
```

## Table of Contents

- [Installation](#installation)
- [Features](#features)
- [Usage](#usage)
    - [Using moka_py.Moka](#using-moka_pymoka)
    - [@cached decorator](#as-a-decorator)
    - [async support](#async-support)
    - [Do not call a function if another function is in progress](#do-not-call-a-function-if-another-function-is-in-progress)
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


# Create a cache with a capacity of 100 entries, with a TTL of 30 seconds
# and a TTI of 5.2 seconds. Entries are always removed after 30 seconds
# and are removed after 5.2 seconds if there are no `get`s happened for this time.
# 
# Both TTL and TTI settings are optional. In the absence of an entry, 
# the corresponding policy will not expire it.

# The default eviction policy is "tiny_lfu" which is optimal for most workloads,
# but you can choose "lru" as well.
cache: Moka[str, list[int]] = Moka(capacity=100, ttl=30, tti=5.2, policy="lru")

# Insert a value.
cache.set("key", [3, 2, 1])

# Retrieve the value.
assert cache.get("key") == [3, 2, 1]

# Wait for 5.2+ seconds, and the entry will be automatically evicted.
sleep(5.3)
assert cache.get("key") is None
```

### As a decorator

moka-py can be used as a drop-in replacement for `@lru_cache()` with TTL + TTI support:

```python
from time import sleep
from moka_py import cached


@cached(maxsize=1024, ttl=10.0, tti=1.0)
def f(x, y):
    print("hard computations")
    return x + y


f(1, 2)  # calls computations
f(1, 2)  # gets from the cache
sleep(1.1)
f(1, 2)  # calls computations (since TTI has passed)
```

### Async support

Unlike `@lru_cache()`, `@moka_py.cached()` supports async functions:

```python
import asyncio
from time import perf_counter
from moka_py import cached


@cached(maxsize=1024, ttl=10.0, tti=1.0)
async def f(x, y):
    print("http request happening")
    await asyncio.sleep(2.0)
    return x + y


start = perf_counter()
assert asyncio.run(f(5, 6)) == 11
assert asyncio.run(f(5, 6)) == 11  # got from cache
assert perf_counter() - start < 4.0
```

### Do not call a function if another function is in progress

moka-py can synchronize threads on keys

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
    sleep(0.3)  # simulation of HTTP request
    return {
        "id": id_,
        "first_name": "Jack",
        "last_name": "Pot",
    }


def process_request(path: str, user_id: int) -> None:
    user = get_user(user_id)
    print(f"user #{user_id} came to {path}, their info is {user}")
    ...


def charge_money(from_user_id: int, amount: Decimal) -> None:
    user = get_user(from_user_id)
    print(f"charging {amount} money from user #{from_user_id} ({user['first_name']} {user['last_name']})")
    ...


if __name__ == '__main__':
    request_processing = threading.Thread(target=process_request, args=("/user/info/123", 123))
    money_charging = threading.Thread(target=charge_money, args=(123, Decimal("3.14")))
    request_processing.start()
    money_charging.start()
    request_processing.join()
    money_charging.join()

    # only one call occurred. without the `wait_concurrent` option, each thread would go for an HTTP request
    # since no cache key was set
    assert len(calls) == 1  
```

> **_ATTENTION:_**  `wait_concurrent` is not yet supported for async functions and will throw `NotImplementedError`

### Eviction listener

moka-py supports adding of an eviction listener that's called whenever a key is dropped
from the cache for some reason. The listener must be a 3-arguments function `(key, value, cause)`. The arguments
are passed as positional (not keyword).

There are 4 reasons why a key may be dropped:

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
    print(f"entry {k}:{v} was evicted. {cause=}")


moka: Moka[str, list[int]] = Moka(2, eviction_listener=key_evicted, ttl=0.1)
moka.set("hello", [1, 2, 3])
moka.set("hello", [3, 2, 1])
moka.set("foo", [4])
moka.set("bar", [])
sleep(1)
moka.get("foo")

# will print
# entry hello:[1, 2, 3] was evicted. cause='replaced'
# entry bar:[] was evicted. cause='size'
# entry hello:[3, 2, 1] was evicted. cause='expired'
# entry foo:[4] was evicted. cause='expired'
```

> **_IMPORTANT NOTES_**:
> 1. It's not guaranteed that the listener will be called just in time. Also, the underlying `moka` doesn't use any
     background threads or tasks, hence, the listener is never called in "background"
> 2. The listener must never raise any kind of `Exception`. If an exception is raised, it might be raised to any of the
     moka-py method in any of the threads that call this method.
> 3. The listener must be fast. Since it's called only when you're interacting with `moka-py` (via `.get()` / `.set()` /
     etc.), the listener will slow down these operations. It's terrible idea to do some sort of IO in the listener. If
     you need so, run a `ThreadPoolExecutor` somewhere and call `.submit()` inside of the listener or commit an async
     task via `asyncio.create_task()`

### Removing entries

An entry can be removed using `Moka.remove(key)`. If a value was set, it is returned; otherwise, `None` is returned.

```python
from moka_py import Moka


c = Moka(128)
c.set("hello", "world")
assert c.remove("hello") == "world"
assert c.get("hello") is None
```

In some cases you may want `None`s to be a valid cache value. In this case you need to distinguish between `None` as a
value and `None` as the absence of a value. Use `Moka.remove(key, default=...)`:

```python
from moka_py import Moka


c = Moka(128)
c.set("hello", None)
assert c.remove("hello", default="WAS_NOT_SET") is None  # None is returned since is was set 

# Now entry with key "hello" doesn't exist so `default` argument is returned 
assert c.remove("hello", default="WAS_NOT_SET") == "WAS_NOT_SET" 
```

## How it works

`Moka` object stores Python object references
(by [`INCREF`ing](https://docs.python.org/3/c-api/refcounting.html#c.Py_INCREF) `PyObject`s) and doesn't use
serialization or deserialization. This means you can use any Python object as a value and any Hashable object as a
key (`Moka` calls keys' `__hash__` magic methods). But also you need to remember that mutable objects stored in `Moka`
are still mutable:

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

moka-py uses the TinyLFU eviction policy as default, with LRU option. You can learn more about the
policies [here](https://github.com/moka-rs/moka/wiki#admission-and-eviction-policies)

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

moka-py is distributed under the [MIT license](LICENSE)
