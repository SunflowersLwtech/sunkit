//! End-to-end encryption among one person's own devices.
//!
//! Three pieces, each a published standard run by an existing implementation;
//! nothing here invents a cryptographic construction:
//!
//! - [`Member`]: one device's place in its owner's MLS group (RFC 9420, OpenMLS).
//!   Adding a device takes a commit signed by a device already in the group;
//!   removing one moves the group to a key the removed device cannot compute.
//!   Application messages (state, events, commands) are MLS messages, so each
//!   carries its sender's authentication: a relay can drop them, not forge them.
//! - [`FrameSealer`] / [`FrameOpener`]: media frames encrypted with SFrame
//!   (RFC 9605), keyed from the MLS group exactly as RFC 9605 §5.2 says:
//!   `base_key = MLS-Exporter("SFrame 1.0 Base Key", "", AEAD.Nk)` per epoch and
//!   one KID range per member (sframe-rs). A frame proves it came from the
//!   group, not from which member (RFC 9605 §7.2): commands never travel as frames.
//! - [`DataKey`]: the key what is stored is sealed under (event history,
//!   conversations, a vlog's edit), so a device added later can read it; sent to
//!   each device inside the group, and wrapped under a recovery secret.
//!   XChaCha20-Poly1305 with a random 24-byte nonce (RustCrypto), keys from
//!   HKDF-SHA256 (RFC 5869).
//!
//! A [`Member`] lives in memory; [`Member::save`] and [`Member::load`] carry it
//! across a restart.

use std::collections::{HashMap, HashSet};

use chacha20poly1305::aead::{Aead, KeyInit, Payload};
use chacha20poly1305::{XChaCha20Poly1305, XNonce};
use hkdf::Hkdf;
use tls_codec::{Deserialize as _, Serialize as _};
use openmls::prelude::*;
use openmls_basic_credential::SignatureKeyPair;
use openmls_rust_crypto::OpenMlsRustCrypto;
use openmls_traits::OpenMlsProvider;
use rand::RngCore;
use sha2::Sha256;
use sframe::frame::validation::{ReplayAttackProtection, Tolerance};
use sframe::frame::{EncryptedFrame, MediaFrame, MonotonicCounter};
use sframe::header::KeyId;
use sframe::key::{DecryptionKey, EncryptionKey};
use sframe::mls::{MlsKeyId, MlsKeyIdBitRange};
use sframe::CipherSuite as FrameSuite;

/// X25519 + AES-128-GCM + SHA-256 + Ed25519, the mandatory MLS suite.
pub const CIPHERSUITE: Ciphersuite = Ciphersuite::MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519;
/// RFC 9605 AES_128_GCM_SHA256_128 (0x0004).
pub const FRAME_SUITE: FrameSuite = FrameSuite::AesGcm128Sha256;
/// RFC 9605 §5.2 exporter label.
pub const SFRAME_EXPORTER_LABEL: &str = "SFrame 1.0 Base Key";
/// Low bits of the epoch carried in a frame's KID: up to 16 epochs in flight.
pub const FRAME_EPOCH_BITS: u8 = 4;
/// Bits for the member index: up to 256 devices in one owner's group.
pub const FRAME_INDEX_BITS: u8 = 8;
/// Frames from one sender this far behind the newest are still accepted once.
pub const FRAME_REPLAY_TOLERANCE: usize = 128;

const DATA_VERSION: u8 = 1;
const SAVE_MAGIC: &[u8; 4] = b"HMS1";
const RECOVERY_SALT: &[u8] = b"hm-seal recovery v1";

#[derive(Debug, thiserror::Error)]
pub enum SealError {
    #[error("this device is not in a group")]
    NoGroup,
    #[error("the message could not be read: {0}")]
    BadMessage(String),
    #[error("this device was removed from the group")]
    Removed,
    #[error("MLS refused: {0}")]
    Mls(String),
    #[error("frame refused: {0}")]
    Frame(String),
    #[error("sealed data could not be opened")]
    Open,
    #[error("the saved state could not be read")]
    BadSave,
}

pub type Result<T> = std::result::Result<T, SealError>;

fn mls<E: std::fmt::Debug>(e: E) -> SealError {
    SealError::Mls(format!("{e:?}"))
}

/// What a device received through its group.
#[derive(PartialEq, Eq)]
pub enum Incoming {
    /// An application message and the leaf index of the device that sent it.
    Application { sender: u32, bytes: Vec<u8> },
    /// A commit was applied; the group is now at this epoch.
    Commit { epoch: u64 },
}

