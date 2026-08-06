#[cfg(feature = "mimalloc")]
#[global_allocator]
static GLOBAL_ALLOCATOR: mimalloc::MiMalloc = mimalloc::MiMalloc;

#[pyo3::pymodule(name = "_moka_py")]
mod moka_py {
    use std::{
        hash::{Hash, Hasher},
        str::FromStr,
        sync::Arc,
        time::{Duration, Instant},
    };

    use moka::{Expiry, notification::RemovalCause, policy::EvictionPolicy, sync::Cache};
    use pyo3::{exceptions::PyValueError, prelude::*, types::PyType};

    #[pymodule_export]
    const _VERSION: &str = env!("CARGO_PKG_VERSION");

    #[derive(Debug)]
    struct AnyKey {
        obj: Py<PyAny>,
        py_hash: isize,
    }

    impl AnyKey {
        #[inline]
        fn new_with_gil(obj: Py<PyAny>, py: Python) -> PyResult<Self> {
            let py_hash = obj.bind_borrowed(py).hash()?;
            Ok(AnyKey { obj, py_hash })
        }
    }

    impl PartialEq for AnyKey {
        #[inline]
        fn eq(&self, other: &Self) -> bool {
            if self.obj.is(&other.obj) {
                return true;
            }
            self.py_hash == other.py_hash
                && Python::attach(|py| {
                    let lhs = self.obj.bind_borrowed(py);
                    let rhs = other.obj.bind_borrowed(py);
                    lhs.eq(rhs).unwrap_or_default()
                })
        }
    }

    impl Eq for AnyKey {}
    impl Hash for AnyKey {
        #[inline]
        fn hash<H: Hasher>(&self, state: &mut H) {
            state.write_isize(self.py_hash)
        }
    }

