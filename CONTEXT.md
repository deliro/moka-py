# moka-py

Python bindings for the Rust moka caching library. One context: an in-memory
concurrent cache exposed to Python.

## Language

**Weigher**:
A user-supplied Python callable `(key, value) -> int` fixed at cache
construction that determines an entry's weight. Evaluated eagerly on the
calling thread during `set()`/`get_with()`, never from inside the cache's
internals.
_Avoid_: sizer, cost function

**Weight**:
The non-negative integer cost of a single entry, fixed at insert time and
recomputed when the entry is replaced. Every entry weighs 1 unless a weigher
computes otherwise. Zero means the entry spends no capacity budget; values
above the cache's internal maximum are treated as that maximum.
_Avoid_: size (collides with the `"size"` eviction cause)

**Capacity**:
The cache's `max_capacity` bound: the maximum total weight of all entries.
Since entries weigh 1 by default, without a weigher this equals the maximum
number of entries.
_Avoid_: maxsize (the `@cached` decorator parameter name), limit
