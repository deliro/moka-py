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
- **Integration with Python:** Simplifies usage with Python-friendly APIs via `pyo3`.

## Installation

You can install `moka-py` using `pip`:

```bash
pip install moka-py
```

## Quick Start

```python
from time import sleep
from moka_py import Moka

# Create a cache with a capacity of 100 entries and, TTL of 30 seconds
# and TTI of 5.2 seconds. Entires are always removed after 30 seconds
# and are removed after 5.2 seconds if no `get`s happened for this time
cache: Moka[list[int]] = Moka(capacity=100, ttl=30, tti=5.2)

# Insert a value.
cache.set("key", [3, 2, 1])

# Retrieve the value.
assert cache.get("key") == [3, 2, 1]

# Wait for 5.2+ seconds, and the entry will be automatically evicted.
sleep(5.3)
assert cache.get("key") is None
```

## License

moka-py is distributed under the [MIT license](LICENSE)
