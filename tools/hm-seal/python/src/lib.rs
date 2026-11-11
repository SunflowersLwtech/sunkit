//! Python binding of hm-seal. Every class holds its Rust value behind a mutex,
//! so it can be used from any thread; bytes go in and come out as `bytes`.

use std::sync::{Mutex, MutexGuard};

use pyo3::create_exception;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use seal_core as core_;

create_exception!(hm_seal, SealError, PyValueError, "hm-seal refused: the message, frame, blob or save did not check out.");
create_exception!(hm_seal, Removed, SealError, "This device was removed from its group.");

fn err(e: core_::SealError) -> PyErr {
    match e {
        core_::SealError::Removed => Removed::new_err(e.to_string()),
        other => SealError::new_err(other.to_string()),
    }
}

fn bytes(py: Python<'_>, v: &[u8]) -> Py<PyBytes> {
    PyBytes::new(py, v).unbind()
}

fn lock<T>(m: &Mutex<T>) -> PyResult<MutexGuard<'_, T>> {
    m.lock().map_err(|_| SealError::new_err("a previous call panicked"))
}

/// One device's place in its owner's MLS group.
#[pyclass(name = "Member", module = "hm_seal")]
struct Member(Mutex<core_::Member>);

#[pymethods]
impl Member {
    #[new]
    fn new(name: &[u8]) -> PyResult<Self> {
        Ok(Self(Mutex::new(core_::Member::new(name).map_err(err)?)))
    }

    /// A device from what `save()` wrote.
    #[staticmethod]
    fn load(saved: &[u8]) -> PyResult<Self> {
        Ok(Self(Mutex::new(core_::Member::load(saved).map_err(err)?)))
    }

    /// Everything this device needs after a restart, private keys included:
    /// write it to a file only the device's user can read.
    fn save(&self, py: Python<'_>) -> PyResult<Py<PyBytes>> {
        Ok(bytes(py, &lock(&self.0)?.save().map_err(err)?))
    }

    fn signature_key(&self, py: Python<'_>) -> PyResult<Py<PyBytes>> {
        Ok(bytes(py, &lock(&self.0)?.signature_key()))
    }

    fn key_package(&self, py: Python<'_>) -> PyResult<Py<PyBytes>> {
        Ok(bytes(py, &lock(&self.0)?.key_package().map_err(err)?))
    }

    fn create_group(&self, group_id: &[u8]) -> PyResult<()> {
        lock(&self.0)?.create_group(group_id).map_err(err)
    }

    fn join(&self, welcome: &[u8]) -> PyResult<()> {
        lock(&self.0)?.join(welcome).map_err(err)
    }

    /// Add the device whose key package this is: (commit for the others, Welcome for it).
    fn add(&self, py: Python<'_>, key_package: &[u8]) -> PyResult<(Py<PyBytes>, Py<PyBytes>)> {
        let added = lock(&self.0)?.add(key_package).map_err(err)?;
        Ok((bytes(py, &added.commit), bytes(py, &added.welcome)))
    }

    /// Remove the device at this leaf index: the commit for the remaining members.
    fn remove(&self, py: Python<'_>, leaf: u32) -> PyResult<Py<PyBytes>> {
        Ok(bytes(py, &lock(&self.0)?.remove(leaf).map_err(err)?))
    }

    fn seal(&self, py: Python<'_>, plaintext: &[u8]) -> PyResult<Py<PyBytes>> {
        Ok(bytes(py, &lock(&self.0)?.seal(plaintext).map_err(err)?))
    }

    /// ("application", sender leaf, bytes) or ("commit", epoch, b"").
    fn handle(&self, py: Python<'_>, message: &[u8]) -> PyResult<(&'static str, u64, Py<PyBytes>)> {
        match lock(&self.0)?.handle(message).map_err(err)? {
            core_::Incoming::Application { sender, bytes: b } => Ok(("application", u64::from(sender), bytes(py, &b))),
            core_::Incoming::Commit { epoch } => Ok(("commit", epoch, bytes(py, b""))),
        }
    }

    fn epoch(&self) -> PyResult<u64> {
        lock(&self.0)?.epoch().map_err(err)
    }

