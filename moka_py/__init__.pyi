from typing import TypeVar, Optional, Generic, Hashable, Union, Callable, Any


K = TypeVar("K", bound=Hashable)
V = TypeVar("V")
Fn = TypeVar("Fn", bound=Callable[..., Any])


class Moka(Generic[K, V]):
    def __init__(
            self,
            capacity: int,
            ttl: Optional[Union[int, float]] = None,
            tti: Optional[Union[int, float]] = None,
    ): ...

    def set(self, key: K, value: V) -> None: ...

    def get(self, key: K) -> Optional[V]: ...

    def get_with(self, key: K, initializer: Callable[[], V]) -> V:
        """
        Lookups for a key in the cache and only if there is no value set, calls the `initializer`
        function to set the key's value.
        If multiple threads call `get_with` with the same key, only one of them calls
        `initializer`, and the others wait until the value is set.
        """

    def remove(self, key: K) -> Optional[V]: ...

    def clear(self) -> None: ...

    def count(self) -> int: ...


def cached(
        maxsize: int = 128,
        typed: bool = False,
        *,
        ttl: Optional[Union[int, float]] = None,
        tti: Optional[Union[int, float]] = None,
        wait_concurrent: bool = False,
) -> Callable[[Fn], Fn]:
    ...
