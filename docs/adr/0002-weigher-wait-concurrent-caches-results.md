# With a weigher, async wait_concurrent caches results, not Tasks

`@cached(wait_concurrent=True)` on an async function normally stores the
in-flight `asyncio.Task` in the cache so concurrent awaiters share one
computation. A weigher cannot weigh a Task (there is no result yet), so when
both a weigher and `wait_concurrent=True` are given for an async function,
the decorator switches strategy: in-flight Tasks coalesce in a side table
keyed by `(event loop id, key)`, and only the awaited result is inserted into
the cache — weighed synchronously like any other `set()` (ADR-0001).

## Considered Options

1. **Reject the combination** (`ValueError` at decoration) — safe but blocks a
   common scenario (weight-bounded caching of async fetches).
2. **Cache the Task with weight 0, re-weigh via done-callback** — creates a
   window where in-flight entries are free (budget overshoot), surfaces
   weigher errors asynchronously in the event loop handler (breaking the
   "weigher error = insert error" contract), and emits a spurious `replaced`
   eviction event per completion.
3. **Coalesce in-flight Tasks separately, cache finished results** — chosen.

## Consequences

- Concurrent-call coalescing is per event loop; the result cache is shared by
  all loops and threads. (Cached results, unlike Tasks, are safe to read from
  any loop.)
- A failed computation is not cached; every waiter sharing the Task receives
  the exception.
- Asymmetry: if the weigher itself raises, the error propagates to the call
  that started the computation, while concurrent waiters already received the
  computed value.
- The plain `wait_concurrent=True` path (no weigher) is deliberately left
  untouched to avoid changing behavior for existing users, including its
  quirk of keeping a failed Task cached until expiry.
