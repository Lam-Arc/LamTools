//! One writer per data directory.
//!
//! Two cores must never write the same database. The guard is a lock file that
//! records who holds it and a heartbeat that proves the holder is alive.
//!
//! Why a heartbeat instead of an OS advisory lock: the heartbeat works the same
//! on Windows, Linux and Android without a platform dependency, and it survives
//! the case an advisory lock cannot fix, which is a holder that is alive but
//! wedged. The cost is a small reclaim window after a crash, which the caller
//! states explicitly.

use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use sunday_protocol::CoreError;

pub const LOCK_FILE: &str = "core.lock";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LockRecord {
    /// Who claims the directory. Free-form, for diagnostics.
    pub owner: String,
    pub pid: u32,
    /// Random per-acquisition token, so a release cannot delete someone else's
    /// lock by accident.
    pub token: String,
    pub acquired_at_ms: u64,
    pub heartbeat_ms: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LockError {
    /// Another writer holds it and is still alive.
    Busy {
        owner: String,
        pid: u32,
        age_ms: u64,
    },
    /// The directory cannot be used at all.
    Io(String),
}

impl std::fmt::Display for LockError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Busy { owner, pid, age_ms } => write!(
                f,
                "another core is writing this data directory: {owner} (pid {pid}, heartbeat {age_ms}ms ago)"
            ),
            Self::Io(reason) => write!(f, "lock failure: {reason}"),
        }
    }
}

impl std::error::Error for LockError {}

impl From<LockError> for CoreError {
    fn from(error: LockError) -> Self {
        match error {
            LockError::Busy { owner, pid, .. } => CoreError::Rejected {
                reason: format!("data directory is locked by {owner} (pid {pid})"),
            },
            LockError::Io(reason) => CoreError::Storage { reason },
        }
    }
}

pub struct SingleWriterLock {
    path: PathBuf,
    token: String,
    stop: Arc<AtomicBool>,
    heartbeat: Option<std::thread::JoinHandle<()>>,
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn read_record(path: &Path) -> Option<LockRecord> {
    let mut text = String::new();
    File::open(path).ok()?.read_to_string(&mut text).ok()?;
    serde_json::from_str(&text).ok()
}

/// How long ago the lock file itself last changed.
///
/// A corrupt record is not proof the holder is dead: it may be a file being
/// rewritten this instant. Falling back to the file's own modification time is
/// the only signal left, and it is a truthful one, because a live holder
/// rewrites the file every heartbeat.
fn file_age_ms(path: &Path) -> u64 {
    std::fs::metadata(path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|modified| SystemTime::now().duration_since(modified).ok())
        .map(|d| d.as_millis() as u64)
        .unwrap_or(u64::MAX)
}

fn write_record(path: &Path, record: &LockRecord) -> std::io::Result<()> {
    let body = serde_json::to_string_pretty(record).unwrap_or_default();
    let mut file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(path)?;
    file.write_all(body.as_bytes())?;
    file.sync_all()
}

impl SingleWriterLock {
    /// Acquires the directory or says who has it.
    ///
    /// `stale_after` is the reclaim window: a holder whose heartbeat is older
    /// than this is presumed dead and the lock is taken over. Choose it larger
    /// than any pause you can tolerate, because taking over a live writer is the
    /// one failure this design cannot undo.
    pub fn acquire(
        dir: impl AsRef<Path>,
        owner: &str,
        stale_after: Duration,
    ) -> Result<Self, LockError> {
        let dir = dir.as_ref();
        std::fs::create_dir_all(dir).map_err(|e| LockError::Io(e.to_string()))?;
        let path = dir.join(LOCK_FILE);
        let token = format!("{:x}-{}", now_ms(), std::process::id());

        match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(mut file) => {
                let record = LockRecord {
                    owner: owner.to_owned(),
                    pid: std::process::id(),
                    token: token.clone(),
                    acquired_at_ms: now_ms(),
                    heartbeat_ms: now_ms(),
                };
                let body = serde_json::to_string_pretty(&record).unwrap_or_default();
                file.write_all(body.as_bytes())
                    .map_err(|e| LockError::Io(e.to_string()))?;
                file.sync_all().map_err(|e| LockError::Io(e.to_string()))?;
            }
            Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => {
                let existing = read_record(&path);
                // A parsed record states its own heartbeat. An unparseable one
                // falls back to the file mtime: a live holder rewrites the file
                // every heartbeat, so a fresh mtime still means "someone is
                // there". Using u64::MAX here would make every corrupt file
                // instantly reclaimable and could put two writers on one
                // database, which is the failure this guard exists to prevent.
                let age = existing
                    .as_ref()
                    .map(|r| now_ms().saturating_sub(r.heartbeat_ms))
                    .unwrap_or_else(|| file_age_ms(&path));
                if age < stale_after.as_millis() as u64 {
                    return Err(match existing {
                        Some(record) => LockError::Busy {
                            owner: record.owner,
                            pid: record.pid,
                            age_ms: age,
                        },
                        None => LockError::Busy {
                            owner: "unknown (unreadable lock file)".into(),
                            pid: 0,
                            age_ms: age,
                        },
                    });
                }
                // Stale: the holder stopped breathing. Take it over, but write the
                // new record atomically so a reader never sees a half file.
                let record = LockRecord {
                    owner: owner.to_owned(),
                    pid: std::process::id(),
                    token: token.clone(),
                    acquired_at_ms: now_ms(),
                    heartbeat_ms: now_ms(),
                };
                let tmp = path.with_extension("lock-tmp");
                write_record(&tmp, &record).map_err(|e| LockError::Io(e.to_string()))?;
                std::fs::rename(&tmp, &path).map_err(|e| LockError::Io(e.to_string()))?;
            }
            Err(err) => return Err(LockError::Io(err.to_string())),
        }

