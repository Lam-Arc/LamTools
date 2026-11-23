//! Native SQLite read pool, serialized write connection, and revision-validated LRU caches.
//!
//! user:“加载/切换/多会话多 agent 同时读写”+(用 Rust 原生读连接池与单写事务串行化替代 Python 层的连接池与线程切换开销，并扩大缓存容量)。

use rusqlite::{Connection, ErrorCode, OpenFlags};
use serde_json::Value;
use std::collections::{HashMap, VecDeque};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Condvar, Mutex, RwLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use thiserror::Error;

const DEFAULT_READ_POOL_SIZE: usize = 16;
// user:“嗯”+(限制内存缓存条目与字节上限，避免切换几十个大历史会话后后端内存持续攀升)
const DEFAULT_METADATA_CACHE_CAPACITY: usize = 8;
const DEFAULT_METADATA_CACHE_MAX_BYTES: usize = 32 * 1024 * 1024;
const DEFAULT_OUTLINE_CACHE_CAPACITY: usize = 64;
const DEFAULT_SUMMARY_CACHE_CAPACITY: usize = 512;
const BUSY_TIMEOUT_MS: i32 = 5000;
const WAL_AUTOCHECKPOINT_PAGES: i32 = 32768;
const CACHE_SIZE_KB: i32 = -8192;
const MMAP_BYTES: i64 = 256 * 1024 * 1024;
const WRITE_RETRY_MS: [u64; 4] = [20, 50, 150, 350];

#[derive(Debug, Error)]
pub enum DbError {
    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("invalid argument: {0}")]
    Invalid(String),
    #[error("conflict: {0}")]
    Conflict(String),
    #[error("engine closed")]
    Closed,
}

#[derive(Clone, Debug)]
pub struct CachedSummary {
    pub revision: i64,
    pub updated_at: String,
    pub summary: Value,
}

#[derive(Clone, Debug)]
pub struct CachedSnapshotMeta {
    pub revision: i64,
    pub snapshot_seq: i64,
    pub active_turn_id: String,
    pub state: Value,
    pub approx_bytes: usize,
}

// user:“规划并实现”+(内存中保存带 revision/snapshot_seq 校验的会话大纲，消除重复点击或并发打开大纲时的全量重算)
#[derive(Clone, Debug)]
pub struct CachedOutline {
    pub revision: i64,
    pub snapshot_seq: i64,
    pub outline: Value,
}

pub struct EngineCache {
    summaries: HashMap<String, CachedSummary>,
    summaries_lru: VecDeque<String>,
    summary_capacity: usize,
    metadata: HashMap<String, CachedSnapshotMeta>,
    metadata_lru: VecDeque<String>,
    metadata_capacity: usize,
    metadata_bytes: usize,
    metadata_max_bytes: usize,
    outlines: HashMap<(String, i64), CachedOutline>,
    outlines_lru: VecDeque<(String, i64)>,
    outline_capacity: usize,
}

impl EngineCache {
    fn new(metadata_capacity: usize) -> Self {
        Self {
            summaries: HashMap::new(),
            summaries_lru: VecDeque::new(),
            summary_capacity: DEFAULT_SUMMARY_CACHE_CAPACITY,
            metadata: HashMap::new(),
            metadata_lru: VecDeque::new(),
            metadata_capacity: metadata_capacity.max(2),
            metadata_bytes: 0,
            metadata_max_bytes: DEFAULT_METADATA_CACHE_MAX_BYTES,
            outlines: HashMap::new(),
            outlines_lru: VecDeque::new(),
            outline_capacity: DEFAULT_OUTLINE_CACHE_CAPACITY,
        }
    }

    pub fn get_summary(&self, thread_id: &str, revision: i64, updated_at: &str) -> Option<Value> {
        let entry = self.summaries.get(thread_id)?;
        if entry.revision == revision && entry.updated_at == updated_at {
            Some(entry.summary.clone())
        } else {
            None
        }
    }

    pub fn put_summary(&mut self, thread_id: String, revision: i64, updated_at: String, summary: Value) {
        if let Some(pos) = self.summaries_lru.iter().position(|id| id == &thread_id) {
            self.summaries_lru.remove(pos);
        } else {
            while self.summaries.len() >= self.summary_capacity {
                let Some(evicted) = self.summaries_lru.pop_front() else {
                    break;
                };
                self.summaries.remove(&evicted);
            }
        }
        self.summaries_lru.push_back(thread_id.clone());
        self.summaries.insert(
            thread_id,
            CachedSummary {
                revision,
                updated_at,
                summary,
            },
        );
    }

