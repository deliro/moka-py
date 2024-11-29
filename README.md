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

## License

moka-py is distributed under the [MIT license](LICENSE)
