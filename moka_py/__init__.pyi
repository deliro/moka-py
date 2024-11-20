import sys
from typing import TypeVar, Optional, Generic, Hashable, Union, Callable


K = TypeVar("K", bound=Hashable)
V = TypeVar("V")
T = TypeVar("T")


class Moka(Generic[K, V]):
    def __init__(
            self,
            capacity: int,
            ttl: Optional[Union[int, float]] = None,
            tti: Optional[Union[int, float]] = None,
    ): ...

    def set(self, key: K, value: V) -> None: ...

    def get(self, key: K) -> Optional[V]: ...

    def remove(self, key: K) -> Optional[V]: ...

    def clear(self) -> None: ...

    def count(self) -> int: ...


if sys.version >= (3, 10):
    from typing import ParamSpec, Callable


    P = ParamSpec("P")


    def cached(
            maxsize: int = 128,
            typed: bool = False,
            *,
            ttl: Optional[Union[int, float]] = None,
            tti: Optional[Union[int, float]] = None,
    ) -> Callable[[Callable[P, T]], Callable[P, T]]:
        ...
else:
    def cached(
            maxsize: int = 128,
            typed: bool = False,
            *,
            ttl: Optional[Union[int, float]] = None,
            tti: Optional[Union[int, float]] = None,
    ) -> Callable[[Callable], Callable]:
        ...