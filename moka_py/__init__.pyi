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
    ): ...
    def set(self, key: K, value: V) -> None: ...
    @overload
    def get(self, key: K, default: D) -> V | D: ...
    @overload
    def get(self, key: K, default: D | None = None) -> V | D | None: ...
    def get_with(self, key: K, initializer: Callable[[], V]) -> V:
        """Lookup or initialize a value for the key.

        If multiple threads call `get_with` with the same key, only one calls `initializer`,
        the others wait until the value is set.
        """

    @overload
    def remove(self, key: K, default: D) -> V | D: ...
    @overload
    def remove(self, key: K, default: D | None = None) -> V | D | None: ...
    def clear(self) -> None: ...
    def count(self) -> int: ...

def cached(
    maxsize: int = 128,
    typed: bool = False,
    *,
    ttl: int | float | None = None,
    tti: int | float | None = None,
    wait_concurrent: bool = False,
    policy: Policy = "tiny_lfu",
) -> Callable[[Fn], Fn]:
    """Decorator for caching function results in a thread-safe in-memory cache.

    - If the decorated function is synchronous: returns the cached value or computes and stores it.
    - If the decorated function is asynchronous: returns an awaitable which yields the cached result.
    - If wait_concurrent=True: concurrent calls with the same arguments wait on a single in-flight computation.
      For async functions this is implemented via a shared asyncio.Task; all awaiters receive the same result
      or the same exception.
    """
