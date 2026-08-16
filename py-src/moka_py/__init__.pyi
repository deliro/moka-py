from collections.abc import Callable, Hashable
from typing import Any, Generic, Literal, TypeVar, overload

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")
D = TypeVar("D")
Fn = TypeVar("Fn", bound=Callable[..., Any])
Cause = Literal["explicit", "size", "expired", "replaced"]
Policy = Literal["tiny_lfu", "lru"]

class Moka(Generic[K, V]):
    def __init__(
        self,
        capacity: int,
        ttl: int | float | None = None,
        tti: int | float | None = None,
        eviction_listener: Callable[[K, V, Cause], None] | None = None,
        policy: Policy = "tiny_lfu",
        weigher: Callable[[K, V], int] | None = None,
    ):
        """Create a cache.

        capacity is the maximum total weight of all entries. Every entry
        weighs 1 unless a weigher is given, in which case it is called once
        per insert (on the calling thread) and must return a non-negative
        int; weights above 2**32 - 1 are clamped to that maximum.
        """
    def set(
        self,
        key: K,
        value: V,
        ttl: int | float | None = None,
        tti: int | float | None = None,
    ) -> None: ...
    @overload
    def get(self, key: K, default: D) -> V | D: ...
    @overload
    def get(self, key: K, default: D | None = None) -> V | D | None: ...
    def get_with(
        self,
        key: K,
        initializer: Callable[[], V],
        ttl: int | float | None = None,
        tti: int | float | None = None,
    ) -> V:
        """Lookup or initialize a value for the key.

        If multiple threads call `get_with` with the same key, only one calls `initializer`,
        the others wait until the value is set.
        """

    @overload
    def remove(self, key: K, default: D) -> V | D: ...
    @overload
    def remove(self, key: K, default: D | None = None) -> V | D | None: ...
    def clear(self) -> None: ...
    def count(self) -> int:
        """Return the approximate number of entries.

        The count may transiently include entries that are pending eviction;
        call run_pending_tasks() first for an accurate number.
        """

    def weighted_size(self) -> int:
        """Return the approximate total weight of all entries.

        Without a weigher every entry weighs 1, so this equals count().
        The value may lag behind pending maintenance; call run_pending_tasks()
        first for an accurate number.
        """

    def run_pending_tasks(self) -> None:
        """Run pending maintenance (evictions, expirations) synchronously.

        Afterwards count() and weighted_size() report converged values.
        """

def cached(
    maxsize: int = 128,
    typed: bool = False,
    *,
    ttl: int | float | None = None,
    tti: int | float | None = None,
    wait_concurrent: bool = False,
    policy: Policy = "tiny_lfu",
    weigher: Callable[[Hashable, Any], int] | None = None,
) -> Callable[[Fn], Fn]:
    """Decorator for caching function results in a thread-safe in-memory cache.

    - If the decorated function is synchronous: returns the cached value or computes and stores it.
    - If the decorated function is asynchronous: returns an awaitable which yields the cached result.
    - If wait_concurrent=True: concurrent calls with the same arguments wait on a single in-flight computation.
      For async functions this is implemented via a shared asyncio.Task; all awaiters receive the same result
      or the same exception.
    - maxsize bounds the total weight of the cache; every entry weighs 1 unless a weigher is
      given. The weigher receives an opaque hashable key and the computed value — weigh the value.
    - With a weigher and wait_concurrent=True, an async function caches finished results instead
      of in-flight Tasks: concurrent calls still share one computation, failed computations are
      not cached, and a weigher error is raised to the call that started the computation.
    """
