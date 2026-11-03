//! API key storage.
//!
//! The key must not sit in a readable file. On Android a file under the app's data
//! directory survives in cloud backups and is readable by anything that can get
//! `run-as` on a debuggable build. The key is therefore sealed by a key generated
//! inside AndroidKeyStore, which never leaves it.
//!
//! Three modes, and the difference between the last two is the whole point:
//!
//! * `Sealed` — the keystore works, the key is ciphertext on disk.
//! * `PlainFile` — a desktop build of this host, where there is no keystore. Owner-only
//!   permissions, and the UI is told which one is in use.
//! * `Broken` — Android, but the keystore refused. **Nothing is written.** Falling back
//!   to a plaintext file here would silently undo the property this module exists to
//!   provide, and the user would be told nothing.
//!
//! An existing plaintext key from before this change is migrated on first read: it is
//! sealed, the ciphertext is written, and the plaintext file is removed.

use std::path::{Path, PathBuf};

use sunday_platform::SecretStore;
use sunday_protocol::CoreError;

pub const API_KEY_NAME: &str = "provider.api_key";
const SEALED_FILE: &str = "core.secret.enc";
const PLAINTEXT_FILE: &str = "core.secret";

/// Which storage is actually in use right now. Reported to the UI so the claim can be
/// checked instead of trusted.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Backend {
    /// Sealed by the Android keystore.
    Sealed,
    /// A desktop build: an owner-only file, which is not equivalent and says so.
    PlainFile,
    /// Android with an unusable keystore. Storage is refused rather than degraded.
    Unavailable { reason: String },
}

