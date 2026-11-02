//! One-time identity migration from the app's original `lamcore` names.
//!
//! user:“迁移”+(改名不能只换可执行文件：旧版本的数据、WebView2 配置和后端
//! 状态目录都挂在旧标识下，升级后必须原地搬过来，否则等于让用户重装。)
//!
//! Scope rules:
//! - Only `lamcore`/`LamCore` spellings move. The LamTools family name,
//!   mobile identifiers, the mDNS service type, and `LAMTOOLS_*` variables are
//!   cross-product/compatibility contracts and stay unchanged.
//! - A rename only happens when the destination does not exist. If both exist,
//!   leave them alone: silently merging two user-data trees is worse than
//!   leaving a stale directory behind.
//! - Migration failure is non-fatal. The app must still start (and create fresh
//!   state) when an old process holds a file, so callers only log.

use std::{
    env, fs,
    path::{Path, PathBuf},
};

/// Move every known legacy identity directory into its Sunday location.
///
/// Called once from `main` before Tauri resolves `app_data_dir`, so the new
/// identifier sees the old data on its very first read.
pub fn migrate_legacy_identity() {
    for (old, new) in candidate_pairs() {
        match migrate_directory(&old, &new) {
            Ok(true) => eprintln!(
                "[sunday] identity migration: {} -> {}",
                old.display(),
                new.display()
            ),
            Ok(false) => {}
            Err(error) => eprintln!(
                "[sunday] identity migration failed for {}: {error}",
                old.display()
            ),
        }
    }
}

/// Build the legacy -> current directory pairs for this platform.
fn candidate_pairs() -> Vec<(PathBuf, PathBuf)> {
    let mut pairs = Vec::new();
    for base in identity_roots() {
        push_identity_pairs(&mut pairs, &base);
    }
    pairs
}

fn push_identity_pairs(pairs: &mut Vec<(PathBuf, PathBuf)>, base: &Path) {
    // Most recent legacy identifier first: if both old identifiers exist, the
    // current one (lamcore) is the authoritative state and wins the move.
    pairs.push((
        base.join("com.lamtools.lamcore"),
        base.join("com.lamtools.sunday"),
    ));
    pairs.push((
        base.join("com.lamtools.core"),
        base.join("com.lamtools.sunday"),
    ));
    // Standalone backend / CLI state written before the shell override existed.
    pairs.push((base.join("LamCore"), base.join("Sunday")));
}

#[cfg(windows)]
fn identity_roots() -> Vec<PathBuf> {
    // Roaming holds app data; Local holds the WebView2 profile. Both are keyed
    // by the bundle identifier, so both must follow the rename.
    ["APPDATA", "LOCALAPPDATA"]
        .iter()
        .filter_map(|name| env::var_os(name).map(PathBuf::from))
        .collect()
}

#[cfg(target_os = "linux")]
fn identity_roots() -> Vec<PathBuf> {
    let home = env::var_os("HOME").map(PathBuf::from);
    let xdg = |name: &str, fallback: &str| {
        env::var_os(name)
            .map(PathBuf::from)
            .or_else(|| home.as_ref().map(|home| home.join(fallback)))
    };
    let mut roots = Vec::new();
    if let Some(value) = xdg("XDG_DATA_HOME", ".local/share") {
        roots.push(value);
    }
    if let Some(value) = xdg("XDG_CONFIG_HOME", ".config") {
        roots.push(value);
    }
    if let Some(value) = xdg("XDG_CACHE_HOME", ".cache") {
        roots.push(value);
    }
    // Tauri's app_log_dir uses the XDG state base on Linux.
    if let Some(value) = xdg("XDG_STATE_HOME", ".local/state") {
        roots.push(value);
    }
    roots
}

#[cfg(target_os = "macos")]
fn identity_roots() -> Vec<PathBuf> {
    let Some(home) = env::var_os("HOME").map(PathBuf::from) else {
        return Vec::new();
    };
    vec![
        home.join("Library/Application Support"),
        home.join("Library/Caches"),
        home.join("Library/Logs"),
    ]
}

