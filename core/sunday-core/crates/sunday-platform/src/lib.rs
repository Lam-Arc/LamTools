//! Platform ports.
//!
//! The core talks to the machine only through these traits. There is one
//! OS-neutral implementation here so tests and the CLI can run anywhere; the
//! Windows and Android hosts supply their own later. No conditional compilation
//! appears in this crate, and none may appear in crates above it.

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Component, Path, PathBuf};
use sunday_protocol::CoreError;

/// A file handle the core can carry around without knowing where it points.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum FileHandle {
    /// Relative to a workspace root the host owns. Rejects `..` and absolutes.
    Workspace { rel: String },
    /// An opaque grant the host resolves. Never parsed as a path here.
    Opaque { grant_id: String, rel: String },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FileEntry {
    pub name: String,
    pub is_dir: bool,
    pub size: u64,
    pub etag: Option<String>,
}

#[async_trait]
pub trait FileAccess: Send + Sync {
    async fn list(&self, handle: &FileHandle) -> Result<Vec<FileEntry>, CoreError>;
    async fn read(&self, handle: &FileHandle) -> Result<Vec<u8>, CoreError>;
    /// `expect` is a compare-and-swap. Mismatch must fail rather than overwrite.
    async fn write(
        &self,
        handle: &FileHandle,
        bytes: &[u8],
        expect: Option<&str>,
    ) -> Result<String, CoreError>;
    async fn delete(&self, handle: &FileHandle, expect: Option<&str>) -> Result<(), CoreError>;
}

pub trait SecretStore: Send + Sync {
    fn get(&self, key: &str) -> Result<Option<String>, CoreError>;
    fn set(&self, key: &str, value: &str) -> Result<(), CoreError>;
    fn delete(&self, key: &str) -> Result<(), CoreError>;
}

/// Which relative paths a workspace may never touch.
///
/// Mirrors the Python core's `DEFAULT_BLOCKED_FILE_PATTERNS`
/// (`tool/approval.py:44`). The rules are split by kind on purpose: a name like
/// `id_rsa` must match exactly, while `server.pem` must be caught by extension,
/// and `.env.local` only by prefix. One merged list gets this wrong.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PathPolicy {
    /// Directory segments that are always denied.
    pub deny_segments: Vec<String>,
    /// Exact file names that are always denied.
    pub deny_names: Vec<String>,
    /// Extensions, including the dot.
    pub deny_extensions: Vec<String>,
    /// File-name prefixes, so `.env` also catches `.env.local`.
    pub deny_prefixes: Vec<String>,
}

impl Default for PathPolicy {
    fn default() -> Self {
        Self {
            deny_segments: vec![".ssh".into(), ".aws".into(), ".gnupg".into(), ".git".into()],
            deny_names: vec![
                "id_rsa".into(),
                "id_ed25519".into(),
                "id_ecdsa".into(),
                "credentials".into(),
                ".netrc".into(),
            ],
            deny_extensions: vec![".env".into(), ".pem".into(), ".key".into(), ".p12".into()],
            deny_prefixes: vec![".env".into()],
        }
    }
}

impl PathPolicy {
    pub fn allows(&self, rel: &str) -> bool {
        let lowered = rel.to_ascii_lowercase();
        let segments: Vec<&str> = lowered.split(['/', '\\']).collect();
        if segments
            .iter()
            .any(|segment| self.deny_segments.iter().any(|d| d == segment))
        {
            return false;
        }
        let file = segments.last().copied().unwrap_or("");
        if self.deny_names.iter().any(|name| file == name) {
            return false;
        }
        if self
            .deny_prefixes
            .iter()
            .any(|prefix| file.starts_with(prefix))
        {
            return false;
        }
        !self
            .deny_extensions
            .iter()
            .any(|extension| file.ends_with(extension))
    }
}

pub struct LocalFiles {
    root: PathBuf,
    policy: PathPolicy,
}

impl LocalFiles {
    pub fn new(root: impl Into<PathBuf>) -> Result<Self, CoreError> {
        Self::with_policy(root, PathPolicy::default())
    }

