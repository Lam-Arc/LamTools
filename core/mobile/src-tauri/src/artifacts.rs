//! Artifact store for the mobile host.
//!
//! The desktop derives artifacts from session events and keeps the facts in
//! `core_artifacts` / `core_artifact_revisions` with blobs on disk. The phone has
//! no event projector, so a revision is recorded at the moment the agent writes
//! a project file (the host observes every tool call), which is the same fact:
//! this file, written by this tool, in this turn, at this point in time.
//!
//! Revisions are immutable: the bytes are stored once under their hash, and
//! restoring a revision writes those bytes back and records a new revision that
//! says where it came from. The artifact id is derived from the project and the
//! path, so repeated writes to one file update one artifact instead of creating
//! a new one per write.
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

/// One artifact as the panels read it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArtifactRecord {
    pub artifact_id: String,
    pub project_id: String,
    pub name: String,
    pub path: String,
    pub mime_type: String,
    pub source: String,
    pub role: String,
    pub latest_revision_id: String,
    pub revision_count: i64,
    pub thread_id: String,
    pub turn_id: String,
    pub item_id: String,
    pub tool_name: String,
    pub deleted: bool,
    pub created_at: String,
    pub updated_at: String,
}

/// One immutable revision of an artifact.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ArtifactRevision {
    pub revision_id: String,
    pub artifact_id: String,
    pub ordinal: i64,
    pub blob_hash: String,
    pub size: i64,
    pub mime_type: String,
    pub thread_id: String,
    pub turn_id: String,
    pub item_id: String,
    pub tool_name: String,
    pub restored_from_revision_id: String,
    pub created_at: String,
}

/// Where one write came from. The desktop fills the same fields from events.
#[derive(Clone, Debug, Default)]
pub struct ArtifactOrigin {
    pub thread_id: String,
    pub turn_id: String,
    pub item_id: String,
    pub tool_name: String,
}

pub struct ArtifactStore {
    connection: Connection,
    blob_root: PathBuf,
}

impl ArtifactStore {
    /// Open (and migrate) the store. `blob_root` is created on demand.
    pub fn open(database: &Path, blob_root: &Path) -> Result<Self, String> {
        if let Some(parent) = database.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let connection = Connection::open(database).map_err(|error| error.to_string())?;
        let store = Self {
            connection,
            blob_root: blob_root.to_path_buf(),
        };
        store.migrate()?;
        Ok(store)
    }

    #[cfg(test)]
    fn open_in_memory(blob_root: &Path) -> Result<Self, String> {
        let store = Self {
            connection: Connection::open_in_memory().map_err(|error| error.to_string())?,
            blob_root: blob_root.to_path_buf(),
        };
        store.migrate()?;
        Ok(store)
    }

