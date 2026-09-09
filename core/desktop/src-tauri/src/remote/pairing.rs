use std::{
    collections::HashMap,
    sync::{Arc, RwLock},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use getrandom::fill as fill_random;
use serde::{Deserialize, Serialize};

use super::identity::{random_token, DeviceIdentity};
use super::secure_store::SecureStore;
use super::{REMOTE_PROTOCOL, REMOTE_PROTOCOL_VERSION};

const DEFAULT_PAIRING_TTL: Duration = Duration::from_secs(5 * 60);
const PAIRING_CODE_LENGTH: usize = 6;
const PAIRING_CODE_SPACE: u64 = 1_000_000;
const MAX_PAIRING_ATTEMPTS: u8 = 5;
const TRUSTED_PEERS_INDEX_KEY: &str = "trusted-peers-index-v1";
const TRUSTED_PEER_STORAGE_PREFIX: &str = "trusted-peer-v1-";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PairingCodePayload {
    pub pairing_id: String,
    #[serde(skip_serializing_if = "String::is_empty")]
    pub code: String,
    pub desktop_device_id: String,
    pub desktop_public_key: String,
    pub gateway_url: String,
    pub expires_at_ms: u64,
    pub protocol: String,
    pub version: u8,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub relay_url: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TrustedPeerSummary {
    pub device_id: String,
    pub name: String,
    pub platform: String,
    pub paired_at_ms: u64,
    pub last_seen_ms: u64,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PairingRedemption {
    pub desktop_device_id: String,
    pub desktop_public_key: String,
    pub device_id: String,
    pub access_token: String,
    pub gateway_url: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub relay_url: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PairingRedeemRequest {
    pub code: String,
    pub device_id: String,
    #[serde(default)]
    pub device_name: String,
    #[serde(default)]
    pub platform: String,
    #[serde(default)]
    pub mobile_public_key: String,
}

#[derive(Clone, Debug)]
struct PairingRecord {
    code: String,
    gateway_url: String,
    relay_url: Option<String>,
    expires_at_ms: u64,
    attempts: u8,
    consumed: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct TrustedPeer {
    summary: TrustedPeerSummary,
    access_token: String,
    #[serde(default)]
    public_key: String,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
struct TrustedPeerIndex {
    device_ids: Vec<String>,
}

/// Pairing/trust registry. Pairing sessions remain process-local and
/// short-lived; trusted peer tokens are persisted through a secure store.
#[derive(Clone)]
pub struct PairingManager {
    identity: DeviceIdentity,
    ttl: Duration,
    pairings: Arc<RwLock<HashMap<String, PairingRecord>>>,
    trusted: Arc<RwLock<HashMap<String, TrustedPeer>>>,
    secure_store: Option<Arc<dyn SecureStore>>,
}

impl PairingManager {
    #[cfg(test)]
    pub fn new(identity: DeviceIdentity) -> Self {
        Self {
            identity,
            ttl: DEFAULT_PAIRING_TTL,
            pairings: Arc::new(RwLock::new(HashMap::new())),
            trusted: Arc::new(RwLock::new(HashMap::new())),
            secure_store: None,
        }
    }

    pub fn with_secure_store(
        identity: DeviceIdentity,
        secure_store: Arc<dyn SecureStore>,
    ) -> Result<Self, String> {
        // Keep the index tiny and each device independent. Keychain and
        // Credential Manager entries have provider-specific size limits; a
        // single JSON blob containing every peer eventually becomes
        // unwriteable. The index contains identifiers only, while each
        // device's credential and public key live in its own entry.
        let index = secure_store
            .load(TRUSTED_PEERS_INDEX_KEY)?
            .map(|bytes| serde_json::from_slice::<TrustedPeerIndex>(&bytes))
            .transpose()
            .map_err(|error| format!("stored trusted peer index is invalid: {error}"))?
            .unwrap_or_default();
        let mut trusted = HashMap::new();
        for device_id in index.device_ids {
            let key = trusted_peer_storage_key(&device_id);
            let Some(bytes) = secure_store.load(&key)? else {
                // A partially written entry is not a usable trusted device;
                // leave it out and let the next successful write repair the
                // index.
                continue;
            };
            let peer = serde_json::from_slice::<TrustedPeer>(&bytes)
                .map_err(|error| format!("stored trusted peer is invalid: {error}"))?;
            if peer.summary.device_id != device_id {
                return Err("stored trusted peer identity does not match its key".to_string());
            }
            trusted.insert(device_id, peer);
        }
        Ok(Self {
            identity,
            ttl: DEFAULT_PAIRING_TTL,
            pairings: Arc::new(RwLock::new(HashMap::new())),
            trusted: Arc::new(RwLock::new(trusted)),
            secure_store: Some(secure_store),
        })
    }

    pub fn create(&self, gateway_url: &str) -> Result<PairingCodePayload, String> {
        self.prune()?;
        let pairing_id = random_token(18)?;
        let code = random_pairing_code()?;
        let expires_at_ms = now_ms().saturating_add(self.ttl.as_millis() as u64);
        let mut pairings = self
            .pairings
            .write()
            .map_err(|_| "pairing store lock failed".to_string())?;
        // There is exactly one code shown by the desktop at a time. Creating
        // a new code invalidates any older code, which keeps Relay and the UI
        // aligned and avoids stale codes remaining usable for five minutes.
        pairings.clear();
        let gateway_url = gateway_url.trim_end_matches('/').to_string();
        pairings.insert(
            pairing_id.clone(),
            PairingRecord {
                code: code.clone(),
                gateway_url: gateway_url.clone(),
                relay_url: None,
                expires_at_ms,
                attempts: 0,
                consumed: false,
            },
        );
        Ok(PairingCodePayload {
            pairing_id,
            code,
            desktop_device_id: self.identity.device_id.clone(),
            desktop_public_key: self.identity.public_key.clone(),
            gateway_url,
            expires_at_ms,
            protocol: REMOTE_PROTOCOL.to_string(),
            version: REMOTE_PROTOCOL_VERSION,
            relay_url: None,
        })
    }

    pub fn device_id(&self) -> String {
        self.identity.device_id.clone()
    }

    /// Resolve the public part of the currently displayed pairing code. This
    /// is bootstrap metadata only; redemption and trust establishment still
    /// happen inside the Noise handshake.
    pub fn resolve(&self, code: &str, gateway_url: &str) -> Result<PairingCodePayload, String> {
        let code = code.trim();
        if !is_valid_pairing_code(code) {
            return Err("配对码必须是六位数字".to_string());
        }
        self.prune()?;
        let pairings = self
            .pairings
            .read()
            .map_err(|_| "pairing store lock failed".to_string())?;
        let Some((pairing_id, record)) = pairings.iter().find(|(_, record)| {
            !record.consumed && constant_time_eq(record.code.as_bytes(), code.as_bytes())
        }) else {
            return Err("配对码无效、已过期或电脑未连接".to_string());
        };
        Ok(PairingCodePayload {
            pairing_id: pairing_id.clone(),
            code: String::new(),
            desktop_device_id: self.identity.device_id.clone(),
            desktop_public_key: self.identity.public_key.clone(),
            gateway_url: if record.gateway_url.is_empty() {
                gateway_url.trim_end_matches('/').to_string()
            } else {
                record.gateway_url.clone()
            },
            expires_at_ms: record.expires_at_ms,
            protocol: REMOTE_PROTOCOL.to_string(),
            version: REMOTE_PROTOCOL_VERSION,
            relay_url: record.relay_url.clone(),
        })
    }

    pub fn redeem(
        &self,
        pairing_id: &str,
        request: PairingRedeemRequest,
        gateway_url: &str,
    ) -> Result<PairingRedemption, String> {
        let pairing_id = pairing_id.trim();
        let code = request.code.trim().to_string();
        if pairing_id.is_empty()
            || !is_valid_pairing_code(&code)
            || request.device_id.trim().is_empty()
        {
            return Err("pairing_id, code and device_id are required".to_string());
        }
        let now = now_ms();
        let mut pairings = self
            .pairings
            .write()
            .map_err(|_| "pairing store lock failed".to_string())?;
        let record = pairings
            .get_mut(pairing_id)
            .ok_or_else(|| "配对已失效或不存在".to_string())?;
        if record.consumed || record.expires_at_ms <= now {
            return Err("配对码无效、已过期或已使用".to_string());
        }
        if !constant_time_eq(record.code.as_bytes(), code.as_bytes()) {
            record.attempts = record.attempts.saturating_add(1);
            if record.attempts >= MAX_PAIRING_ATTEMPTS {
                record.consumed = true;
                return Err("配对码尝试次数过多，请在电脑端重新生成".to_string());
            }
            return Err("配对码无效、已过期或已使用".to_string());
        }
        record.consumed = true;
        drop(pairings);

        let device_id = request.device_id.trim().to_string();
        let access_token = random_token(32)?;
        let paired_at_ms = now;
        let summary = TrustedPeerSummary {
            device_id: device_id.clone(),
            name: if request.device_name.trim().is_empty() {
                device_id.clone()
            } else {
                request.device_name.trim().to_string()
            },
            platform: if request.platform.trim().is_empty() {
                "mobile".to_string()
            } else {
                request.platform.trim().to_string()
            },
            paired_at_ms,
            last_seen_ms: paired_at_ms,
        };
        self.trusted
            .write()
            .map_err(|_| "trusted peer store lock failed".to_string())?
            .insert(
                device_id.clone(),
                TrustedPeer {
                    summary,
                    access_token: access_token.clone(),
                    public_key: request.mobile_public_key.trim().to_string(),
                },
            );
        self.persist_trusted_peer(&device_id)?;

        Ok(PairingRedemption {
            desktop_device_id: self.identity.device_id.clone(),
            desktop_public_key: self.identity.public_key.clone(),
            device_id,
            access_token,
            gateway_url: gateway_url.trim_end_matches('/').to_string(),
            relay_url: None,
        })
    }

    #[cfg(test)]
    pub fn trusted_tokens(&self) -> Result<Vec<String>, String> {
        self.trusted
            .read()
            .map_err(|_| "trusted peer store lock failed".to_string())
            .map(|trusted| {
                trusted
                    .values()
                    .map(|peer| peer.access_token.clone())
                    .collect()
            })
    }

    pub fn authenticate(&self, access_token: &str) -> Result<bool, String> {
        let now = now_ms();
        let changed_peer = {
            let mut trusted = self
                .trusted
                .write()
                .map_err(|_| "trusted peer store lock failed".to_string())?;
            let Some(peer) = trusted.values_mut().find(|peer| {
                constant_time_eq(peer.access_token.as_bytes(), access_token.as_bytes())
            }) else {
                return Ok(false);
            };
            let device_id = peer.summary.device_id.clone();
            let should_persist = now.saturating_sub(peer.summary.last_seen_ms) >= 60_000;
            peer.summary.last_seen_ms = now;
            should_persist.then(|| (device_id, peer.clone()))
        };
        if let Some((device_id, peer)) = changed_peer {
            self.persist_trusted_peer_value(&device_id, &peer)?;
        }
        Ok(true)
    }

    pub fn authenticate_peer(
        &self,
        public_key: &[u8],
        access_token: &str,
        device_id: &str,
    ) -> Result<bool, String> {
        let encoded_key = super::identity::encode_urlsafe(public_key);
        let trusted = self
            .trusted
            .read()
            .map_err(|_| "trusted peer store lock failed".to_string())?;
        Ok(trusted.values().any(|peer| {
            !peer.public_key.is_empty()
                && constant_time_eq(peer.public_key.as_bytes(), encoded_key.as_bytes())
                && constant_time_eq(peer.access_token.as_bytes(), access_token.as_bytes())
                && peer.summary.device_id == device_id
        }))
    }

    pub fn pairing_exists(&self, pairing_id: &str) -> Result<bool, String> {
        self.prune()?;
        let pairings = self
            .pairings
            .read()
            .map_err(|_| "pairing store lock failed".to_string())?;
        Ok(pairings
            .get(pairing_id)
            .is_some_and(|record| !record.consumed && record.attempts < MAX_PAIRING_ATTEMPTS))
    }

    pub fn trusted_devices(&self) -> Result<Vec<TrustedPeerSummary>, String> {
        self.trusted
            .read()
            .map_err(|_| "trusted peer store lock failed".to_string())
            .map(|trusted| trusted.values().map(|peer| peer.summary.clone()).collect())
    }

    pub fn revoke(&self, device_id: &str) -> Result<bool, String> {
        let removed = self
            .trusted
            .write()
            .map_err(|_| "trusted peer store lock failed")?
            .remove(device_id.trim())
            .is_some();
        if removed {
            if let Some(store) = self.secure_store.as_ref() {
                store.delete(&trusted_peer_storage_key(device_id.trim()))?;
            }
            self.persist_trusted_index()?;
        }
        Ok(removed)
    }

    pub fn prune(&self) -> Result<(), String> {
        let now = now_ms();
        self.pairings
            .write()
            .map_err(|_| "pairing store lock failed".to_string())?
            .retain(|_, record| !record.consumed && record.expires_at_ms > now);
        Ok(())
    }

    fn persist_trusted_peer(&self, device_id: &str) -> Result<(), String> {
        let peer = self
            .trusted
            .read()
            .map_err(|_| "trusted peer store lock failed".to_string())?
            .get(device_id)
            .cloned();
        let Some(peer) = peer else {
            return Ok(());
        };
        self.persist_trusted_peer_value(device_id, &peer)
    }

    fn persist_trusted_peer_value(
        &self,
        device_id: &str,
        peer: &TrustedPeer,
    ) -> Result<(), String> {
        let Some(store) = self.secure_store.as_ref() else {
            return Ok(());
        };
        store.save(
            &trusted_peer_storage_key(device_id),
            &serde_json::to_vec(peer).map_err(|error| error.to_string())?,
        )?;
        self.persist_trusted_index()
    }

    fn persist_trusted_index(&self) -> Result<(), String> {
        let Some(store) = self.secure_store.as_ref() else {
            return Ok(());
        };
        let trusted = self
            .trusted
            .read()
            .map_err(|_| "trusted peer store lock failed".to_string())?;
        let mut device_ids = trusted.keys().cloned().collect::<Vec<_>>();
        device_ids.sort_unstable();
        let index = TrustedPeerIndex { device_ids };
        store.save(
            TRUSTED_PEERS_INDEX_KEY,
            &serde_json::to_vec(&index).map_err(|error| error.to_string())?,
        )
    }
}

fn trusted_peer_storage_key(device_id: &str) -> String {
    format!(
        "{TRUSTED_PEER_STORAGE_PREFIX}{}",
        super::identity::encode_urlsafe(device_id.as_bytes())
    )
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn random_pairing_code() -> Result<String, String> {
    // Rejection sampling keeps every six-digit value equally likely while
    // preserving leading zeroes for display and manual entry.
    let range = (u32::MAX as u64) + 1;
    let limit = range - (range % PAIRING_CODE_SPACE);
    let mut bytes = [0_u8; 4];
    loop {
        fill_random(&mut bytes).map_err(|error| error.to_string())?;
        let value = u32::from_le_bytes(bytes) as u64;
        if value < limit {
            return Ok(format!("{:06}", value % PAIRING_CODE_SPACE));
        }
    }
}

fn is_valid_pairing_code(value: &str) -> bool {
    value.len() == PAIRING_CODE_LENGTH && value.bytes().all(|byte| byte.is_ascii_digit())
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut diff = 0_u8;
    for (a, b) in left.iter().zip(right.iter()) {
        diff |= a ^ b;
    }
    diff == 0
}

#[cfg(test)]
mod tests {
    use super::{
        is_valid_pairing_code, random_pairing_code, trusted_peer_storage_key, PairingManager,
        PairingRedeemRequest, TRUSTED_PEERS_INDEX_KEY,
    };
    use crate::remote::identity::DeviceIdentity;
    use crate::remote::secure_store::{MemorySecureStore, SecureStore};
    use std::sync::Arc;

    #[test]
    fn pairing_codes_are_six_decimal_digits() {
        for _ in 0..128 {
            let code = random_pairing_code().expect("pairing code");
            assert!(is_valid_pairing_code(&code), "invalid pairing code: {code}");
        }
        assert!(is_valid_pairing_code("012345"));
        assert!(!is_valid_pairing_code("12345"));
        assert!(!is_valid_pairing_code("1234567"));
        assert!(!is_valid_pairing_code("12a456"));
    }

    #[test]
    fn pairing_is_single_use() {
        let identity = DeviceIdentity::generate().expect("identity");
        let manager = PairingManager::new(identity);
        let pairing = manager.create("http://127.0.0.1:4000").expect("pairing");
        let request = PairingRedeemRequest {
            code: pairing.code.clone(),
            device_id: "mobile-test".to_string(),
            device_name: "Test phone".to_string(),
            platform: "test".to_string(),
            mobile_public_key: "mobile-key".to_string(),
        };
        let redemption = manager
            .redeem(
                &pairing.pairing_id,
                request.clone(),
                "http://127.0.0.1:4000",
            )
            .expect("redeem");
        assert_eq!(redemption.device_id, "mobile-test");
        assert!(manager
            .redeem(&pairing.pairing_id, request, "http://127.0.0.1:4000")
            .is_err());
        assert_eq!(manager.trusted_devices().expect("trusted").len(), 1);
    }

    #[test]
    fn trusted_peer_tokens_persist_and_revocation_persists() {
        let identity = DeviceIdentity::generate().expect("identity");
        let store = Arc::new(MemorySecureStore::default());
        let manager =
            PairingManager::with_secure_store(identity.clone(), store.clone()).expect("manager");
        let pairing = manager.create("http://127.0.0.1:4000").expect("pairing");
        let redemption = manager
            .redeem(
                &pairing.pairing_id,
                PairingRedeemRequest {
                    code: pairing.code,
                    device_id: "phone-1".to_string(),
                    device_name: "Phone".to_string(),
                    platform: "ios".to_string(),
                    mobile_public_key: "mobile-key".to_string(),
                },
                "http://127.0.0.1:4000",
            )
            .expect("redeem");

        let restored =
            PairingManager::with_secure_store(identity.clone(), store.clone()).expect("restore");
        assert_eq!(restored.trusted_devices().expect("devices").len(), 1);
        assert_eq!(
            restored.trusted_tokens().expect("tokens"),
            vec![redemption.access_token.clone()]
        );
        assert!(restored
            .authenticate(&redemption.access_token)
            .expect("authenticate"));
        assert!(restored.revoke("phone-1").expect("revoke"));
        assert!(!restored
            .authenticate(&redemption.access_token)
            .expect("revoked auth"));

        let after_revoke =
            PairingManager::with_secure_store(identity, store).expect("restore after revoke");
        assert!(after_revoke.trusted_devices().expect("devices").is_empty());
        assert!(after_revoke.trusted_tokens().expect("tokens").is_empty());
    }

    #[test]
    fn trusted_peers_are_stored_in_independent_entries() {
        let identity = DeviceIdentity::generate().expect("identity");
        let store = Arc::new(MemorySecureStore::default());
        let manager = PairingManager::with_secure_store(identity, store.clone()).expect("manager");

        for device_id in ["phone-a", "phone-b"] {
            let pairing = manager.create("http://127.0.0.1:4000").expect("pairing");
            manager
                .redeem(
                    &pairing.pairing_id,
                    PairingRedeemRequest {
                        code: pairing.code,
                        device_id: device_id.to_string(),
                        device_name: device_id.to_string(),
                        platform: "test".to_string(),
                        mobile_public_key: format!("{device_id}-key"),
                    },
                    "http://127.0.0.1:4000",
                )
                .expect("redeem");
        }

        let index = store
            .load(TRUSTED_PEERS_INDEX_KEY)
            .expect("index load")
            .expect("index");
        let index: serde_json::Value = serde_json::from_slice(&index).expect("index json");
        assert_eq!(
            index["device_ids"],
            serde_json::json!(["phone-a", "phone-b"])
        );
        assert!(store
            .load(&trusted_peer_storage_key("phone-a"))
            .expect("peer a load")
            .is_some());
        assert!(store
            .load(&trusted_peer_storage_key("phone-b"))
            .expect("peer b load")
            .is_some());
        assert_eq!(store.load("trusted-peers-v1").expect("legacy load"), None);

        manager.revoke("phone-a").expect("revoke");
        assert_eq!(
            store
                .load(&trusted_peer_storage_key("phone-a"))
                .expect("revoked peer load"),
            None
        );
    }
}