    pub fn with_policy(root: impl Into<PathBuf>, policy: PathPolicy) -> Result<Self, CoreError> {
        let root = root.into();
        std::fs::create_dir_all(&root).map_err(CoreError::storage)?;
        let root = root.canonicalize().map_err(CoreError::storage)?;
        Ok(Self { root, policy })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn policy(&self) -> &PathPolicy {
        &self.policy
    }

    /// Resolves a handle to a real path, refusing three things: traversal,
    /// denied names, and symlinks that point outside the root.
    fn resolve(&self, handle: &FileHandle) -> Result<PathBuf, CoreError> {
        let rel = match handle {
            FileHandle::Workspace { rel } => rel,
            FileHandle::Opaque { .. } => {
                return Err(CoreError::PermissionDenied {
                    resource: "opaque handle requires a host provider".into(),
                })
            }
        };
        deny_traversal(rel)?;
        if !self.policy.allows(rel) {
            return Err(CoreError::PermissionDenied {
                resource: format!("{rel} is a protected path"),
            });
        }
        let candidate = normalise(&self.root.join(rel));
        if !candidate.starts_with(&self.root) {
            return Err(CoreError::PermissionDenied {
                resource: format!("{rel} is outside the workspace"),
            });
        }
        // Lexical checks cannot see a symlink. Resolve the deepest existing
        // ancestor and make sure it still lives under the root.
        let resolved = deepest_existing(&candidate)
            .canonicalize()
            .map_err(CoreError::storage)?;
        if !resolved.starts_with(&self.root) {
            return Err(CoreError::PermissionDenied {
                resource: format!("{rel} resolves outside the workspace through a link"),
            });
        }
        Ok(candidate)
    }
}

fn deny_traversal(rel: &str) -> Result<(), CoreError> {
    if rel.is_empty() {
        return Err(CoreError::invalid("empty path"));
    }
    let path = Path::new(rel);
    // `Path::is_absolute` is platform-specific: `C:/x` is not absolute on Linux.
    // The check has to be shape-based so Windows, Android and Linux agree, which
    // is the only way one core can behave the same on both hosts.
    let looks_absolute = path.is_absolute()
        || rel.starts_with('/')
        || rel.starts_with('\\')
        || rel
            .as_bytes()
            .get(1)
            .map(|colon| *colon == b':')
            .unwrap_or(false);
    if looks_absolute {
        return Err(CoreError::PermissionDenied {
            resource: format!("{rel} is absolute"),
        });
    }
    for component in path.components() {
        match component {
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                return Err(CoreError::PermissionDenied {
                    resource: format!("{rel} escapes the workspace"),
                })
            }
            _ => {}
        }
    }
    Ok(())
}

/// The longest existing prefix of `path`, so `canonicalize` can run before the
/// file itself exists.
fn deepest_existing(path: &Path) -> PathBuf {
    let mut current = path.to_path_buf();
    loop {
        if current.exists() {
            return current;
        }
        match current.parent() {
            Some(parent) => current = parent.to_path_buf(),
            None => return path.to_path_buf(),
        }
    }
}

/// Lexical normalisation: resolves `.` and `..` without touching the disk.
fn normalise(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::ParentDir => {
                out.pop();
            }
            Component::CurDir => {}
            other => out.push(other.as_os_str()),
        }
    }
    out
}

fn fingerprint(bytes: &[u8]) -> String {
    sunday_protocol::digest_str(&String::from_utf8_lossy(bytes))
}

#[async_trait]
impl FileAccess for LocalFiles {
    async fn list(&self, handle: &FileHandle) -> Result<Vec<FileEntry>, CoreError> {
        let dir = self.resolve(handle)?;
        let mut out = Vec::new();
        for entry in std::fs::read_dir(&dir).map_err(CoreError::storage)? {
            let entry = entry.map_err(CoreError::storage)?;
            let meta = entry.metadata().map_err(CoreError::storage)?;
            out.push(FileEntry {
                name: entry.file_name().to_string_lossy().into_owned(),
                is_dir: meta.is_dir(),
                size: if meta.is_dir() { 0 } else { meta.len() },
                etag: None,
            });
        }
        out.sort_by(|a, b| a.name.cmp(&b.name));
        Ok(out)
    }

