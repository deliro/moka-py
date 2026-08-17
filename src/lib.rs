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
    use pyo3::{
        exceptions::{PyTypeError, PyValueError},
        prelude::*,
        types::{PyInt, PyType},
    };

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
            state.write_isize(self.py_hash);
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

    /// Convert a number of seconds coming from Python into a `Duration`.
    ///
    /// Rejects zero, negative, NaN and infinite values explicitly instead of
    /// relying on the saturating behaviour of a `f64 as u64` cast, which
    /// silently turned an absurd value such as `1e30` into a ~584942 year TTL.
    #[inline]
    fn parse_duration(value: Option<f64>, name: &str) -> PyResult<Option<Duration>> {
        let Some(seconds) = value else {
            return Ok(None);
        };
        if !seconds.is_finite() || seconds <= 0.0 {
            return Err(PyValueError::new_err(format!("{name} must be positive")));
        }
        let duration = Duration::try_from_secs_f64(seconds)
            .map_err(|e| PyValueError::new_err(format!("{name} is out of range: {e}")))?;
        Ok(Some(duration))
    }

    #[derive(Clone)]
    struct ValueWrapper {
        value: Arc<Py<PyAny>>,
        per_entry_ttl: Option<Duration>,
        per_entry_tti: Option<Duration>,
        created_at: Instant,
        weight: u32,
    }

    /// Compute the entry weight by calling the user-supplied weigher eagerly,
    /// on the calling thread, before the entry enters moka (see ADR-0001).
    /// Without a weigher every entry weighs 1, i.e. capacity = entry count.
    fn compute_weight(
        py: Python,
        weigher: &Py<PyAny>,
        key: &Py<PyAny>,
        value: &Py<PyAny>,
    ) -> PyResult<u32> {
        let result = weigher.call1(py, (key, value))?;
        let bound = result.bind(py);
        if !bound.is_instance_of::<PyInt>() {
            return Err(PyTypeError::new_err(format!(
                "weigher must return an int, got {}",
                bound.get_type().name()?
            )));
        }
        match bound.extract::<u64>() {
            // Weights above u32::MAX clamp: "this entry is enormous" is the
            // honest reading, and moka cannot represent anything larger anyway.
            Ok(v) => Ok(u32::try_from(v).unwrap_or(u32::MAX)),
            // An int that does not fit u64 is either negative (a bug in the
            // weigher, refuse loudly) or astronomically large (clamp).
            Err(_) => {
                if bound.lt(0)? {
                    Err(PyValueError::new_err(
                        "weigher must return a non-negative int",
                    ))
                } else {
                    Ok(u32::MAX)
                }
            }
        }
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
    struct Moka {
        cache: Cache<AnyKey, ValueWrapper, ahash::RandomState>,
        weigher: Option<Py<PyAny>>,
    }

    #[pymethods]
    impl Moka {
        #[new]
        #[pyo3(signature = (capacity, ttl=None, tti=None, eviction_listener=None, policy="tiny_lfu", weigher=None))]
        fn new(
            capacity: u64,
            ttl: Option<f64>,
            tti: Option<f64>,
            eviction_listener: Option<Py<PyAny>>,
            policy: &str,
            weigher: Option<Py<PyAny>>,
        ) -> PyResult<Self> {
            let policy = policy.parse::<Policy>().map_err(PyValueError::new_err)?;
            let mut builder = Cache::builder()
                .max_capacity(capacity)
                .expire_after(PerEntryExpiry)
                .eviction_policy(policy.into())
                // The weight is precomputed on the calling thread (ADR-0001);
                // moka only ever reads the stored field, no Python involved.
                .weigher(|_k: &AnyKey, v: &ValueWrapper| v.weight);

            if let Some(time_to_live) = parse_duration(ttl, "ttl")? {
                builder = builder.time_to_live(time_to_live);
            }

            if let Some(time_to_idle) = parse_duration(tti, "tti")? {
                builder = builder.time_to_idle(time_to_idle);
            }

            if let Some(listener) = eviction_listener {
                let listen_fn = move |k: Arc<AnyKey>, v: ValueWrapper, cause: RemovalCause| {
                    Python::attach(|py| {
                        let key = k.as_ref().obj.clone_ref(py);
                        let value = v.value.as_ref().clone_ref(py);
                        if let Err(e) = listener.call1(py, (key, value, cause_to_str(cause))) {
                            e.restore(py);
                        }
                    });
                };
                builder = builder.eviction_listener(Box::new(listen_fn));
            }

            Ok(Moka {
                cache: builder.build_with_hasher(ahash::RandomState::default()),
                weigher,
            })
        }

        #[classmethod]
        fn __class_getitem__(cls: &Bound<'_, PyType>, _key: &Bound<'_, PyAny>) -> Py<PyAny> {
            cls.clone().into_any().unbind()
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
            let weight = match self.weigher.as_ref() {
                Some(weigher) => compute_weight(py, weigher, &key, &value)?,
                None => 1,
            };
            let hashable_key = AnyKey::new_with_gil(key, py)?;
            let time_to_live = parse_duration(ttl, "ttl")?;
            let time_to_idle = parse_duration(tti, "tti")?;
            let wrapper = ValueWrapper {
                value: Arc::new(value),
                per_entry_ttl: time_to_live,
                per_entry_tti: time_to_idle,
                created_at: Instant::now(),
                weight,
            };
            self.cache.insert(hashable_key, wrapper);
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
            let value = self.cache.get(&hashable_key);
            Ok(value.map(|v| v.value.clone_ref(py)).or(default))
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
            // Argument validation happens before the hit fast path so that an
            // invalid ttl/tti raises even when the key is already cached.
            let time_to_live = parse_duration(ttl, "ttl")?;
            let time_to_idle = parse_duration(tti, "tti")?;
            let hashable_key = AnyKey::new_with_gil(key, py)?;
            if let Some(v) = self.cache.get(&hashable_key) {
                return Ok(v.value.clone_ref(py));
            }
            let weigher_ctx = self
                .weigher
                .as_ref()
                .map(|w| (w.clone_ref(py), hashable_key.obj.clone_ref(py)));
            py.detach(|| {
                self.cache.try_get_with(hashable_key, move || {
                    Python::attach(|py| -> PyResult<ValueWrapper> {
                        let v = initializer.call0(py)?;
                        let weight = match &weigher_ctx {
                            Some((weigher, key)) => compute_weight(py, weigher, key, &v)?,
                            None => 1,
                        };
                        Ok(ValueWrapper {
                            value: Arc::new(v),
                            per_entry_ttl: time_to_live,
                            per_entry_tti: time_to_idle,
                            created_at: Instant::now(),
                            weight,
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
            let removed = self.cache.remove(&hashable_key);
            Ok(removed.map(|v| v.value.clone_ref(py)).or(default))
        }

        fn clear(&self, py: Python) {
            py.detach(|| self.cache.invalidate_all());
        }

        fn count(&self, py: Python) -> u64 {
            py.detach(|| self.cache.entry_count())
        }

        fn run_pending_tasks(&self, py: Python) {
            py.detach(|| self.cache.run_pending_tasks());
        }

        fn weighted_size(&self, py: Python) -> u64 {
            py.detach(|| self.cache.weighted_size())
        }
    }
}