        let stop = Arc::new(AtomicBool::new(false));
        let heartbeat_path = path.clone();
        let heartbeat_token = token.clone();
        let heartbeat_stop = stop.clone();
        let handle = std::thread::spawn(move || {
            while !heartbeat_stop.load(Ordering::SeqCst) {
                std::thread::sleep(Duration::from_millis(500));
                if heartbeat_stop.load(Ordering::SeqCst) {
                    break;
                }
                if let Some(mut record) = read_record(&heartbeat_path) {
                    if record.token == heartbeat_token {
                        record.heartbeat_ms = now_ms();
                        let _ = write_record(&heartbeat_path, &record);
                    }
                }
            }
        });

        Ok(Self {
            path,
            token,
            stop,
            heartbeat: Some(handle),
        })
    }

    pub fn token(&self) -> &str {
        &self.token
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// True when this guard's record is still the one on disk.
    pub fn still_owner(&self) -> bool {
        read_record(&self.path)
            .map(|r| r.token == self.token)
            .unwrap_or(false)
    }

    pub fn record(&self) -> Option<LockRecord> {
        read_record(&self.path)
    }

    /// Releases only if the record still belongs to this guard. A takeover by
    /// another process must not be undone by a late drop.
    pub fn release(mut self) -> bool {
        self.finish()
    }

    fn finish(&mut self) -> bool {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(handle) = self.heartbeat.take() {
            let _ = handle.join();
        }
        match read_record(&self.path) {
            Some(record) if record.token == self.token => std::fs::remove_file(&self.path).is_ok(),
            _ => false,
        }
    }
}

/// Debug prints the identity that matters when diagnosing a conflicting writer
/// and deliberately omits the heartbeat thread handle.
impl std::fmt::Debug for SingleWriterLock {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SingleWriterLock")
            .field("path", &self.path)
            .field("token", &self.token)
            .field("heartbeat_running", &self.heartbeat.is_some())
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

    fn short() -> Duration {
        Duration::from_millis(400)
    }

    #[test]
    fn a_second_writer_is_refused_and_told_who_has_it() {
        let dir = tempfile::tempdir().unwrap();
        let first = SingleWriterLock::acquire(dir.path(), "core-a", short()).unwrap();
        let err = SingleWriterLock::acquire(dir.path(), "core-b", short()).unwrap_err();
        match err {
            LockError::Busy { owner, pid, .. } => {
                assert_eq!(owner, "core-a");
                assert_eq!(pid, std::process::id());
            }
            other => panic!("expected busy, got {other:?}"),
        }
        drop(first);
    }

    #[test]
    fn releasing_lets_the_next_writer_in() {
        let dir = tempfile::tempdir().unwrap();
        let first = SingleWriterLock::acquire(dir.path(), "core-a", short()).unwrap();
        assert!(first.release());
        let second = SingleWriterLock::acquire(dir.path(), "core-b", short()).unwrap();
        assert_eq!(second.record().unwrap().owner, "core-b");
    }

