# Performance program: single-threaded latency, transparent-only

moka-py's performance goal is to iteratively reduce the latency of single
operations (`get` hit above all, then `get_with` as the killer feature, `set`
as the profile dictates) in the **single-threaded** scenario, measured against
our own saved baseline. The external reference points are `cachebox` and
`theine` — the claim we aim for is "the fastest feature-complete Python
cache". `lru-dict` and `functools.lru_cache` are shown honestly in benchmark
tables but are not promised to be beaten: they play in a different category
(no TTL / weigher / eviction listeners — they do strictly less work per
operation). Free-threaded Python is supported as nice-to-have but is not a
performance target; hit-rate improvements belong upstream in moka itself.

All optimizations must be **transparent**: the public API and observable
semantics are frozen. Tuning knobs (constructor flags that trade features for
speed) and semantic changes are out of scope — if transparent optimization
hits a ceiling, adding a knob is a new decision requiring its own ADR.

## Considered Options

1. **Concurrent / free-threaded throughput as the headline target** —
   rejected: free-threaded Python is a marginal branch we do not bet on;
   single-threaded latency is what real workloads and competitor tables
   measure.
2. **Opt-in performance knobs** (`Moka(..., per_entry_expiry=False)` etc.) —
   rejected for now: multiplies the test/docs matrix, most users never touch
   knobs, and "fastest if configured correctly" undermines the claim on
   default configuration.
3. **Transparent-only optimization against a saved local baseline** — chosen.

## Merge bar

- A standalone optimization must show **≥3%** improvement on its target
  operation over the saved baseline.
- Anything requiring `unsafe`, logic duplication, or bypassing PyO3
  abstractions must buy **≥10%**.
- A regression **>1%** on any other benchmarked operation blocks the merge,
  regardless of the win.
- Sub-threshold wins are batched into one PR, not spread across many.

## Measurement protocol

- Local only, no CI benchmarking. Canonical environment: one dedicated Mac,
  mains power, pinned Python version.
- pytest-benchmark with `--benchmark-save` per commit and
  `--benchmark-compare` against the stored baseline (`just bench-save` /
  `bench-compare` / `bench-verdict`).
- Benchmark matrix (~15 cases): `get` hit/miss × {int, short str, long str,
  tuple}, `set` int/str + replace of an existing key, `get_with` hit/miss
  (cheap initializer), `remove` hit/miss.
- Any optimization round starts with a budget profile — a nanosecond
  breakdown of the target operation across layers (CPython call → PyO3
  argument parsing → key hash → moka core → INCREF/result) — not with code
  changes.

### Noise control

Measured 2026-08: two runs of the *same binary* swung str/tuple `get`
benches by ±13% while int stayed within ±2%. Cause: a single needle's
collision-chain length is a per-process lottery — CPython randomizes
str/tuple hashes per process, and each `Moka` instance draws random ahash
seeds. A merge bar of 1% is unenforceable against that floor, so the
protocol requires all three of:

- `PYTHONHASHSEED=0` for every benchmark run (baked into the just targets) —
  removes the CPython side of the lottery;
- `get` benches cycle over a pool of ~100 equal-but-not-identical needles
  instead of hammering one key — averages bucket luck (including the ahash
  side, which cannot be pinned transparently) at the cost of a constant
  `next()` overhead in every number;
- a merge verdict uses the **median of ≥3 process runs**
  (`just bench-verdict`), never a single comparison; a single
  `bench-compare` run is for iteration speed only.

Cross-build comparisons carry an additional code-layout component that
cannot be eliminated; deltas below ~2% on a single operation are treated as
unattributable even under this protocol.

## Consequences

- The bridge code stays honest: no fast-path spaghetti justified by
  sub-percent wins; complexity must be paid for by double-digit percentages.
- Deliberately excluded from the matrix: multi-threaded benches
  (free-threading is nice-to-have), large payloads (the value is always a
  single pointer; object size does not affect bridge latency), exotic key
  types.
- README benchmark tables remain a showcase; the regression instrument is the
  saved local baselines.

## Follow-up: 2026-08-21 budget profile

The budget-profile step this ADR mandates was executed; full findings in
[docs/perf/2026-08-21-op-budget.md](../perf/2026-08-21-op-budget.md).
Headline: after 54a6fdb the bridge contributes ~7ns of glue plus ~9ns of
semantically-required Python calls (hash + `__eq__`) to a ~40-50ns moka-core
read; no double-digit transparent win remains in `src/lib.rs` for `get`/`set`.
Levers measured and closed: PyO3 argument parsing (~5ns), `Arc<Py>` double
indirection (~1ns), replacing/dropping the second (ahash) hash pass
(identity hashing collapses 30-80x on stride-4096 int keys). Open levers,
each requiring a new decision: the always-installed `expire_after` read tax
(~5-10ns on a get hit), a sub-threshold batch (skip `Instant::now()` when no
per-entry ttl/tti), and upstream moka work (read machinery, insert path).
