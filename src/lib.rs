use std::hash::{Hash, Hasher};
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use moka::notification::RemovalCause;
use moka::policy::EvictionPolicy;
use moka::sync::Cache;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::pyclass::CompareOp;
use pyo3::types::{PyString, PyType};

#[derive(Debug)]
enum KeyKind {
    /// String keys are the most common. If the string is short enough,
    /// we can get faster and more freedom from GIL by copying a string
    /// to Rust and hashing it using `ahash` instead of calling
    /// the standard Python hash function.
    ///
    /// Using this 'hack' gives ~x1.1 speed up on `.get` hits and
    /// ~x1.15 on `.get_with` calls, but ~x0.8 slow down on `.get`s on cache misses.
    ShortStr(String),

    /// Other keys (even long Python strings) go this (slower) way
    Other { py_hash: isize },
}

#[derive(Debug)]
struct AnyKey {
    obj: PyObject,
    kind: KeyKind,
}

impl AnyKey {
    const SHORT_STR: usize = 64;

    #[inline]
    fn new_with_gil(obj: PyObject, py: Python) -> PyResult<Self> {
        let kind = match obj.downcast_bound::<PyString>(py) {
            Ok(s) if s.len()? <= Self::SHORT_STR => KeyKind::ShortStr(s.to_string()),
            _ => {
                let py_hash = obj.bind_borrowed(py).hash()?;
                KeyKind::Other { py_hash }
            }
        };
        Ok(AnyKey { obj, kind })
    }
}

impl PartialEq for AnyKey {
    #[inline]
    fn eq(&self, other: &Self) -> bool {
        match (self, other) {
            (
                AnyKey {
                    kind: KeyKind::ShortStr(lhs),
                    ..
                },
                AnyKey {
                    kind: KeyKind::ShortStr(rhs),
                    ..
                },
            ) => lhs == rhs,

            // It is expected that `hash` will be stable for an object. Hence, since we already
            // know both objects' hashes, we can claim that if their hashes are different,
            // the objects aren't equal. Only if the hashes are the same, the objects
            // might be equal, and only in that case we raise the GIL to run Python
            // rich comparison.
            (
                AnyKey {
                    kind: KeyKind::Other { py_hash: lhs_hash },
                    obj: lhs_obj,
                },
                AnyKey {
                    kind: KeyKind::Other { py_hash: rhs_hash },
                    obj: rhs_obj,
                },
            ) => {
                *lhs_hash == *rhs_hash
                    && Python::with_gil(|py| {
                        let lhs = lhs_obj.bind_borrowed(py);
                        let rhs = rhs_obj.bind_borrowed(py);
                        match lhs.rich_compare(rhs, CompareOp::Eq) {
                            Ok(v) => v.is_truthy().unwrap_or_default(),
                            Err(_) => false,
                        }
                    })
            }
            _ => false,
        }
    }
}

impl Eq for AnyKey {}
impl Hash for AnyKey {
    #[inline]
    fn hash<H: Hasher>(&self, state: &mut H) {
        match &self.kind {
            KeyKind::ShortStr(s) => s.hash(state),
            KeyKind::Other { py_hash } => py_hash.hash(state),
        }
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

#[pyclass]
struct Moka(Cache<AnyKey, Arc<PyObject>, ahash::RandomState>);

#[pymethods]
impl Moka {
    #[new]
    #[pyo3(signature = (capacity, ttl=None, tti=None, eviction_listener=None, policy="tiny_lfu"))]
    fn new(
        capacity: u64,
        ttl: Option<f64>,
        tti: Option<f64>,
        eviction_listener: Option<PyObject>,
        policy: &str,
    ) -> PyResult<Self> {
        let policy = policy.parse::<Policy>().map_err(PyValueError::new_err)?;
        let mut builder = Cache::builder()
            .max_capacity(capacity)
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
            let listen_fn = move |k: Arc<AnyKey>, v: Arc<PyObject>, cause: RemovalCause| {
                Python::with_gil(|py| {
                    let key = k.as_ref().obj.clone_ref(py);
                    let value = v.as_ref().clone_ref(py);
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
    fn __class_getitem__<'a>(
        cls: &'a Bound<'a, PyType>,
        _v: PyObject,
    ) -> PyResult<&'a Bound<'a, PyType>> {
        Ok(cls)
    }

    fn set(&self, py: Python, key: PyObject, value: PyObject) -> PyResult<()> {
        let hashable_key = AnyKey::new_with_gil(key, py)?;
        let value = Arc::new(value);
        py.allow_threads(|| self.0.insert(hashable_key, value));
        Ok(())
    }

    #[pyo3(signature = (key, default=None))]
    fn get(
        &self,
        py: Python,
        key: PyObject,
        default: Option<PyObject>,
    ) -> PyResult<Option<PyObject>> {
        let hashable_key = AnyKey::new_with_gil(key, py)?;
        let value = py.allow_threads(|| self.0.get(&hashable_key));
        Ok(value
            .map(|v| v.clone_ref(py))
            .or_else(|| default.map(|v| v.clone_ref(py))))
    }

    fn get_with(&self, py: Python, key: PyObject, initializer: PyObject) -> PyResult<PyObject> {
        let hashable_key = AnyKey::new_with_gil(key, py)?;
        py.allow_threads(|| {
            self.0.try_get_with(hashable_key, || {
                Python::with_gil(|py| initializer.call0(py).map(Arc::new))
            })
        })
        .map(|v| v.clone_ref(py))
        .map_err(|e| e.clone_ref(py))
    }

    fn remove(&self, py: Python, key: PyObject) -> PyResult<Option<PyObject>> {
        let hashable_key = AnyKey::new_with_gil(key, py)?;
        let removed = py.allow_threads(|| self.0.remove(&hashable_key));
        Ok(removed.map(|obj| obj.clone_ref(py)))
    }

    fn clear(&self, py: Python) {
        py.allow_threads(|| self.0.invalidate_all());
    }

    fn count(&self, py: Python) -> u64 {
        py.allow_threads(|| self.0.entry_count())
    }
}

#[pyfunction]
fn get_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pymodule]
fn moka_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Moka>()?;
    m.add_function(wrap_pyfunction!(get_version, m)?)?;
    Ok(())
}
