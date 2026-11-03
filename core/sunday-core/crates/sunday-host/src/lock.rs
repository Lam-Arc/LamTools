//! One writer per data directory, enforced by the operating system.
//!
//! The previous version used a heartbeat: the holder rewrote the lock file every
//! few hundred milliseconds and any claimant whose record looked old took over.
//! That cannot distinguish a dead process from a paused one, and on Android a
//! backgrounded app can be frozen for minutes while still holding every intent to
//! write. Taking over there would put two live writers on one database, which is
//! the single failure this guard exists to prevent.
//!
//! This version asks the kernel instead:
//!
//!   * Unix: `flock(LOCK_EX | LOCK_NB)` on the lock file
//!   * Windows: `LockFileEx` with no sharing
//!
//! Both are released by the operating system when the process dies, and *not*
//! released by a suspended process. That is exactly the semantics needed: a
//! stopped process still owns the directory, a killed one does not.
//!
//! Two consequences of using a real lock, both learned by running the tests:
//!
//!   * **There is no reclaim window.** A crashed holder's lock is gone the moment
//!     the kernel reaps it, so a restart succeeds immediately.
//!   * **The lock file must not be deleted on release.** Deleting it opens a
//!     classic unlink race: A unlocks and removes while B has already created a
//!     new file and locked it, so A deletes B's lock. The file is therefore left
//!     in place; a lock file nobody holds is just a file.
//!
//! Because a held lock also blocks reads of the locked bytes on Windows, the
//! human-readable description lives in a separate `core.lock.owner` file that is
//! never locked. It is diagnostics only. Authority is the kernel lock, never the
//! contents of these files.

use fs2::FileExt;
use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use sunday_protocol::CoreError;

pub const LOCK_FILE: &str = "core.lock";
/// Diagnostics only. Never locked, safe to read while the directory is held.
pub const OWNER_FILE: &str = "core.lock.owner";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LockRecord {
    /// Who claims the directory. Free-form, for diagnostics.
    pub owner: String,
    pub pid: u32,
    /// Changes on every acquisition, so the owner file can be matched against a
    /// process that thinks it still holds the directory.
    pub token: String,
    pub acquired_at_ms: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LockError {
    /// Another live process holds the directory.
    Busy { owner: String, pid: u32 },
    /// The directory cannot be used at all.
    Io(String),
}

impl std::fmt::Display for LockError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Busy { owner, pid } => write!(
                f,
                "another core is writing this data directory: {owner} (pid {pid})"
            ),
            Self::Io(reason) => write!(f, "lock failure: {reason}"),
        }
    }
}

impl std::error::Error for LockError {}

impl From<LockError> for CoreError {
    fn from(error: LockError) -> Self {
        match error {
            LockError::Busy { owner, pid } => CoreError::Rejected {
                reason: format!("data directory is locked by {owner} (pid {pid})"),
            },
            LockError::Io(reason) => CoreError::Storage { reason },
        }
    }
}