    fn leaf_index(&self) -> PyResult<u32> {
        lock(&self.0)?.leaf_index().map_err(err)
    }

    /// [(leaf index, name)] of every device in the group.
    fn members(&self, py: Python<'_>) -> PyResult<Vec<(u32, Py<PyBytes>)>> {
        Ok(lock(&self.0)?.members().map_err(err)?.into_iter().map(|(l, n)| (l, bytes(py, &n))).collect())
    }

    fn frame_sealer(&self) -> PyResult<FrameSealer> {
        Ok(FrameSealer(Mutex::new(lock(&self.0)?.frame_sealer().map_err(err)?)))
    }

    fn update_opener(&self, opener: &FrameOpener) -> PyResult<()> {
        let member = lock(&self.0)?;
        let mut opener = lock(&opener.0)?;
        member.update_opener(&mut opener).map_err(err)
    }
}

/// Encrypts this device's frames for the epoch it was made in.
#[pyclass(name = "FrameSealer", module = "hm_seal")]
struct FrameSealer(Mutex<core_::FrameSealer>);

#[pymethods]
impl FrameSealer {
    #[pyo3(signature = (payload, meta = b"" as &[u8]))]
    fn seal(&self, py: Python<'_>, payload: &[u8], meta: &[u8]) -> PyResult<Py<PyBytes>> {
        Ok(bytes(py, &lock(&self.0)?.seal(payload, meta).map_err(err)?))
    }
}

/// Decrypts the other members' frames, refusing a frame seen before.
#[pyclass(name = "FrameOpener", module = "hm_seal")]
struct FrameOpener(Mutex<core_::FrameOpener>);

#[pymethods]
impl FrameOpener {
    #[new]
    fn new() -> Self {
        Self(Mutex::new(core_::FrameOpener::default()))
    }

    #[pyo3(signature = (frame, meta = b"" as &[u8]))]
    fn open(&self, py: Python<'_>, frame: &[u8], meta: &[u8]) -> PyResult<Py<PyBytes>> {
        Ok(bytes(py, &lock(&self.0)?.open(frame, meta).map_err(err)?))
    }
}

/// The key stored data is sealed under.
#[pyclass(name = "DataKey", module = "hm_seal", frozen)]
struct DataKey(core_::DataKey);

#[pymethods]
impl DataKey {
    #[staticmethod]
    fn generate() -> Self {
        Self(core_::DataKey::generate())
    }

    #[staticmethod]
    fn from_bytes(raw: &[u8]) -> PyResult<Self> {
        Ok(Self(core_::DataKey::from_bytes(raw).map_err(err)?))
    }

    /// The raw key, to hand to another device of the same owner inside the group.
    fn to_bytes(&self, py: Python<'_>) -> Py<PyBytes> {
        bytes(py, &self.0.to_bytes())
    }

    fn seal(&self, py: Python<'_>, purpose: &[u8], plaintext: &[u8]) -> PyResult<Py<PyBytes>> {
        Ok(bytes(py, &self.0.seal(purpose, plaintext).map_err(err)?))
    }

    fn open(&self, py: Python<'_>, purpose: &[u8], blob: &[u8]) -> PyResult<Py<PyBytes>> {
        Ok(bytes(py, &self.0.open(purpose, blob).map_err(err)?))
    }

    fn wrap_for_recovery(&self, py: Python<'_>, recovery_secret: [u8; 32]) -> PyResult<Py<PyBytes>> {
        Ok(bytes(py, &self.0.wrap_for_recovery(&recovery_secret).map_err(err)?))
    }

    #[staticmethod]
    fn unwrap_from_recovery(recovery_secret: [u8; 32], wrapped: &[u8]) -> PyResult<Self> {
        Ok(Self(core_::DataKey::unwrap_from_recovery(&recovery_secret, wrapped).map_err(err)?))
    }
}

#[pymodule]
fn hm_seal(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Member>()?;
    m.add_class::<FrameSealer>()?;
    m.add_class::<FrameOpener>()?;
    m.add_class::<DataKey>()?;
    m.add("SealError", m.py().get_type::<SealError>())?;
    m.add("Removed", m.py().get_type::<Removed>())?;
    Ok(())
}