/// Prints the length of an application message, never its bytes: they are plaintext.
impl std::fmt::Debug for Incoming {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Incoming::Application { sender, bytes } => {
                write!(f, "Application {{ sender: {sender}, {} bytes }}", bytes.len())
            }
            Incoming::Commit { epoch } => write!(f, "Commit {{ epoch: {epoch} }}"),
        }
    }
}

/// A commit adding a device, and the Welcome that device joins with.
pub struct Added {
    pub commit: Vec<u8>,
    pub welcome: Vec<u8>,
}

/// One device: its signing key, its credential, and its group.
pub struct Member {
    provider: OpenMlsRustCrypto,
    signer: SignatureKeyPair,
    credential: CredentialWithKey,
    group: Option<MlsGroup>,
}

impl Member {
    /// A new device with a fresh signing key. `name` is how other devices see it.
    pub fn new(name: &[u8]) -> Result<Self> {
        let provider = OpenMlsRustCrypto::default();
        let signer = SignatureKeyPair::new(CIPHERSUITE.signature_algorithm()).map_err(mls)?;
        signer.store(provider.storage()).map_err(mls)?;
        let credential = CredentialWithKey {
            credential: BasicCredential::new(name.to_vec()).into(),
            signature_key: signer.public().into(),
        };
        Ok(Self { provider, signer, credential, group: None })
    }

    /// This device's public signing key: what an owner compares when adding it.
    pub fn signature_key(&self) -> Vec<u8> {
        self.signer.public().to_vec()
    }

    /// A key package another device can add this one with (TLS-encoded MLS message).
    pub fn key_package(&self) -> Result<Vec<u8>> {
        let bundle = KeyPackage::builder()
            .build(CIPHERSUITE, &self.provider, &self.signer, self.credential.clone())
            .map_err(mls)?;
        MlsMessageOut::from(bundle.key_package().clone())
            .tls_serialize_detached()
            .map_err(mls)
    }

    /// Start the owner's group with this device as its only member.
    pub fn create_group(&mut self, group_id: &[u8]) -> Result<()> {
        let config = MlsGroupCreateConfig::builder()
            .ciphersuite(CIPHERSUITE)
            .use_ratchet_tree_extension(true)
            .build();
        let group = MlsGroup::new_with_group_id(
            &self.provider,
            &self.signer,
            &config,
            GroupId::from_slice(group_id),
            self.credential.clone(),
        )
        .map_err(mls)?;
        self.group = Some(group);
        Ok(())
    }

    /// Join with the Welcome a device already in the group made when it added this one.
    pub fn join(&mut self, welcome: &[u8]) -> Result<()> {
        let message = MlsMessageIn::tls_deserialize_exact(welcome)
            .map_err(|e| SealError::BadMessage(format!("{e:?}")))?;
        let MlsMessageBodyIn::Welcome(welcome) = message.extract() else {
            return Err(SealError::BadMessage("not a Welcome".into()));
        };
        let config = MlsGroupJoinConfig::builder().use_ratchet_tree_extension(true).build();
        let staged = StagedWelcome::new_from_welcome(&self.provider, &config, welcome, None)
            .map_err(mls)?;
        self.group = Some(staged.into_group(&self.provider).map_err(mls)?);
        Ok(())
    }

    fn group(&self) -> Result<&MlsGroup> {
        self.group.as_ref().ok_or(SealError::NoGroup)
    }

    /// Add the device whose key package this is. The commit goes to every other
    /// member; the Welcome to the new device. This device moves to the new epoch.
    pub fn add(&mut self, key_package: &[u8]) -> Result<Added> {
        let message = MlsMessageIn::tls_deserialize_exact(key_package)
            .map_err(|e| SealError::BadMessage(format!("{e:?}")))?;
        let MlsMessageBodyIn::KeyPackage(kp) = message.extract() else {
            return Err(SealError::BadMessage("not a key package".into()));
        };
        let kp = kp.validate(self.provider.crypto(), ProtocolVersion::Mls10).map_err(mls)?;
        let (provider, signer) = (&self.provider, &self.signer);
        let group = self.group.as_mut().ok_or(SealError::NoGroup)?;
        let (commit, welcome, _) = group.add_members(provider, signer, &[kp]).map_err(mls)?;
        group.merge_pending_commit(provider).map_err(mls)?;
        Ok(Added {
            commit: commit.tls_serialize_detached().map_err(mls)?,
            welcome: welcome.tls_serialize_detached().map_err(mls)?,
        })
    }

