# moka-py

* * * 

**moka-py** is a Python binding for the highly efficient [Moka](https://github.com/moka-rs/moka) caching library written
in Rust. This library allows you to leverage the power of Moka's high-performance, feature-rich cache in your Python
projects.

## Features

- **Synchronous Cache:** Supports thread-safe, in-memory caching for Python applications.
- **TTL Support:** Automatically evicts entries after a configurable time-to-live (TTL).
- **TTI Support:** Automatically evicts entries after a configurable time-to-idle (TTI).
- **Size-based Eviction:** Automatically removes items when the cache exceeds its size limit using the TinyLFU policy.
- **Concurrency:** Optimized for high-performance, concurrent access in multi-threaded environments.

## Installation

You can install `moka-py` using `pip`:

```bash
pip install moka-py
```

## Quick Start

```python
from time import sleep
from moka_py import Moka


# Create a cache with a capacity of 100 entries, with a TTL of 30 seconds
# and a TTI of 5.2 seconds. Entries are always removed after 30 seconds
# and are removed after 5.2 seconds if there are no `get`s happened for this time.
# 
# Both TTL and TTI settings are optional. In the absence of an entry, 
# the corresponding policy will not expire it.
cache: Moka[str, list[int]] = Moka(capacity=100, ttl=30, tti=5.2)

# Insert a value.
cache.set("key", [3, 2, 1])

# Retrieve the value.
assert cache.get("key") == [3, 2, 1]

# Wait for 5.2+ seconds, and the entry will be automatically evicted.
sleep(5.3)
assert cache.get("key") is None
```

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

But unlike `@lru_cache()`, `@moka_py.cached()` also supports async functions:

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

## Performance

*Measured using MacBook Pro 2021 with Apple M1 Pro processor and 16GiB RAM*

```
------------------------------------------------------------------------------------------- benchmark: 5 tests -------------------------------------------------------------------------------------------
Name (time in ns)                    Min                 Max                Mean             StdDev              Median                IQR            Outliers  OPS (Mops/s)            Rounds  Iterations
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
test_bench_get_non_existent     206.3389 (1.0)      208.9872 (1.0)      207.0240 (1.0)       1.1154 (4.27)     206.5119 (1.0)       0.9932 (2.73)          1;1        4.8304 (1.0)           5    10000000
test_bench_get                  224.4981 (1.09)     229.1849 (1.10)     225.8305 (1.09)      1.9252 (7.37)     224.9832 (1.09)      1.8345 (5.05)          1;0        4.4281 (0.92)          5    10000000
test_bench_get_with             248.2484 (1.20)     248.9123 (1.19)     248.5142 (1.20)      0.2612 (1.0)      248.5172 (1.20)      0.3634 (1.0)           2;0        4.0239 (0.83)          5     2020760
test_bench_set_huge             676.6090 (3.28)     692.0143 (3.31)     683.5817 (3.30)      6.5151 (24.94)    684.8168 (3.32)     10.9585 (30.16)         2;0        1.4629 (0.30)          5     1000000
test_bench_set                  723.4063 (3.51)     770.0967 (3.68)     738.1940 (3.57)     18.5167 (70.89)    733.0997 (3.55)     18.1077 (49.83)         1;0        1.3547 (0.28)          5     1000000
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
```

## License

moka-py is distributed under the [MIT license](LICENSE)