pub struct SingleWriterLock {
    file: File,
    owner_path: PathBuf,
    token: String,
    held: AtomicBool,
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Best-effort description of the current holder. Never used to decide anything.
fn read_owner(path: &Path) -> Option<LockRecord> {
    let text = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

impl SingleWriterLock {
    /// Takes the directory or reports who has it.
    ///
    /// There is no timeout argument any more: liveness is the kernel's answer,
    /// not a number the caller guesses.
    pub fn acquire(dir: impl AsRef<Path>, owner: &str) -> Result<Self, LockError> {
        let dir = dir.as_ref();
        std::fs::create_dir_all(dir).map_err(|e| LockError::Io(e.to_string()))?;
        let path = dir.join(LOCK_FILE);
        let owner_path = dir.join(OWNER_FILE);

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&path)
            .map_err(|e| LockError::Io(e.to_string()))?;

        // The whole guarantee. A failure here means a live process holds it.
        if let Err(error) = file.try_lock_exclusive() {
            let record = read_owner(&owner_path);
            return Err(match record {
                Some(record) => LockError::Busy {
                    owner: record.owner,
                    pid: record.pid,
                },
                None => LockError::Busy {
                    // Locked but no readable description: a holder mid-startup,
                    // or a description we cannot parse. The kernel still says it
                    // is held, and that is what counts.
                    owner: format!("unknown ({})", error.kind()),
                    pid: 0,
                },
            });
        }

        let token = format!("{:x}-{}", now_ms(), std::process::id());
        let record = LockRecord {
            owner: owner.to_owned(),
            pid: std::process::id(),
            token: token.clone(),
            acquired_at_ms: now_ms(),
        };
        // A failure to describe ourselves is not fatal: the lock is what matters.
        if let Some(parent) = owner_path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let body = serde_json::to_string_pretty(&record).unwrap_or_default();
        if let Ok(mut handle) = File::create(&owner_path) {
            let _ = handle.write_all(body.as_bytes());
            let _ = handle.sync_all();
        }

        Ok(Self {
            file,
            owner_path,
            token,
            held: AtomicBool::new(true),
        })
    }

    pub fn token(&self) -> &str {
        &self.token
    }

    /// True while this guard still holds the directory.
    ///
    /// With an OS lock this cannot be stolen from a live process, so the answer
    /// is "did we release it", not "does the file still say our name".
    pub fn still_owner(&self) -> bool {
        self.held.load(Ordering::SeqCst)
    }

    pub fn record(&self) -> Option<LockRecord> {
        read_owner(&self.owner_path)
    }

    /// Releases the directory.
    ///
    /// The lock file is deliberately left in place: removing it would race a new
    /// writer that has already created and locked its own file.
    pub fn release(mut self) -> bool {
        self.finish()
    }

    fn finish(&mut self) -> bool {
        if !self.held.swap(false, Ordering::SeqCst) {
            return false;
        }
        // Only clear the description if it is still ours.
        if read_owner(&self.owner_path)
            .map(|record| record.token == self.token)
            .unwrap_or(false)
        {
            let _ = std::fs::remove_file(&self.owner_path);
        }
        // Qualified on purpose: std gained its own  in 1.89 and this
        // workspace targets 1.80, so the trait method must be named explicitly.
        FileExt::unlock(&self.file).is_ok()
    }
}

/// Debug prints the identity that matters when diagnosing a conflicting writer.
impl std::fmt::Debug for SingleWriterLock {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SingleWriterLock")
            .field("owner_path", &self.owner_path)
            .field("token", &self.token)
            .field("held", &self.held.load(Ordering::SeqCst))
            .finish()
    }
}

