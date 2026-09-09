use std::{collections::HashMap, sync::Mutex};

use base64::Engine;
use serde::{Deserialize, Serialize};

pub const DESKTOP_ACCOUNT_SESSION_KEY: &str = "desktop-account-session-v1";

/// The desktop's authenticated control-plane session.  Access and refresh
/// tokens are stored only through SecureStore; this structure is never logged
/// or returned by a diagnostic endpoint.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DesktopAccountSession {
    pub base_url: String,
    pub server_id: String,
    pub username: String,
    pub node_id: String,
    pub public_key: String,
    pub access_token: String,
    pub refresh_token: String,
    pub access_expires_at_ms: i64,
    pub refresh_expires_at_ms: i64,
}

impl DesktopAccountSession {
    pub fn is_valid(&self) -> bool {
        !self.base_url.trim().is_empty()
            && !self.server_id.trim().is_empty()
            && !self.username.trim().is_empty()
            && !self.node_id.trim().is_empty()
            && !self.public_key.trim().is_empty()
            && !self.access_token.trim().is_empty()
            && !self.refresh_token.trim().is_empty()
            && self.access_expires_at_ms > 0
            && self.refresh_expires_at_ms > 0
    }
}

/// Storage boundary used by device identity and trusted peers.
///
/// Windows uses Credential Manager and macOS uses Keychain; tests and
/// unsupported targets use the in-memory implementation. Keeping the trait
/// here prevents callers from falling back to plaintext configuration.
pub trait SecureStore: Send + Sync {
    fn load(&self, key: &str) -> Result<Option<Vec<u8>>, String>;
    fn save(&self, key: &str, value: &[u8]) -> Result<(), String>;
    fn delete(&self, key: &str) -> Result<(), String>;
}

#[derive(Default)]
pub struct MemorySecureStore {
    values: Mutex<HashMap<String, Vec<u8>>>,
}

#[cfg(any(windows, target_os = "macos"))]
#[derive(Default)]
pub struct PlatformSecureStore;

#[cfg(any(windows, target_os = "macos"))]
impl PlatformSecureStore {
    fn entry(key: &str) -> Result<keyring::Entry, String> {
        keyring::Entry::new("com.lamtools.desktop.remote", key).map_err(|error| error.to_string())
    }
}

#[cfg(any(windows, target_os = "macos"))]
impl SecureStore for PlatformSecureStore {
    fn load(&self, key: &str) -> Result<Option<Vec<u8>>, String> {
        match Self::entry(key)?.get_password() {
            Ok(value) => base64::engine::general_purpose::STANDARD
                .decode(value)
                .map(Some)
                .map_err(|error| error.to_string()),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(error) => Err(error.to_string()),
        }
    }

    fn save(&self, key: &str, value: &[u8]) -> Result<(), String> {
        Self::entry(key)?
            .set_password(&base64::engine::general_purpose::STANDARD.encode(value))
            .map_err(|error| error.to_string())
    }

    fn delete(&self, key: &str) -> Result<(), String> {
        match Self::entry(key)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(error) => Err(error.to_string()),
        }
    }
}

#[cfg(not(any(windows, target_os = "macos")))]
#[derive(Default)]
pub struct PlatformSecureStore {
    fallback: MemorySecureStore,
}

#[cfg(not(any(windows, target_os = "macos")))]
impl SecureStore for PlatformSecureStore {
    fn load(&self, key: &str) -> Result<Option<Vec<u8>>, String> {
        self.fallback.load(key)
    }
    fn save(&self, key: &str, value: &[u8]) -> Result<(), String> {
        self.fallback.save(key, value)
    }
    fn delete(&self, key: &str) -> Result<(), String> {
        self.fallback.delete(key)
    }
}

impl SecureStore for MemorySecureStore {
    fn load(&self, key: &str) -> Result<Option<Vec<u8>>, String> {
        self.values
            .lock()
            .map_err(|_| "secure store lock failed".to_string())
            .map(|values| values.get(key).cloned())
    }

    fn save(&self, key: &str, value: &[u8]) -> Result<(), String> {
        self.values
            .lock()
            .map_err(|_| "secure store lock failed".to_string())?
            .insert(key.to_string(), value.to_vec());
        Ok(())
    }

    fn delete(&self, key: &str) -> Result<(), String> {
        self.values
            .lock()
            .map_err(|_| "secure store lock failed".to_string())?
            .remove(key);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::{MemorySecureStore, SecureStore};

    #[test]
    fn memory_store_round_trips_and_deletes_secret_bytes() {
        let store = MemorySecureStore::default();
        assert_eq!(store.load("device").expect("initial load"), None);
        store.save("device", b"secret\0bytes").expect("save");
        assert_eq!(
            store.load("device").expect("stored load"),
            Some(b"secret\0bytes".to_vec())
        );
        store.delete("device").expect("delete");
        assert_eq!(store.load("device").expect("deleted load"), None);
    }
}
