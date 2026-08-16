# Eager weighing outside moka internals

The weigher feature exposes a moka-style constructor callback
(`Moka(capacity, weigher=lambda k, v: int)`), but we deliberately do NOT wire
the Python callable into moka's own `builder().weigher(..)` callback path.
Instead, the weight is computed eagerly in `set()` / `get_with()` on the
calling thread (GIL already held) before the entry enters moka; the value
wrapper stores the precomputed weight and the Rust-side weigher closure merely
reads that field. This keeps arbitrary Python code out of moka's internal
locks — a Python weigher invoked from inside the cache could re-enter the
cache and deadlock (the known hazard of sync-cache eviction listeners) and
would have no natural channel for exceptions. With eager weighing, a weigher
exception simply propagates from `set()`/`get_with()` and the insert never
happens ("weigher error = insert error"; for `get_with`, all concurrent
waiters receive the exception and nothing is cached, matching
`try_get_with` error semantics).

## Considered Options

1. **Callback inside moka** (exact moka semantics) — rejected: re-entrancy /
   deadlock risk inside cache internals, no exception channel, a Python call
   per admission from foreign contexts.
2. **Explicit `weight=` argument on `set()`** — rejected: spreads the source
   of truth over every call-site and cannot serve the `@cached` decorator.
3. **Constructor callback, evaluated eagerly before insertion** — chosen.

## Consequences

- Weight is fixed per entry version; a replace via `set()` recomputes it —
  identical to moka's observable behavior.
- Weigher return contract: `0` allowed (entry spends no capacity budget),
  negative raises `ValueError`, values above `u32::MAX` clamp to `u32::MAX`,
  non-int raises `TypeError` (`bool` passes as an int subclass).
- `capacity` always bounds the total weight of all entries; every entry
  weighs 1 unless a weigher computes otherwise, so without a weigher it
  degenerates to the maximum entry count (same single-parameter model as
  moka's `max_capacity`).
