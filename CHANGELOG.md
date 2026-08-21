# Changelog

## [0.5.0](https://github.com/deliro/moka-py/compare/0.4.0...0.5.0) (2026-08-21)


### Features

* size-aware capacity via weigher, weighted_size and run_pending_tasks ([2b7176b](https://github.com/deliro/moka-py/commit/2b7176b02f05bf48e14ef5e63a57a280924f0a50))


### Performance

* serve get_with hits via a plain cache read ([54a6fdb](https://github.com/deliro/moka-py/commit/54a6fdba0b25322a552196b4bdbf47397502374f))


### Documentation

* **adr:** ADR-0003 performance program ([7e26d69](https://github.com/deliro/moka-py/commit/7e26d69a4db3842f79cde347ed1c540741cfec37))
* **perf:** record ADR-0003 budget-profile findings ([156c49b](https://github.com/deliro/moka-py/commit/156c49b19aece4e2d1b5fbc514b71ef296139b3c))


### Dependencies

* bump moka in the cargo group across 1 directory ([#27](https://github.com/deliro/moka-py/issues/27)) ([cd29eb4](https://github.com/deliro/moka-py/commit/cd29eb4631f5b220fe91ef282b55dbec6a380e24))
* bump ruff in the python group across 1 directory ([#28](https://github.com/deliro/moka-py/issues/28)) ([6cb94f6](https://github.com/deliro/moka-py/commit/6cb94f610d04b48ba2a11c74b72793dc079a43b2))

## [0.4.0](https://github.com/deliro/moka-py/compare/0.3.0...0.4.0) (2026-08-07)


### ⚠ BREAKING CHANGES

* Python 3.9 is no longer supported; the minimum supported version is 3.10.

### Features

* v0.4.0 — Python 3.15, PyO3 0.29, mimalloc, WASM/Android wheels ([#15](https://github.com/deliro/moka-py/issues/15)) ([a8eee09](https://github.com/deliro/moka-py/commit/a8eee097a10dfc39a7fd228c874fdd97daebc023))


### Bug Fixes

* reject non-finite and out-of-range ttl/tti values ([#19](https://github.com/deliro/moka-py/issues/19)) ([803fcea](https://github.com/deliro/moka-py/commit/803fceaec1b8a8de80b9fa4c51d6145020cdd5f3))


### Documentation

* add status badges and wire up coverage reporting ([#23](https://github.com/deliro/moka-py/issues/23)) ([66db1b3](https://github.com/deliro/moka-py/commit/66db1b36b628e9917495080f49f61d331639cc9e))
