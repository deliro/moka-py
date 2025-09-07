use std::hash::{Hash, Hasher};
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use moka::notification::RemovalCause;
use moka::policy::EvictionPolicy;
use moka::sync::Cache;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyType;

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

#[pyclass]
struct Moka(Cache<AnyKey, Arc<Py<PyAny>>, ahash::RandomState>);

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
            let listen_fn = move |k: Arc<AnyKey>, v: Arc<Py<PyAny>>, cause: RemovalCause| {
                Python::attach(|py| {
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
        _v: Py<PyAny>,
    ) -> PyResult<&'a Bound<'a, PyType>> {
        Ok(cls)
    }

    fn set(&self, py: Python, key: Py<PyAny>, value: Py<PyAny>) -> PyResult<()> {
        let hashable_key = AnyKey::new_with_gil(key, py)?;
        let value = Arc::new(value);
        self.0.insert(hashable_key, value);
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
        // Here we could release GIL to get some free threading, but under this `get`
        // a lot of comparisons happen, which require to acquire GIL each time.
        // So it's ~30% faster to keep GIL acquired all the time search happening
        // instead of switching it on and off.
        let value = self.0.get(&hashable_key);
        Ok(value
            .map(|v| v.clone_ref(py))
            .or_else(|| default.map(|v| v.clone_ref(py))))
    }

    fn get_with(&self, py: Python, key: Py<PyAny>, initializer: Py<PyAny>) -> PyResult<Py<PyAny>> {
        let hashable_key = AnyKey::new_with_gil(key, py)?;
        py.detach(|| {
            self.0.try_get_with(hashable_key, || {
                Python::attach(|py| initializer.call0(py).map(Arc::new))
            })
        })
        .map(|v| v.clone_ref(py))
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
            .map(|v| v.clone_ref(py))
            .or_else(|| default.map(|v| v.clone_ref(py))))
    }

    fn clear(&self, py: Python) {
        py.detach(|| self.0.invalidate_all());
    }

    fn count(&self, py: Python) -> u64 {
        py.detach(|| self.0.entry_count())
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