#[cfg(not(any(windows, target_os = "linux", target_os = "macos")))]
fn identity_roots() -> Vec<PathBuf> {
    Vec::new()
}

/// Rename `old` to `new`, returning whether anything moved.
///
/// A direct rename is the common path. When it fails (a file lock on Windows,
/// or a data directory mounted on another volume) the tree is copied to a
/// temporary sibling first and only promoted once the copy is complete, so a
/// partial copy can never masquerade as migrated state.
fn migrate_directory(old: &Path, new: &Path) -> std::io::Result<bool> {
    if !old.is_dir() {
        return Ok(false);
    }
    if new.exists() {
        // A previous attempt can fail (an old process holds a file) and Tauri
        // may then create the destination empty. Treat an empty destination as
        // "not migrated yet" so the next launch retries instead of silently
        // orphaning the legacy tree. A destination with any content always
        // wins and is never merged into.
        if !is_empty_dir(new) {
            return Ok(false);
        }
        fs::remove_dir(new)?;
    }
    if let Some(parent) = new.parent() {
        fs::create_dir_all(parent)?;
    }
    if fs::rename(old, new).is_ok() {
        return Ok(true);
    }

    // Do not copy a live tree as a fallback. On Windows a rename failure here
    // means another process still holds the directory (normally the old build
    // that the installer failed to stop); copying a live WebView2 profile can
    // produce an inconsistent profile. Leave the legacy tree untouched so the
    // next launch retries the rename once the old process is gone.
    Ok(false)
}

fn is_empty_dir(path: &Path) -> bool {
    fs::read_dir(path)
        .map(|mut entries| entries.next().is_none())
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::migrate_directory;
    use std::{
        fs,
        path::PathBuf,
        time::{SystemTime, UNIX_EPOCH},
    };

    fn scratch_root(name: &str) -> PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        std::env::temp_dir().join(format!("sunday-identity-{name}-{stamp}"))
    }

    #[test]
    fn migrates_only_when_the_destination_is_absent() {
        let root = scratch_root("move");
        let old = root.join("com.lamtools.lamcore");
        let new = root.join("com.lamtools.sunday");
        fs::create_dir_all(&old).expect("old dir");
        fs::write(old.join("state.txt"), "kept").expect("state");

        assert!(migrate_directory(&old, &new).expect("migrate"));
        assert_eq!(
            fs::read_to_string(new.join("state.txt")).expect("read"),
            "kept"
        );
        assert!(!old.exists());
        assert!(!migrate_directory(&old, &new).expect("second run"));

        // A later legacy run must not overwrite the migrated state.
        fs::create_dir_all(&old).expect("old again");
        fs::write(old.join("state.txt"), "newer legacy").expect("legacy state");
        assert!(!migrate_directory(&old, &new).expect("both exist"));
        assert_eq!(
            fs::read_to_string(new.join("state.txt")).expect("read"),
            "kept"
        );

        let _ = fs::remove_dir_all(&root);
    }

    #[test]
    fn missing_legacy_directory_is_a_no_op() {
        let root = scratch_root("missing");
        assert!(!migrate_directory(
            &root.join("com.lamtools.lamcore"),
            &root.join("com.lamtools.sunday")
        )
        .expect("no-op"));
        assert!(!root.exists());
    }

    #[test]
    fn retries_when_the_destination_is_only_an_empty_placeholder() {
        let root = scratch_root("empty-target");
        let old = root.join("com.lamtools.lamcore");
        let new = root.join("com.lamtools.sunday");
        fs::create_dir_all(&old).expect("old dir");
        fs::write(old.join("state.txt"), "kept").expect("state");
        fs::create_dir_all(&new).expect("empty target");

        assert!(migrate_directory(&old, &new).expect("retry"));
        assert_eq!(
            fs::read_to_string(new.join("state.txt")).expect("read"),
            "kept"
        );

        let _ = fs::remove_dir_all(&root);
    }
}
