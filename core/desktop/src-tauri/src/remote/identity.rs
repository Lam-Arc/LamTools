use base64::Engine;
use getrandom::fill as fill_random;
use serde::{Deserialize, Serialize};

use super::secure_store::SecureStore;

const DEVICE_ID_BYTES: usize = 12;
const STATIC_KEY_BYTES: usize = 32;
const IDENTITY_STORAGE_KEY: &str = "desktop-identity-v1";
const ACCOUNT_IDENTITY_STORAGE_PREFIX: &str = "desktop-account-identity-v1";

/// Long-lived desktop identity.  The private key is deliberately skipped by
/// serde; persistence must go through a SecureStore implementation.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeviceIdentity {
    pub device_id: String,
    pub public_key: String,
    #[serde(skip)]
    pub(crate) private_key: Vec<u8>,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StoredIdentity {
    device_id: String,
    private_key: String,
}

pub fn load_or_create_identity(store: &dyn SecureStore) -> Result<DeviceIdentity, String> {
    load_or_create_identity_at(store, IDENTITY_STORAGE_KEY)
}

pub fn load_or_create_account_identity(
    store: &dyn SecureStore,
    server_id: &str,
    username: &str,
) -> Result<DeviceIdentity, String> {
    let scope = encode_urlsafe(
        format!("{}:{}", server_id.trim(), username.trim().to_lowercase()).as_bytes(),
    );
    load_or_create_identity_at(store, &format!("{ACCOUNT_IDENTITY_STORAGE_PREFIX}:{scope}"))
}

fn load_or_create_identity_at(
    store: &dyn SecureStore,
    storage_key: &str,
) -> Result<DeviceIdentity, String> {
    if let Some(bytes) = store.load(storage_key)? {
        let stored: StoredIdentity = serde_json::from_slice(&bytes)
            .map_err(|error| format!("stored desktop identity is invalid: {error}"))?;
        let private_key = decode_urlsafe(&stored.private_key)
            .ok_or_else(|| "stored desktop identity key is invalid".to_string())?;
        return DeviceIdentity::from_private_key(stored.device_id, private_key);
    }
    let identity = DeviceIdentity::generate()?;
    let stored = StoredIdentity {
        device_id: identity.device_id.clone(),
        private_key: encode_urlsafe(&identity.private_key),
    };
    store.save(
        storage_key,
        &serde_json::to_vec(&stored).map_err(|error| error.to_string())?,
    )?;
    Ok(identity)
}

impl DeviceIdentity {
    pub fn generate() -> Result<Self, String> {
        let mut device_id_bytes = [0_u8; DEVICE_ID_BYTES];
        let mut private_key = [0_u8; STATIC_KEY_BYTES];
        fill_random(&mut device_id_bytes).map_err(|error| error.to_string())?;
        fill_random(&mut private_key).map_err(|error| error.to_string())?;

        let params = "Noise_XX_25519_ChaChaPoly_BLAKE2b"
            .parse()
            .map_err(|error| format!("Noise protocol is unavailable: {error}"))?;
        let keypair = snow::Builder::new(params)
            .generate_keypair()
            .map_err(|error| error.to_string())?;
        private_key.copy_from_slice(&keypair.private);
        Ok(Self {
            device_id: format!("desktop-{}", encode_urlsafe(&device_id_bytes)),
            public_key: encode_urlsafe(&keypair.public),
            private_key: private_key.to_vec(),
        })
    }

    pub fn from_private_key(
        device_id: impl Into<String>,
        private_key: Vec<u8>,
    ) -> Result<Self, String> {
        if private_key.len() != STATIC_KEY_BYTES {
            return Err("Noise static private key must contain 32 bytes".to_string());
        }
        // snow does not expose a public-key derivation helper.  Build an
        // initiator and read the static public key from the generated
        // X25519 keypair only for newly-created identities; persisted v2
        // identities include the public key below.
        let public_key = x25519_public_from_private(&private_key)?;
        Ok(Self {
            device_id: device_id.into(),
            public_key: encode_urlsafe(&public_key),
            private_key,
        })
    }
}

fn x25519_public_from_private(private_key: &[u8]) -> Result<Vec<u8>, String> {
    use snow::resolvers::{CryptoResolver, DefaultResolver};
    let resolver = DefaultResolver;
    let mut dh = resolver
        .resolve_dh(&snow::params::DHChoice::Curve25519)
        .ok_or_else(|| "X25519 is unavailable".to_string())?;
    dh.set(private_key);
    Ok(dh.pubkey().to_vec())
}

pub(crate) fn random_token(bytes: usize) -> Result<String, String> {
    let mut value = vec![0_u8; bytes];
    fill_random(&mut value).map_err(|error| error.to_string())?;
    Ok(encode_urlsafe(&value))
}

pub(crate) fn encode_urlsafe(value: &[u8]) -> String {
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(value)
}

pub(crate) fn decode_urlsafe(value: &str) -> Option<Vec<u8>> {
    base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(value)
        .ok()
}

#[cfg(test)]
mod tests {
    use super::{load_or_create_account_identity, load_or_create_identity, DeviceIdentity};
    use crate::remote::secure_store::MemorySecureStore;

    #[test]
    fn identity_public_key_is_x25519_and_stable() {
        let identity = DeviceIdentity::generate().expect("identity");
        assert_eq!(
            super::decode_urlsafe(&identity.public_key).unwrap().len(),
            32
        );
        let restored = DeviceIdentity::from_private_key(
            identity.device_id.clone(),
            identity.private_key.clone(),
        )
        .unwrap();
        assert_eq!(identity.public_key, restored.public_key);
    }

    #[test]
    fn identity_is_stable_when_loaded_from_secure_storage() {
        let store = MemorySecureStore::default();
        let first = load_or_create_identity(&store).expect("first identity");
        let second = load_or_create_identity(&store).expect("stored identity");
        assert_eq!(second.device_id, first.device_id);
        assert_eq!(second.public_key, first.public_key);
        assert_eq!(second.private_key, first.private_key);
    }

    #[test]
    fn account_identities_are_stable_and_isolated() {
        let store = MemorySecureStore::default();
        let first = load_or_create_account_identity(&store, "server-1", "alice").unwrap();
        let restored = load_or_create_account_identity(&store, "server-1", "Alice").unwrap();
        let second = load_or_create_account_identity(&store, "server-1", "bob").unwrap();
        assert_eq!(restored.device_id, first.device_id);
        assert_ne!(second.device_id, first.device_id);
    }
}
