import asyncio as _asyncio
from functools import wraps as _wraps, _make_key
from .moka_py import Moka, get_version as _get_version


__all__ = ["Moka", "cached", "VERSION"]

VERSION = _get_version()


def cached(maxsize=128, typed=False, *, ttl=None, tti=None, wait_concurrent=False, policy="tiny_lfu"):
    cache = Moka(maxsize, ttl=ttl, tti=tti, policy=policy)
    empty = object()

    def dec(fn):
        if _asyncio.iscoroutinefunction(fn):
            if wait_concurrent:
                raise NotImplementedError("wait_concurrent is not yet supported for async functions")

            @_wraps(fn)
            async def inner(*args, **kwargs):
                key = _make_key(args, kwargs, typed)
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
