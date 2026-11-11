//! WebAssembly binding of hm-seal, for the browser. Bytes go in and come out
//! as `Uint8Array`. A refusal throws an `Error` whose `name` is "SealError",
//! "Removed" when this device was removed from its group, or "WrongDevice"
//! when pairing met a device other than the one the owner confirmed.

use js_sys::{Array, Error, Object, Reflect, Uint8Array};
use seal_core as core_;
use wasm_bindgen::prelude::*;

type Result<T> = std::result::Result<T, JsValue>;

fn err(e: core_::SealError) -> JsValue {
    let error = Error::new(&e.to_string());
    error.set_name(match e {
        core_::SealError::Removed => "Removed",
        core_::SealError::WrongDevice => "WrongDevice",
        _ => "SealError",
    });
    error.into()
}

fn refused(message: &str) -> JsValue {
    let error = Error::new(message);
    error.set_name("SealError");
    error.into()
}

fn object(fields: &[(&str, JsValue)]) -> Result<Object> {
    let o = Object::new();
    for (key, value) in fields {
        Reflect::set(&o, &JsValue::from_str(key), value)?;
    }
    Ok(o)
}

fn bytes(v: &[u8]) -> JsValue {
    Uint8Array::from(v).into()
}

/// MLS epochs count commits; a Number holds them exactly far beyond any real group.
fn number(epoch: u64) -> JsValue {
    JsValue::from_f64(epoch as f64)
}

fn secret(raw: &[u8]) -> Result<[u8; 32]> {
    raw.try_into().map_err(|_| refused("a recovery secret is 32 bytes"))
}

/// One device's place in its owner's MLS group.
#[wasm_bindgen]
pub struct Member(core_::Member);

#[wasm_bindgen]
impl Member {
    #[wasm_bindgen(constructor)]
    pub fn new(name: &[u8]) -> Result<Member> {
        Ok(Self(core_::Member::new(name).map_err(err)?))
    }

    /// A device from what `save()` wrote.
    pub fn load(saved: &[u8]) -> Result<Member> {
        Ok(Self(core_::Member::load(saved).map_err(err)?))
    }

    /// Everything this device needs after a reload, private keys included:
    /// store it only where this origin's own code can read it.
    pub fn save(&self) -> Result<Vec<u8>> {
        self.0.save().map_err(err)
    }

    #[wasm_bindgen(js_name = signatureKey)]
    pub fn signature_key(&self) -> Vec<u8> {
        self.0.signature_key()
    }

    #[wasm_bindgen(js_name = keyPackage)]
    pub fn key_package(&self) -> Result<Vec<u8>> {
        self.0.key_package().map_err(err)
    }

    #[wasm_bindgen(js_name = createGroup)]
    pub fn create_group(&mut self, group_id: &[u8]) -> Result<()> {
        self.0.create_group(group_id).map_err(err)
    }

    /// Join the group a Welcome adds this device to. `adderSignatureKey` is the
    /// key of the device that should be adding this one, as confirmed while pairing.
    pub fn join(&mut self, welcome: &[u8], adder_signature_key: &[u8]) -> Result<()> {
        self.0.join(welcome, adder_signature_key).map_err(err)
    }

    /// Add the device whose key package this is and whose signature key the
    /// owner confirmed: `{commit, welcome}`, the commit for the others and the
    /// Welcome for it.
    pub fn add(&mut self, key_package: &[u8], signature_key: &[u8]) -> Result<Object> {
        let added = self.0.add(key_package, signature_key).map_err(err)?;
        object(&[("commit", bytes(&added.commit)), ("welcome", bytes(&added.welcome))])
    }

    /// Remove the device at this leaf index: the commit for the remaining members.
    pub fn remove(&mut self, leaf: u32) -> Result<Vec<u8>> {
        self.0.remove(leaf).map_err(err)
    }

    pub fn seal(&mut self, plaintext: &[u8]) -> Result<Vec<u8>> {
        self.0.seal(plaintext).map_err(err)
    }