    async fn read(&self, handle: &FileHandle) -> Result<Vec<u8>, CoreError> {
        let path = self.resolve(handle)?;
        std::fs::read(&path).map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => {
                CoreError::invalid(format!("missing {}", path.display()))
            }
            std::io::ErrorKind::PermissionDenied => CoreError::PermissionDenied {
                resource: path.to_string_lossy().into_owned(),
            },
            _ => CoreError::storage(e),
        })
    }

    async fn write(
        &self,
        handle: &FileHandle,
        bytes: &[u8],
        expect: Option<&str>,
    ) -> Result<String, CoreError> {
        let path = self.resolve(handle)?;
        if let Some(expected) = expect {
            match std::fs::read(&path) {
                Ok(current) => {
                    if fingerprint(&current) != expected {
                        return Err(CoreError::RevisionConflict {
                            expected: 0,
                            actual: 0,
                        });
                    }
                }
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                    return Err(CoreError::RevisionConflict {
                        expected: 0,
                        actual: 0,
                    })
                }
                Err(e) => return Err(CoreError::storage(e)),
            }
        }
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(CoreError::storage)?;
        }
        // Write beside the target and rename, so a crash never leaves half a file.
        let tmp = path.with_extension("sunday-tmp");
        std::fs::write(&tmp, bytes).map_err(CoreError::storage)?;
        std::fs::rename(&tmp, &path).map_err(CoreError::storage)?;
        Ok(fingerprint(bytes))
    }

    async fn delete(&self, handle: &FileHandle, expect: Option<&str>) -> Result<(), CoreError> {
        let path = self.resolve(handle)?;
        if let Some(expected) = expect {
            let current = std::fs::read(&path).map_err(CoreError::storage)?;
            if fingerprint(&current) != expected {
                return Err(CoreError::RevisionConflict {
                    expected: 0,
                    actual: 0,
                });
            }
        }
        std::fs::remove_file(&path).map_err(CoreError::storage)
    }
}

/// In-memory secrets for tests and for hosts that have no key store yet.
#[derive(Default)]
pub struct MemorySecrets {
    values: std::sync::Mutex<BTreeMap<String, String>>,
}

