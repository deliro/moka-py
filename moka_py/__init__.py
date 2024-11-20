import asyncio
from functools import wraps, _make_key
from .moka_py import Moka


__all__ = ["Moka", "cached"]


def cached(maxsize=128, typed=False, *, ttl=None, tti=None):
    cache = Moka(maxsize, ttl, tti)

    def dec(fn):
        if asyncio.iscoroutinefunction(fn):
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
                maybe_value = cache.get(key)
                if maybe_value is not None:
                    return maybe_value
                value = fn(*args, **kwargs)
                cache.set(key, value)
                return value

        return inner

    return dec