    pub fn get_metadata(&mut self, thread_id: &str, revision: i64, snapshot_seq: i64) -> Option<CachedSnapshotMeta> {
        let entry = self.metadata.get(thread_id)?.clone();
        if entry.revision == revision && entry.snapshot_seq == snapshot_seq {
            if let Some(pos) = self.metadata_lru.iter().position(|id| id == thread_id) {
                self.metadata_lru.remove(pos);
            }
            self.metadata_lru.push_back(thread_id.to_string());
            Some(entry)
        } else {
            None
        }
    }

    fn evict_metadata_key(&mut self, key: &str) {
        if let Some(old) = self.metadata.remove(key) {
            self.metadata_bytes = self.metadata_bytes.saturating_sub(old.approx_bytes);
        }
    }

    pub fn put_metadata(
        &mut self,
        thread_id: String,
        revision: i64,
        snapshot_seq: i64,
        active_turn_id: String,
        state: Value,
    ) {
        self.put_metadata_sized(thread_id, revision, snapshot_seq, active_turn_id, state, 0);
    }

    pub fn put_metadata_sized(
        &mut self,
        thread_id: String,
        revision: i64,
        snapshot_seq: i64,
        active_turn_id: String,
        state: Value,
        approx_bytes: usize,
    ) {
        if let Some(pos) = self.metadata_lru.iter().position(|id| id == &thread_id) {
            self.metadata_lru.remove(pos);
        }
        self.evict_metadata_key(&thread_id);

        while self.metadata.len() >= self.metadata_capacity
            || (self.metadata.len() >= 2
                && self.metadata_bytes.saturating_add(approx_bytes) > self.metadata_max_bytes)
        {
            let Some(evicted) = self.metadata_lru.pop_front() else {
                break;
            };
            self.evict_metadata_key(&evicted);
        }

        self.metadata_bytes = self.metadata_bytes.saturating_add(approx_bytes);
        self.metadata_lru.push_back(thread_id.clone());
        self.metadata.insert(
            thread_id,
            CachedSnapshotMeta {
                revision,
                snapshot_seq,
                active_turn_id,
                state,
                approx_bytes,
            },
        );
    }

    pub fn get_outline(&self, thread_id: &str, char_limit: i64, revision: i64, snapshot_seq: i64) -> Option<Value> {
        let key = (thread_id.to_string(), char_limit);
        let entry = self.outlines.get(&key)?;
        if entry.revision == revision && entry.snapshot_seq == snapshot_seq {
            Some(entry.outline.clone())
        } else {
            None
        }
    }

    pub fn put_outline(&mut self, thread_id: String, char_limit: i64, revision: i64, snapshot_seq: i64, outline: Value) {
        let key = (thread_id, char_limit);
        if let Some(pos) = self.outlines_lru.iter().position(|k| k == &key) {
            self.outlines_lru.remove(pos);
        } else {
            while self.outlines.len() >= self.outline_capacity {
                let Some(evicted) = self.outlines_lru.pop_front() else {
                    break;
                };
                self.outlines.remove(&evicted);
            }
        }
        self.outlines_lru.push_back(key.clone());
        self.outlines.insert(
            key,
            CachedOutline {
                revision,
                snapshot_seq,
                outline,
            },
        );
    }

    pub fn invalidate_thread(&mut self, thread_id: Option<&str>) {
        match thread_id {
            Some(tid) => {
                self.summaries.remove(tid);
                self.summaries_lru.retain(|id| id != tid);
                self.evict_metadata_key(tid);
                if let Some(pos) = self.metadata_lru.iter().position(|id| id == tid) {
                    self.metadata_lru.remove(pos);
                }
                self.outlines.retain(|(k_tid, _), _| k_tid != tid);
                self.outlines_lru.retain(|(k_tid, _)| k_tid != tid);
            }
            None => {
                self.summaries.clear();
                self.summaries_lru.clear();
                self.metadata.clear();
                self.metadata_lru.clear();
                self.metadata_bytes = 0;
                self.outlines.clear();
                self.outlines_lru.clear();
            }
        }
    }
}