impl SecretStore for MemorySecrets {
    fn get(&self, key: &str) -> Result<Option<String>, CoreError> {
        Ok(self.values.lock().unwrap().get(key).cloned())
    }
    fn set(&self, key: &str, value: &str) -> Result<(), CoreError> {
        self.values
            .lock()
            .unwrap()
            .insert(key.to_owned(), value.to_owned());
        Ok(())
    }
    fn delete(&self, key: &str) -> Result<(), CoreError> {
        self.values.lock().unwrap().remove(key);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn files() -> (tempfile::TempDir, LocalFiles) {
        let dir = tempfile::tempdir().unwrap();
        let files = LocalFiles::new(dir.path()).unwrap();
        (dir, files)
    }

    #[tokio::test]
    async fn refuses_parent_traversal() {
        let (_dir, files) = files();
        for escape in ["../escape", "a/../../escape"] {
            let err = files
                .list(&FileHandle::Workspace { rel: escape.into() })
                .await
                .unwrap_err();
            assert!(
                matches!(err, CoreError::PermissionDenied { .. }),
                "{escape}"
            );
        }
    }

    #[tokio::test]
    async fn refuses_absolute_paths_in_every_shape() {
        let (_dir, files) = files();
        for rel in [
            "C:/Windows/win.ini",
            "C:\\Windows\\win.ini",
            "/etc/passwd",
            "\\\\server\\share\\x",
        ] {
            let err = files
                .read(&FileHandle::Workspace { rel: rel.into() })
                .await
                .unwrap_err();
            assert!(
                matches!(err, CoreError::PermissionDenied { .. }),
                "{rel} should be refused, got {err:?}"
            );
        }
    }

    #[tokio::test]
    async fn refuses_opaque_handles_without_a_host_provider() {
        let (_dir, files) = files();
        let err = files
            .read(&FileHandle::Opaque {
                grant_id: "g".into(),
                rel: "a".into(),
            })
            .await
            .unwrap_err();
        assert!(matches!(err, CoreError::PermissionDenied { .. }));
    }

    #[tokio::test]
    async fn write_then_read_round_trips_and_returns_an_etag() {
        let (_dir, files) = files();
        let handle = FileHandle::Workspace {
            rel: "notes/a.txt".into(),
        };
        let etag = files.write(&handle, b"hello", None).await.unwrap();
        assert_eq!(files.read(&handle).await.unwrap(), b"hello");
        assert!(!etag.is_empty());
    }

    #[tokio::test]
    async fn a_stale_etag_is_refused_instead_of_overwriting() {
        let (_dir, files) = files();
        let handle = FileHandle::Workspace {
            rel: "a.txt".into(),
        };
        files.write(&handle, b"first", None).await.unwrap();
        let err = files
            .write(&handle, b"second", Some("stale-etag"))
            .await
            .unwrap_err();
        assert!(matches!(err, CoreError::RevisionConflict { .. }));
        assert_eq!(files.read(&handle).await.unwrap(), b"first");
    }

    #[tokio::test]
    async fn listing_is_sorted_and_reports_directories() {
        let (_dir, files) = files();
        let root = FileHandle::Workspace { rel: ".".into() };
        files
            .write(
                &FileHandle::Workspace {
                    rel: "b.txt".into(),
                },
                b"x",
                None,
            )
            .await
            .unwrap();
        files
            .write(
                &FileHandle::Workspace {
                    rel: "a.txt".into(),
                },
                b"x",
                None,
            )
            .await
            .unwrap();
        let entries = files.list(&root).await.unwrap();
        let names: Vec<&str> = entries.iter().map(|e| e.name.as_str()).collect();
        assert_eq!(names, vec!["a.txt", "b.txt"]);
    }

    // ---- security boundaries -----------------------------------------

    #[tokio::test]
    async fn protected_paths_are_refused_for_read_and_write() {
        let (_dir, files) = files();
        for rel in [
            ".env",
            ".env.local",
            ".ssh/id_rsa",
            "id_rsa",
            "server.pem",
            "tls.key",
            ".aws/credentials",
            ".git/config",
        ] {
            let write = files
                .write(&FileHandle::Workspace { rel: rel.into() }, b"x", None)
                .await;
            assert!(
                matches!(write, Err(CoreError::PermissionDenied { .. })),
                "{rel} should be refused, got {write:?}"
            );
            let read = files.read(&FileHandle::Workspace { rel: rel.into() }).await;
            assert!(
                matches!(read, Err(CoreError::PermissionDenied { .. })),
                "{rel} should not be readable, got {read:?}"
            );
        }
    }

    #[tokio::test]
    async fn ordinary_files_are_still_allowed() {
        let (_dir, files) = files();
        for rel in ["notes.txt", "src/main.rs", "config/settings.json"] {
            files
                .write(&FileHandle::Workspace { rel: rel.into() }, b"x", None)
                .await
                .unwrap_or_else(|e| panic!("{rel} should be allowed: {e:?}"));
        }
    }

    #[tokio::test]
    async fn a_symlink_pointing_outside_is_refused() {
        let outside = tempfile::tempdir().unwrap();
        let inside = tempfile::tempdir().unwrap();
        let files = LocalFiles::new(inside.path()).unwrap();

        let link = inside.path().join("escape");
        let made = create_dir_link(outside.path(), &link);
        if !made {
            // Creating a symlink on Windows needs developer mode or elevation.
            // CI on Linux always exercises this path.
            eprintln!("skipped: this machine cannot create directory symlinks");
            return;
        }

        let err = files
            .read(&FileHandle::Workspace {
                rel: "escape/secret.txt".into(),
            })
            .await
            .unwrap_err();
        assert!(
            matches!(err, CoreError::PermissionDenied { .. }),
            "a link out of the workspace must be refused, got {err:?}"
        );
    }

    fn create_dir_link(target: &Path, link: &Path) -> bool {
        #[cfg(windows)]
        {
            std::os::windows::fs::symlink_dir(target, link).is_ok()
        }
        #[cfg(not(windows))]
        {
            std::os::unix::fs::symlink(target, link).is_ok()
        }
    }
}
