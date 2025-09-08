import threading
from time import sleep

import pytest

import moka_py


def test_decorator_typed_flag():
    calls = []

    @moka_py.cached(typed=True)
    def f(x):
        calls.append(x)
        return x

    f(1)
    f(1.0)
    assert len(calls) == 2


def test_decorator_ttl():
    calls = []

    @moka_py.cached(ttl=0.2)
    def f(x):
        calls.append(x)
        return x

    assert f(1) == 1
    assert f(1) == 1
    sleep(0.22)
    assert f(1) == 1
    assert len(calls) == 2


def test_decorator_tti():
    calls = []

    @moka_py.cached(tti=0.2)
    def f(x):
        calls.append(x)
        return x

    assert f(1) == 1
    sleep(0.1)
    assert f(1) == 1
    sleep(0.1)
    assert f(1) == 1
    sleep(0.25)
    assert f(1) == 1
    assert len(calls) == 2


def test_count_and_clear():
    c = moka_py.Moka(3)
    before = c.count()
    c.set("a", 1)
    c.set("b", 2)
    # Count may be approximate; verify behaviorally
    assert c.get("a") == 1
    assert c.get("b") == 2
    c.set("a", 3)
    assert c.get("a") == 3
    assert c.remove("a") == 3
    assert c.get("a") is None
    c.clear()
    after = c.count()
    assert c.get("b") is None
    assert after <= before


def test_get_with_exception_retry():
    c = moka_py.Moka(16)
    called = {"n": 0}

    def init():
        called["n"] += 1
        if called["n"] == 1:
            raise RuntimeError("boom")
        return "ok"

    with pytest.raises(RuntimeError):
        c.get_with("k", init)
    assert c.get("k") is None
    assert c.get_with("k", init) == "ok"
    assert called["n"] == 2


def test_sync_wait_concurrent_exception():
    calls = []

    @moka_py.cached(wait_concurrent=True)
    def f(x):
        calls.append(x)
        sleep(0.1)
        raise ValueError("bad")

    def target():
        with pytest.raises(ValueError):
            f(1)

    threads = [threading.Thread(target=target) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1


@pytest.mark.parametrize(
    "ttl,tti",
    [
        (0.0, None),
        (-1.0, None),
        (None, 0.0),
        (None, -2.0),
    ],
)
def test_invalid_ttl_tti(ttl, tti):
    kwargs = {}
    if ttl is not None:
        kwargs["ttl"] = ttl
    if tti is not None:
        kwargs["tti"] = tti
    with pytest.raises(ValueError):
        moka_py.Moka(4, **kwargs)


def test_unhashable_key():
    c = moka_py.Moka(4)
    with pytest.raises(TypeError):
        c.set(["a"], 1)
