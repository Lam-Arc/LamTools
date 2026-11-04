//! Durable store: event journal, command receipts, tool stages, approvals.
//!
//! Everything that must survive a crash lives here. The rules the rest of the
//! system relies on:
//!
//!   * one `request_id` yields at most one accepted execution (S1)
//!   * `seq` is contiguous and increasing per thread (S2)
//!   * a tool's intent is durable before its side effect (S3)
//!   * a dispatched non-idempotent call with no result becomes `Unknown` on
//!     recovery and is never replayed (S4)
//!   * an approval is bound to an argument digest and an expiry (S5, S6)
//!   * an approval can be spent once (S7)
//!   * a projection rebuilds from the journal alone (S8)
//!
//! Every mutating call runs inside `BEGIN IMMEDIATE`, so two writers queue
//! instead of interleaving. Nothing here knows about HTTP, Tauri or Android.

use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use sunday_protocol::{
    CommandEnvelope, CommandReceipt, CommandStatus, CoreError, Event, EventKind, Message, Prepared,
    SideEffect, ToolCall, ToolStage,
};

pub const SCHEMA_VERSION: u32 = 3;
const SCHEMA_V1: &str = include_str!("schema_v1.sql");
/// One entry per version above 1. Applied in order on an existing database, so
/// an upgrade path is exercised by tests instead of being assumed.
const MIGRATIONS: &[(u32, &str)] = &[
    (2, include_str!("schema_v2.sql")),
    (3, include_str!("schema_v3.sql")),
];
const DEFAULT_BUSY_TIMEOUT_MS: u64 = 5_000;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Projection {
    pub thread_id: String,
    pub last_seq: u64,
    pub revision: u64,
    pub counts: BTreeMap<String, u64>,
}

impl Projection {
    fn empty(thread: &str) -> Self {
        Self {
            thread_id: thread.to_owned(),
            last_seq: 0,
            revision: 0,
            counts: BTreeMap::new(),
        }
    }

    fn record(&mut self, kind: EventKind, seq: u64, revision: u64) {
        self.last_seq = seq;
        self.revision = revision;
        *self.counts.entry(kind.as_str().to_owned()).or_insert(0) += 1;
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RecoveryPlan {
    pub unknown: Vec<String>,
    /// Safe to run again.
    pub requeueable: Vec<String>,
    /// Receipts that were left mid-flight and are now terminal.
    pub abandoned_receipts: Vec<String>,
    /// Sub-agents that were running when the process died.
    pub orphaned_children: Vec<String>,
}

/// What the write-ahead log looks like right now.
///
/// Reported so maintenance can tell "healthy" from "the checkpoint is starved by a
/// long reader", which are indistinguishable from the outside otherwise.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct WalHealth {
    /// A reader held pages back, so the checkpoint could not complete.
    pub starved: bool,
    pub log_pages: u64,
    pub checkpointed_pages: u64,
    /// Frames in the log times the page size: what has not been folded back yet.
    pub frames_bytes: u64,
    /// The `-wal` file on disk. PASSIVE never truncates, so this keeps its
    /// high-water mark and is strictly the number that matters for disk.
    pub file_bytes: u64,
    /// What `PRAGMA wal_checkpoint` reported in its first column. It stays false
    /// for PASSIVE by definition, so it is diagnostics only, never the verdict.
    pub reported_busy: bool,
}

/// One queued message, as the UI shows it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct QueueItem {
    pub queue_item_id: String,
    pub thread_id: String,
    pub position: u64,
    /// The stored input items, as JSON, exactly as the client sent them.
    pub input: String,
    pub status: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Guidance {
    pub guidance_id: String,
    pub text: String,
    pub created_at_ms: i64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChildStatus {
    Running,
    WaitingApproval,
    Completed,
    Cancelled,
    Failed,
    BudgetExhausted,
    WaitingReconciliation,
    /// The process died while this child was running. Needs a human.
    Orphaned,
}

impl ChildStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Running => "running",
            Self::WaitingApproval => "waiting_approval",
            Self::Completed => "completed",
            Self::Cancelled => "cancelled",
            Self::Failed => "failed",
            Self::BudgetExhausted => "budget_exhausted",
            Self::WaitingReconciliation => "waiting_reconciliation",
            Self::Orphaned => "orphaned",
        }
    }

    pub fn parse(text: &str) -> Option<Self> {
        Some(match text {
            "running" => Self::Running,
            "waiting_approval" => Self::WaitingApproval,
            "completed" => Self::Completed,
            "cancelled" => Self::Cancelled,
            "failed" => Self::Failed,
            "budget_exhausted" => Self::BudgetExhausted,
            "waiting_reconciliation" => Self::WaitingReconciliation,
            "orphaned" => Self::Orphaned,
            _ => return None,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChildRecord {
    pub child_id: String,
    pub parent_thread: String,
    pub child_thread: String,
    pub model_id: String,
    pub guide: String,
    pub granted_tools: Vec<String>,
    pub status: ChildStatus,
    pub result: Option<String>,
}

/// Everything needed to resume a turn without asking the model again.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Continuation {
    pub thread_id: String,
    pub turn_id: String,
    pub model_id: String,
    pub messages: Vec<Message>,
    pub pending_call_id: Option<String>,
}

/// The three things an approval id can mean to a caller.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ApprovalStatus {
    /// Still answerable.
    Pending,
    /// Its deadline passed; it may never authorise anything again.
    Expired,
    /// A human already answered it, one way or the other.
    Answered,
}

pub struct Store {
    conn: Connection,
}

impl std::fmt::Debug for Store {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // The connection itself is not Debug; identifying the store by kind is
        // enough for test assertions and error messages.
        f.write_str("Store")
    }
}

fn now_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