impl Backend {
    pub fn kind(&self) -> &'static str {
        match self {
            Self::Sealed => "android-keystore",
            Self::PlainFile => "owner-only-file",
            Self::Unavailable { .. } => "unavailable",
        }
    }

    pub fn reason(&self) -> Option<&str> {
        match self {
            Self::Unavailable { reason } => Some(reason),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum Mode {
    Sealed,
    PlainFile,
    Broken(String),
}

fn sealed_path(dir: &Path) -> PathBuf {
    dir.join(SEALED_FILE)
}

fn plaintext_path(dir: &Path) -> PathBuf {
    dir.join(PLAINTEXT_FILE)
}

fn read_optional(path: &Path) -> Result<Option<String>, CoreError> {
    match std::fs::read_to_string(path) {
        Ok(text) => {
            let trimmed = text.trim().to_owned();
            Ok(if trimmed.is_empty() { None } else { Some(trimmed) })
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(CoreError::storage(format!("secret read: {error}"))),
    }
}

fn mode() -> Mode {
    #[cfg(target_os = "android")]
    {
        match crate::keystore::probe() {
            Ok(()) => Mode::Sealed,
            Err(reason) => Mode::Broken(reason),
        }
    }
    #[cfg(not(target_os = "android"))]
    {
        // No keystore exists on a desktop build, and pretending otherwise would make
        // every call fail. The file is the honest answer there.
        Mode::PlainFile
    }
}

pub fn backend() -> Backend {
    match mode() {
        Mode::Sealed => Backend::Sealed,
        Mode::PlainFile => Backend::PlainFile,
        Mode::Broken(reason) => Backend::Unavailable { reason },
    }
}

/// What the settings screen needs to tell the truth about the key.
pub fn storage_view(dir: &Path) -> serde_json::Value {
    let backend = backend();
    serde_json::json!({
        "kind": backend.kind(),
        "reason": backend.reason(),
        // A plaintext file still on disk means an upgrade has not happened yet.
        "needs_migration": plaintext_path(dir).exists(),
        "has_key": has_api_key(dir),
    })
}

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
    fn get(&self, _key: &str) -> Result<Option<String>, CoreError> {
        let sealed = sealed_path(&self.dir);
        let plain = plaintext_path(&self.dir);
        match mode() {
            Mode::Sealed => {
                if sealed.exists() {
                    let blob = read_optional(&sealed)?.unwrap_or_default();
                    if blob.is_empty() {
                        return Ok(None);
                    }
                    return crate::keystore::open(&blob).map(Some);
                }
                // Upgrade path: seal what is on disk, then remove the readable copy.
                if let Some(value) = read_optional(&plain)? {
                    let blob = crate::keystore::seal(&value)?;
                    sunday_host::private_file::write(&sealed, &blob, "sealed secret")?;
                    // Only remove the plaintext once the sealed copy is durable.
                    if let Err(error) = std::fs::remove_file(&plain) {
                        println!("keystore: sealed the key but could not remove {PLAINTEXT_FILE}: {error}");
                    }
                    println!("keystore: migrated the stored key into AndroidKeyStore");
                    return Ok(Some(value));
                }
                Ok(None)
            }
            Mode::Broken(reason) => {
                if sealed.exists() {
                    return Err(CoreError::storage(format!(
                        "the API key is sealed with the Android keystore, which is unusable \
                         right now ({reason}); refusing to guess"
                    )));
                }
                // A key written before this change is still readable. It is not a
                // downgrade to read it; it is the old state, and it is reported.
                read_optional(&plain)
            }
            Mode::PlainFile => read_optional(&plain),
        }
    }

    fn set(&self, _key: &str, value: &str) -> Result<(), CoreError> {
        match mode() {
            Mode::Sealed => {
                let blob = crate::keystore::seal(value)?;
                std::fs::create_dir_all(&self.dir).map_err(|error| {
                    CoreError::storage(format!("cannot create {}: {error}", self.dir.display()))
                })?;
                sunday_host::private_file::write(&sealed_path(&self.dir), &blob, "sealed secret")?;
                // The readable copy must not survive the sealed one.
                let _ = std::fs::remove_file(plaintext_path(&self.dir));
                Ok(())
            }
            Mode::Broken(reason) => Err(CoreError::storage(format!(
                "refusing to store the API key in the clear: the Android keystore is \
                 unavailable ({reason})"
            ))),
            Mode::PlainFile => {
                std::fs::create_dir_all(&self.dir).map_err(|error| {
                    CoreError::storage(format!("cannot create {}: {error}", self.dir.display()))
                })?;
                sunday_host::private_file::write(
                    &plaintext_path(&self.dir),
                    value,
                    "secret file",
                )
            }
        }
    }

    fn delete(&self, _key: &str) -> Result<(), CoreError> {
        for path in [sealed_path(&self.dir), plaintext_path(&self.dir)] {
            if path.exists() {
                std::fs::remove_file(&path)
                    .map_err(|error| CoreError::storage(format!("cannot remove secret: {error}")))?;
            }
        }
        Ok(())
    }
}

/// Reads the API key, or an empty string when none is configured.
pub fn read_api_key(dir: &Path) -> Result<String, Box<dyn std::error::Error>> {
    match HostSecrets::new(dir).get(API_KEY_NAME) {
        Ok(value) => Ok(value.unwrap_or_default()),
        Err(error) => Err(error.into()),
    }
}

pub fn has_api_key(dir: &Path) -> bool {
    sealed_path(dir).exists() || plaintext_path(dir).exists()
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
        assert_eq!(store.get(API_KEY_NAME).unwrap().as_deref(), Some("sk-test-123"));
        assert!(has_api_key(dir.path()));
    }

    #[test]
    fn deleting_removes_it() {
        let dir = tempfile::tempdir().unwrap();
        let store = HostSecrets::new(dir.path());
        store.set(API_KEY_NAME, "sk-test-123").unwrap();
        store.delete(API_KEY_NAME).unwrap();
        assert_eq!(store.get(API_KEY_NAME).unwrap(), None);
        assert!(!has_api_key(dir.path()));
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
        let mode = std::fs::metadata(plaintext_path(dir.path()))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o077, 0, "the key file is readable by others: {mode:o}");
    }

    /// On a desktop build there is no keystore, and the report says so rather than
    /// claiming system-level storage.
    #[cfg(not(target_os = "android"))]
    #[test]
    fn a_desktop_build_reports_a_file_not_a_keystore() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(backend(), Backend::PlainFile);
        let view = storage_view(dir.path());
        assert_eq!(view["kind"], "owner-only-file");
    }
}
