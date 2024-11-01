use std::sync::Arc;
use std::time::Duration;

use moka::sync::Cache;
use pyo3::prelude::*;

#[pyclass]
struct Moka(Arc<Cache<String, String>>);

#[pymethods]
impl Moka {
    #[new]
    fn new(capacity: u64, ttl_seconds: Option<u64>, tti_seconds: Option<u64>) -> Self {
        let mut builder = Cache::builder().max_capacity(capacity);

        if let Some(ttl) = ttl_seconds {
            builder = builder.time_to_live(Duration::from_secs(ttl))
        }

        if let Some(tti) = tti_seconds {
            builder = builder.time_to_idle(Duration::from_secs(tti))
        }

        Moka(Arc::new(builder.build()))
    }

    fn insert(&self, key: String, value: String) {
        self.0.insert(key, value);
    }

    fn get(&self, key: String) -> Option<String> {
        self.0.get(&key)
    }

    fn invalidate(&self, key: String) {
        self.0.invalidate(&key);
    }

    fn clear(&self) {
        self.0.invalidate_all();
    }
}

#[pymodule]
fn moka_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Moka>()?;
    Ok(())
}