    /// Remove the device at `leaf`. The commit goes to every remaining member.
    pub fn remove(&mut self, leaf: u32) -> Result<Vec<u8>> {
        let (provider, signer) = (&self.provider, &self.signer);
        let group = self.group.as_mut().ok_or(SealError::NoGroup)?;
        let (commit, _, _) = group
            .remove_members(provider, signer, &[LeafNodeIndex::new(leaf)])
            .map_err(mls)?;
        group.merge_pending_commit(provider).map_err(mls)?;
        commit.tls_serialize_detached().map_err(mls)
    }

    /// Seal application bytes for every other device in the group.
    pub fn seal(&mut self, plaintext: &[u8]) -> Result<Vec<u8>> {
        let (provider, signer) = (&self.provider, &self.signer);
        let group = self.group.as_mut().ok_or(SealError::NoGroup)?;
        group
            .create_message(provider, signer, plaintext)
            .map_err(mls)?
            .tls_serialize_detached()
            .map_err(mls)
    }

    /// Read one message from the group: an application message or a commit.
    pub fn handle(&mut self, message: &[u8]) -> Result<Incoming> {
        let message = MlsMessageIn::tls_deserialize_exact(message)
            .map_err(|e| SealError::BadMessage(format!("{e:?}")))?;
        let protocol = message
            .try_into_protocol_message()
            .map_err(|e| SealError::BadMessage(format!("{e:?}")))?;
        let provider = &self.provider;
        let group = self.group.as_mut().ok_or(SealError::NoGroup)?;
        if !group.is_active() {
            return Err(SealError::Removed);
        }
        let processed = group.process_message(provider, protocol).map_err(mls)?;
        let sender = match processed.sender() {
            Sender::Member(leaf) => leaf.u32(),
            _ => return Err(SealError::BadMessage("not from a member".into())),
        };
        match processed.into_content() {
            ProcessedMessageContent::ApplicationMessage(app) => {
                Ok(Incoming::Application { sender, bytes: app.into_bytes() })
            }
            ProcessedMessageContent::StagedCommitMessage(staged) => {
                group.merge_staged_commit(provider, *staged).map_err(mls)?;
                if !group.is_active() {
                    return Err(SealError::Removed);
                }
                Ok(Incoming::Commit { epoch: group.epoch().as_u64() })
            }
            _ => Err(SealError::BadMessage("proposals are not used".into())),
        }
    }

    pub fn epoch(&self) -> Result<u64> {
        Ok(self.group()?.epoch().as_u64())
    }

    pub fn leaf_index(&self) -> Result<u32> {
        Ok(self.group()?.own_leaf_index().u32())
    }

    /// (leaf index, name) of every device in the group.
    pub fn members(&self) -> Result<Vec<(u32, Vec<u8>)>> {
        Ok(self
            .group()?
            .members()
            .map(|m| (m.index.u32(), m.credential.serialized_content().to_vec()))
            .collect())
    }

    /// Everything this device needs to carry on after a restart, its private
    /// keys included: keep it where only this device's user can read it (a file
    /// of mode 600, the Keychain) or seal it under a key that is. Save again
    /// after every call that changes the group or its keys (`key_package`,
    /// `create_group`, `join`, `add`, `remove`, `seal`, `handle`), so a restart
    /// never goes back to an older state.
    pub fn save(&self) -> Result<Vec<u8>> {
        let mut out = Vec::new();
        out.extend_from_slice(SAVE_MAGIC);
        put_field(&mut out, self.credential.credential.serialized_content());
        put_field(&mut out, self.signer.public());
        put_field(&mut out, self.group.as_ref().map(|g| g.group_id().as_slice()).unwrap_or(&[]));
        let values = self.provider.storage().values.read().map_err(|_| SealError::BadSave)?;
        let mut entries: Vec<_> = values.iter().collect();
        entries.sort();
        out.extend_from_slice(&(entries.len() as u32).to_be_bytes());
        for (k, v) in entries {
            put_field(&mut out, k);
            put_field(&mut out, v);
        }
        Ok(out)
    }