    #[test]
    fn a_lock_whose_holder_stopped_breathing_is_reclaimed() {
        let dir = tempfile::tempdir().unwrap();
        // A record with an old heartbeat, as a killed process would leave behind.
        let record = LockRecord {
            owner: "dead-core".into(),
            pid: 999_999,
            token: "dead".into(),
            acquired_at_ms: 0,
            heartbeat_ms: 0,
        };
        write_record(&dir.path().join(LOCK_FILE), &record).unwrap();

        let lock = SingleWriterLock::acquire(dir.path(), "core-new", Duration::from_millis(50))
            .expect("a stale lock must be reclaimed");
        assert_eq!(lock.record().unwrap().owner, "core-new");
    }

    #[test]
    fn a_late_drop_does_not_delete_someone_elses_lock() {
        let dir = tempfile::tempdir().unwrap();
        let first =
            SingleWriterLock::acquire(dir.path(), "core-a", Duration::from_millis(50)).unwrap();
        let path = first.path().to_path_buf();
        // Simulate a takeover while the first guard is still in memory.
        let stolen = LockRecord {
            owner: "core-b".into(),
            pid: 1234,
            token: "other".into(),
            acquired_at_ms: now_ms(),
            heartbeat_ms: now_ms(),
        };
        write_record(&path, &stolen).unwrap();
        assert!(!first.still_owner());
        assert!(!first.release(), "a stale owner must not release the lock");
        assert!(path.exists(), "the new owner's lock must survive");
        assert_eq!(read_record(&path).unwrap().owner, "core-b");
    }

    #[test]
    fn the_heartbeat_advances_while_the_guard_lives() {
        let dir = tempfile::tempdir().unwrap();
        let lock =
            SingleWriterLock::acquire(dir.path(), "core-a", Duration::from_secs(30)).unwrap();
        let first = lock.record().unwrap().heartbeat_ms;
        std::thread::sleep(Duration::from_millis(1_200));
        let second = lock.record().unwrap().heartbeat_ms;
        assert!(
            second > first,
            "heartbeat did not advance: {first} -> {second}"
        );
    }

    #[test]
    fn a_corrupt_lock_file_is_treated_as_held_not_free() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::write(dir.path().join(LOCK_FILE), b"{not json").unwrap();
        let err =
            SingleWriterLock::acquire(dir.path(), "core-b", Duration::from_secs(30)).unwrap_err();
        assert!(matches!(err, LockError::Busy { .. }), "got {err:?}");
    }

    #[test]
    fn a_killed_holder_is_reclaimed_after_the_window() {
        // The child takes the lock and is killed without releasing it.
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().to_path_buf();
        let mut child = std::process::Command::new(std::env::current_exe().unwrap())
            // The test is nested in this module, so the filter needs the full
            // path; a bare `lock_child_helper` matches nothing and the child
            // would exit without ever taking the lock.
            .args([
                "--exact",
                "lock::tests::lock_child_helper",
                "--ignored",
                "--nocapture",
            ])
            .env("SUNDAY_LOCK_CHILD", path.to_string_lossy().to_string())
            .spawn()
            .expect("spawn child");
        // Wait until the child actually holds it.
        let mut held = false;
        for _ in 0..100 {
            if read_record(&path.join(LOCK_FILE)).is_some() {
                held = true;
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        assert!(held, "the child never took the lock; the filter is wrong");
        assert!(
            SingleWriterLock::acquire(&path, "probe", Duration::from_secs(30)).is_err(),
            "the child should still hold the lock"
        );
        child.kill().unwrap();
        let _ = child.wait();

        // The reclaim window must pass: a heartbeat written a moment ago is
        // indistinguishable from a live holder, and that is the intended trade.
        assert!(
            SingleWriterLock::acquire(&path, "too-early", Duration::from_secs(30)).is_err(),
            "reclaiming inside the window would race a live writer"
        );
        std::thread::sleep(Duration::from_millis(500));
        let lock = SingleWriterLock::acquire(&path, "after-crash", Duration::from_millis(200))
            .expect("a killed holder must be reclaimed once the window passes");
        assert_eq!(lock.record().unwrap().owner, "after-crash");
    }

    #[test]
    #[ignore = "helper process; spawned by the kill test"]
    fn lock_child_helper() {
        let Ok(dir) = std::env::var("SUNDAY_LOCK_CHILD") else {
            return;
        };
        let _lock = SingleWriterLock::acquire(dir, "child-holder", Duration::from_secs(300))
            .expect("child must get the lock");
        // Hold it until killed.
        std::thread::sleep(Duration::from_secs(30));
    }
}
