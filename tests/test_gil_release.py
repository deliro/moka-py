"""Regression tests for #35: moka calls must not hold the GIL.

moka runs Python code from inside its own locks: the eviction listener is
delivered while the evicted key's lock is held, and a key's ``__eq__`` runs
during hash-table and maintenance work. Any such Python code can give the GIL
away. If another thread then blocks inside moka *while holding the GIL* (on
that key lock, or busy-waiting on the full write buffer behind a maintenance
run owned by the first thread), the first thread can never get the GIL back
and the process hangs without an exception.

Each scenario runs in a subprocess: a deadlocked thread keeps the GIL, so an
in-process test could not even reach its assertion to fail.
"""

import subprocess
import sys
import textwrap

import pytest

TIMEOUT = 120.0

# Threads replacing the same key with an eviction listener installed:
# `set()` → replace → listener runs under that key's lock (the issue's repro).
SHARED_KEY_WITH_LISTENER = """
    import threading
    from moka_py import Moka

    events = []

    def key_evicted(k, v, cause):
        events.append((k, v, cause))

    moka = Moka(1000, eviction_listener=key_evicted)

    def work():
        for i in range(50_000):
            moka.set("hello", [i])

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert events, "replacing a key must notify the listener"
    print("finished")
"""

# No listener at all: keys whose __eq__ is Python code, in an over-capacity
# cache, so maintenance compares keys while other threads keep writing.
PYTHON_EQ_KEYS_OVER_CAPACITY = """
    import threading
    from dataclasses import dataclass
    from moka_py import Moka

    @dataclass(frozen=True)
    class Key:
        a: int
        b: str

    moka = Moka(64)

    def work():
        for i in range(50_000):
            moka.set(Key(i, "x"), i)

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print("finished")
"""

# Readers drive maintenance too: with a listener, evicting a victim takes its
# key lock, which a writer may hold while it is inside the listener.
READERS_WITH_LISTENER_OVER_CAPACITY = """
    import threading
    from moka_py import Moka

    events = []

    def listener(k, v, cause):
        events.append(cause)

    moka = Moka(64, eviction_listener=listener)
    stop = threading.Event()

    def setter(offset):
        for i in range(50_000):
            moka.set((i + offset) % 256, i)

    def getter():
        i = 0
        while not stop.is_set():
            moka.get(i % 256)
            i += 1

    setters = [threading.Thread(target=setter, args=(o,)) for o in (0, 64, 128)]
    getters = [threading.Thread(target=getter) for _ in range(2)]
    for t in setters + getters:
        t.start()
    for t in setters:
        t.join()
    stop.set()
    for t in getters:
        t.join()
    assert events, "an over-capacity cache must evict"
    print("finished")
"""

# `remove()` delivers the "explicit" notification under the key lock as well.
REMOVE_WITH_LISTENER = """
    import threading
    from moka_py import Moka

    events = []

    def listener(k, v, cause):
        events.append(cause)

    moka = Moka(1000, eviction_listener=listener)

    def work():
        for i in range(50_000):
            moka.set("hello", i)
            moka.remove("hello")

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert events, "removing a key must notify the listener"
    print("finished")
"""


@pytest.mark.parametrize(
    "script",
    [
        SHARED_KEY_WITH_LISTENER,
        PYTHON_EQ_KEYS_OVER_CAPACITY,
        READERS_WITH_LISTENER_OVER_CAPACITY,
        REMOVE_WITH_LISTENER,
    ],
    ids=[
        "shared_key_with_listener",
        "python_eq_keys_over_capacity",
        "readers_with_listener_over_capacity",
        "remove_with_listener",
    ],
)
def test_concurrent_cache_operations_do_not_deadlock(script: str) -> None:
    proc = subprocess.run(  # noqa: S603 - fixed interpreter and script text
        [sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "finished"