    /// A device from what [`Member::save`] wrote.
    pub fn load(saved: &[u8]) -> Result<Self> {
        let mut r = Reader(saved);
        if r.take(4)? != SAVE_MAGIC {
            return Err(SealError::BadSave);
        }
        let name = r.field()?.to_vec();
        let public = r.field()?.to_vec();
        let group_id = r.field()?.to_vec();
        let count = u32::from_be_bytes(r.take(4)?.try_into().map_err(|_| SealError::BadSave)?);
        let provider = OpenMlsRustCrypto::default();
        {
            let mut values = provider.storage().values.write().map_err(|_| SealError::BadSave)?;
            for _ in 0..count {
                let key = r.field()?.to_vec();
                let value = r.field()?.to_vec();
                values.insert(key, value);
            }
        }
        if !r.0.is_empty() {
            return Err(SealError::BadSave);
        }
        let signer = SignatureKeyPair::read(provider.storage(), &public, CIPHERSUITE.signature_algorithm())
            .ok_or(SealError::BadSave)?;
        let credential = CredentialWithKey {
            credential: BasicCredential::new(name).into(),
            signature_key: signer.public().into(),
        };
        let group = if group_id.is_empty() {
            None
        } else {
            Some(
                MlsGroup::load(provider.storage(), &GroupId::from_slice(&group_id))
                    .map_err(mls)?
                    .ok_or(SealError::BadSave)?,
            )
        };
        Ok(Self { provider, signer, credential, group })
    }

    fn frame_base_key(&self) -> Result<Vec<u8>> {
        self.group()?
            .export_secret(self.provider.crypto(), SFRAME_EXPORTER_LABEL, b"", FRAME_SUITE.key_len())
            .map_err(mls)
    }

    /// A sealer for this device's frames in the current epoch.
    ///
    /// Each sealer takes a fresh random context value in its KID (RFC 9605 §5.2:
    /// "Senders may choose any KID value within their assigned set of KID
    /// values"), and the frame key is derived from the KID, so two sealers of one
    /// epoch (two streams, or the same device after a restart) never share a key
    /// although each counts its frames from 0.
    pub fn frame_sealer(&self) -> Result<FrameSealer> {
        let base = self.frame_base_key()?;
        let kid = frame_kid(random_context(), self.epoch()?, self.leaf_index()?)?;
        Ok(FrameSealer { key: frame_encryption_key(&base, kid)?, counter: MonotonicCounter::default() })
    }

    /// Let `opener` read the other members' frames of the current epoch.
    ///
    /// The previous epoch stays readable (frames in flight across a commit) only
    /// while every device that was in it is still in the group. A device that
    /// left knows that epoch's base key and could seal frames under any member's
    /// KID in it (RFC 9605 §7.2), so after a removal the previous epoch is
    /// dropped at once. Devices are compared by signature key, because MLS gives
    /// a removed device's leaf index to the next device added. Older epochs are
    /// always dropped, with their keys and replay windows.
    pub fn update_opener(&self, opener: &mut FrameOpener) -> Result<()> {
        let group = self.group()?;
        let epoch = group.epoch().as_u64();
        let me = group.own_leaf_index();
        let mut senders = HashSet::new();
        let mut signers = HashSet::new();
        for m in group.members() {
            if m.index != me {
                senders.insert(m.index.u32());
            }
            signers.insert(m.signature_key);
        }
        let base_key = self.frame_base_key()?;
        opener
            .epochs
            .retain(|_, e| e.epoch == epoch || (e.epoch + 1 == epoch && e.signers.is_subset(&signers)));
        let kept: HashSet<u64> = opener.epochs.values().map(|e| e.epoch).collect();
        opener.keys.retain(|(e, _), _| kept.contains(e));
        opener.replay.retain(|(e, _), _| kept.contains(e));
        // RFC 9605 §5.2: an epoch with the same low bits replaces the old one.
        opener
            .epochs
            .insert(epoch % (1 << FRAME_EPOCH_BITS), OpenerEpoch { epoch, base_key, senders, signers });
        Ok(())
    }

    /// The group's MLS exporter with any label, context and length, so a test can
    /// check the frame key against RFC 9605 §5.2 independently of this crate's constants.
    #[cfg(feature = "test-support")]
    #[doc(hidden)]
    pub fn export_secret_for_test(&self, label: &str, context: &[u8], len: usize) -> Result<Vec<u8>> {
        self.group()?.export_secret(self.provider.crypto(), label, context, len).map_err(mls)
    }
}

fn frame_encryption_key<K: Into<sframe::header::KeyId>>(base: &[u8], kid: K) -> Result<EncryptionKey> {
    EncryptionKey::derive_from(FRAME_SUITE, kid, base).map_err(|e| SealError::Frame(format!("{e:?}")))
}