struct ReadPoolState {
    idle: Vec<Connection>,
    total_created: usize,
    closed: bool,
}

pub struct ReadPool {
    db_path: PathBuf,
    max_size: usize,
    state: Mutex<ReadPoolState>,
    available: Condvar,
}

impl ReadPool {
    fn new(db_path: PathBuf, max_size: usize) -> Self {
        Self {
            db_path,
            max_size: max_size.max(1),
            state: Mutex::new(ReadPoolState {
                idle: Vec::with_capacity(max_size.min(16)),
                total_created: 0,
                closed: false,
            }),
            available: Condvar::new(),
        }
    }

    fn open_read_conn(db_path: &Path) -> Result<Connection, DbError> {
        let flags = OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX;
        let conn = Connection::open_with_flags(db_path, flags)?;
        let _ = conn.execute_batch(&format!(
            "PRAGMA busy_timeout={BUSY_TIMEOUT_MS};\
             PRAGMA cache_size={CACHE_SIZE_KB};\
             PRAGMA temp_store=MEMORY;\
             PRAGMA mmap_size={MMAP_BYTES};\
             PRAGMA query_only=ON;"
        ));
        Ok(conn)
    }

    pub fn checkout(&self) -> Result<ReadGuard<'_>, DbError> {
        let mut guard = self.state.lock().unwrap_or_else(|e| e.into_inner());
        loop {
            if guard.closed {
                return Err(DbError::Closed);
            }
            if let Some(conn) = guard.idle.pop() {
                return Ok(ReadGuard {
                    pool: self,
                    conn: Some(conn),
                });
            }
            if guard.total_created < self.max_size {
                guard.total_created += 1;
                drop(guard);
                match Self::open_read_conn(&self.db_path) {
                    Ok(conn) => {
                        return Ok(ReadGuard {
                            pool: self,
                            conn: Some(conn),
                        });
                    }
                    Err(err) => {
                        let mut g = self.state.lock().unwrap_or_else(|e| e.into_inner());
                        g.total_created = g.total_created.saturating_sub(1);
                        self.available.notify_one();
                        return Err(err);
                    }
                }
            }
            guard = self.available.wait(guard).unwrap_or_else(|e| e.into_inner());
        }
    }

    fn checkin(&self, conn: Connection) {
        let mut guard = self.state.lock().unwrap_or_else(|e| e.into_inner());
        if guard.closed {
            drop(conn);
        } else {
            guard.idle.push(conn);
            self.available.notify_one();
        }
    }

    pub fn close(&self) {
        let mut guard = self.state.lock().unwrap_or_else(|e| e.into_inner());
        guard.closed = true;
        guard.idle.clear();
        self.available.notify_all();
    }
}

pub struct ReadGuard<'a> {
    pool: &'a ReadPool,
    conn: Option<Connection>,
}

impl<'a> std::ops::Deref for ReadGuard<'a> {
    type Target = Connection;
    fn deref(&self) -> &Self::Target {
        self.conn.as_ref().expect("connection active")
    }
}

impl<'a> Drop for ReadGuard<'a> {
    fn drop(&mut self) {
        if let Some(conn) = self.conn.take() {
            self.pool.checkin(conn);
        }
    }
}

#[derive(Default)]
pub struct EngineStats {
    pub summary_cache_hits: AtomicU64,
    pub summary_cache_misses: AtomicU64,
    pub snapshot_cache_hits: AtomicU64,
    pub snapshot_cache_misses: AtomicU64,
    pub read_queries: AtomicU64,
    pub write_txs: AtomicU64,
}

pub struct DbEngine {
    pub db_path: PathBuf,
    read_pool: ReadPool,
    write_conn: Mutex<Option<Connection>>,
    pub cache: RwLock<EngineCache>,
    pub stats: EngineStats,
    pub sub_agents_ready: AtomicBool,
}

static ID_COUNTER: AtomicU64 = AtomicU64::new(1);

pub(crate) fn next_hex_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos() as u64;
    let seq = ID_COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("{:016x}{:016x}", nanos ^ seq.rotate_left(17), seq)
}

pub(crate) fn now_unix_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

