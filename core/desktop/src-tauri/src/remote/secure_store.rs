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
/// Windows uses Credential Manager, macOS uses Keychain, and Linux uses the
/// persistent Secret Service backend. Tests and unsupported targets use the
/// in-memory implementation. Keeping the trait here prevents callers from
/// falling back to plaintext configuration.
pub trait SecureStore: Send + Sync {
    fn load(&self, key: &str) -> Result<Option<Vec<u8>>, String>;
    fn save(&self, key: &str, value: &[u8]) -> Result<(), String>;
    fn delete(&self, key: &str) -> Result<(), String>;
}

#[derive(Default)]
pub struct MemorySecureStore {
    values: Mutex<HashMap<String, Vec<u8>>>,
}

#[cfg(any(windows, target_os = "macos", target_os = "linux"))]
#[derive(Default)]
pub struct PlatformSecureStore;

#[cfg(any(windows, target_os = "macos", target_os = "linux"))]
impl PlatformSecureStore {
    /// Keyring namespace. The legacy name is only read, never written, so an
    /// upgraded install keeps its paired-device credentials without forcing a
    /// re-pair, and a rollback to the previous build still finds them.
    const SERVICE: &'static str = "com.lamtools.sunday.remote";
    const LEGACY_SERVICE: &'static str = "com.lamtools.desktop.remote";

    fn entry_for(service: &str, key: &str) -> Result<keyring::Entry, String> {
        keyring::Entry::new(service, key).map_err(|error| error.to_string())
    }

    fn entry(key: &str) -> Result<keyring::Entry, String> {
        Self::entry_for(Self::SERVICE, key)
    }

    fn decode(value: String) -> Result<Option<Vec<u8>>, String> {
        base64::engine::general_purpose::STANDARD
            .decode(value)
            .map(Some)
            .map_err(|error| error.to_string())
    }
}

#[cfg(any(windows, target_os = "macos", target_os = "linux"))]
impl SecureStore for PlatformSecureStore {
    fn load(&self, key: &str) -> Result<Option<Vec<u8>>, String> {
        match Self::entry(key)?.get_password() {
            Ok(value) => Self::decode(value),
            Err(keyring::Error::NoEntry) => {
                // user:“迁移”+(旧密钥服务名里的凭据要能继续用，不能因为改名让用户重新配对。)
                match Self::entry_for(Self::LEGACY_SERVICE, key)?.get_password() {
                    Ok(value) => {
                        let decoded = Self::decode(value)?;
                        // Promote to the new service so later loads stop
                        // depending on the legacy entry. Best effort: a
                        // locked/unavailable keyring must not break a read.
                        if let Some(bytes) = decoded.as_ref() {
                            // 不能把创建新 entry 的失败冒泡出去：凭据已经读到了，
                            // 提升失败只意味着下次还会走旧服务名。
                            if let Ok(entry) = Self::entry(key) {
                                let _ = entry.set_password(
                                    &base64::engine::general_purpose::STANDARD.encode(bytes),
                                );
                            }
                        }
                        Ok(decoded)
                    }
                    Err(keyring::Error::NoEntry) => Ok(None),
                    Err(error) => Err(error.to_string()),
                }
            }
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
            Ok(()) | Err(keyring::Error::NoEntry) => {}
            Err(error) => return Err(error.to_string()),
        }
        // Best effort: remove the legacy copy too so a deleted credential is
        // not resurrected by the fallback on the next load.
        match Self::entry_for(Self::LEGACY_SERVICE, key)?.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(error) => Err(error.to_string()),
        }
    }
}

#[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
#[derive(Default)]
pub struct PlatformSecureStore {
    fallback: MemorySecureStore,
}

#[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
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
