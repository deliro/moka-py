import asyncio as _asyncio
import inspect as _inspect
from functools import _make_key
from functools import wraps as _wraps
from typing import Any as _Any

from ._moka_py import _VERSION, Moka

__all__ = ["VERSION", "Moka", "cached"]

VERSION = _VERSION


def cached(
    maxsize=128,
    typed=False,
    *,
    ttl=None,
    tti=None,
    wait_concurrent=False,
    policy="tiny_lfu",
):
    """Cache decorator for sync and async functions with TTL/TTI and optional concurrent-waiting.

    - For sync functions: returns cached value if present, otherwise computes and stores it.
    - For async functions: returns an awaitable; with wait_concurrent=True a single shared task is created per key
      so concurrent awaiters share the same result or exception.
    """
    cache = Moka(maxsize, ttl=ttl, tti=tti, policy=policy)
    empty = object()

    def dec(fn):
        if _inspect.iscoroutinefunction(fn):

            @_wraps(fn)
            async def inner(*args, **kwargs):
                key = _make_key(args, kwargs, typed)
                if wait_concurrent:
                    # Store a shared Task in cache while computation is in-flight
                    def init() -> _Any:
                        return _asyncio.create_task(fn(*args, **kwargs))

                    task = cache.get_with(key, init)
                    return await task
                else:
                    maybe_value = cache.get(key, empty)
                    if maybe_value is not empty:
                        return maybe_value
                    value = await fn(*args, **kwargs)
                    cache.set(key, value)
                    return value
        else:

            @_wraps(fn)
            def inner(*args, **kwargs):
                key = _make_key(args, kwargs, typed)
                if wait_concurrent:
                    return cache.get_with(key, lambda: fn(*args, **kwargs))
                else:
                    maybe_value = cache.get(key, empty)
                    if maybe_value is not empty:
                        return maybe_value
                    value = fn(*args, **kwargs)
                    cache.set(key, value)
                    return value

        inner.cache_clear = cache.clear
        return inner

    return dec