impl DbEngine {
    pub fn open(db_path: impl AsRef<Path>) -> Result<Self, DbError> {
        let path = db_path.as_ref().to_path_buf();
        let flags = OpenFlags::SQLITE_OPEN_READ_WRITE
            | OpenFlags::SQLITE_OPEN_CREATE
            | OpenFlags::SQLITE_OPEN_NO_MUTEX;
        let conn = Connection::open_with_flags(&path, flags)?;
        let _ = conn.execute_batch(&format!(
            "PRAGMA busy_timeout={BUSY_TIMEOUT_MS};\
             PRAGMA journal_mode=WAL;\
             PRAGMA synchronous=NORMAL;\
             PRAGMA wal_autocheckpoint={WAL_AUTOCHECKPOINT_PAGES};\
             PRAGMA cache_size={CACHE_SIZE_KB};\
             PRAGMA temp_store=MEMORY;\
             PRAGMA mmap_size={MMAP_BYTES};"
        ));
        ensure_hotpath_schema(&conn)?;
        Ok(Self {
            db_path: path.clone(),
            read_pool: ReadPool::new(path, DEFAULT_READ_POOL_SIZE),
            write_conn: Mutex::new(Some(conn)),
            cache: RwLock::new(EngineCache::new(DEFAULT_METADATA_CACHE_CAPACITY)),
            stats: EngineStats::default(),
            sub_agents_ready: AtomicBool::new(false),
        })
    }

    /// Best-effort non-blocking write transaction for opportunistic read-side cache persistence
    /// so concurrent read RPCs never stall behind an active writer.
    pub(crate) fn try_write_tx<T>(
        &self,
        mut f: impl FnMut(&Connection) -> Result<T, DbError>,
    ) -> Option<T> {
        let Ok(mut guard) = self.write_conn.try_lock() else {
            return None;
        };
        let conn = guard.as_mut()?;
        if conn.execute_batch("BEGIN IMMEDIATE").is_err() {
            return None;
        }
        match f(conn) {
            Ok(val) => {
                if conn.execute_batch("COMMIT").is_ok() {
                    Some(val)
                } else {
                    let _ = conn.execute_batch("ROLLBACK");
                    None
                }
            }
            Err(_) => {
                let _ = conn.execute_batch("ROLLBACK");
                None
            }
        }
    }

    pub fn read<T>(&self, f: impl FnOnce(&Connection) -> Result<T, DbError>) -> Result<T, DbError> {
        self.stats.read_queries.fetch_add(1, Ordering::Relaxed);
        let guard = self.read_pool.checkout()?;
        f(&guard)
    }

    pub fn write_tx<T>(
        &self,
        mut f: impl FnMut(&Connection) -> Result<T, DbError>,
    ) -> Result<T, DbError> {
        self.stats.write_txs.fetch_add(1, Ordering::Relaxed);
        let mut guard = self.write_conn.lock().unwrap_or_else(|e| e.into_inner());
        let conn = guard.as_mut().ok_or(DbError::Closed)?;

        for attempt in 0..=WRITE_RETRY_MS.len() {
            match conn.execute_batch("BEGIN IMMEDIATE") {
                Ok(()) => {
                    let result = f(conn);
                    match result {
                        Ok(val) => {
                            if let Err(err) = conn.execute_batch("COMMIT") {
                                let _ = conn.execute_batch("ROLLBACK");
                                if is_busy_err(&err) && attempt < WRITE_RETRY_MS.len() {
                                    std::thread::sleep(Duration::from_millis(WRITE_RETRY_MS[attempt]));
                                    continue;
                                }
                                return Err(DbError::Sqlite(err));
                            }
                            return Ok(val);
                        }
                        Err(err) => {
                            let _ = conn.execute_batch("ROLLBACK");
                            if let DbError::Sqlite(ref sq_err) = err {
                                if is_busy_err(sq_err) && attempt < WRITE_RETRY_MS.len() {
                                    std::thread::sleep(Duration::from_millis(WRITE_RETRY_MS[attempt]));
                                    continue;
                                }
                            }
                            return Err(err);
                        }
                    }
                }
                Err(err) => {
                    if is_busy_err(&err) && attempt < WRITE_RETRY_MS.len() {
                        std::thread::sleep(Duration::from_millis(WRITE_RETRY_MS[attempt]));
                        continue;
                    }
                    return Err(DbError::Sqlite(err));
                }
            }
        }
        Err(DbError::Invalid("write retry exhausted".into()))
    }

