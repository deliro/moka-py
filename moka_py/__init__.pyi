from typing import TypeVar, Optional, Generic, Hashable, Union, Callable, Any, overload, Literal


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
            ttl: Optional[Union[int, float]] = None,
            tti: Optional[Union[int, float]] = None,
            eviction_listener: Optional[Callable[[K, V, Cause], None]] = None,
            policy: Policy = "tiny_lfu",
    ): ...

    def set(self, key: K, value: V) -> None: ...

    @overload
    def get(self, key: K, default: D) -> Union[V, D]: ...

    @overload
    def get(self, key: K, default: Optional[D] = None) -> Optional[Union[V, D]]: ...

    def get_with(self, key: K, initializer: Callable[[], V]) -> V:
        """
        Lookups for a key in the cache and only if there is no value set, calls the `initializer`
        function to set the key's value.
        If multiple threads call `get_with` with the same key, only one of them calls
        `initializer`, and the others wait until the value is set.
        """

    @overload
    def remove(self, key: K, default: D) -> Union[V, D]: ...

    @overload
    def remove(self, key: K, default: Optional[D] = None) -> Optional[Union[V, D]]: ...

    def clear(self) -> None: ...

    def count(self) -> int: ...


def cached(
        maxsize: int = 128,
        typed: bool = False,
        *,
        ttl: Optional[Union[int, float]] = None,
        tti: Optional[Union[int, float]] = None,
        wait_concurrent: bool = False,
        policy: Policy = "tiny_lfu",
) -> Callable[[Fn], Fn]:
    ...