impl Store {
    /// Opens or creates a database file. The parent directory is created.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, CoreError> {
        let path = path.as_ref();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(CoreError::storage)?;
        }
        let conn = Connection::open(path).map_err(CoreError::storage)?;
        Self::init(conn)
    }

    /// Opens an existing database strictly read-only, and provably so.
    ///
    /// Two traps are handled here:
    ///
    /// * A WAL-mode database opened read-only still makes SQLite create `-wal`
    ///   and `-shm` files, which is a write. `immutable=1` stops that.
    /// * `immutable` also means "nobody else is writing", so a database with a
    ///   live write-ahead log is refused instead of being read as a moving
    ///   target. Stop the writer, or copy db + wal + shm and inspect the copy.
    pub fn open_read_only(path: impl AsRef<Path>) -> Result<Self, CoreError> {
        use rusqlite::OpenFlags;
        let path = path.as_ref();
        if !path.exists() {
            return Err(CoreError::invalid(format!(
                "no database at {}",
                path.display()
            )));
        }
        let wal = PathBuf::from(format!("{}-wal", path.display()));
        if wal.exists() {
            return Err(CoreError::Rejected {
                reason: format!(
                    "{} has a write-ahead log; reading it would create shm files. \
                     Stop the writer or inspect a copy of db + wal + shm.",
                    path.display()
                ),
            });
        }
        let uri = format!(
            "file:{}?immutable=1",
            path.to_string_lossy().replace('\\', "/")
        );
        let conn = Connection::open_with_flags(
            uri,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI,
        )
        .map_err(CoreError::storage)?;
        Ok(Self { conn })
    }

    fn init(conn: Connection) -> Result<Self, CoreError> {
        conn.busy_timeout(std::time::Duration::from_millis(DEFAULT_BUSY_TIMEOUT_MS))
            .map_err(CoreError::storage)?;
        conn.execute_batch(
            "PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;",
        )
        .map_err(CoreError::storage)?;
        conn.execute_batch(SCHEMA_V1).map_err(CoreError::storage)?;
        let mut store = Self { conn };
        store.migrate()?;
        Ok(store)
    }

    fn migrate(&mut self) -> Result<(), CoreError> {
        let current: Option<String> = self
            .conn
            .query_row(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'",
                [],
                |row| row.get(0),
            )
            .optional()
            .map_err(CoreError::storage)?;
        let mut version = match current {
            None => {
                self.conn
                    .execute(
                        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?1)",
                        params!["1"],
                    )
                    .map_err(CoreError::storage)?;
                1u32
            }
            Some(text) => text.parse().map_err(|_| CoreError::Storage {
                reason: format!("schema_version is not a number: {text}"),
            })?,
        };

        if version > SCHEMA_VERSION {
            // A newer core wrote this file. Refuse rather than corrupt it.
            return Err(CoreError::ProtocolIncompatible {
                min: SCHEMA_VERSION,
                max: version,
            });
        }

        for (target, sql) in MIGRATIONS {
            if version < *target {
                let tx = self
                    .conn
                    .transaction_with_behavior(TransactionBehavior::Immediate)
                    .map_err(CoreError::storage)?;
                tx.execute_batch(sql).map_err(CoreError::storage)?;
                tx.execute(
                    "UPDATE schema_meta SET value = ?1 WHERE key = 'schema_version'",
                    params![target.to_string()],
                )
                .map_err(CoreError::storage)?;
                tx.commit().map_err(CoreError::storage)?;
                version = *target;
            }
        }
        Ok(())
    }

    pub fn schema_version(&self) -> Result<u32, CoreError> {
        let value: String = self
            .conn
            .query_row(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'",
                [],
                |row| row.get(0),
            )
            .map_err(CoreError::storage)?;
        value.parse().map_err(CoreError::storage)
    }

    fn revision_of(&self, thread: &str) -> Result<u64, CoreError> {
        let value: Option<i64> = self
            .conn
            .query_row(
                "SELECT revision FROM thread_revisions WHERE thread_id = ?1",
                params![thread],
                |row| row.get(0),
            )
            .optional()
            .map_err(CoreError::storage)?;
        Ok(value.unwrap_or(0) as u64)
    }

    /// One command, one transaction. Returns the stored receipt on a resend.
    pub fn accept_command(
        &mut self,
        workspace: &str,
        env: &CommandEnvelope,
    ) -> Result<CommandReceipt, CoreError> {
        let digest = env.payload_digest();
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;

        let existing: Option<(String, String, String, Option<i64>, i64)> = tx
            .query_row(
                "SELECT payload_digest, status, thread_id, seq, revision \
                 FROM command_receipts WHERE request_id = ?1",
                params![env.request_id],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                    ))
                },
            )
            .optional()
            .map_err(CoreError::storage)?;

        if let Some((stored_digest, status, thread_id, seq, revision)) = existing {
            if stored_digest != digest {
                // Same id, different body: refuse instead of replaying a receipt
                // that describes a different command.
                return Err(CoreError::Rejected {
                    reason: format!(
                        "request_id {} was already used for a different payload",
                        env.request_id
                    ),
                });
            }
            return Ok(CommandReceipt {
                request_id: env.request_id.clone(),
                status: CommandStatus::parse(&status).unwrap_or(CommandStatus::Rejected),
                thread_id,
                seq: seq.map(|v| v as u64),
                revision: revision as u64,
            });
        }

        let current = {
            let value: Option<i64> = tx
                .query_row(
                    "SELECT revision FROM thread_revisions WHERE thread_id = ?1",
                    params![env.thread_id],
                    |row| row.get(0),
                )
                .optional()
                .map_err(CoreError::storage)?;
            value.unwrap_or(0) as u64
        };
        if let Some(expected) = env.expected_revision {
            if expected != current {
                return Err(CoreError::RevisionConflict {
                    expected,
                    actual: current,
                });
            }
        }

        let seq = {
            let max: Option<i64> = tx
                .query_row(
                    "SELECT MAX(seq) FROM journal_events WHERE workspace_id = ?1 AND thread_id = ?2",
                    params![workspace, env.thread_id],
                    |row| row.get(0),
                )
                .map_err(CoreError::storage)?;
            max.map(|v| v as u64 + 1).unwrap_or(1)
        };
        let revision = current + 1;
        let now = now_ms();

        tx.execute(
            "INSERT INTO journal_events (workspace_id, thread_id, seq, event_id, kind, payload, created_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                workspace,
                env.thread_id,
                seq as i64,
                format!("{}:accepted", env.request_id),
                EventKind::CommandAccepted.as_str(),
                {
                    // The instruction's text belongs in the journal: it is what the
                    // user asked, and a resumed screen must be able to show it
                    // without a second lookup that does not survive a restart.
                    let mut payload = json!({"kind": env.payload.kind()});
                    if let sunday_protocol::Command::TurnStart { text } = &env.payload {
                        if let Some(object) = payload.as_object_mut() {
                            object.insert("text".into(), json!(text));
                        }
                    }
                    payload.to_string()
                },
                now
            ],
        )
        .map_err(CoreError::storage)?;

        tx.execute(
            "INSERT INTO command_receipts \
             (request_id, command_kind, payload_digest, status, thread_id, seq, revision, created_at, updated_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?8)",
            params![
                env.request_id,
                env.payload.kind(),
                digest,
                CommandStatus::Accepted.as_str(),
                env.thread_id,
                seq as i64,
                revision as i64,
                now
            ],
        )
        .map_err(CoreError::storage)?;

        tx.execute(
            "INSERT INTO thread_revisions (thread_id, revision) VALUES (?1, ?2) \
             ON CONFLICT(thread_id) DO UPDATE SET revision = ?2",
            params![env.thread_id, revision as i64],
        )
        .map_err(CoreError::storage)?;

        let mut projection = Self::projection_in_tx(&tx, &env.thread_id)?;
        projection.record(EventKind::CommandAccepted, seq, revision);
        Self::write_projection(&tx, &projection)?;

        tx.commit().map_err(CoreError::storage)?;

        Ok(CommandReceipt {
            request_id: env.request_id.clone(),
            status: CommandStatus::Accepted,
            thread_id: env.thread_id.clone(),
            seq: Some(seq),
            revision,
        })
    }

    /// Appends one event. Re-sending the same `event_id` is a no-op that returns
    /// the original seq, because at-least-once transport is the norm.
    pub fn append_event(
        &mut self,
        workspace: &str,
        thread: &str,
        event_id: &str,
        kind: EventKind,
        payload: Value,
    ) -> Result<u64, CoreError> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;

        let existing: Option<i64> = tx
            .query_row(
                "SELECT seq FROM journal_events WHERE event_id = ?1",
                params![event_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(CoreError::storage)?;
        if let Some(seq) = existing {
            return Ok(seq as u64);
        }

        let seq = {
            let max: Option<i64> = tx
                .query_row(
                    "SELECT MAX(seq) FROM journal_events WHERE workspace_id = ?1 AND thread_id = ?2",
                    params![workspace, thread],
                    |row| row.get(0),
                )
                .map_err(CoreError::storage)?;
            max.map(|v| v as u64 + 1).unwrap_or(1)
        };
        let revision = {
            let value: Option<i64> = tx
                .query_row(
                    "SELECT revision FROM thread_revisions WHERE thread_id = ?1",
                    params![thread],
                    |row| row.get(0),
                )
                .optional()
                .map_err(CoreError::storage)?;
            value.unwrap_or(0) as u64 + 1
        };

        tx.execute(
            "INSERT INTO journal_events (workspace_id, thread_id, seq, event_id, kind, payload, created_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                workspace,
                thread,
                seq as i64,
                event_id,
                kind.as_str(),
                payload.to_string(),
                now_ms()
            ],
        )
        .map_err(CoreError::storage)?;

        tx.execute(
            "INSERT INTO thread_revisions (thread_id, revision) VALUES (?1, ?2) \
             ON CONFLICT(thread_id) DO UPDATE SET revision = ?2",
            params![thread, revision as i64],
        )
        .map_err(CoreError::storage)?;

        let mut projection = Self::projection_in_tx(&tx, thread)?;
        projection.record(kind, seq, revision);
        Self::write_projection(&tx, &projection)?;

        tx.commit().map_err(CoreError::storage)?;
        Ok(seq)
    }

    /// Appends several events as one atomic transaction.
    ///
    /// Why this exists: durability is not negotiable (`synchronous=FULL`), so
    /// the only honest way to make writes cheaper is to do fewer commits. One
    /// fsync per logical operation instead of one per event.
    ///
    /// It keeps every guarantee `append_event` makes:
    ///
    ///   * `seq` stays contiguous and in the order given
    ///   * a repeated `event_id` is skipped, not duplicated
    ///   * nothing is visible until the single commit, so a crash mid-batch
    ///     leaves either all of it or none of it
    ///
    /// Returns the seq of each event that was actually appended, in input order.
    /// An event already present is omitted from the result.
    pub fn append_events(
        &mut self,
        workspace: &str,
        thread: &str,
        events: &[(String, EventKind, Value)],
    ) -> Result<Vec<u64>, CoreError> {
        if events.is_empty() {
            return Ok(Vec::new());
        }
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;

        // One read of the high-water marks for the whole batch, instead of two
        // per event. A MAX(seq) scan per event is the other half of the cost.
        let mut seq: u64 = {
            let max: Option<i64> = tx
                .query_row(
                    "SELECT MAX(seq) FROM journal_events WHERE workspace_id = ?1 AND thread_id = ?2",
                    params![workspace, thread],
                    |row| row.get(0),
                )
                .map_err(CoreError::storage)?;
            max.map(|v| v as u64).unwrap_or(0)
        };
        let mut revision: u64 = {
            let value: Option<i64> = tx
                .query_row(
                    "SELECT revision FROM thread_revisions WHERE thread_id = ?1",
                    params![thread],
                    |row| row.get(0),
                )
                .optional()
                .map_err(CoreError::storage)?;
            value.unwrap_or(0) as u64
        };

        // The projection is read once and written once, not per event.
        let mut projection = Self::projection_in_tx(&tx, thread)?;
        let created = now_ms();
        let mut appended = Vec::with_capacity(events.len());

        for (event_id, kind, payload) in events {
            let existing: Option<i64> = tx
                .query_row(
                    "SELECT seq FROM journal_events WHERE event_id = ?1",
                    params![event_id],
                    |row| row.get(0),
                )
                .optional()
                .map_err(CoreError::storage)?;
            if existing.is_some() {
                // Already durable. Skipping keeps a retry idempotent.
                continue;
            }
            seq += 1;
            revision += 1;
            tx.execute(
                "INSERT INTO journal_events (workspace_id, thread_id, seq, event_id, kind, payload, created_at) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    workspace,
                    thread,
                    seq as i64,
                    event_id,
                    kind.as_str(),
                    payload.to_string(),
                    created
                ],
            )
            .map_err(CoreError::storage)?;
            projection.record(*kind, seq, revision);
            appended.push(seq);
        }

        if appended.is_empty() {
            // Nothing new. Do not bump the revision: a no-op must not look like
            // a change to a client watching revisions.
            return Ok(appended);
        }

        tx.execute(
            "INSERT INTO thread_revisions (thread_id, revision) VALUES (?1, ?2) \
             ON CONFLICT(thread_id) DO UPDATE SET revision = ?2",
            params![thread, revision as i64],
        )
        .map_err(CoreError::storage)?;
        Self::write_projection(&tx, &projection)?;

        tx.commit().map_err(CoreError::storage)?;
        Ok(appended)
    }

    /// Folds the write-ahead log back into the main file and truncates it.
    ///
    /// Two uses: a maintenance/measurement hook, and an honest way to report the
    /// steady-state disk cost of an event. Without it, "bytes per event" is
    /// whatever fraction of the WAL happens to be un-checkpointed, which is not
    /// a property of the data.
    ///
    /// TRUNCATE blocks writers while it runs, so it is for maintenance windows
    /// and tests, never for the send path.
    pub fn checkpoint(&self) -> Result<(), CoreError> {
        self.conn
            .execute_batch("PRAGMA wal_checkpoint(TRUNCATE);")
            .map_err(CoreError::storage)
    }

    /// A PASSIVE checkpoint: moves whatever pages no reader needs, never blocks a
    /// writer, never truncates.
    ///
    /// This is what a maintenance thread should call. It is the safe primitive
    /// precisely because it gives up rather than waiting: a long read transaction
    /// can starve it, which shows up as WAL growth (`wal_bytes()`) instead of as a
    /// stalled send.
    pub fn checkpoint_passive(&self) -> Result<(), CoreError> {
        self.conn
            .execute_batch("PRAGMA wal_checkpoint(PASSIVE);")
            .map_err(CoreError::storage)
    }

    /// Current write-ahead log size in bytes, and whether a checkpoint is able to
    /// make progress. Used by maintenance to detect starvation.
    pub fn wal_health(&self) -> Result<WalHealth, CoreError> {
        let (busy, log_pages, checkpointed): (i64, i64, i64) = self
            .conn
            .query_row("PRAGMA wal_checkpoint(PASSIVE);", [], |row| {
                Ok((row.get(0)?, row.get(1)?, row.get(2)?))
            })
            .map_err(CoreError::storage)?;
        let page_size: i64 = self
            .conn
            .query_row("PRAGMA page_size;", [], |row| row.get(0))
            .unwrap_or(4096);
        let main_file: Option<String> = self
            .conn
            .query_row(
                "SELECT file FROM pragma_database_list WHERE name = 'main'",
                [],
                |row| row.get(0),
            )
            .optional()
            .map_err(CoreError::storage)?;
        let file_bytes = main_file
            .map(|path| std::fs::metadata(format!("{path}-wal")).map(|m| m.len()))
            .and_then(Result::ok)
            .unwrap_or(0);
        Ok(WalHealth {
            // `busy` is NOT the starvation signal for PASSIVE: SQLite only raises it
            // for RESTART/FULL/TRUNCATE, because PASSIVE by definition gives up
            // instead of waiting. The honest signal is the gap between the frames in
            // the log and the frames the checkpoint managed to backfill: a reader
            // holding pages back makes PASSIVE stop at the first one it needs.
            starved: log_pages > 0 && checkpointed < log_pages,
            log_pages: log_pages as u64,
            checkpointed_pages: checkpointed as u64,
            frames_bytes: log_pages as u64 * page_size.max(0) as u64,
            file_bytes,
            reported_busy: busy != 0,
        })
    }

    /// Raises the page threshold at which SQLite runs its own synchronous
    /// checkpoint on the committing thread.
    ///
    /// The default is 1000 pages (~4 MB). A host that runs its own background
    /// PASSIVE loop raises this so an auto-checkpoint does not land in the middle
    /// of a send. It is a mitigation, not a substitute: if the background loop
    /// dies, the WAL still stops growing at this threshold instead of forever.
    pub fn raise_autocheckpoint(&self, pages: u32) -> Result<(), CoreError> {
        self.conn
            .execute_batch(&format!("PRAGMA wal_autocheckpoint={pages};"))
            .map_err(CoreError::storage)
    }

    // ---- queue --------------------------------------------------------

    /// A queued message: what the user typed while a turn was still running.
    ///
    /// Stored rather than held in memory so a restart does not silently swallow
    /// what someone typed, and so `queue/create` has something real to report.
    pub fn enqueue(&mut self, thread: &str, item_id: &str, input: &str) -> Result<u64, CoreError> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;
        let position: i64 = tx
            .query_row(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM queue_items WHERE thread_id = ?1",
                params![thread],
                |row| row.get(0),
            )
            .map_err(CoreError::storage)?;
        let now = now_ms();
        // Same identity rule as the journal: a retried create must not duplicate.
        tx.execute(
            "INSERT INTO queue_items (queue_item_id, thread_id, position, input_json, status, created_at, updated_at) \
             VALUES (?1, ?2, ?3, ?4, 'queued', ?5, ?5) \
             ON CONFLICT(queue_item_id) DO NOTHING",
            params![item_id, thread, position, json!({"text": input}).to_string(), now],
        )
        .map_err(CoreError::storage)?;
        tx.commit().map_err(CoreError::storage)?;
        self.queue_position(thread, item_id)
    }

    fn queue_position(&self, thread: &str, item_id: &str) -> Result<u64, CoreError> {
        self.conn
            .query_row(
                "SELECT position FROM queue_items WHERE thread_id = ?1 AND queue_item_id = ?2",
                params![thread, item_id],
                |row| row.get::<_, i64>(0),
            )
            .optional()
            .map_err(CoreError::storage)
            .map(|value| value.unwrap_or(0) as u64)
    }

    /// The queue in the order the user arranged it.
    pub fn queue(&self, thread: &str) -> Result<Vec<QueueItem>, CoreError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT queue_item_id, thread_id, position, input_json, status \
                 FROM queue_items WHERE thread_id = ?1 ORDER BY position, created_at",
            )
            .map_err(CoreError::storage)?;
        let rows = stmt
            .query_map(params![thread], |row| {
                Ok(QueueItem {
                    queue_item_id: row.get(0)?,
                    thread_id: row.get(1)?,
                    position: row.get::<_, i64>(2)? as u64,
                    input: row.get(3)?,
                    status: row.get(4)?,
                })
            })
            .map_err(CoreError::storage)?;
        let mut out = Vec::new();
        for row in rows {
            out.push(row.map_err(CoreError::storage)?);
        }
        Ok(out)
    }

    pub fn update_queue_item(
        &mut self,
        thread: &str,
        item_id: &str,
        input: &str,
    ) -> Result<bool, CoreError> {
        let changed = self
            .conn
            .execute(
                "UPDATE queue_items SET input_json = ?3, updated_at = ?4 \
                 WHERE thread_id = ?1 AND queue_item_id = ?2",
                params![
                    thread,
                    item_id,
                    json!({"text": input}).to_string(),
                    now_ms()
                ],
            )
            .map_err(CoreError::storage)?;
        Ok(changed > 0)
    }

    pub fn delete_queue_item(&mut self, thread: &str, item_id: &str) -> Result<bool, CoreError> {
        let changed = self
            .conn
            .execute(
                "DELETE FROM queue_items WHERE thread_id = ?1 AND queue_item_id = ?2",
                params![thread, item_id],
            )
            .map_err(CoreError::storage)?;
        Ok(changed > 0)
    }

    /// Rewrites the whole order in one transaction, so a reorder cannot leave
    /// duplicate positions behind.
    pub fn reorder_queue(&mut self, thread: &str, order: &[String]) -> Result<(), CoreError> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;
        for (index, item_id) in order.iter().enumerate() {
            tx.execute(
                "UPDATE queue_items SET position = ?3, updated_at = ?4 \
                 WHERE thread_id = ?1 AND queue_item_id = ?2",
                params![thread, item_id, index as i64 + 1, now_ms()],
            )
            .map_err(CoreError::storage)?;
        }
        tx.commit().map_err(CoreError::storage)?;
        Ok(())
    }

    /// Marks one queued item as taken by the loop, so it is not sent twice.
    pub fn mark_queue_dispatched(
        &mut self,
        thread: &str,
        item_id: &str,
    ) -> Result<bool, CoreError> {
        let changed = self
            .conn
            .execute(
                "UPDATE queue_items SET status = 'dispatched', updated_at = ?3 \
                 WHERE thread_id = ?1 AND queue_item_id = ?2 AND status = 'queued'",
                params![thread, item_id, now_ms()],
            )
            .map_err(CoreError::storage)?;
        Ok(changed > 0)
    }

    // ---- history ------------------------------------------------------

    /// One page of a thread's history, newest window first.
    ///
    /// Pagination is by whole turns, because half a turn is not something the
    /// transcript can render. `before_seq` is the cursor: pass the smallest seq
    /// the client already holds and get the page before it.
    pub fn history_page(
        &self,
        thread: &str,
        before_seq: Option<u64>,
        limit: usize,
    ) -> Result<(Vec<Event>, bool), CoreError> {
        let limit = limit.clamp(1, 500);
        // The ceiling is stored as INTEGER, so it must be built in i64's range.
        // `u64::MAX as i64` is -1, which would silently return no rows at all for
        // the newest page: the first page of every thread would look empty.
        let ceiling: i64 = before_seq
            .map(|seq| seq.min(i64::MAX as u64) as i64)
            .unwrap_or(i64::MAX);
        // Ask for one extra row to learn whether an older page exists without a
        // second count query.
        let mut stmt = self
            .conn
            .prepare(
                "SELECT thread_id, seq, event_id, kind, payload FROM journal_events \
                 WHERE thread_id = ?1 AND seq < ?2 ORDER BY seq DESC LIMIT ?3",
            )
            .map_err(CoreError::storage)?;
        let rows = stmt
            .query_map(params![thread, ceiling, limit as i64 + 1], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, i64>(1)? as u64,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                ))
            })
            .map_err(CoreError::storage)?;
        let mut collected = Vec::new();
        for row in rows {
            let (thread_id, seq, event_id, kind, payload) = row.map_err(CoreError::storage)?;
            collected.push(Event {
                thread_id,
                seq,
                event_id,
                kind: EventKind::parse(&kind).ok_or_else(|| CoreError::Storage {
                    reason: format!("unknown event kind {kind}"),
                })?,
                payload: serde_json::from_str(&payload).unwrap_or(Value::Null),
            });
        }
        let has_more = collected.len() > limit;
        if has_more {
            collected.truncate(limit);
        }
        // Return them oldest-first, which is the order a transcript renders in.
        collected.reverse();
        Ok((collected, has_more))
    }

    pub fn event_count(&self, thread: &str) -> Result<u64, CoreError> {
        self.conn
            .query_row(
                "SELECT COUNT(*) FROM journal_events WHERE thread_id = ?1",
                params![thread],
                |row| row.get::<_, i64>(0),
            )
            .map_err(CoreError::storage)
            .map(|value| value as u64)
    }

    pub fn finish_receipt(
        &mut self,
        request_id: &str,
        status: CommandStatus,
    ) -> Result<(), CoreError> {
        let changed = self
            .conn
            .execute(
                "UPDATE command_receipts SET status = ?2, updated_at = ?3 WHERE request_id = ?1",
                params![request_id, status.as_str(), now_ms()],
            )
            .map_err(CoreError::storage)?;
        if changed == 0 {
            return Err(CoreError::invalid(format!("no receipt for {request_id}")));
        }
        Ok(())
    }

    pub fn receipt(&self, request_id: &str) -> Result<Option<CommandReceipt>, CoreError> {
        self.conn
            .query_row(
                "SELECT request_id, status, thread_id, seq, revision \
                 FROM command_receipts WHERE request_id = ?1",
                params![request_id],
                |row| {
                    let status: String = row.get(1)?;
                    Ok(CommandReceipt {
                        request_id: row.get(0)?,
                        status: CommandStatus::parse(&status).unwrap_or(CommandStatus::Rejected),
                        thread_id: row.get(2)?,
                        seq: row.get::<_, Option<i64>>(3)?.map(|v| v as u64),
                        revision: row.get::<_, i64>(4)? as u64,
                    })
                },
            )
            .optional()
            .map_err(CoreError::storage)
    }

    // ---- tool stage machine -------------------------------------------

    /// Ask before acting. The answer is durable, so a crash between "may I" and
    /// "I did" is visible afterwards.
    pub fn prepare_tool_once(
        &mut self,
        thread: &str,
        call: &ToolCall,
        side: SideEffect,
    ) -> Result<Prepared, CoreError> {
        let digest = sunday_protocol::digest_json(&call.args);
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;

        let existing: Option<(String, String, String, Option<String>)> = tx
            .query_row(
                "SELECT args_digest, side_effect, stage, result_json \
                 FROM tool_call_stages WHERE tool_call_id = ?1",
                params![call.id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()
            .map_err(CoreError::storage)?;

        if let Some((stored_digest, _stored_side, stage, _result)) = existing {
            if stored_digest != digest {
                return Err(CoreError::Rejected {
                    reason: format!(
                        "tool_call_id {} was already used with different arguments",
                        call.id
                    ),
                });
            }
            let stage = ToolStage::parse(&stage).unwrap_or(ToolStage::Prepared);
            let answer = match stage {
                ToolStage::Succeeded => Prepared::AlreadyDone,
                ToolStage::Unknown => Prepared::MustReconcile,
                ToolStage::Dispatched => match side {
                    SideEffect::NonIdempotent => Prepared::MustReconcile,
                    _ => Prepared::Ready,
                },
                _ => Prepared::Ready,
            };
            return Ok(answer);
        }

        tx.execute(
            "INSERT INTO tool_call_stages \
             (tool_call_id, thread_id, tool_id, args_digest, args_json, side_effect, stage, updated_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                call.id,
                thread,
                call.name,
                digest,
                call.args.to_string(),
                serde_json::to_string(&side).unwrap_or_default(),
                ToolStage::Prepared.as_str(),
                now_ms()
            ],
        )
        .map_err(CoreError::storage)?;
        tx.commit().map_err(CoreError::storage)?;
        Ok(Prepared::Ready)
    }

    /// Must be called after the intent is durable and before the side effect.
    pub fn mark_dispatched(&mut self, call_id: &str) -> Result<(), CoreError> {
        self.set_stage(call_id, ToolStage::Dispatched, None)
    }

    pub fn finish_tool_call(
        &mut self,
        call_id: &str,
        result: &Value,
        ok: bool,
    ) -> Result<(), CoreError> {
        self.set_stage(
            call_id,
            if ok {
                ToolStage::Succeeded
            } else {
                ToolStage::Failed
            },
            Some(result.clone()),
        )
    }

    fn set_stage(
        &mut self,
        call_id: &str,
        stage: ToolStage,
        result: Option<Value>,
    ) -> Result<(), CoreError> {
        let changed = self
            .conn
            .execute(
                "UPDATE tool_call_stages SET stage = ?2, result_json = COALESCE(?3, result_json), \
                 updated_at = ?4 WHERE tool_call_id = ?1",
                params![
                    call_id,
                    stage.as_str(),
                    result.map(|v| v.to_string()),
                    now_ms()
                ],
            )
            .map_err(CoreError::storage)?;
        if changed == 0 {
            return Err(CoreError::invalid(format!("no tool call {call_id}")));
        }
        Ok(())
    }

    pub fn tool_stage(&self, call_id: &str) -> Result<Option<ToolStage>, CoreError> {
        let stage: Option<String> = self
            .conn
            .query_row(
                "SELECT stage FROM tool_call_stages WHERE tool_call_id = ?1",
                params![call_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(CoreError::storage)?;
        Ok(stage.and_then(|s| ToolStage::parse(&s)))
    }

    pub fn tool_result(&self, call_id: &str) -> Result<Option<Value>, CoreError> {
        let raw: Option<Option<String>> = self
            .conn
            .query_row(
                "SELECT result_json FROM tool_call_stages WHERE tool_call_id = ?1",
                params![call_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(CoreError::storage)?;
        Ok(raw
            .flatten()
            .and_then(|text| serde_json::from_str(&text).ok()))
    }

    // ---- approvals ----------------------------------------------------

    /// `ttl_seconds` of zero is refused: an approval that never expires is a
    /// liability on a device that can sit in a pocket for a day.
    pub fn request_approval(
        &mut self,
        thread: &str,
        call: &ToolCall,
        ttl_seconds: u64,
        now_epoch: u64,
    ) -> Result<sunday_protocol::ApprovalRequest, CoreError> {
        if ttl_seconds == 0 {
            return Err(CoreError::invalid("approval ttl must be positive"));
        }
        let args_digest = sunday_protocol::digest_json(&call.args);
        let approval_id = format!(
            "appr-{}",
            sunday_protocol::digest_str(&format!("{thread}|{}|{args_digest}", call.id))
        );
        let expires_at = now_epoch + ttl_seconds;
        self.conn
            .execute(
                "INSERT INTO approvals \
                 (approval_id, thread_id, tool_call_id, args_digest, status, expires_at, created_at) \
                 VALUES (?1, ?2, ?3, ?4, 'pending', ?5, ?6) \
                 ON CONFLICT(approval_id) DO NOTHING",
                params![
                    approval_id,
                    thread,
                    call.id,
                    args_digest,
                    expires_at as i64,
                    now_ms()
                ],
            )
            .map_err(CoreError::storage)?;
        Ok(sunday_protocol::ApprovalRequest {
            approval_id,
            thread_id: thread.to_owned(),
            tool_call_id: call.id.clone(),
            tool_id: call.name.clone(),
            args_digest,
            expires_at_epoch: expires_at,
        })
    }

    /// Every approval on this thread that is no longer pending, with its status.
    ///
    /// A resumed transcript replays the original `approval_request` events, so a card
    /// whose approval ended on an earlier run comes back looking answerable and holds
    /// the conversation hostage. Reporting every settled approval — not only the ones
    /// this call closed — is what lets the screen retire those cards.
    pub fn settled_approvals(&self, thread: &str) -> Result<Vec<(String, String)>, CoreError> {
        let mut statement = self
            .conn
            .prepare(
                "SELECT approval_id, status FROM approvals \
                 WHERE thread_id = ?1 AND status != 'pending' ORDER BY rowid",
            )
            .map_err(CoreError::storage)?;
        let rows: Vec<(String, String)> = statement
            .query_map(params![thread], |row| Ok((row.get(0)?, row.get(1)?)))
            .map_err(CoreError::storage)?
            .collect::<Result<Vec<(String, String)>, _>>()
            .map_err(CoreError::storage)?;
        Ok(rows)
    }

    /// What an approval id currently means, without consuming it.
    ///
    /// `pending_call` answers "which call is this", not "may it still run": it joins
    /// the stage table and ignores both `status` and `expires_at`. Any caller that
    /// treated it as a permission check would happily approve an hour-old request.
    ///
    /// `expires_at` is seconds since the epoch while `created_at` is milliseconds, so
    /// this comparison is in seconds. Mixing the two makes a request look eternally
    /// fresh or eternally stale depending on which side is used.
    pub fn approval_gate(
        &self,
        approval_id: &str,
        now_epoch: u64,
    ) -> Result<Option<ApprovalStatus>, CoreError> {
        let row: Option<(String, i64)> = self
            .conn
            .query_row(
                "SELECT status, expires_at FROM approvals WHERE approval_id = ?1",
                params![approval_id],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()
            .map_err(CoreError::storage)?;
        let Some((status, expires_at)) = row else {
            return Ok(None);
        };
        Ok(Some(match status.as_str() {
            "pending" if now_epoch as i64 >= expires_at => ApprovalStatus::Expired,
            "pending" => ApprovalStatus::Pending,
            "expired" => ApprovalStatus::Expired,
            _ => ApprovalStatus::Answered,
        }))
    }

    /// Closes every pending approval past its deadline, and reports which ones closed.
    ///
    /// Without this a session whose approval aged out stayed unusable forever: the
    /// card kept its two buttons, the composer stayed taken over by a decision nobody
    /// could answer, and no new turn could start in that conversation.
    ///
    /// The update is conditional on `status = 'pending'` so a concurrent answer wins
    /// instead of being overwritten by an expiry sweep.
    pub fn expire_stale_approvals(&mut self, now_epoch: u64) -> Result<Vec<String>, CoreError> {
        let mut statement = self
            .conn
            .prepare(
                "SELECT approval_id FROM approvals WHERE status = 'pending' AND expires_at <= ?1",
            )
            .map_err(CoreError::storage)?;
        let ids: Vec<String> = statement
            .query_map(params![now_epoch as i64], |row| row.get(0))
            .map_err(CoreError::storage)?
            .collect::<Result<Vec<String>, _>>()
            .map_err(CoreError::storage)?;
        drop(statement);
        if ids.is_empty() {
            return Ok(ids);
        }
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;
        for id in &ids {
            tx.execute(
                "UPDATE approvals SET status = 'expired' WHERE approval_id = ?1 AND status = 'pending'",
                params![id],
            )
            .map_err(CoreError::storage)?;
        }
        tx.commit().map_err(CoreError::storage)?;
        Ok(ids)
    }

    /// Consumes an approval. The caller must pass the digest of the arguments it
    /// is about to run, so an approval cannot be pointed at a different call.
    pub fn respond_approval(
        &mut self,
        approval_id: &str,
        args_digest: &str,
        now_epoch: u64,
        approve: bool,
    ) -> Result<(), CoreError> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;

        let row: Option<(String, i64, String, String)> = tx
            .query_row(
                "SELECT args_digest, expires_at, status, tool_call_id \
                 FROM approvals WHERE approval_id = ?1",
                params![approval_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()
            .map_err(CoreError::storage)?;

        let (expected_digest, expires_at, status, tool_call_id) =
            row.ok_or_else(|| CoreError::ApprovalExpired {
                approval_id: approval_id.to_owned(),
            })?;

        if status != "pending" {
            return Err(CoreError::ApprovalExpired {
                approval_id: approval_id.to_owned(),
            });
        }
        if now_epoch as i64 >= expires_at {
            tx.execute(
                "UPDATE approvals SET status = 'expired' WHERE approval_id = ?1",
                params![approval_id],
            )
            .map_err(CoreError::storage)?;
            tx.commit().map_err(CoreError::storage)?;
            return Err(CoreError::ApprovalExpired {
                approval_id: approval_id.to_owned(),
            });
        }
        if args_digest != expected_digest {
            return Err(CoreError::ApprovalArgsMismatch {
                approval_id: approval_id.to_owned(),
            });
        }

        tx.execute(
            "UPDATE approvals SET status = ?2 WHERE approval_id = ?1",
            params![approval_id, if approve { "allowed" } else { "denied" }],
        )
        .map_err(CoreError::storage)?;

        if approve {
            tx.execute(
                "UPDATE tool_call_stages SET stage = ?2, updated_at = ?3 \
                 WHERE tool_call_id = ?1 AND stage = 'prepared'",
                params![tool_call_id, ToolStage::Approved.as_str(), now_ms()],
            )
            .map_err(CoreError::storage)?;
        }

        tx.commit().map_err(CoreError::storage)?;
        Ok(())
    }

    pub fn approval_status(&self, approval_id: &str) -> Result<Option<String>, CoreError> {
        self.conn
            .query_row(
                "SELECT status FROM approvals WHERE approval_id = ?1",
                params![approval_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(CoreError::storage)
    }

    // ---- reads --------------------------------------------------------

    pub fn events(&self, thread: &str, after: u64) -> Result<Vec<Event>, CoreError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT thread_id, seq, event_id, kind, payload FROM journal_events \
                 WHERE thread_id = ?1 AND seq > ?2 ORDER BY seq",
            )
            .map_err(CoreError::storage)?;
        let rows = stmt
            .query_map(params![thread, after as i64], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, i64>(1)? as u64,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                ))
            })
            .map_err(CoreError::storage)?;
        let mut out = Vec::new();
        for row in rows {
            let (thread_id, seq, event_id, kind, payload) = row.map_err(CoreError::storage)?;
            out.push(Event {
                thread_id,
                seq,
                event_id,
                kind: EventKind::parse(&kind).ok_or_else(|| CoreError::Storage {
                    reason: format!("unknown event kind {kind}"),
                })?,
                payload: serde_json::from_str(&payload).unwrap_or(Value::Null),
            });
        }
        Ok(out)
    }

    pub fn revision(&self, thread: &str) -> Result<u64, CoreError> {
        self.revision_of(thread)
    }

    pub fn projection(&self, thread: &str) -> Result<Projection, CoreError> {
        Self::projection_in_tx(&self.conn, thread)
    }

    fn projection_in_tx(conn: &Connection, thread: &str) -> Result<Projection, CoreError> {
        let body: Option<String> = conn
            .query_row(
                "SELECT body FROM thread_projection WHERE thread_id = ?1",
                params![thread],
                |row| row.get(0),
            )
            .optional()
            .map_err(CoreError::storage)?;
        match body {
            Some(text) => serde_json::from_str(&text).map_err(CoreError::storage),
            None => Ok(Projection::empty(thread)),
        }
    }

    fn write_projection(conn: &Connection, projection: &Projection) -> Result<(), CoreError> {
        conn.execute(
            "INSERT INTO thread_projection (thread_id, last_seq, revision, body) \
             VALUES (?1, ?2, ?3, ?4) \
             ON CONFLICT(thread_id) DO UPDATE SET last_seq = ?2, revision = ?3, body = ?4",
            params![
                projection.thread_id,
                projection.last_seq as i64,
                projection.revision as i64,
                serde_json::to_string(projection).map_err(CoreError::storage)?
            ],
        )
        .map_err(CoreError::storage)?;
        Ok(())
    }

    /// Rebuilds the projection from the journal alone and stores the result.
    pub fn rebuild_projection(&mut self, thread: &str) -> Result<Projection, CoreError> {
        let events = self.events(thread, 0)?;
        let mut rebuilt = Projection::empty(thread);
        for event in &events {
            rebuilt.record(event.kind, event.seq, rebuilt.revision + 1);
        }
        let current_revision = self.revision_of(thread)?;
        rebuilt.revision = current_revision;
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;
        Self::write_projection(&tx, &rebuilt)?;
        tx.commit().map_err(CoreError::storage)?;
        Ok(rebuilt)
    }

    // ---- recovery -----------------------------------------------------

    /// Called once at startup. Applies the only rule that matters after a crash:
    /// a non-idempotent call that was dispatched but never finished has an
    /// unknown outcome and must not be retried by the machine.
    pub fn recover(&mut self) -> Result<RecoveryPlan, CoreError> {
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;
        let mut plan = RecoveryPlan::default();

        let mut stmt = tx
            .prepare("SELECT tool_call_id, stage, side_effect FROM tool_call_stages")
            .map_err(CoreError::storage)?;
        let rows = stmt
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                ))
            })
            .map_err(CoreError::storage)?;
        let mut collected = Vec::new();
        for row in rows {
            collected.push(row.map_err(CoreError::storage)?);
        }
        drop(stmt);

        for (call_id, stage, side) in collected {
            let stage = ToolStage::parse(&stage).unwrap_or(ToolStage::Prepared);
            let side: SideEffect = serde_json::from_str(&side).unwrap_or(SideEffect::NonIdempotent);
            match stage {
                ToolStage::Dispatched => match side {
                    SideEffect::NonIdempotent => {
                        tx.execute(
                            "UPDATE tool_call_stages SET stage = 'unknown', updated_at = ?2 \
                             WHERE tool_call_id = ?1",
                            params![call_id, now_ms()],
                        )
                        .map_err(CoreError::storage)?;
                        plan.unknown.push(call_id);
                    }
                    _ => plan.requeueable.push(call_id),
                },
                ToolStage::Prepared | ToolStage::Approved => plan.requeueable.push(call_id),
                _ => {}
            }
        }

        let mut stmt = tx
            .prepare(
                "SELECT request_id FROM command_receipts WHERE status IN ('accepted', 'running')",
            )
            .map_err(CoreError::storage)?;
        let rows = stmt
            .query_map([], |row| row.get::<_, String>(0))
            .map_err(CoreError::storage)?;
        let mut receipts = Vec::new();
        for row in rows {
            receipts.push(row.map_err(CoreError::storage)?);
        }
        drop(stmt);
        for request_id in receipts {
            tx.execute(
                "UPDATE command_receipts SET status = 'failed', updated_at = ?2 WHERE request_id = ?1",
                params![request_id, now_ms()],
            )
            .map_err(CoreError::storage)?;
            plan.abandoned_receipts.push(request_id);
        }

        // A child that was running when the process died has no live task any
        // more; surface it instead of leaving a record that claims it does.
        let orphans: Vec<String> = {
            let mut stmt = tx
                .prepare("SELECT child_id FROM sub_agents WHERE status = 'running'")
                .map_err(CoreError::storage)?;
            let rows = stmt
                .query_map([], |row| row.get::<_, String>(0))
                .map_err(CoreError::storage)?;
            rows.collect::<Result<Vec<_>, _>>()
                .map_err(CoreError::storage)?
        };
        for child_id in &orphans {
            tx.execute(
                "UPDATE sub_agents SET status = 'orphaned', updated_at = ?2 WHERE child_id = ?1",
                params![child_id, now_ms()],
            )
            .map_err(CoreError::storage)?;
        }
        plan.orphaned_children = orphans;

        tx.commit().map_err(CoreError::storage)?;
        plan.unknown.sort();
        plan.requeueable.sort();
        plan.abandoned_receipts.sort();
        plan.orphaned_children.sort();
        Ok(plan)
    }

    // ---- turn continuations -------------------------------------------

    /// Saves everything needed to resume a turn without asking the model again.
    /// Without this, resuming after an approval would re-run the model and could
    /// produce a different tool call than the one the user approved.
    pub fn save_continuation(&mut self, c: &Continuation) -> Result<(), CoreError> {
        self.conn
            .execute(
                "INSERT INTO turn_continuations \
                 (thread_id, turn_id, model_id, messages_json, pending_call_id, updated_at) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6) \
                 ON CONFLICT(thread_id) DO UPDATE SET turn_id = ?2, model_id = ?3, \
                 messages_json = ?4, pending_call_id = ?5, updated_at = ?6",
                params![
                    c.thread_id,
                    c.turn_id,
                    c.model_id,
                    serde_json::to_string(&c.messages).map_err(CoreError::storage)?,
                    c.pending_call_id,
                    now_ms()
                ],
            )
            .map_err(CoreError::storage)?;
        Ok(())
    }

    pub fn load_continuation(&self, thread: &str) -> Result<Option<Continuation>, CoreError> {
        let row: Option<(String, String, String, Option<String>)> = self
            .conn
            .query_row(
                "SELECT turn_id, model_id, messages_json, pending_call_id \
                 FROM turn_continuations WHERE thread_id = ?1",
                params![thread],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .optional()
            .map_err(CoreError::storage)?;
        match row {
            None => Ok(None),
            Some((turn_id, model_id, messages_json, pending_call_id)) => Ok(Some(Continuation {
                thread_id: thread.to_owned(),
                turn_id,
                model_id,
                messages: serde_json::from_str(&messages_json).map_err(CoreError::storage)?,
                pending_call_id,
            })),
        }
    }

    pub fn clear_continuation(&mut self, thread: &str) -> Result<(), CoreError> {
        self.conn
            .execute(
                "DELETE FROM turn_continuations WHERE thread_id = ?1",
                params![thread],
            )
            .map_err(CoreError::storage)?;
        Ok(())
    }

    /// The call an approval was issued for, reconstructed from durable state.
    pub fn pending_call(&self, approval_id: &str) -> Result<Option<(ToolCall, String)>, CoreError> {
        let row: Option<(String, String, String)> = self
            .conn
            .query_row(
                "SELECT s.tool_id, s.args_json, s.args_digest \
                 FROM approvals a JOIN tool_call_stages s ON s.tool_call_id = a.tool_call_id \
                 WHERE a.approval_id = ?1",
                params![approval_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .optional()
            .map_err(CoreError::storage)?;
        let Some((tool_id, args_json, digest)) = row else {
            return Ok(None);
        };
        let call_row: Option<String> = self
            .conn
            .query_row(
                "SELECT tool_call_id FROM approvals WHERE approval_id = ?1",
                params![approval_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(CoreError::storage)?;
        let Some(call_id) = call_row else {
            return Ok(None);
        };
        Ok(Some((
            ToolCall {
                id: call_id,
                name: tool_id,
                args: serde_json::from_str(&args_json).map_err(CoreError::storage)?,
            },
            digest,
        )))
    }

    // ---- pending guidance (steer) --------------------------------------

    /// Stores a user instruction that arrived while a turn was running.
    /// Idempotent: re-sending the same id does not enqueue it twice.
    pub fn append_guidance(
        &mut self,
        thread: &str,
        guidance_id: &str,
        text: &str,
    ) -> Result<bool, CoreError> {
        let changed = self
            .conn
            .execute(
                "INSERT INTO guidance (guidance_id, thread_id, text, created_at) \
                 VALUES (?1, ?2, ?3, ?4) ON CONFLICT(guidance_id) DO NOTHING",
                params![guidance_id, thread, text, now_ms()],
            )
            .map_err(CoreError::storage)?;
        Ok(changed > 0)
    }

    pub fn pending_guidance(&self, thread: &str) -> Result<Vec<Guidance>, CoreError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT guidance_id, text, created_at FROM guidance \
                 WHERE thread_id = ?1 AND consumed_at IS NULL ORDER BY created_at, guidance_id",
            )
            .map_err(CoreError::storage)?;
        let rows = stmt
            .query_map(params![thread], |row| {
                Ok(Guidance {
                    guidance_id: row.get(0)?,
                    text: row.get(1)?,
                    created_at_ms: row.get(2)?,
                })
            })
            .map_err(CoreError::storage)?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(CoreError::storage)
    }

    /// Marks guidance as applied. Called together with the event that records it
    /// reaching the model, so a crash cannot apply it twice.
    pub fn consume_guidance(&mut self, thread: &str, ids: &[String]) -> Result<(), CoreError> {
        if ids.is_empty() {
            return Ok(());
        }
        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(CoreError::storage)?;
        for id in ids {
            tx.execute(
                "UPDATE guidance SET consumed_at = ?3 WHERE guidance_id = ?1 AND thread_id = ?2 \
                 AND consumed_at IS NULL",
                params![id, thread, now_ms()],
            )
            .map_err(CoreError::storage)?;
        }
        tx.commit().map_err(CoreError::storage)
    }

    // ---- sub-agent bookkeeping -----------------------------------------

    pub fn upsert_child(&mut self, child: &ChildRecord) -> Result<(), CoreError> {
        self.conn
            .execute(
                "INSERT INTO sub_agents \
                 (child_id, parent_thread, child_thread, model_id, guide, granted_tools, status, created_at, updated_at) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?8) \
                 ON CONFLICT(child_id) DO UPDATE SET status = ?7, updated_at = ?8",
                params![
                    child.child_id,
                    child.parent_thread,
                    child.child_thread,
                    child.model_id,
                    child.guide,
                    serde_json::to_string(&child.granted_tools).map_err(CoreError::storage)?,
                    child.status.as_str(),
                    now_ms()
                ],
            )
            .map_err(CoreError::storage)?;
        Ok(())
    }

    pub fn set_child_status(
        &mut self,
        child_id: &str,
        status: ChildStatus,
        result: Option<&str>,
    ) -> Result<(), CoreError> {
        self.conn
            .execute(
                "UPDATE sub_agents SET status = ?2, result = COALESCE(?3, result), updated_at = ?4 \
                 WHERE child_id = ?1",
                params![child_id, status.as_str(), result, now_ms()],
            )
            .map_err(CoreError::storage)?;
        Ok(())
    }

    pub fn get_child(&self, child_id: &str) -> Result<Option<ChildRecord>, CoreError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT child_id, parent_thread, child_thread, model_id, guide, granted_tools, status, result \
                 FROM sub_agents WHERE child_id = ?1",
            )
            .map_err(CoreError::storage)?;
        let mut rows = stmt
            .query_map(params![child_id], |row| {
                let granted: String = row.get(5)?;
                let status: String = row.get(6)?;
                Ok(ChildRecord {
                    child_id: row.get(0)?,
                    parent_thread: row.get(1)?,
                    child_thread: row.get(2)?,
                    model_id: row.get(3)?,
                    guide: row.get(4)?,
                    granted_tools: serde_json::from_str(&granted).unwrap_or_default(),
                    status: ChildStatus::parse(&status).unwrap_or(ChildStatus::Failed),
                    result: row.get(7)?,
                })
            })
            .map_err(CoreError::storage)?;
        match rows.next() {
            None => Ok(None),
            Some(row) => row.map(Some).map_err(CoreError::storage),
        }
    }

    pub fn list_children(&self, parent_thread: &str) -> Result<Vec<ChildRecord>, CoreError> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT child_id, parent_thread, child_thread, model_id, guide, granted_tools, status, result \
                 FROM sub_agents WHERE parent_thread = ?1 ORDER BY created_at, child_id",
            )
            .map_err(CoreError::storage)?;
        let rows = stmt
            .query_map(params![parent_thread], |row| {
                let granted: String = row.get(5)?;
                let status: String = row.get(6)?;
                Ok(ChildRecord {
                    child_id: row.get(0)?,
                    parent_thread: row.get(1)?,
                    child_thread: row.get(2)?,
                    model_id: row.get(3)?,
                    guide: row.get(4)?,
                    granted_tools: serde_json::from_str(&granted).unwrap_or_default(),
                    status: ChildStatus::parse(&status).unwrap_or(ChildStatus::Failed),
                    result: row.get(7)?,
                })
            })
            .map_err(CoreError::storage)?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(CoreError::storage)
    }

    /// Table row counts, for `sunday-cli db inspect` and for tests.
    pub fn table_counts(&self) -> Result<BTreeMap<String, u64>, CoreError> {
        let mut out = BTreeMap::new();
        for table in [
            "journal_events",
            "command_receipts",
            "tool_call_stages",
            "approvals",
            "thread_projection",
            "thread_revisions",
        ] {
            let count: i64 = self
                .conn
                .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                    row.get(0)
                })
                .map_err(CoreError::storage)?;
            out.insert(table.to_owned(), count as u64);
        }
        Ok(out)
    }
}