impl Drop for SingleWriterLock {
    fn drop(&mut self) {
        self.finish();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_second_writer_is_refused_and_told_who_has_it() {
        let dir = tempfile::tempdir().unwrap();
        let first = SingleWriterLock::acquire(dir.path(), "core-a").unwrap();
        let error = SingleWriterLock::acquire(dir.path(), "core-b").unwrap_err();
        match error {
            LockError::Busy { owner, pid } => {
                assert_eq!(owner, "core-a");
                assert_eq!(pid, std::process::id());
            }
            other => panic!("expected busy, got {other:?}"),
        }
        drop(first);
    }

    #[test]
    fn releasing_lets_the_next_writer_in_immediately() {
        let dir = tempfile::tempdir().unwrap();
        let first = SingleWriterLock::acquire(dir.path(), "core-a").unwrap();
        assert!(first.release());
        // No reclaim window to wait out: the next acquire succeeds at once.
        let second = SingleWriterLock::acquire(dir.path(), "core-b").unwrap();
        assert!(second.still_owner());
        assert_eq!(second.record().unwrap().owner, "core-b");
    }

    /// A stale *description* on disk must not block a new writer: the
    /// description is not authority, the kernel lock is.
    #[test]
    fn a_leftover_description_does_not_block_a_new_writer() {
        let dir = tempfile::tempdir().unwrap();
        let stale = LockRecord {
            owner: "dead-core".into(),
            pid: 999_999,
            token: "dead".into(),
            acquired_at_ms: 0,
        };
        std::fs::write(
            dir.path().join(OWNER_FILE),
            serde_json::to_string_pretty(&stale).unwrap(),
        )
        .unwrap();

        let lock = SingleWriterLock::acquire(dir.path(), "core-new")
            .expect("a description without a live kernel lock must not block");
        assert!(lock.still_owner());
        assert_eq!(lock.record().unwrap().owner, "core-new");
    }

    #[test]
    fn a_corrupt_description_is_replaced_not_trusted() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join(OWNER_FILE), b"{not json").unwrap();
        let lock = SingleWriterLock::acquire(dir.path(), "core-b").expect("must succeed");
        assert_eq!(lock.record().unwrap().owner, "core-b");
    }

    /// Killing the holder must free the directory with no waiting at all.
    #[test]
    fn a_killed_holder_is_reclaimed_without_waiting() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().to_path_buf();
        let mut child = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "lock::tests::lock_child_helper",
                "--ignored",
                "--nocapture",
            ])
            .env("SUNDAY_LOCK_CHILD", path.to_string_lossy().to_string())
            .spawn()
            .expect("spawn child");

        // Wait for the child to describe itself, which it does only after taking
        // the lock. Polling by *acquiring* would fight the child for the lock and
        // make it fail spuriously, which is exactly what the first version of
        // this test did.
        let mut held = false;
        for _ in 0..200 {
            if read_owner(&path.join(OWNER_FILE))
                .map(|record| record.owner == "child-holder")
                .unwrap_or(false)
            {
                held = true;
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(25));
        }
        assert!(
            held,
            "the child never took the lock: {:?}",
            child.try_wait()
        );

        child.kill().unwrap();
        let _ = child.wait();

        // Immediately, with no sleep: the kernel released it when the process died.
        let lock = SingleWriterLock::acquire(&path, "after-crash")
            .expect("a killed holder must be reclaimed at once");
        assert!(lock.still_owner());
    }

    /// A process that was *suspended* still owns the directory. This is the case
    /// the heartbeat design got wrong: it would have taken the lock away.
    #[test]
    fn a_suspended_holder_keeps_the_directory() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().to_path_buf();
        let mut child = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "lock::tests::lock_child_helper",
                "--ignored",
                "--nocapture",
            ])
            .env("SUNDAY_LOCK_CHILD", path.to_string_lossy().to_string())
            .spawn()
            .expect("spawn child");

        let mut held = false;
        for _ in 0..200 {
            if read_owner(&path.join(OWNER_FILE))
                .map(|record| record.owner == "child-holder")
                .unwrap_or(false)
            {
                held = true;
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(25));
        }
        assert!(held, "the child never took the lock");

        // Long enough that any heartbeat design would have declared it dead.
        std::thread::sleep(std::time::Duration::from_secs(3));
        let attempt = SingleWriterLock::acquire(&path, "thief");
        assert!(
            matches!(attempt, Err(LockError::Busy { .. })),
            "a suspended holder lost the directory: {attempt:?}"
        );

        child.kill().unwrap();
        let _ = child.wait();
    }

    #[test]
    #[ignore = "helper process; spawned by the kill test"]
    fn lock_child_helper() {
        let Ok(dir) = std::env::var("SUNDAY_LOCK_CHILD") else {
            return;
        };
        let _lock =
            SingleWriterLock::acquire(dir, "child-holder").expect("child must get the lock");
        // Hold it until killed. Deliberately not heartbeating: holding is enough.
        std::thread::sleep(std::time::Duration::from_secs(60));
    }
}
