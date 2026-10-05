//! Artifact registry for the mobile host.
//!
//! 成果只记"当前是什么"：哪份文件、谁写的、属于哪一轮。内容就是项目里的那个
//! 文件，不保留历史版本（旧库里的 `artifact_revisions` 表原样留着，不再读写）。
//! 成果 id 由项目与路径派生，所以同一个文件反复写入仍然是同一份成果。
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;

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
    pub thread_id: String,
    pub turn_id: String,
    pub item_id: String,
    pub tool_name: String,
    pub deleted: bool,
    pub created_at: String,
    pub updated_at: String,
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
}

impl ArtifactStore {
    /// Open (and migrate) the store.
    pub fn open(database: &Path) -> Result<Self, String> {
        if let Some(parent) = database.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let store = Self {
            connection: Connection::open(database).map_err(|error| error.to_string())?,
        };
        store.migrate()?;
        Ok(store)
    }

    #[cfg(test)]
    fn open_in_memory() -> Result<Self, String> {
        let store = Self {
            connection: Connection::open_in_memory().map_err(|error| error.to_string())?,
        };
        store.migrate()?;
        Ok(store)
    }

    fn migrate(&self) -> Result<(), String> {
        // `latest_revision_id` / `revision_count` / `artifact_revisions` 是旧版本的
        // 历史数据：表原样保留（不删列、不删表），但现在的读写都不再碰它们。
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

    /// 登记（或刷新）一份成果：内容就是项目里的那个文件。
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
        if let Err(error) = std::fs::metadata(&absolute) {
            if error.kind() == std::io::ErrorKind::NotFound {
                return Ok(None);
            }
            return Err(error.to_string());
        }
        let artifact_id = artifact_id_for(project_id, &runtime_path);
        let mime_type = mime_for(relative_path);
        let now = now_iso();
        if self.artifact(&artifact_id)?.is_none() {
            self.connection
                .execute(
                    "insert into artifacts (artifact_id, project_id, name, path, mime_type, source, role,
                        thread_id, turn_id, item_id, tool_name, created_at, updated_at)
                     values (?1, ?2, ?3, ?4, ?5, 'agent_generated', 'deliverable', ?6, ?7, ?8, ?9, ?10, ?10)",
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
        } else {
            self.connection
                .execute(
                    "update artifacts set mime_type = ?2,
                        thread_id = case when ?3 = '' then thread_id else ?3 end,
                        turn_id = case when ?4 = '' then turn_id else ?4 end,
                        item_id = case when ?5 = '' then item_id else ?5 end,
                        tool_name = case when ?6 = '' then tool_name else ?6 end,
                        updated_at = ?7
                     where artifact_id = ?1",
                    params![
                        artifact_id,
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
        self.artifact(&artifact_id)
    }

    pub fn list(&self, project_id: &str, include_deleted: bool) -> Result<Vec<ArtifactRecord>, String> {
        let mut statement = self
            .connection
            .prepare(
                "select artifact_id, project_id, name, path, mime_type, source, role,
                        thread_id, turn_id, item_id, tool_name, deleted, created_at, updated_at
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
                "select artifact_id, project_id, name, path, mime_type, source, role,
                        thread_id, turn_id, item_id, tool_name, deleted, created_at, updated_at
                 from artifacts where artifact_id = ?1",
                params![artifact_id],
                read_artifact_row,
            )
            .optional()
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

}

/// 读取成果当前的内容：工作区里的那个文件（附件型成果由附件通路负责）。
pub fn file_bytes(root: &Path, record: &ArtifactRecord) -> Result<(Vec<u8>, String), String> {
    let relative = record
        .path
        .strip_prefix("workspace://")
        .ok_or_else(|| "该成果不是工作区文件，请使用附件打开".to_owned())?;
    let bytes = std::fs::read(root.join(relative)).map_err(|error| format!("读取成果内容失败: {error}"))?;
    Ok((bytes, record.mime_type.clone()))
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
        thread_id: row.get(7)?,
        turn_id: row.get(8)?,
        item_id: row.get(9)?,
        tool_name: row.get(10)?,
        deleted: row.get::<_, i64>(11)? != 0,
        created_at: row.get(12)?,
        updated_at: row.get(13)?,
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
    use std::path::PathBuf;

    fn fixture() -> (tempdir::TempPath, ArtifactStore, PathBuf) {
        let root = tempdir::new("sunday-artifacts");
        let project = root.join("project");
        fs::create_dir_all(&project).unwrap();
        let store = ArtifactStore::open_in_memory().unwrap();
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
    fn recording_a_file_keeps_one_artifact_and_no_history() {
        let (_root, store, project) = fixture();
        let target = project.join("notes.txt");
        fs::write(&target, "one").unwrap();
        let origin = || ArtifactOrigin {
            thread_id: "thread-1".into(),
            turn_id: "turn-1".into(),
            item_id: "item-1".into(),
            tool_name: "write_file".into(),
        };

        let first = store
            .record_file("project-1", &project, "notes.txt", origin())
            .unwrap()
            .expect("artifact");
        assert_eq!(first.name, "notes.txt");
        assert_eq!(first.mime_type, "text/plain");
        assert_eq!(first.thread_id, "thread-1");

        // 反复写入仍是同一份成果，读到的永远是当前文件。
        for content in ["two", "three"] {
            fs::write(&target, content).unwrap();
            let again = store
                .record_file("project-1", &project, "notes.txt", origin())
                .unwrap()
                .expect("artifact");
            assert_eq!(again.artifact_id, first.artifact_id);
            let (bytes, mime) = file_bytes(&project, &again).unwrap();
            assert_eq!(String::from_utf8(bytes).unwrap(), content);
            assert_eq!(mime, "text/plain");
        }
        assert_eq!(store.list("project-1", false).unwrap().len(), 1);
        // 旧库里的版本表不再被写入。
        let revisions: i64 = store
            .connection
            .query_row("select count(*) from artifact_revisions", [], |row| row.get(0))
            .unwrap();
        assert_eq!(revisions, 0);

        // A failed write (file gone) records nothing new.
        fs::remove_file(&target).unwrap();
        assert!(store
            .record_file("project-1", &project, "notes.txt", origin())
            .unwrap()
            .is_none());
        let _ = fs::remove_dir_all(&_root.path);
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
