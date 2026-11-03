//! API key storage.
//!
//! The key must not sit in a JSON file. On Android, files under the app's data
//! directory are included in cloud backups and are readable by anything that can
//! get `run-as` on a debuggable build; a plain-text key there is a leaked key.
//!
//! This module provides one interface and two backends:
//!
//!   * the platform `SecretStore` port from `sunday-platform`
//!   * a file backend with owner-only permissions, used on desktop builds of this
//!     host and by tests
//!
//! The Android backend is wired through Tauri so the app can supply a Keystore
//! implementation. Until that plugin is installed the file backend is used, and
//! that fact is reported honestly by `backend()` rather than being papered over:
//! claiming Keystore when the key is in a file would be worse than the file.

use std::path::{Path, PathBuf};
use sunday_platform::SecretStore;

pub const API_KEY_NAME: &str = "provider.api_key";
const FALLBACK_FILE: &str = "core.secret";

/// Which backend is actually in use. Reported to the UI so the claim can be
/// checked instead of trusted.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Backend {
    /// The platform keychain (Android Keystore, or the desktop equivalent).
    Keystore,
    /// A file with owner-only permissions. Not equivalent, and labelled as such.
    RestrictedFile,
}

pub fn backend() -> Backend {
    if keystore_available() {
        Backend::Keystore
    } else {
        Backend::RestrictedFile
    }
}

/// True when a real keychain plugin is compiled in.
///
/// Kept as one function so enabling the plugin later is a single change, and so
/// the rest of the code cannot accidentally assume it is present.
fn keystore_available() -> bool {
    // Set by the build when the keychain plugin is linked. Deliberately a compile
    // time fact rather than a runtime guess: a runtime probe that fails open would
    // silently downgrade to a file.
    option_env!("SUNDAY_KEYSTORE").is_some()
}

fn file_path(dir: &Path) -> PathBuf {
    dir.join(FALLBACK_FILE)
}

/// The store this build uses.
pub struct HostSecrets {
    dir: PathBuf,
}

impl HostSecrets {
    pub fn new(dir: impl AsRef<Path>) -> Self {
        Self {
            dir: dir.as_ref().to_path_buf(),
        }
    }
}

impl SecretStore for HostSecrets {
    fn get(&self, key: &str) -> Result<Option<String>, sunday_protocol::CoreError> {
        read_from(&self.dir, key)
    }

    fn set(&self, key: &str, value: &str) -> Result<(), sunday_protocol::CoreError> {
        write_to(&self.dir, key, value)
    }

    fn delete(&self, _key: &str) -> Result<(), sunday_protocol::CoreError> {
        let path = file_path(&self.dir);
        if path.exists() {
            std::fs::remove_file(&path).map_err(|e| {
                sunday_protocol::CoreError::storage(format!("cannot remove secret: {e}"))
            })?;
        }
        Ok(())
    }
}

/// Reads the API key, or an empty string when none is configured.
pub fn read_api_key(dir: &Path) -> Result<String, Box<dyn std::error::Error>> {
    Ok(read_from(dir, API_KEY_NAME)?.unwrap_or_default())
}

pub fn has_api_key(dir: &Path) -> bool {
    read_from(dir, API_KEY_NAME)
        .map(|value| value.map(|text| !text.is_empty()).unwrap_or(false))
        .unwrap_or(false)
}

/// Writes the key with owner-only permissions.
///
/// One key per file. A multi-key file would need its own format and its own
/// permission story, and there is exactly one provider today.
///
/// The permission rule itself lives in `sunday_host::private_file`, because the
/// connection token and the provider binding file need the same rule and three
/// copies of it is how a fix ends up applied to the one nobody uses.
fn write_to(dir: &Path, _key: &str, value: &str) -> Result<(), sunday_protocol::CoreError> {
    std::fs::create_dir_all(dir).map_err(|e| {
        sunday_protocol::CoreError::storage(format!("cannot create {}: {e}", dir.display()))
    })?;
    sunday_host::private_file::write(&file_path(dir), value, "secret file")
}

fn read_from(dir: &Path, _key: &str) -> Result<Option<String>, sunday_protocol::CoreError> {
    let path = file_path(dir);
    match std::fs::read_to_string(&path) {
        Ok(text) => {
            let trimmed = text.trim().to_owned();
            Ok(if trimmed.is_empty() {
                None
            } else {
                Some(trimmed)
            })
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(sunday_protocol::CoreError::storage(format!(
            "secret read: {error}"
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_missing_key_is_none_not_an_error() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(read_api_key(dir.path()).unwrap(), "");
        assert!(!has_api_key(dir.path()));
    }

    #[test]
    fn a_key_round_trips() {
        let dir = tempfile::tempdir().unwrap();
        let store = HostSecrets::new(dir.path());
        store.set(API_KEY_NAME, "sk-test-123").unwrap();
        assert_eq!(
            store.get(API_KEY_NAME).unwrap().as_deref(),
            Some("sk-test-123")
        );
        assert!(has_api_key(dir.path()));
    }

    #[test]
    fn deleting_removes_it() {
        let dir = tempfile::tempdir().unwrap();
        let store = HostSecrets::new(dir.path());
        store.set(API_KEY_NAME, "sk-test-123").unwrap();
        store.delete(API_KEY_NAME).unwrap();
        assert_eq!(store.get(API_KEY_NAME).unwrap(), None);
    }

    /// The key must never end up inside the JSON config.
    #[test]
    fn the_key_is_not_in_the_config_file() {
        let dir = tempfile::tempdir().unwrap();
        crate::config::load_or_default(dir.path()).unwrap();
        let store = HostSecrets::new(dir.path());
        store.set(API_KEY_NAME, "sk-must-not-leak").unwrap();

        let config = std::fs::read_to_string(crate::config::path_in(dir.path())).unwrap();
        assert!(
            !config.contains("sk-must-not-leak"),
            "the API key was written into the config file"
        );
    }

    #[cfg(unix)]
    #[test]
    fn the_secret_file_is_owner_only() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::tempdir().unwrap();
        let store = HostSecrets::new(dir.path());
        store.set(API_KEY_NAME, "sk-test").unwrap();
        let mode = std::fs::metadata(file_path(dir.path()))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(
            mode & 0o077,
            0,
            "the key file is readable by others: {mode:o}"
        );
    }
}
