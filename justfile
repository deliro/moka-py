default: check

lint:
    cargo clippy --all-targets --all-features -- -D warnings -W clippy::style -D clippy::perf

clippy: lint

fmt:
    cargo fmt

fmt-check:
    cargo fmt -- --check

check: fmt lint

dev:
    uv venv --allow-existing
    uv run maturin develop --release

test: dev
    uv run pytest tests/ -v --ignore=tests/test_benches.py

bench: dev
    uv run pytest tests/test_benches.py

build:
    uv run maturin build --release

clean:
    cargo clean
    rm -rf dist/
    rm -rf target/wheels/
    uv venv --clear