    /// `{kind: "application", sender, senderKey, bytes}` or `{kind: "commit", epoch}`.
    /// Leaf indices are reused after a removal: decide by `senderKey`.
    pub fn handle(&mut self, message: &[u8]) -> Result<Object> {
        match self.0.handle(message).map_err(err)? {
            core_::Incoming::Application { sender, sender_key, bytes: b } => object(&[
                ("kind", JsValue::from_str("application")),
                ("sender", JsValue::from(sender)),
                ("senderKey", bytes(&sender_key)),
                ("bytes", bytes(&b)),
            ]),
            core_::Incoming::Commit { epoch } => {
                object(&[("kind", JsValue::from_str("commit")), ("epoch", number(epoch))])
            }
        }
    }

    pub fn epoch(&self) -> Result<f64> {
        Ok(self.0.epoch().map_err(err)? as f64)
    }

    #[wasm_bindgen(js_name = leafIndex)]
    pub fn leaf_index(&self) -> Result<u32> {
        self.0.leaf_index().map_err(err)
    }

    /// `[{leaf, name}]` of every device in the group.
    pub fn members(&self) -> Result<Array> {
        let list = Array::new();
        for (leaf, name) in self.0.members().map_err(err)? {
            list.push(&object(&[("leaf", JsValue::from(leaf)), ("name", bytes(&name))])?.into());
        }
        Ok(list)
    }

    #[wasm_bindgen(js_name = frameSealer)]
    pub fn frame_sealer(&self) -> Result<FrameSealer> {
        Ok(FrameSealer(self.0.frame_sealer().map_err(err)?))
    }

    /// Teach the opener this epoch's senders and keys; call it after every commit.
    #[wasm_bindgen(js_name = updateOpener)]
    pub fn update_opener(&self, opener: &mut FrameOpener) -> Result<()> {
        self.0.update_opener(&mut opener.0).map_err(err)
    }
}

/// Encrypts this device's frames for the epoch it was made in.
#[wasm_bindgen]
pub struct FrameSealer(core_::FrameSealer);

#[wasm_bindgen]
impl FrameSealer {
    pub fn seal(&mut self, payload: &[u8], meta: Option<Vec<u8>>) -> Result<Vec<u8>> {
        self.0.seal(payload, meta.as_deref().unwrap_or_default()).map_err(err)
    }
}

/// Decrypts the other members' frames, refusing a frame seen before.
#[wasm_bindgen]
pub struct FrameOpener(core_::FrameOpener);

#[wasm_bindgen]
impl FrameOpener {
    #[wasm_bindgen(constructor)]
    pub fn new() -> FrameOpener {
        Self(core_::FrameOpener::default())
    }

    pub fn open(&mut self, frame: &[u8], meta: Option<Vec<u8>>) -> Result<Vec<u8>> {
        self.0.open(frame, meta.as_deref().unwrap_or_default()).map_err(err)
    }
}

impl Default for FrameOpener {
    fn default() -> Self {
        Self::new()
    }
}

/// The key stored data is sealed under.
#[wasm_bindgen]
pub struct DataKey(core_::DataKey);

#[wasm_bindgen]
impl DataKey {
    pub fn generate() -> DataKey {
        Self(core_::DataKey::generate())
    }

    #[wasm_bindgen(js_name = fromBytes)]
    pub fn from_bytes(raw: &[u8]) -> Result<DataKey> {
        Ok(Self(core_::DataKey::from_bytes(raw).map_err(err)?))
    }

    /// The raw key, to hand to another device of the same owner inside the group.
    #[wasm_bindgen(js_name = toBytes)]
    pub fn to_bytes(&self) -> Vec<u8> {
        self.0.to_bytes().to_vec()
    }

    pub fn seal(&self, purpose: &[u8], plaintext: &[u8]) -> Result<Vec<u8>> {
        self.0.seal(purpose, plaintext).map_err(err)
    }

    pub fn open(&self, purpose: &[u8], blob: &[u8]) -> Result<Vec<u8>> {
        self.0.open(purpose, blob).map_err(err)
    }

    #[wasm_bindgen(js_name = wrapForRecovery)]
    pub fn wrap_for_recovery(&self, recovery_secret: &[u8]) -> Result<Vec<u8>> {
        self.0.wrap_for_recovery(&secret(recovery_secret)?).map_err(err)
    }

    #[wasm_bindgen(js_name = unwrapFromRecovery)]
    pub fn unwrap_from_recovery(recovery_secret: &[u8], wrapped: &[u8]) -> Result<DataKey> {
        Ok(Self(core_::DataKey::unwrap_from_recovery(&secret(recovery_secret)?, wrapped).map_err(err)?))
    }
}
