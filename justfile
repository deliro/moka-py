default: check

lint-py:
    uv run ruff check .

lint-rust:
    cargo clippy --all-targets --all-features -- -D warnings -W clippy::style -D clippy::perf

lint: lint-py lint-rust

# Supply-chain audits (same checks CI runs)
deny:
    cargo deny check advisories bans licenses sources

# `uv export` already pins every transitive dependency, so --no-deps keeps
# pip-audit from building an isolated resolution environment.
audit-py:
    uv export --no-emit-project --all-groups --format requirements-txt > /tmp/moka-py-requirements.txt
    uvx pip-audit --strict --no-deps --disable-pip --requirement /tmp/moka-py-requirements.txt

audit: deny audit-py

# Test run with coverage, same invocation CI uses
coverage: dev
    uv run pytest tests/ --ignore=tests/test_benches.py --ignore=tests/test_wasm.py --cov --cov-report=term --cov-report=xml

clippy: lint

fmt-py:
    uv run ruff format --exit-non-zero-on-format .

fmt-rust:
    cargo fmt

fmt: fmt-py fmt-rust

check: fmt lint

dev:
    uv venv --allow-existing
    uv run maturin develop --release

test: dev
    uv run pytest tests/ -v --ignore=tests/test_benches.py

# PYTHONHASHSEED=0 removes CPython's per-process str/tuple hash randomization,
# one of the two sources of run-to-run bucket-luck noise (ADR-0003); the other
# (per-instance ahash seeds) is averaged out by the needle pools in the benches.
bench: dev
    PYTHONHASHSEED=0 uv run pytest --benchmark-min-time=0.5 tests/test_benches.py

# Save a named baseline (ADR-0003: canonical machine, mains power only)
bench-save name: dev
    PYTHONHASHSEED=0 uv run pytest --benchmark-min-time=0.5 --benchmark-save={{name}} tests/test_benches.py

# Compare the current code against a saved baseline (single run, for iteration)
bench-compare name: dev
    PYTHONHASHSEED=0 uv run pytest --benchmark-min-time=0.5 --benchmark-compare={{name}} tests/test_benches.py

# Merge verdict: three process runs against a baseline; judge by the median
# of the three (ADR-0003)
bench-verdict name: dev
    PYTHONHASHSEED=0 uv run pytest --benchmark-min-time=0.5 --benchmark-compare={{name}} tests/test_benches.py
    PYTHONHASHSEED=0 uv run pytest --benchmark-min-time=0.5 --benchmark-compare={{name}} tests/test_benches.py
    PYTHONHASHSEED=0 uv run pytest --benchmark-min-time=0.5 --benchmark-compare={{name}} tests/test_benches.py

build:
    uv run maturin build --release

clean:
    cargo clean
    rm -rf dist/
    rm -rf target/wheels/
    uv venv --clear
