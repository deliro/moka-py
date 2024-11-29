import asyncio
from functools import wraps, _make_key
from .moka_py import Moka


__all__ = ["Moka", "cached"]


def cached(maxsize=128, typed=False, *, ttl=None, tti=None, wait_concurrent=False):
    cache = Moka(maxsize, ttl, tti)

    def dec(fn):
        if asyncio.iscoroutinefunction(fn):
            if wait_concurrent:
                raise NotImplementedError("wait_concurrent is not yet supported for async functions")

            @wraps(fn)
            async def inner(*args, **kwargs):
                key = _make_key(args, kwargs, typed)
                maybe_value = cache.get(key)
                if maybe_value is not None:
                    return maybe_value
                value = await fn(*args, **kwargs)
                cache.set(key, value)
                return value
        else:
            @wraps(fn)
            def inner(*args, **kwargs):
                key = _make_key(args, kwargs, typed)
                if wait_concurrent:
                    return cache.get_with(key, lambda: fn(*args, **kwargs))
                else:
                    maybe_value = cache.get(key)
                    if maybe_value is not None:
                        return maybe_value
                    value = fn(*args, **kwargs)
                    cache.set(key, value)
                    return value

        inner.cache_clear = cache.clear
        return inner

    return dec
