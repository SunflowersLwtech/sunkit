//! WebAssembly binding of hm-seal, for the browser. Bytes go in and come out
//! as `Uint8Array`, and only a `Uint8Array` is taken as bytes. A refusal throws an `Error` whose `name` is "SealError",
//! "Removed" when this device was removed from its group, "WrongDevice"
//! when pairing met a device other than the one the owner confirmed, or
//! "NotAdmin" when a device that is not an admin tried to add or remove a
//! device or change who the admins are.

use js_sys::{Array, Error, Object, Reflect, Uint8Array};
use seal_core as core_;
use wasm_bindgen::prelude::*;

type Result<T> = std::result::Result<T, JsValue>;

fn err(e: core_::SealError) -> JsValue {
    let error = Error::new(&e.to_string());
    error.set_name(match e {
        core_::SealError::Removed => "Removed",
        core_::SealError::WrongDevice => "WrongDevice",
        core_::SealError::NotAdmin => "NotAdmin",
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

/// The bytes in `value`, which must be a `Uint8Array` (a Node `Buffer` is one).
/// wasm-bindgen's own glue would copy anything array-like with
/// `Uint8Array.prototype.set`, so a string arrived as other bytes, each
/// character its numeric value and most of them 0: a frame sealed with the
/// metadata "camera-a" opened with "camera-b".
fn input(value: &JsValue, what: &str) -> Result<Vec<u8>> {
    value
        .dyn_ref::<Uint8Array>()
        .map(Uint8Array::to_vec)
        .ok_or_else(|| refused(&format!("{what} must be a Uint8Array")))
}

/// As `input`, with `undefined` or `null` meaning no bytes.
fn optional(value: &JsValue, what: &str) -> Result<Vec<u8>> {
    if value.is_undefined() || value.is_null() {
        Ok(Vec::new())
    } else {
        input(value, what)
    }
}

/// A leaf index, which must be a whole Number from 0 to 2^32 - 1. Taken as a
/// `u32`, wasm-bindgen's glue converts with `>>> 0` and no check, so
/// `undefined`, `null` and `NaN` became leaf 0 (the phone that started the
/// group) and `1.5` became leaf 1.
fn leaf_index(value: &JsValue) -> Result<u32> {
    value
        .as_f64()
        // NaN and the infinities fail `fract() == 0.0`.
        .filter(|n| n.fract() == 0.0 && (0.0..=f64::from(u32::MAX)).contains(n))
        .map(|n| n as u32)
        .ok_or_else(|| refused("a leaf is a whole number from 0 to 4294967295"))
}

fn secret(value: &JsValue) -> Result<[u8; 32]> {
    input(value, "a recovery secret")?
        .try_into()
        .map_err(|_| refused("a recovery secret is 32 bytes"))
}

/// A commit, applied or refused: `{kind, epoch, by, added, removed}`.
fn change(kind: &str, epoch: u64, by: Vec<u8>, added: Vec<Vec<u8>>, removed: Vec<Vec<u8>>) -> Result<Object> {
    let keys = |list: Vec<Vec<u8>>| list.iter().map(|k| bytes(k)).collect::<Array>().into();
    object(&[
        ("kind", JsValue::from_str(kind)),
        ("epoch", number(epoch)),
        ("by", bytes(&by)),
        ("added", keys(added)),
        ("removed", keys(removed)),
    ])
}

/// One device's place in its owner's MLS group.
#[wasm_bindgen]
pub struct Member(core_::Member);

#[wasm_bindgen]
impl Member {
    #[wasm_bindgen(constructor)]
    pub fn new(#[wasm_bindgen(unchecked_param_type = "Uint8Array")] name: JsValue) -> Result<Member> {
        Ok(Self(core_::Member::new(&input(&name, "name")?).map_err(err)?))
    }

    /// A device from what `save()` wrote.
    pub fn load(#[wasm_bindgen(unchecked_param_type = "Uint8Array")] saved: JsValue) -> Result<Member> {
        Ok(Self(core_::Member::load(&input(&saved, "a save")?).map_err(err)?))
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
    pub fn create_group(&mut self, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] group_id: JsValue) -> Result<()> {
        self.0.create_group(&input(&group_id, "a group id")?).map_err(err)
    }

    /// Join the group a Welcome adds this device to. `adderSignatureKey` is the
    /// key of the device that should be adding this one, as confirmed while pairing.
    pub fn join(
        &mut self,
        #[wasm_bindgen(unchecked_param_type = "Uint8Array")] welcome: JsValue,
        #[wasm_bindgen(unchecked_param_type = "Uint8Array")] adder_signature_key: JsValue,
    ) -> Result<()> {
        let (welcome, adder) = (input(&welcome, "a Welcome")?, input(&adder_signature_key, "a signature key")?);
        self.0.join(&welcome, &adder).map_err(err)
    }

    /// Add the device whose key package this is and whose signature key the
    /// owner confirmed: `{commit, welcome}`, the commit for the others and the
    /// Welcome for it.
    pub fn add(
        &mut self,
        #[wasm_bindgen(unchecked_param_type = "Uint8Array")] key_package: JsValue,
        #[wasm_bindgen(unchecked_param_type = "Uint8Array")] signature_key: JsValue,
    ) -> Result<Object> {
        let (key_package, key) = (input(&key_package, "a key package")?, input(&signature_key, "a signature key")?);
        let added = self.0.add(&key_package, &key).map_err(err)?;
        object(&[("commit", bytes(&added.commit)), ("welcome", bytes(&added.welcome))])
    }

    /// Remove the device at this leaf index: the commit for the remaining members.
    pub fn remove(&mut self, #[wasm_bindgen(unchecked_param_type = "number")] leaf: JsValue) -> Result<Vec<u8>> {
        self.0.remove(leaf_index(&leaf)?).map_err(err)
    }

    pub fn seal(&mut self, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] plaintext: JsValue) -> Result<Vec<u8>> {
        self.0.seal(&input(&plaintext, "a message")?).map_err(err)
    }

    /// `{kind: "application", sender, senderKey, bytes}` or
    /// `{kind: "commit", epoch, by, added, removed}`: the committer's signature
    /// key and those of the devices added and removed; or the same with
    /// `kind: "refused"` for a commit a device that is not an admin made to add
    /// or remove a device or change the admin list, which is not
    /// applied. Leaf indices are reused after a removal: decide by `senderKey`.
    pub fn handle(&mut self, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] message: JsValue) -> Result<Object> {
        match self.0.handle(&input(&message, "a message")?).map_err(err)? {
            core_::Incoming::Application { sender, sender_key, bytes: b } => object(&[
                ("kind", JsValue::from_str("application")),
                ("sender", JsValue::from(sender)),
                ("senderKey", bytes(&sender_key)),
                ("bytes", bytes(&b)),
            ]),
            core_::Incoming::Commit { epoch, by, added, removed } => change("commit", epoch, by, added, removed),
            core_::Incoming::Refused { epoch, by, added, removed } => change("refused", epoch, by, added, removed),
        }
    }

    /// Make the device with this signature key an admin too: the commit for the others.
    #[wasm_bindgen(js_name = makeAdmin)]
    pub fn make_admin(&mut self, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] signature_key: JsValue) -> Result<Vec<u8>> {
        self.0.make_admin(&input(&signature_key, "a signature key")?).map_err(err)
    }

    /// The admin devices' signature keys: the only ones that may add or remove
    /// devices. A device paired again with a removed admin's keys is not one
    /// until an admin makes it one again.
    pub fn admins(&self) -> Result<Array> {
        Ok(self.0.admins().map_err(err)?.iter().map(|k| bytes(k)).collect())
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
    pub fn seal(&mut self, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] payload: JsValue, #[wasm_bindgen(unchecked_optional_param_type = "Uint8Array")] meta: JsValue) -> Result<Vec<u8>> {
        self.0.seal(&input(&payload, "a frame")?, &optional(&meta, "metadata")?).map_err(err)
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

    pub fn open(&mut self, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] frame: JsValue, #[wasm_bindgen(unchecked_optional_param_type = "Uint8Array")] meta: JsValue) -> Result<Vec<u8>> {
        self.0.open(&input(&frame, "a frame")?, &optional(&meta, "metadata")?).map_err(err)
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
    pub fn from_bytes(#[wasm_bindgen(unchecked_param_type = "Uint8Array")] raw: JsValue) -> Result<DataKey> {
        Ok(Self(core_::DataKey::from_bytes(&input(&raw, "a data key")?).map_err(err)?))
    }

    /// The raw key, to hand to another device of the same owner inside the group.
    #[wasm_bindgen(js_name = toBytes)]
    pub fn to_bytes(&self) -> Vec<u8> {
        self.0.to_bytes().to_vec()
    }

    pub fn seal(&self, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] purpose: JsValue, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] plaintext: JsValue) -> Result<Vec<u8>> {
        self.0.seal(&input(&purpose, "a purpose")?, &input(&plaintext, "data")?).map_err(err)
    }

    pub fn open(&self, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] purpose: JsValue, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] blob: JsValue) -> Result<Vec<u8>> {
        self.0.open(&input(&purpose, "a purpose")?, &input(&blob, "sealed data")?).map_err(err)
    }

    #[wasm_bindgen(js_name = wrapForRecovery)]
    pub fn wrap_for_recovery(&self, #[wasm_bindgen(unchecked_param_type = "Uint8Array")] recovery_secret: JsValue) -> Result<Vec<u8>> {
        self.0.wrap_for_recovery(&secret(&recovery_secret)?).map_err(err)
    }

    #[wasm_bindgen(js_name = unwrapFromRecovery)]
    pub fn unwrap_from_recovery(
        #[wasm_bindgen(unchecked_param_type = "Uint8Array")] recovery_secret: JsValue,
        #[wasm_bindgen(unchecked_param_type = "Uint8Array")] wrapped: JsValue,
    ) -> Result<DataKey> {
        let wrapped = input(&wrapped, "a wrapped key")?;
        Ok(Self(core_::DataKey::unwrap_from_recovery(&secret(&recovery_secret)?, &wrapped).map_err(err)?))
    }
}
