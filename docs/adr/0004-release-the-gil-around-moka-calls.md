# Release the GIL around moka calls that can wait

moka's sync cache runs Python code from inside its own synchronization:
the eviction listener is delivered while the evicted key's lock is held
(`do_insert_with_hash`, `invalidate_with_hash`, victim eviction in the
maintenance run), and a key's `__eq__` runs through `AnyKey::eq` inside the
hash table and the maintenance run. Both can give the GIL away. A second
thread that then enters moka *holding the GIL* and waits for the first one
(on that key lock, or busy-waiting in `schedule_write_op` because the write
buffer is full and the maintenance run belongs to the first thread) starves
it of the GIL for good: the process hangs with no exception (#35). On
free-threaded builds the attached-but-blocked thread additionally stalls the
stop-the-world phase of a garbage collection started inside the listener.

Until 0.5.0, `set()`, `get()`, `remove()` and the `get_with()` hit path
called moka attached; the releases had been removed as single-threaded
optimizations (9044c0d, 54a6fdb). The hazard does not depend on the
listener: Python `__eq__` on keys plus the write-buffer wait is enough.

The rule is now: **a thread may hold the GIL inside moka only on a path that
cannot wait for another thread.**

- `set()` and `remove()` always run detached (`py.detach`): both can take a
  key lock and both go through the write-buffer wait.
- `get()` and the `get_with()` hit path run detached only when an eviction
  listener is installed. Without one, moka's read path never waits: the
  table read is lock-free, the read buffer is fed with `try_send` and
  discards on full, and the maintenance run is entered with `try_lock`.
  With a listener, the maintenance run a read may perform takes per-key
  locks that a writer can hold while it waits for the GIL inside the
  listener.
- The `get_with()` miss path, `clear()`, `count()`, `run_pending_tasks()`
  and `weighted_size()` were already detached and stay so.

## Considered Options

1. **Keep the GIL, move Python out of moka** (queue listener notifications
   and deliver them after the call returns) — rejected: `__eq__` cannot be
   deferred, and the write-buffer wait exists without a listener.
2. **Detach every call unconditionally** — correct and simplest, rejected
   for the read path: on the dev box a `get` hit went from ~100 ns to
   ~220 ns (one detach/attach pair, plus a second GIL round trip when
   `AnyKey::eq` re-attaches for a non-identical needle), with no safety
   gained for caches without a listener.
3. **Detach writes always, reads only with a listener** — chosen.

## Consequences

- Cost, dev box (aarch64 Linux VM, not the ADR-0003 canonical machine,
  single run against a saved baseline): `set` +8..12%, `remove` hit +20%,
  `remove` miss +40 ns (37 -> 77 ns), `get`/`get_with` hits and misses
  unchanged without a listener; with a listener every operation pays one
  detach/attach pair, and a non-identical equal key adds a second GIL round
  trip inside `AnyKey::eq`. ADR-0003's merge bar is for optimizations; this
  is a correctness floor that no future optimization may remove. Any perf
  work that wants to drop a `py.detach` must first show the path cannot
  wait for another thread.
- The read-path exemption rests on three properties of moka 0.12's read
  path (lock-free table read, discarding `try_send`, `try_lock` for
  maintenance). A moka bump should re-check them; `tests/test_gil_release.py`
  exercises the known hazards in subprocesses with a timeout.
- `AnyKey::eq` and the listener call `Python::attach` from a detached
  thread; the GIL is held only for the Python call, never across a wait on
  a moka lock. `Py` objects dropped inside moka while detached are
  released through PyO3's deferred reference pool when the call re-attaches.
- Unchanged: a listener that calls back into the same cache can still
  self-deadlock on moka's (non-reentrant) key lock. That is moka's
  documented constraint for the sync cache, not a GIL matter.