/// RFC 9605 Appendix C known-answer check: one frame from a raw base key, KID and
/// counter. Test builds only: a caller choosing the counter can repeat a nonce.
#[cfg(feature = "test-support")]
#[doc(hidden)]
pub fn seal_frame_with_base_key(base_key: &[u8], kid: u64, counter: u64, payload: &[u8], meta: &[u8]) -> Result<Vec<u8>> {
    let key = frame_encryption_key(base_key, kid)?;
    let mut ctr = sframe::frame::SingleUseCounter::new(counter);
    let frame = MediaFrame::try_with_meta_data(&mut ctr, payload, meta)
        .map_err(|e| SealError::Frame(format!("{e:?}")))?;
    let encrypted = frame.encrypt(&key).map_err(|e| SealError::Frame(format!("{e:?}")))?;
    Ok(encrypted.as_ref()[meta.len()..].to_vec())
}

fn put_field(out: &mut Vec<u8>, bytes: &[u8]) {
    out.extend_from_slice(&(bytes.len() as u32).to_be_bytes());
    out.extend_from_slice(bytes);
}

struct Reader<'a>(&'a [u8]);

impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8]> {
        if self.0.len() < n {
            return Err(SealError::BadSave);
        }
        let (head, rest) = self.0.split_at(n);
        self.0 = rest;
        Ok(head)
    }

    fn field(&mut self) -> Result<&'a [u8]> {
        let len = u32::from_be_bytes(self.take(4)?.try_into().map_err(|_| SealError::BadSave)?);
        self.take(len as usize)
    }
}

fn frame_bits() -> MlsKeyIdBitRange {
    MlsKeyIdBitRange::new(FRAME_EPOCH_BITS, FRAME_INDEX_BITS)
}

/// A random context value filling the KID bits above epoch and member index.
fn random_context() -> u64 {
    rand::rngs::OsRng.next_u64() >> (FRAME_EPOCH_BITS + FRAME_INDEX_BITS)
}

fn frame_kid(context: u64, epoch: u64, leaf: u32) -> Result<MlsKeyId> {
    MlsKeyId::try_new(context, epoch, u64::from(leaf), frame_bits())
        .map_err(|e| SealError::Frame(format!("{e:?}")))
}

/// Encrypts one device's frames (RFC 9605) for the epoch it was made in.
pub struct FrameSealer {
    key: EncryptionKey,
    counter: MonotonicCounter,
}

impl FrameSealer {
    /// One encrypted frame: SFrame header, ciphertext and tag. `meta` is
    /// authenticated, not encrypted, and is not part of the output.
    pub fn seal(&mut self, payload: &[u8], meta: &[u8]) -> Result<Vec<u8>> {
        let frame = MediaFrame::try_with_meta_data(&mut self.counter, payload, meta)
            .map_err(|e| SealError::Frame(format!("{e:?}")))?;
        let encrypted = frame.encrypt(&self.key).map_err(|e| SealError::Frame(format!("{e:?}")))?;
        Ok(encrypted.as_ref()[meta.len()..].to_vec())
    }
}

struct OpenerEpoch {
    epoch: u64,
    base_key: Vec<u8>,
    /// Leaf indices whose frames this opener accepts: every member but itself.
    senders: HashSet<u32>,
    /// Signature keys of every member in this epoch, itself included.
    signers: HashSet<Vec<u8>>,
}

/// Decrypts the other members' frames, refusing a frame seen before.
///
/// A frame's key is derived from its KID (sender, epoch, the sealer's context)
/// and kept only once a frame under it has opened, so frames under made-up
/// KIDs cost a derivation and a failed tag check, and leave nothing behind.
#[derive(Default)]
pub struct FrameOpener {
    epochs: HashMap<u64, OpenerEpoch>,
    keys: HashMap<(u64, KeyId), DecryptionKey>,
    replay: HashMap<(u64, KeyId), ReplayAttackProtection>,
}

