import asyncio as _asyncio
import inspect as _inspect
from functools import _make_key
from functools import wraps as _wraps
from typing import Any as _Any

from ._moka_py import _VERSION, Moka

__all__ = ["VERSION", "Moka", "cached"]

VERSION = _VERSION


def _make_coalescing_async(fn, cache, typed, empty):
    """Wrap an async fn so the cache holds finished results, not in-flight Tasks.

    Used when both a weigher and wait_concurrent are requested: a Task has no
    result to weigh yet, so concurrent calls coalesce on a side table of Tasks
    and only the awaited value is inserted — weighed synchronously, like any
    other set().
    """
    inflight = {}

    @_wraps(fn)
    async def inner(*args, **kwargs):
        key = _make_key(args, kwargs, typed)
        value = cache.get(key, empty)
        if value is not empty:
            return value
        # Tasks are only awaitable from their own loop, so coalesce
        # per event loop; the cache of results is shared by all
        loop_key = (id(_asyncio.get_running_loop()), key)
        task = inflight.get(loop_key)
        if task is not None:
            return await task
        task = _asyncio.create_task(fn(*args, **kwargs))
        inflight[loop_key] = task
        try:
            value = await task
        finally:
            inflight.pop(loop_key, None)
        cache.set(key, value)
        return value

    return inner


def _make_task_caching_async(fn, cache, typed):
    @_wraps(fn)
    async def inner(*args, **kwargs):
        key = _make_key(args, kwargs, typed)

        # Store a shared Task in cache while computation is in-flight
        def init() -> _Any:
            return _asyncio.create_task(fn(*args, **kwargs))

        task = cache.get_with(key, init)
        return await task

    return inner


def _make_plain_async(fn, cache, typed, empty):
    @_wraps(fn)
    async def inner(*args, **kwargs):
        key = _make_key(args, kwargs, typed)
        maybe_value = cache.get(key, empty)
        if maybe_value is not empty:
            return maybe_value
        value = await fn(*args, **kwargs)
        cache.set(key, value)
        return value

    return inner


def _make_sync(fn, cache, typed, empty, wait_concurrent):
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

    return inner


def cached(
    maxsize=128,
    typed=False,
    *,
    ttl=None,
    tti=None,
    wait_concurrent=False,
    policy="tiny_lfu",
    weigher=None,
):
    """Cache decorator for sync and async functions with TTL/TTI and optional concurrent-waiting.

    - For sync functions: returns cached value if present, otherwise computes and stores it.
    - For async functions: returns an awaitable; with wait_concurrent=True a single shared task is created per key
      so concurrent awaiters share the same result or exception.
    - maxsize bounds the total weight of the cache; every entry weighs 1 unless a weigher
      is given. The weigher receives an opaque hashable key and the computed value; weigh
      the value.
    """
    cache = Moka(maxsize, ttl=ttl, tti=tti, policy=policy, weigher=weigher)
    empty = object()

    def dec(fn):
        if not _inspect.iscoroutinefunction(fn):
            inner = _make_sync(fn, cache, typed, empty, wait_concurrent)
        elif wait_concurrent and weigher is not None:
            inner = _make_coalescing_async(fn, cache, typed, empty)
        elif wait_concurrent:
            inner = _make_task_caching_async(fn, cache, typed)
        else:
            inner = _make_plain_async(fn, cache, typed, empty)

        inner.cache_clear = cache.clear
        return inner

    return dec