    #[inline]
    fn cause_to_str(cause: RemovalCause) -> &'static str {
        match cause {
            RemovalCause::Expired => "expired",
            RemovalCause::Explicit => "explicit",
            RemovalCause::Replaced => "replaced",
            RemovalCause::Size => "size",
        }
    }

    #[derive(Copy, Clone, Debug)]
    enum Policy {
        Lru,
        TinyLfu,
    }

    impl FromStr for Policy {
        type Err = String;

        fn from_str(s: &str) -> Result<Self, Self::Err> {
            match s {
                "tiny_lfu" => Ok(Policy::TinyLfu),
                "lru" => Ok(Policy::Lru),
                v => Err(format!("'{v}' is not valid policy")),
            }
        }
    }

    impl From<Policy> for EvictionPolicy {
        fn from(value: Policy) -> Self {
            match value {
                Policy::Lru => EvictionPolicy::lru(),
                Policy::TinyLfu => EvictionPolicy::tiny_lfu(),
            }
        }
    }

    #[inline]
    fn parse_duration(value: Option<f64>, name: &str) -> PyResult<Option<Duration>> {
        match value {
            Some(v) => {
                let micros = (v * 1_000_000.0) as u64;
                if micros == 0 {
                    return Err(PyValueError::new_err(format!("{name} must be positive")));
                }
                Ok(Some(Duration::from_micros(micros)))
            }
            None => Ok(None),
        }
    }

    #[derive(Clone)]
    struct ValueWrapper {
        value: Arc<Py<PyAny>>,
        per_entry_ttl: Option<Duration>,
        per_entry_tti: Option<Duration>,
        created_at: Instant,
    }

    struct PerEntryExpiry;

    impl PerEntryExpiry {
        #[inline]
        fn remaining_ttl(value: &ValueWrapper, now: Instant) -> Option<Duration> {
            value.per_entry_ttl.map(|ttl| {
                let elapsed = now.saturating_duration_since(value.created_at);
                ttl.saturating_sub(elapsed)
            })
        }
    }

    impl Expiry<AnyKey, ValueWrapper> for PerEntryExpiry {
        fn expire_after_create(
            &self,
            _key: &AnyKey,
            value: &ValueWrapper,
            _created_at: Instant,
        ) -> Option<Duration> {
            match (value.per_entry_ttl, value.per_entry_tti) {
                (Some(ttl), Some(tti)) => Some(ttl.min(tti)),
                (Some(x), None) | (None, Some(x)) => Some(x),
                (None, None) => None,
            }
        }

        fn expire_after_read(
            &self,
            _key: &AnyKey,
            value: &ValueWrapper,
            read_at: Instant,
            duration_until_expiry: Option<Duration>,
            _last_modified_at: Instant,
        ) -> Option<Duration> {
            let remaining_ttl = Self::remaining_ttl(value, read_at);
            match (value.per_entry_tti, remaining_ttl) {
                (Some(tti), Some(ttl_rem)) => Some(tti.min(ttl_rem)),
                (Some(tti), None) => Some(tti),
                (None, _) => duration_until_expiry,
            }
        }

        fn expire_after_update(
            &self,
            _key: &AnyKey,
            value: &ValueWrapper,
            _updated_at: Instant,
            _duration_until_expiry: Option<Duration>,
        ) -> Option<Duration> {
            match (value.per_entry_ttl, value.per_entry_tti) {
                (Some(ttl), Some(tti)) => Some(ttl.min(tti)),
                (Some(x), None) | (None, Some(x)) => Some(x),
                (None, None) => None,
            }
        }
    }

    #[pyclass]
    struct Moka(Cache<AnyKey, ValueWrapper, ahash::RandomState>);

    #[pymethods]
    impl Moka {
        #[new]
        #[pyo3(signature = (capacity, ttl=None, tti=None, eviction_listener=None, policy="tiny_lfu"))]
        fn new(
            capacity: u64,
            ttl: Option<f64>,
            tti: Option<f64>,
            eviction_listener: Option<Py<PyAny>>,
            policy: &str,
        ) -> PyResult<Self> {
            let policy = policy.parse::<Policy>().map_err(PyValueError::new_err)?;
            let mut builder = Cache::builder()
                .max_capacity(capacity)
                .expire_after(PerEntryExpiry)
                .eviction_policy(policy.into());

            if let Some(ttl) = ttl {
                let ttl_micros = (ttl * 1_000_000.0) as u64;
                if ttl_micros == 0 {
                    return Err(PyValueError::new_err("ttl must be positive"));
                }
                builder = builder.time_to_live(Duration::from_micros(ttl_micros));
            }

            if let Some(tti) = tti {
                let tti_micros = (tti * 1_000_000.0) as u64;
                if tti_micros == 0 {
                    return Err(PyValueError::new_err("tti must be positive"));
                }
                builder = builder.time_to_idle(Duration::from_micros(tti_micros));
            }

            if let Some(listener) = eviction_listener {
                let listen_fn = move |k: Arc<AnyKey>, v: ValueWrapper, cause: RemovalCause| {
                    Python::attach(|py| {
                        let key = k.as_ref().obj.clone_ref(py);
                        let value = v.value.as_ref().clone_ref(py);
                        if let Err(e) = listener.call1(py, (key, value, cause_to_str(cause))) {
                            e.restore(py)
                        }
                    });
                };
                builder = builder.eviction_listener(Box::new(listen_fn));
            }

            Ok(Moka(
                builder.build_with_hasher(ahash::RandomState::default()),
            ))
        }

        #[classmethod]
        fn __class_getitem__(
            cls: &Bound<'_, PyType>,
            _key: &Bound<'_, PyAny>,
        ) -> PyResult<Py<PyAny>> {
            Ok(cls.clone().into_any().unbind())
        }

        #[pyo3(signature = (key, value, ttl=None, tti=None))]
        fn set(
            &self,
            py: Python,
            key: Py<PyAny>,
            value: Py<PyAny>,
            ttl: Option<f64>,
            tti: Option<f64>,
        ) -> PyResult<()> {
            let hashable_key = AnyKey::new_with_gil(key, py)?;
            let per_entry_ttl = parse_duration(ttl, "ttl")?;
            let per_entry_tti = parse_duration(tti, "tti")?;
            let wrapper = ValueWrapper {
                value: Arc::new(value),
                per_entry_ttl,
                per_entry_tti,
                created_at: Instant::now(),
            };
            self.0.insert(hashable_key, wrapper);
            Ok(())
        }

        #[pyo3(signature = (key, default=None))]
        fn get(
            &self,
            py: Python,
            key: Py<PyAny>,
            default: Option<Py<PyAny>>,
        ) -> PyResult<Option<Py<PyAny>>> {
            let hashable_key = AnyKey::new_with_gil(key, py)?;
            let value = self.0.get(&hashable_key);
            Ok(value
                .map(|v| v.value.clone_ref(py))
                .or_else(|| default.map(|v| v.clone_ref(py))))
        }

        #[pyo3(signature = (key, initializer, ttl=None, tti=None))]
        fn get_with(
            &self,
            py: Python,
            key: Py<PyAny>,
            initializer: Py<PyAny>,
            ttl: Option<f64>,
            tti: Option<f64>,
        ) -> PyResult<Py<PyAny>> {
            let hashable_key = AnyKey::new_with_gil(key, py)?;
            let per_entry_ttl = parse_duration(ttl, "ttl")?;
            let per_entry_tti = parse_duration(tti, "tti")?;
            py.detach(|| {
                self.0.try_get_with(hashable_key, || {
                    Python::attach(|py| {
                        initializer.call0(py).map(|v| ValueWrapper {
                            value: Arc::new(v),
                            per_entry_ttl,
                            per_entry_tti,
                            created_at: Instant::now(),
                        })
                    })
                })
            })
            .map(|v| v.value.clone_ref(py))
            .map_err(|e| e.clone_ref(py))
        }

        #[pyo3(signature = (key, default=None))]
        fn remove(
            &self,
            py: Python,
            key: Py<PyAny>,
            default: Option<Py<PyAny>>,
        ) -> PyResult<Option<Py<PyAny>>> {
            let hashable_key = AnyKey::new_with_gil(key, py)?;
            let removed = self.0.remove(&hashable_key);
            Ok(removed
                .map(|v| v.value.clone_ref(py))
                .or_else(|| default.map(|v| v.clone_ref(py))))
        }

        fn clear(&self, py: Python) {
            py.detach(|| self.0.invalidate_all());
        }

        fn count(&self, py: Python) -> u64 {
            py.detach(|| self.0.entry_count())
        }
    }
}