impl FrameOpener {
    pub fn open(&mut self, frame: &[u8], meta: &[u8]) -> Result<Vec<u8>> {
        let bad = |e: &dyn std::fmt::Debug| SealError::Frame(format!("{e:?}"));
        let encrypted = EncryptedFrame::try_with_meta_data(frame, meta).map_err(|e| bad(&e))?;
        let kid = encrypted.header().key_id();
        let parts = MlsKeyId::from_key_id(kid, frame_bits());
        let entry = self
            .epochs
            .get(&parts.epoch_lsb())
            .ok_or_else(|| SealError::Frame("no key for this frame's epoch".into()))?;
        let sender = u32::try_from(parts.member_index()).map_err(|e| bad(&e))?;
        if !entry.senders.contains(&sender) {
            return Err(SealError::Frame("not a frame of another member".into()));
        }
        let slot = (entry.epoch, kid);
        if let (Some(key), Some(replay)) = (self.keys.get(&slot), self.replay.get_mut(&slot)) {
            let media = encrypted.validated_decrypt(key, replay).map_err(|e| bad(&e))?;
            return Ok(media.payload().to_vec());
        }
        let key = DecryptionKey::derive_from(FRAME_SUITE, kid, &entry.base_key).map_err(|e| bad(&e))?;
        let mut replay = ReplayAttackProtection::new(kid, Tolerance::new(FRAME_REPLAY_TOLERANCE));
        let media = encrypted.validated_decrypt(&key, &mut replay).map_err(|e| bad(&e))?;
        let payload = media.payload().to_vec();
        self.keys.insert(slot, key);
        self.replay.insert(slot, replay);
        Ok(payload)
    }
}

/// The key stored data is sealed under. 32 random bytes.
#[derive(Clone)]
pub struct DataKey([u8; 32]);

impl DataKey {
    pub fn generate() -> Self {
        let mut k = [0u8; 32];
        rand::rngs::OsRng.fill_bytes(&mut k);
        Self(k)
    }

    pub fn from_bytes(bytes: &[u8]) -> Result<Self> {
        Ok(Self(bytes.try_into().map_err(|_| SealError::Open)?))
    }

    /// The raw key, for sending to another device of the same owner inside the group.
    pub fn to_bytes(&self) -> [u8; 32] {
        self.0
    }

    /// Seal `plaintext` for `purpose` (bound into the tag: a blob sealed for one
    /// purpose does not open as another). Output: version || nonce || ciphertext.
    pub fn seal(&self, purpose: &[u8], plaintext: &[u8]) -> Result<Vec<u8>> {
        seal_with(&self.0, purpose, plaintext)
    }

    pub fn open(&self, purpose: &[u8], blob: &[u8]) -> Result<Vec<u8>> {
        open_with(&self.0, purpose, blob)
    }

    /// This key, wrapped under a 32-byte recovery secret the owner keeps.
    pub fn wrap_for_recovery(&self, recovery_secret: &[u8; 32]) -> Result<Vec<u8>> {
        seal_with(&recovery_kek(recovery_secret), RECOVERY_SALT, &self.0)
    }

    pub fn unwrap_from_recovery(recovery_secret: &[u8; 32], wrapped: &[u8]) -> Result<Self> {
        Self::from_bytes(&open_with(&recovery_kek(recovery_secret), RECOVERY_SALT, wrapped)?)
    }
}

fn recovery_kek(secret: &[u8; 32]) -> [u8; 32] {
    let mut out = [0u8; 32];
    Hkdf::<Sha256>::new(Some(RECOVERY_SALT), secret)
        .expand(b"data key wrap", &mut out)
        .expect("32 bytes is a valid HKDF-SHA256 length");
    out
}

fn seal_with(key: &[u8; 32], aad: &[u8], plaintext: &[u8]) -> Result<Vec<u8>> {
    let cipher = XChaCha20Poly1305::new(key.into());
    let mut nonce = [0u8; 24];
    rand::rngs::OsRng.fill_bytes(&mut nonce);
    let ct = cipher
        .encrypt(XNonce::from_slice(&nonce), Payload { msg: plaintext, aad })
        .map_err(|_| SealError::Open)?;
    let mut out = Vec::with_capacity(1 + 24 + ct.len());
    out.push(DATA_VERSION);
    out.extend_from_slice(&nonce);
    out.extend_from_slice(&ct);
    Ok(out)
}

fn open_with(key: &[u8; 32], aad: &[u8], blob: &[u8]) -> Result<Vec<u8>> {
    if blob.len() < 1 + 24 + 16 || blob[0] != DATA_VERSION {
        return Err(SealError::Open);
    }
    XChaCha20Poly1305::new(key.into())
        .decrypt(XNonce::from_slice(&blob[1..25]), Payload { msg: &blob[25..], aad })
        .map_err(|_| SealError::Open)
}