    fn migrate(&self) -> Result<(), String> {
        self.connection
            .execute_batch(
                "create table if not exists artifacts (
                    artifact_id text primary key,
                    project_id text not null,
                    name text not null default '',
                    path text not null,
                    mime_type text not null default '',
                    source text not null default 'agent_generated',
                    role text not null default 'deliverable',
                    latest_revision_id text not null default '',
                    revision_count integer not null default 0,
                    thread_id text not null default '',
                    turn_id text not null default '',
                    item_id text not null default '',
                    tool_name text not null default '',
                    deleted integer not null default 0,
                    created_at text not null,
                    updated_at text not null
                );
                create index if not exists idx_artifacts_project on artifacts(project_id, deleted);
                create table if not exists artifact_revisions (
                    revision_id text primary key,
                    artifact_id text not null,
                    ordinal integer not null,
                    blob_hash text not null,
                    size integer not null default 0,
                    mime_type text not null default '',
                    project_id text not null default '',
                    thread_id text not null default '',
                    turn_id text not null default '',
                    item_id text not null default '',
                    tool_name text not null default '',
                    restored_from_revision_id text not null default '',
                    created_at text not null
                );
                create index if not exists idx_artifact_revisions on artifact_revisions(artifact_id, ordinal);",
            )
            .map_err(|error| error.to_string())
    }

    /// Record the current bytes of one project file as a new revision.
    ///
    /// Returns `None` when the path is not a readable file inside the project —
    /// a failed write must not create an empty artifact.
    pub fn record_file(
        &self,
        project_id: &str,
        project_root: &Path,
        relative_path: &str,
        origin: ArtifactOrigin,
    ) -> Result<Option<ArtifactRecord>, String> {
        let runtime_path = format!("workspace://{relative_path}");
        let absolute = project_root.join(relative_path);
        let bytes = match std::fs::read(&absolute) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.to_string()),
        };
        let artifact_id = artifact_id_for(project_id, &runtime_path);
        let blob_hash = sha256_hex(&bytes);
        let mime_type = mime_for(&relative_path);
        let now = now_iso();

        if let Some(existing) = self.artifact(&artifact_id)? {
            // An unchanged write is not a new revision; the desktop's projector
            // collapses those too, or every no-op edit would add history.
            if existing_latest_hash(self, &existing)?.as_deref() == Some(blob_hash.as_str()) {
                return Ok(Some(existing));
            }
        } else {
            self.connection
                .execute(
                    "insert into artifacts (artifact_id, project_id, name, path, mime_type, source, role,
                        revision_count, thread_id, turn_id, item_id, tool_name, created_at, updated_at)
                     values (?1, ?2, ?3, ?4, ?5, 'agent_generated', 'deliverable', 0, ?6, ?7, ?8, ?9, ?10, ?10)",
                    params![
                        artifact_id,
                        project_id,
                        file_name(&runtime_path),
                        runtime_path,
                        mime_type,
                        origin.thread_id,
                        origin.turn_id,
                        origin.item_id,
                        origin.tool_name,
                        now,
                    ],
                )
                .map_err(|error| error.to_string())?;
        }
        self.store_blob(&blob_hash, &bytes)?;
        let ordinal = self
            .connection
            .query_row(
                "select coalesce(max(ordinal), 0) + 1 from artifact_revisions where artifact_id = ?1",
                params![artifact_id],
                |row| row.get::<_, i64>(0),
            )
            .map_err(|error| error.to_string())?;
        let revision_id = format!(
            "rev-{}",
            short_hash(&format!("{artifact_id}:{ordinal}:{blob_hash}"))
        );
        self.connection
            .execute(
                "insert into artifact_revisions (revision_id, artifact_id, ordinal, blob_hash, size, mime_type,
                    project_id, thread_id, turn_id, item_id, tool_name, created_at)
                 values (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
                params![
                    revision_id,
                    artifact_id,
                    ordinal,
                    blob_hash,
                    bytes.len() as i64,
                    mime_type,
                    project_id,
                    origin.thread_id,
                    origin.turn_id,
                    origin.item_id,
                    origin.tool_name,
                    now,
                ],
            )
            .map_err(|error| error.to_string())?;
        self.connection
            .execute(
                "update artifacts set latest_revision_id = ?2, revision_count = ?3, mime_type = ?4,
                    thread_id = case when ?5 = '' then thread_id else ?5 end,
                    turn_id = case when ?6 = '' then turn_id else ?6 end,
                    item_id = case when ?7 = '' then item_id else ?7 end,
                    tool_name = case when ?8 = '' then tool_name else ?8 end,
                    updated_at = ?9
                 where artifact_id = ?1",
                params![
                    artifact_id,
                    revision_id,
                    ordinal,
                    mime_type,
                    origin.thread_id,
                    origin.turn_id,
                    origin.item_id,
                    origin.tool_name,
                    now,
                ],
            )
            .map_err(|error| error.to_string())?;
        self.artifact(&artifact_id)
    }

    pub fn list(&self, project_id: &str, include_deleted: bool) -> Result<Vec<ArtifactRecord>, String> {
        let mut statement = self
            .connection
            .prepare(
                "select artifact_id, project_id, name, path, mime_type, source, role, latest_revision_id,
                        revision_count, thread_id, turn_id, item_id, tool_name, deleted, created_at, updated_at
                 from artifacts
                 where project_id = ?1 and (?2 = 1 or deleted = 0)
                 order by created_at desc, artifact_id",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(params![project_id, include_deleted as i64], read_artifact_row)
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    pub fn artifact(&self, artifact_id: &str) -> Result<Option<ArtifactRecord>, String> {
        self.connection
            .query_row(
                "select artifact_id, project_id, name, path, mime_type, source, role, latest_revision_id,
                        revision_count, thread_id, turn_id, item_id, tool_name, deleted, created_at, updated_at
                 from artifacts where artifact_id = ?1",
                params![artifact_id],
                read_artifact_row,
            )
            .optional()
            .map_err(|error| error.to_string())
    }

    pub fn revisions(&self, artifact_id: &str) -> Result<Vec<ArtifactRevision>, String> {
        let mut statement = self
            .connection
            .prepare(
                "select revision_id, artifact_id, ordinal, blob_hash, size, mime_type, thread_id, turn_id,
                        item_id, tool_name, restored_from_revision_id, created_at
                 from artifact_revisions where artifact_id = ?1 order by ordinal desc",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(params![artifact_id], |row| {
                Ok(ArtifactRevision {
                    revision_id: row.get(0)?,
                    artifact_id: row.get(1)?,
                    ordinal: row.get(2)?,
                    blob_hash: row.get(3)?,
                    size: row.get(4)?,
                    mime_type: row.get(5)?,
                    thread_id: row.get(6)?,
                    turn_id: row.get(7)?,
                    item_id: row.get(8)?,
                    tool_name: row.get(9)?,
                    restored_from_revision_id: row.get(10)?,
                    created_at: row.get(11)?,
                })
            })
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    /// Soft-delete (or un-delete) artifacts of one project; returns how many
    /// rows changed, like the desktop's `soft_remove`.
    pub fn set_deleted(&self, project_id: &str, ids: &[String], deleted: bool) -> Result<usize, String> {
        let now = now_iso();
        let mut changed = 0;
        for id in ids {
            changed += self
                .connection
                .execute(
                    "update artifacts set deleted = ?3, updated_at = ?4 where artifact_id = ?1 and project_id = ?2",
                    params![id, project_id, deleted as i64, now],
                )
                .map_err(|error| error.to_string())?;
        }
        Ok(changed)
    }

    /// Write an older revision's bytes back and record that as a new revision.
    pub fn restore_revision(
        &self,
        project_id: &str,
        project_root: &Path,
        artifact_id: &str,
        revision_id: &str,
    ) -> Result<ArtifactRecord, String> {
        let artifact = self
            .artifact(artifact_id)?
            .filter(|record| record.project_id == project_id)
            .ok_or_else(|| format!("工件 '{artifact_id}' 不存在"))?;
        let revision = self
            .revisions(artifact_id)?
            .into_iter()
            .find(|revision| revision.revision_id == revision_id)
            .ok_or_else(|| format!("版本 '{revision_id}' 不存在"))?;
        let bytes = self.read_blob(&revision.blob_hash)?;
        let relative = artifact
            .path
            .strip_prefix("workspace://")
            .ok_or_else(|| format!("工件 '{artifact_id}' 不是工作区文件，无法回滚"))?;
        if relative != artifact.path && relative.contains("..") {
            return Err("工件路径越界".into());
        }
        let absolute = project_root.join(relative);
        if let Some(parent) = absolute.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        std::fs::write(&absolute, &bytes).map_err(|error| error.to_string())?;

        let blob_hash = sha256_hex(&bytes);
        let ordinal = self
            .connection
            .query_row(
                "select coalesce(max(ordinal), 0) + 1 from artifact_revisions where artifact_id = ?1",
                params![artifact_id],
                |row| row.get::<_, i64>(0),
            )
            .map_err(|error| error.to_string())?;
        let now = now_iso();
        let new_revision_id = format!(
            "rev-{}",
            short_hash(&format!("{artifact_id}:{ordinal}:{blob_hash}:restored"))
        );
        self.store_blob(&blob_hash, &bytes)?;
        self.connection
            .execute(
                "insert into artifact_revisions (revision_id, artifact_id, ordinal, blob_hash, size, mime_type,
                    project_id, restored_from_revision_id, created_at)
                 values (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
                params![
                    new_revision_id,
                    artifact_id,
                    ordinal,
                    blob_hash,
                    bytes.len() as i64,
                    artifact.mime_type,
                    project_id,
                    revision_id,
                    now,
                ],
            )
            .map_err(|error| error.to_string())?;
        self.connection
            .execute(
                "update artifacts set latest_revision_id = ?2, revision_count = ?3, updated_at = ?4
                 where artifact_id = ?1",
                params![artifact_id, new_revision_id, ordinal, now],
            )
            .map_err(|error| error.to_string())?;
        self.artifact(artifact_id)?
            .ok_or_else(|| "工件在回滚后消失".to_owned())
    }

    /// Bytes of one revision (or of the latest one), with the artifact's MIME
    /// type. This is what the file route serves.
    pub fn revision_bytes(
        &self,
        artifact: &ArtifactRecord,
        revision_id: Option<&str>,
    ) -> Result<(Vec<u8>, String), String> {
        let wanted = revision_id.unwrap_or(artifact.latest_revision_id.as_str());
        let revision = self
            .revisions(&artifact.artifact_id)?
            .into_iter()
            .find(|revision| revision.revision_id == wanted)
            .ok_or_else(|| format!("版本 '{wanted}' 不存在"))?;
        let mime = if revision.mime_type.is_empty() {
            artifact.mime_type.clone()
        } else {
            revision.mime_type.clone()
        };
        Ok((self.read_blob(&revision.blob_hash)?, mime))
    }

    fn store_blob(&self, hash: &str, bytes: &[u8]) -> Result<(), String> {
        std::fs::create_dir_all(&self.blob_root).map_err(|error| error.to_string())?;
        let target = self.blob_root.join(hash);
        if target.is_file() {
            return Ok(());
        }
        let temporary = self.blob_root.join(format!("{hash}.tmp"));
        std::fs::write(&temporary, bytes).map_err(|error| error.to_string())?;
        std::fs::rename(&temporary, &target).map_err(|error| error.to_string())
    }

    fn read_blob(&self, hash: &str) -> Result<Vec<u8>, String> {
        std::fs::read(self.blob_root.join(hash)).map_err(|error| format!("读取版本内容失败: {error}"))
    }
}

fn existing_latest_hash(
    store: &ArtifactStore,
    artifact: &ArtifactRecord,
) -> Result<Option<String>, String> {
    if artifact.latest_revision_id.is_empty() {
        return Ok(None);
    }
    Ok(store
        .revisions(&artifact.artifact_id)?
        .into_iter()
        .find(|revision| revision.revision_id == artifact.latest_revision_id)
        .map(|revision| revision.blob_hash))
}

fn read_artifact_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<ArtifactRecord> {
    Ok(ArtifactRecord {
        artifact_id: row.get(0)?,
        project_id: row.get(1)?,
        name: row.get(2)?,
        path: row.get(3)?,
        mime_type: row.get(4)?,
        source: row.get(5)?,
        role: row.get(6)?,
        latest_revision_id: row.get(7)?,
        revision_count: row.get(8)?,
        thread_id: row.get(9)?,
        turn_id: row.get(10)?,
        item_id: row.get(11)?,
        tool_name: row.get(12)?,
        deleted: row.get::<_, i64>(13)? != 0,
        created_at: row.get(14)?,
        updated_at: row.get(15)?,
    })
}

/// Artifact ids are derived from project and path so a rewrite updates one
/// artifact; the desktop derives theirs from the path for the same reason.
fn artifact_id_for(project_id: &str, path: &str) -> String {
    format!("artifact-{}", short_hash(&format!("{project_id}\n{path}")))
}

fn short_hash(value: &str) -> String {
    sha256_hex(value.as_bytes())[..16].to_owned()
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    // A tiny SHA-256 so the host does not need a crypto dependency for hashing
    // file bytes; the desktop hashes blobs the same way (content address).
    let digest = sha256(bytes);
    let mut out = String::with_capacity(64);
    for byte in digest {
        let _ = write!(out, "{byte:02x}");
    }
    out
}

fn file_name(path: &str) -> String {
    path.rsplit('/').next().unwrap_or(path).to_owned()
}

fn mime_for(path: &str) -> String {
    let extension = Path::new(path)
        .extension()
        .map(|value| value.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    match extension.as_str() {
        "md" => "text/markdown",
        "txt" | "log" => "text/plain",
        "json" | "jsonc" => "application/json",
        "csv" => "text/csv",
        "html" | "htm" => "text/html",
        "css" => "text/css",
        "js" | "mjs" | "cjs" => "text/javascript",
        "ts" | "tsx" | "vue" => "text/plain",
        "yaml" | "yml" => "application/yaml",
        "toml" => "application/toml",
        "py" => "text/x-python",
        "rs" => "text/x-rust",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "svg" => "image/svg+xml",
        "pdf" => "application/pdf",
        "mp4" => "video/mp4",
        "webm" => "video/webm",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        _ => "application/octet-stream",
    }
    .to_owned()
}

fn now_iso() -> String {
    // Seconds-since-epoch is enough for ordering and reads as an ISO string the
    // panels already parse.
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_secs())
        .unwrap_or_default();
    iso_from_seconds(seconds)
}

fn iso_from_seconds(seconds: u64) -> String {
    // Civil date from days since the epoch (Howard Hinnant's algorithm), so the
    // host needs no date crate for one field.
    let days = (seconds / 86_400) as i64;
    let time = seconds % 86_400;
    let (hour, minute, second) = (time / 3600, (time % 3600) / 60, time % 60);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { year + 1 } else { year };
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

/// SHA-256 implementation (FIPS 180-4), so artifact blobs are content-addressed
/// without pulling a crypto crate into the mobile host.
fn sha256(input: &[u8]) -> [u8; 32] {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];
    let mut message = input.to_vec();
    let bit_len = (input.len() as u64) * 8;
    message.push(0x80);
    while message.len() % 64 != 56 {
        message.push(0);
    }
    message.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in message.chunks(64) {
        let mut w = [0u32; 64];
        for (index, word) in chunk.chunks(4).enumerate() {
            w[index] = u32::from_be_bytes([word[0], word[1], word[2], word[3]]);
        }
        for index in 16..64 {
            let s0 = w[index - 15].rotate_right(7) ^ w[index - 15].rotate_right(18) ^ (w[index - 15] >> 3);
            let s1 = w[index - 2].rotate_right(17) ^ w[index - 2].rotate_right(19) ^ (w[index - 2] >> 10);
            w[index] = w[index - 16]
                .wrapping_add(s0)
                .wrapping_add(w[index - 7])
                .wrapping_add(s1);
        }
        let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
            (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
        for index in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[index])
                .wrapping_add(w[index]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }
    let mut digest = [0u8; 32];
    for (index, word) in h.iter().enumerate() {
        digest[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    digest
}

/// The snapshot projection the message views read: artifacts grouped by the
/// item that produced them.
pub fn snapshot_map(records: &[ArtifactRecord]) -> Value {
    let mut map = serde_json::Map::new();
    for record in records {
        map.insert(
            record.artifact_id.clone(),
            serde_json::to_value(record).unwrap_or(Value::Null),
        );
    }
    Value::Object(map)
}

/// Kept so callers can build an empty payload without depending on json!.
pub fn empty_artifacts() -> Value {
    json!({})
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn fixture() -> (tempdir::TempPath, ArtifactStore, PathBuf) {
        let root = tempdir::new("sunday-artifacts");
        let project = root.join("project");
        fs::create_dir_all(&project).unwrap();
        let store = ArtifactStore::open_in_memory(&root.join("blobs")).unwrap();
        (root, store, project)
    }

    /// A minimal temp directory so the host needs no dev-dependency for tests.
    mod tempdir {
        use std::path::{Path, PathBuf};

        pub struct TempPath {
            pub path: PathBuf,
        }

        impl TempPath {
            pub fn join(&self, part: &str) -> PathBuf {
                self.path.join(part)
            }
        }

        impl Drop for TempPath {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.path);
            }
        }

        pub fn new(prefix: &str) -> TempPath {
            let path = std::env::temp_dir().join(format!(
                "{prefix}-{}",
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map(|value| value.as_nanos())
                    .unwrap_or_default()
            ));
            std::fs::create_dir_all(&path).unwrap();
            let _ = Path::new(&path);
            TempPath { path }
        }
    }

    #[test]
    fn sha256_matches_the_published_vectors() {
        assert_eq!(
            sha256_hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn recording_a_file_creates_one_artifact_and_only_changed_writes_become_revisions() {
        let (root, store, project) = fixture();
        fs::write(project.join("notes.md"), "# 第一版").unwrap();
        let origin = ArtifactOrigin {
            thread_id: "thread-1".into(),
            turn_id: "turn-1".into(),
            item_id: "item-1".into(),
            tool_name: "write_file".into(),
        };
        let first = store
            .record_file("p1", &project, "notes.md", origin.clone())
            .unwrap()
            .expect("recorded");
        assert_eq!(first.source, "agent_generated");
        assert_eq!(first.path, "workspace://notes.md");
        assert_eq!(first.name, "notes.md");
        assert_eq!(first.mime_type, "text/markdown");
        assert_eq!(first.revision_count, 1);
        assert_eq!(first.tool_name, "write_file");

        // The same content again is not a new revision.
        let unchanged = store
            .record_file("p1", &project, "notes.md", origin.clone())
            .unwrap()
            .expect("recorded");
        assert_eq!(unchanged.revision_count, 1);
        assert_eq!(unchanged.latest_revision_id, first.latest_revision_id);

        // Different content is.
        fs::write(project.join("notes.md"), "# 第二版").unwrap();
        let second = store
            .record_file("p1", &project, "notes.md", origin)
            .unwrap()
            .expect("recorded");
        assert_eq!(second.artifact_id, first.artifact_id, "one artifact per path");
        assert_eq!(second.revision_count, 2);
        let revisions = store.revisions(&first.artifact_id).unwrap();
        assert_eq!(revisions.len(), 2);
        // Newest first, and the blob of the first version is still there.
        assert_eq!(revisions[0].ordinal, 2);
        let (oldest_bytes, _) = store
            .revision_bytes(&second, Some(&revisions[1].revision_id))
            .unwrap();
        assert_eq!(String::from_utf8(oldest_bytes).unwrap(), "# 第一版");

        let listed = store.list("p1", false).unwrap();
        assert_eq!(listed.len(), 1);
        assert_eq!(listed[0].artifact_id, first.artifact_id);
        // Another project sees nothing.
        assert!(store.list("p2", false).unwrap().is_empty());

        // A missing file is not an artifact.
        assert!(store
            .record_file("p1", &project, "gone.md", ArtifactOrigin::default())
            .unwrap()
            .is_none());
        let _ = root;
    }

    #[test]
    fn restoring_a_revision_writes_the_bytes_back_and_records_where_they_came_from() {
        let (root, store, project) = fixture();
        fs::write(project.join("a.txt"), "one").unwrap();
        let first = store
            .record_file("p1", &project, "a.txt", ArtifactOrigin::default())
            .unwrap()
            .unwrap();
        let first_revision = first.latest_revision_id.clone();
        fs::write(project.join("a.txt"), "two").unwrap();
        let second = store
            .record_file("p1", &project, "a.txt", ArtifactOrigin::default())
            .unwrap()
            .unwrap();
        assert_eq!(second.revision_count, 2);

        let restored = store
            .restore_revision("p1", &project, &first.artifact_id, &first_revision)
            .unwrap();
        assert_eq!(std::fs::read_to_string(project.join("a.txt")).unwrap(), "one");
        assert_eq!(restored.revision_count, 3);
        let revisions = store.revisions(&restored.artifact_id).unwrap();
        assert_eq!(revisions[0].restored_from_revision_id, first_revision);
        // A revision from another artifact cannot be restored into this one.
        assert!(store
            .restore_revision("p1", &project, &first.artifact_id, "rev-nope")
            .is_err());
        assert!(store
            .restore_revision("p2", &project, &first.artifact_id, &first_revision)
            .is_err());
        let _ = root;
    }

    #[test]
    fn deleting_is_soft_and_restoring_brings_the_artifact_back() {
        let (root, store, project) = fixture();
        fs::write(project.join("b.txt"), "x").unwrap();
        let record = store
            .record_file("p1", &project, "b.txt", ArtifactOrigin::default())
            .unwrap()
            .unwrap();
        assert_eq!(store.set_deleted("p1", &[record.artifact_id.clone()], true).unwrap(), 1);
        assert!(store.list("p1", false).unwrap().is_empty());
        assert_eq!(store.list("p1", true).unwrap().len(), 1);
        // Another project cannot touch it.
        assert_eq!(store.set_deleted("p2", &[record.artifact_id.clone()], true).unwrap(), 0);
        assert_eq!(store.set_deleted("p1", &[record.artifact_id.clone()], false).unwrap(), 1);
        assert_eq!(store.list("p1", false).unwrap().len(), 1);
        let _ = root;
    }
}