    pub fn invalidate_thread(&self, thread_id: Option<&str>) {
        if let Ok(mut cache) = self.cache.write() {
            cache.invalidate_thread(thread_id);
        }
    }

    pub fn close(&self) {
        self.read_pool.close();
        if let Ok(mut guard) = self.write_conn.lock() {
            guard.take();
        }
        self.invalidate_thread(None);
    }

    pub fn stats_json(&self) -> Value {
        let (meta_len, meta_bytes, outline_len, summary_len) = match self.cache.read() {
            Ok(c) => (c.metadata.len(), c.metadata_bytes, c.outlines.len(), c.summaries.len()),
            Err(e) => {
                let c = e.into_inner();
                (c.metadata.len(), c.metadata_bytes, c.outlines.len(), c.summaries.len())
            }
        };
        serde_json::json!({
            "summary_cache_hits": self.stats.summary_cache_hits.load(Ordering::Relaxed),
            "summary_cache_misses": self.stats.summary_cache_misses.load(Ordering::Relaxed),
            "snapshot_cache_hits": self.stats.snapshot_cache_hits.load(Ordering::Relaxed),
            "snapshot_cache_misses": self.stats.snapshot_cache_misses.load(Ordering::Relaxed),
            "read_queries": self.stats.read_queries.load(Ordering::Relaxed),
            "write_txs": self.stats.write_txs.load(Ordering::Relaxed),
            "metadata_cache_entries": meta_len,
            "metadata_cache_bytes": meta_bytes,
            "outline_cache_entries": outline_len,
            "summary_cache_entries": summary_len,
        })
    }
}

fn is_busy_err(err: &rusqlite::Error) -> bool {
    matches!(
        err.sqlite_error_code(),
        Some(ErrorCode::DatabaseBusy) | Some(ErrorCode::DatabaseLocked)
    )
}

fn ensure_hotpath_schema(conn: &Connection) -> Result<(), DbError> {
    let has_items_table: bool = conn
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='core_thread_snapshot_items'",
            [],
            |_| Ok(true),
        )
        .unwrap_or(false);
    if has_items_table {
        let mut has_item_type = false;
        let mut stmt = conn.prepare("PRAGMA table_info(core_thread_snapshot_items)")?;
        let mut rows = stmt.query([])?;
        while let Some(row) = rows.next()? {
            let name: String = row.get(1)?;
            if name == "item_type" {
                has_item_type = true;
                break;
            }
        }
        drop(rows);
        drop(stmt);
        if !has_item_type {
            conn.execute_batch("ALTER TABLE core_thread_snapshot_items ADD COLUMN item_type TEXT")?;
        }
        conn.execute_batch(
            "CREATE INDEX IF NOT EXISTS idx_core_snapshot_items_thread_type_seq \
             ON core_thread_snapshot_items (thread_id, item_type, seq)",
        )?;
    }
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS core_thread_outlines (
            thread_id TEXT NOT NULL,
            char_limit INTEGER NOT NULL,
            revision INTEGER NOT NULL,
            snapshot_seq INTEGER NOT NULL,
            outline_json TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (thread_id, char_limit)
        );
        CREATE TABLE IF NOT EXISTS core_thread_snapshot_artifacts (
            thread_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            artifact_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (thread_id, artifact_id)
        );
        CREATE TABLE IF NOT EXISTS core_thread_snapshot_turns (
            thread_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            seq INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT '',
            core_turn_json TEXT,
            app_turn_json TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (thread_id, turn_id)
        );
        CREATE INDEX IF NOT EXISTS idx_core_snapshot_turns_status
            ON core_thread_snapshot_turns (thread_id, status);"
    )?;
    let has_events_table: bool = conn
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='core_app_events'",
            [],
            |_| Ok(true),
        )
        .unwrap_or(false);
    if has_events_table {
        // user:“继续”+(为 (thread_id, item_id, seq) 建部分索引，支持快照条目精简引用后的极速批量回填)
        conn.execute_batch(
            "CREATE INDEX IF NOT EXISTS idx_core_events_thread_item_seq \
             ON core_app_events (thread_id, item_id, seq) WHERE item_id IS NOT NULL",
        )?;
    }
    Ok(())
}
