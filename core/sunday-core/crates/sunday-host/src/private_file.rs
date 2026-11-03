//! Writing a file that must not be readable by anyone else.
//!
//! One implementation, because two copies of a permission rule drift and the copy
//! that gets fixed is never the one that is actually used. The connection token and
//! the provider binding file both go through here.

use std::io::Write;
use std::path::Path;
use sunday_protocol::CoreError;

/// Writes `contents` to `path` with owner-only permissions, then syncs it.
///
/// On Unix that is `0o600`. On Windows the file inherits the profile directory's
/// ACL, which already excludes other users, and `File::create` does not widen it.
pub fn write(path: &Path, contents: &str, what: &str) -> Result<(), CoreError> {
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options
        .open(path)
        .map_err(|e| CoreError::storage(format!("{what}: {e}")))?;
    file.write_all(contents.as_bytes())
        .map_err(|e| CoreError::storage(format!("{what} write: {e}")))?;
    // Synced, because a binding that is lost in a crash silently becomes "never
    // approved", which shows up as a confusing re-prompt rather than a bug.
    file.sync_all()
        .map_err(|e| CoreError::storage(format!("{what} sync: {e}")))?;
    Ok(())
}
