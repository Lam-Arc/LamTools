//! Connection authentication for the app-server transport.
//!
//! A random port on loopback is **not** access control. Any process on the device
//! can enumerate listening sockets, and on Android any app on the device can reach
//! another app's loopback listener. Before this module, a client that guessed the
//! port could read transcripts, trigger file writes and answer approvals.
//!
//! The rule now:
//!
//!   * every server instance owns a random token, written to the data directory
//!     with owner-only permissions
//!   * the first frame must be `initialize` carrying that token
//!   * every other method before a successful `initialize` is refused
//!   * a wrong token closes the connection
//!
//! The token is compared in constant time. That is not paranoia for its own sake:
//! a timing side channel on a token that unlocks destructive file writes is worth
//! the three extra lines.

use std::path::{Path, PathBuf};
use sunday_protocol::CoreError;

pub const TOKEN_FILE: &str = "core.token";
const TOKEN_BYTES: usize = 32;

/// Reads the token for a data directory, creating it on first use.
///
/// The file is written with owner-only permissions. On Unix that is `0o600`; on
/// Windows the file inherits the profile directory's ACL, which already excludes
/// other users, and `File::create` does not widen it.
pub fn load_or_create(dir: impl AsRef<Path>) -> Result<String, CoreError> {
    let dir = dir.as_ref();
    std::fs::create_dir_all(dir).map_err(|e| CoreError::storage(format!("token dir: {e}")))?;
    let path = dir.join(TOKEN_FILE);

    if let Ok(existing) = std::fs::read_to_string(&path) {
        let trimmed = existing.trim();
        // A truncated or empty file is a real possibility after a crash mid-write,
        // so it is treated as absent rather than trusted.
        if trimmed.len() >= 32 {
            return Ok(trimmed.to_owned());
        }
    }

    let token = random_hex(TOKEN_BYTES)?;
    write_private(&path, &token)?;
    Ok(token)
}

fn write_private(path: &Path, token: &str) -> Result<(), CoreError> {
    // One implementation of "owner-only file" lives in `private_file`, because two
    // copies of a permission rule drift and the copy that gets fixed is never the
    // one that is used.
    crate::private_file::write(path, token, "token file")
}

pub fn path_in(dir: impl AsRef<Path>) -> PathBuf {
    dir.as_ref().join(TOKEN_FILE)
}

fn random_hex(bytes: usize) -> Result<String, CoreError> {
    let mut buffer = vec![0u8; bytes];
    getrandom::fill(&mut buffer)
        .map_err(|e| CoreError::storage(format!("no system randomness: {e}")))?;
    let mut out = String::with_capacity(bytes * 2);
    for byte in buffer {
        out.push_str(&format!("{byte:02x}"));
    }
    Ok(out)
}

/// Compares two tokens without short-circuiting on the first differing byte.
pub fn matches(expected: &str, presented: &str) -> bool {
    let a = expected.as_bytes();
    let b = presented.as_bytes();
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (left, right) in a.iter().zip(b.iter()) {
        diff |= left ^ right;
    }
    diff == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_token_is_created_once_and_stable() {
        let dir = tempfile::tempdir().unwrap();
        let first = load_or_create(dir.path()).unwrap();
        let second = load_or_create(dir.path()).unwrap();
        assert_eq!(first, second, "the token changed between loads");
        assert_eq!(first.len(), TOKEN_BYTES * 2, "unexpected token length");
    }

    #[test]
    fn two_directories_get_different_tokens() {
        let a = tempfile::tempdir().unwrap();
        let b = tempfile::tempdir().unwrap();
        assert_ne!(
            load_or_create(a.path()).unwrap(),
            load_or_create(b.path()).unwrap(),
            "two cores share a token, so knowing one grants the other"
        );
    }

    #[test]
    fn a_truncated_token_file_is_replaced() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join(TOKEN_FILE), b"abc").unwrap();
        let token = load_or_create(dir.path()).unwrap();
        assert!(
            token.len() >= 32,
            "a truncated token was trusted: {token:?}"
        );
    }

    #[test]
    fn comparison_is_exact() {
        assert!(matches("abcdef", "abcdef"));
        assert!(!matches("abcdef", "abcdeg"));
        assert!(!matches("abcdef", "abcde"));
        assert!(!matches("abcdef", "abcdefg"));
        assert!(!matches("abcdef", ""));
    }

    /// On Unix the token file must not be readable by other users.
    #[cfg(unix)]
    #[test]
    fn the_token_file_is_owner_only() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::tempdir().unwrap();
        load_or_create(dir.path()).unwrap();
        let mode = std::fs::metadata(dir.path().join(TOKEN_FILE))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(
            mode & 0o077,
            0,
            "the token is readable by group or others: {mode:o}"
        );
    }
}
