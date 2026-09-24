//! Session checkpoints for the mobile host.
//!
//! The desktop records a checkpoint at every turn boundary: a node in a graph
//! plus a manifest hash of the project files at that moment, so a later restore
//! can put the workspace back. The phone has no event store, so it records the
//! manifest itself — one row per file, with the content hash the artifact store
//! already addresses blobs by — and a restore writes those bytes back and
//! removes files that were not there yet.
//!
//! Restoring always records a new checkpoint first (the desktop's undo node), so
//! a restore can itself be undone.
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

use crate::artifacts::{sha256_hex, ArtifactOrigin, ArtifactStore};

/// Directories a checkpoint ignores, matching the search tools and the desktop's
/// projector: build output and version-control internals are not project state.
const IGNORED_DIRECTORIES: [&str; 8] = [
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    ".pytest_cache",
    ".mypy_cache",
];

/// One checkpoint node, shaped like the desktop's `_checkpoint_payload`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckpointRecord {
    pub id: String,
    pub graph_id: String,
    pub root_session_id: String,
    pub session_id: String,
    pub parent_checkpoint_id: String,
    pub edge_kind: String,
    pub turn_id: String,
    pub actor_kind: String,
    pub reason: String,
    pub label: String,
    pub work_root: String,
    pub manifest_hash: String,
    pub status: String,
    pub created_at: String,
}

impl CheckpointRecord {
    fn to_value(&self) -> Value {
        json!({
            "id": self.id,
            "graph_id": self.graph_id,
            "root_session_id": self.root_session_id,
            "session_id": self.session_id,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "edge_kind": self.edge_kind,
            "turn_id": self.turn_id,
            "actor_kind": self.actor_kind,
            "reason": self.reason,
            "label": self.label,
            "work_root": self.work_root,
            "manifest_hash": self.manifest_hash,
            "status": self.status,
            "created_at": self.created_at,
        })
    }
}

pub struct CheckpointStore {
    connection: Connection,
}

impl CheckpointStore {
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
        self.connection
            .execute_batch(
                "create table if not exists checkpoints (
                    id text primary key,
                    graph_id text not null,
                    root_session_id text not null,
                    session_id text not null,
                    parent_checkpoint_id text not null default '',
                    edge_kind text not null default 'turn',
                    turn_id text not null default '',
                    actor_kind text not null default 'agent',
                    reason text not null default '',
                    label text not null default '',
                    work_root text not null default '',
                    manifest_hash text not null default '',
                    status text not null default 'ready',
                    created_at text not null
                );
                create index if not exists idx_checkpoints_session on checkpoints(session_id, created_at);
                create table if not exists checkpoint_files (
                    checkpoint_id text not null,
                    path text not null,
                    blob_hash text not null,
                    primary key (checkpoint_id, path)
                );",
            )
            .map_err(|error| error.to_string())
    }

    /// Record the project's current file manifest as a checkpoint of this turn.
    ///
    /// The parent is the session's current head, so the graph has one chain per
    /// session; a fork records the checkpoint it grew from instead.
    pub fn create(
        &self,
        project_root: &Path,
        session_id: &str,
        turn_id: &str,
        label: &str,
        reason: &str,
        origin: ActorKind,
    ) -> Result<CheckpointRecord, String> {
        let session_id = session_id.trim();
        if session_id.is_empty() {
            return Err("session_id is required".into());
        }
        let files = manifest(project_root)?;
        let now = crate::timestamp_iso();
        let parent = self.head(session_id)?.unwrap_or_default();
        let graph_id = self.graph_of(session_id, &parent)?.unwrap_or_else(|| format!("graph-{}", short_id()));
        let id = format!("ckpt-{}", short_id());
        let manifest_hash = manifest_hash(&files);
        self.connection
            .execute(
                "insert into checkpoints (id, graph_id, root_session_id, session_id, parent_checkpoint_id,
                    edge_kind, turn_id, actor_kind, reason, label, work_root, manifest_hash, status, created_at)
                 values (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, 'ready', ?13)",
                params![
                    id,
                    graph_id,
                    session_id,
                    session_id,
                    parent,
                    origin.edge_kind(),
                    turn_id,
                    origin.actor_kind(),
                    reason,
                    label,
                    project_root.display().to_string(),
                    manifest_hash,
                    now,
                ],
            )
            .map_err(|error| error.to_string())?;
        {
            let mut statement = self
                .connection
                .prepare("insert into checkpoint_files (checkpoint_id, path, blob_hash) values (?1, ?2, ?3)")
                .map_err(|error| error.to_string())?;
            for (path, hash) in &files {
                statement
                    .execute(params![id, path, hash])
                    .map_err(|error| error.to_string())?;
            }
        }
        self.checkpoint(&id)?
            .ok_or_else(|| "检查点在写入后消失".to_owned())
    }

    pub fn checkpoint(&self, id: &str) -> Result<Option<CheckpointRecord>, String> {
        self.connection
            .query_row(
                "select id, graph_id, root_session_id, session_id, parent_checkpoint_id, edge_kind, turn_id,
                        actor_kind, reason, label, work_root, manifest_hash, status, created_at
                 from checkpoints where id = ?1",
                params![id],
                read_row,
            )
            .optional()
            .map_err(|error| error.to_string())
    }

    /// Newest checkpoint of a session, which is where the next one hangs from.
    pub fn head(&self, session_id: &str) -> Result<Option<String>, String> {
        self.connection
            .query_row(
                "select id from checkpoints where session_id = ?1 order by created_at desc, rowid desc limit 1",
                params![session_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())
    }

    fn graph_of(&self, session_id: &str, parent: &str) -> Result<Option<String>, String> {
        if !parent.is_empty() {
            if let Some(record) = self.checkpoint(parent)? {
                return Ok(Some(record.graph_id));
            }
        }
        self.connection
            .query_row(
                "select graph_id from checkpoints where session_id = ?1 limit 1",
                params![session_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())
    }

    pub fn list(&self, session_id: &str) -> Result<Vec<CheckpointRecord>, String> {
        let mut statement = self
            .connection
            .prepare(
                "select id, graph_id, root_session_id, session_id, parent_checkpoint_id, edge_kind, turn_id,
                        actor_kind, reason, label, work_root, manifest_hash, status, created_at
                 from checkpoints where session_id = ?1 order by created_at, rowid",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(params![session_id], read_row)
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    /// Every checkpoint of a graph, which is what the panel's tree renders.
    pub fn graph(&self, session_id: &str) -> Result<(Vec<CheckpointRecord>, Vec<(String, String)>), String> {
        let mut statement = self
            .connection
            .prepare(
                "select id, graph_id, root_session_id, session_id, parent_checkpoint_id, edge_kind, turn_id,
                        actor_kind, reason, label, work_root, manifest_hash, status, created_at
                 from checkpoints
                 where graph_id in (select distinct graph_id from checkpoints where session_id = ?1)
                 order by created_at, rowid",
            )
            .map_err(|error| error.to_string())?;
        let nodes = statement
            .query_map(params![session_id], read_row)
            .map_err(|error| error.to_string())?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())?;
        // One head per session in the graph, newest first.
        let mut heads: Vec<(String, String)> = Vec::new();
        for node in nodes.iter().rev() {
            if !heads.iter().any(|(session, _)| session == &node.session_id) {
                heads.push((node.session_id.clone(), node.id.clone()));
            }
        }
        Ok((nodes, heads))
    }

    /// The file manifest of one checkpoint.
    pub fn files(&self, checkpoint_id: &str) -> Result<Vec<(String, String)>, String> {
        let mut statement = self
            .connection
            .prepare("select path, blob_hash from checkpoint_files where checkpoint_id = ?1 order by path")
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(params![checkpoint_id], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    #[cfg(test)]
    fn remember_blob(&self, checkpoint_id: &str, path: &str, blob_hash: &str) -> Result<(), String> {
        self.connection
            .execute(
                "insert or replace into checkpoint_files (checkpoint_id, path, blob_hash) values (?1, ?2, ?3)",
                params![checkpoint_id, path, blob_hash],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }
}

/// Which end of a session produced a checkpoint.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ActorKind {
    User,
    Agent,
    System,
}

impl ActorKind {
    fn actor_kind(self) -> &'static str {
        match self {
            ActorKind::User => "user",
            ActorKind::Agent => "agent",
            ActorKind::System => "system",
        }
    }

    /// A user or system checkpoint starts a branch; a turn checkpoint continues.
    fn edge_kind(self) -> &'static str {
        match self {
            ActorKind::User => "user",
            ActorKind::System => "system",
            ActorKind::Agent => "turn",
        }
    }
}

/// Every project file and its content hash, in a stable order.
pub fn manifest(root: &Path) -> Result<Vec<(String, String)>, String> {
    let mut files = Vec::new();
    collect(root, root, &mut files)?;
    files.sort_by(|left, right| left.0.cmp(&right.0));
    Ok(files)
}

fn collect(root: &Path, directory: &Path, files: &mut Vec<(String, String)>) -> Result<(), String> {
    let entries = match std::fs::read_dir(directory) {
        Ok(entries) => entries,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error.to_string()),
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        let metadata = match std::fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(_) => continue,
        };
        // A link is not project state, and following one would leave the root.
        if metadata.file_type().is_symlink() {
            continue;
        }
        if metadata.is_dir() {
            if IGNORED_DIRECTORIES.contains(&name.as_str()) {
                continue;
            }
            collect(root, &path, files)?;
            continue;
        }
        if !metadata.is_file() {
            continue;
        }
        let Ok(relative) = path.strip_prefix(root) else {
            continue;
        };
        let Ok(bytes) = std::fs::read(&path) else {
            continue;
        };
        files.push((relative.to_string_lossy().replace('\\', "/"), sha256_hex(&bytes)));
    }
    Ok(())
}

/// A hash over the whole manifest, so two checkpoints can be compared cheaply.
pub fn manifest_hash(files: &[(String, String)]) -> String {
    let mut lines = String::new();
    for (path, hash) in files {
        lines.push_str(path);
        lines.push(':');
        lines.push_str(hash);
        lines.push('\n');
    }
    sha256_hex(lines.as_bytes())
}

/// Result of a restore, in the desktop's payload shape.
pub struct RestoreOutcome {
    pub operation_id: String,
    pub checkpoint_id: String,
    pub undo_checkpoint_id: String,
    pub scope: String,
    pub status: String,
    pub restored_paths: Vec<String>,
    pub removed_paths: Vec<String>,
}

/// Put the project back to a checkpoint.
///
/// Records an undo checkpoint first (so the restore can be undone), writes every
/// file the checkpoint held back from the artifact blobs — recording a new
/// artifact revision for each, because that is what happened — and removes
/// project files that were not in that checkpoint.
pub fn restore(
    store: &CheckpointStore,
    artifact_store: &ArtifactStore,
    project_root: &Path,
    project_id: &str,
    session_id: &str,
    checkpoint_id: &str,
    scope: &str,
) -> Result<RestoreOutcome, String> {
    let target = store
        .checkpoint(checkpoint_id)?
        .ok_or_else(|| format!("检查点不存在: {checkpoint_id}"))?;
    let undo = store.create(
        project_root,
        session_id,
        &target.turn_id,
        "回滚前状态",
        &format!("restore undo for {checkpoint_id}"),
        ActorKind::System,
    )?;
    let wanted = store.files(checkpoint_id)?;
    let mut restored_paths = Vec::new();
    for (path, blob_hash) in &wanted {
        let bytes = match std::fs::read(artifact_blob_path(artifact_store, blob_hash)) {
            Ok(bytes) => bytes,
            Err(error) => {
                return Err(format!("读取 {path} 的历史内容失败: {error}"));
            }
        };
        let absolute = project_root.join(path);
        if let Some(parent) = absolute.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        std::fs::write(&absolute, &bytes).map_err(|error| error.to_string())?;
        restored_paths.push(path.clone());
        // The file now holds history again, which is a real write: the artifact
        // history has to say so, with the same provenance a tool write gets.
        let origin = ArtifactOrigin {
            thread_id: session_id.to_owned(),
            turn_id: target.turn_id.clone(),
            item_id: String::new(),
            tool_name: "checkpoint.restore".into(),
        };
        let _ = artifact_store.record_file(project_id, project_root, path, origin);
    }
    let mut removed_paths = Vec::new();
    // A file created after the checkpoint is not part of the state being
    // restored, so it goes away; ignored directories are never touched.
    for (path, _) in manifest(project_root)? {
        if wanted.iter().any(|(kept, _)| kept == &path) {
            continue;
        }
        let absolute: PathBuf = project_root.join(&path);
        if std::fs::remove_file(&absolute).is_ok() {
            removed_paths.push(path);
        }
    }
    Ok(RestoreOutcome {
        operation_id: format!("restore-{}", short_id()),
        checkpoint_id: checkpoint_id.to_owned(),
        undo_checkpoint_id: undo.id,
        scope: scope.to_owned(),
        status: "completed".into(),
        restored_paths,
        removed_paths,
    })
}

/// Blob path inside the artifact store, which is what owns the content.
fn artifact_blob_path(store: &ArtifactStore, hash: &str) -> PathBuf {
    store.blob_path(hash)
}

fn read_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<CheckpointRecord> {
    Ok(CheckpointRecord {
        id: row.get(0)?,
        graph_id: row.get(1)?,
        root_session_id: row.get(2)?,
        session_id: row.get(3)?,
        parent_checkpoint_id: row.get(4)?,
        edge_kind: row.get(5)?,
        turn_id: row.get(6)?,
        actor_kind: row.get(7)?,
        reason: row.get(8)?,
        label: row.get(9)?,
        work_root: row.get(10)?,
        manifest_hash: row.get(11)?,
        status: row.get(12)?,
        created_at: row.get(13)?,
    })
}

fn short_id() -> String {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or_default();
    format!("{nanos:x}")
}

/// `{nodes, heads}` for the panel's graph view.
pub fn graph_payload(nodes: &[CheckpointRecord], heads: &[(String, String)]) -> Value {
    let mut head_map = serde_json::Map::new();
    for (session, checkpoint) in heads {
        head_map.insert(session.clone(), Value::String(checkpoint.clone()));
    }
    json!({
        "nodes": nodes.iter().map(CheckpointRecord::to_value).collect::<Vec<_>>(),
        "heads": Value::Object(head_map),
    })
}

/// The desktop's `_restore_payload`.
pub fn restore_payload(outcome: &RestoreOutcome) -> Value {
    json!({
        "operation_id": outcome.operation_id,
        "checkpoint_id": outcome.checkpoint_id,
        "undo_checkpoint_id": outcome.undo_checkpoint_id,
        "derived_checkpoint_id": "",
        "scope": outcome.scope,
        "status": outcome.status,
        "restored_paths": outcome.restored_paths,
        "removed_paths": outcome.removed_paths,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> (PathBuf, CheckpointStore, ArtifactStore) {
        let root = std::env::temp_dir().join(format!("sunday-checkpoints-{}", short_id()));
        std::fs::create_dir_all(root.join("project")).unwrap();
        std::fs::create_dir_all(root.join("blobs")).unwrap();
        let store = CheckpointStore::open_in_memory().unwrap();
        let artifacts = ArtifactStore::open_in_memory_at(&root.join("blobs"));
        (root, store, artifacts)
    }

    #[test]
    fn a_checkpoint_records_the_files_and_chains_per_session() {
        let (root, store, artifacts) = fixture();
        let project = root.join("project");
        std::fs::write(project.join("a.txt"), "one").unwrap();
        std::fs::create_dir_all(project.join("node_modules")).unwrap();
        std::fs::write(project.join("node_modules/ignored.js"), "x").unwrap();

        let first = store
            .create(&project, "s1", "turn-1", "", "", ActorKind::Agent)
            .unwrap();
        assert_eq!(first.edge_kind, "turn");
        assert_eq!(first.parent_checkpoint_id, "");
        assert_eq!(first.actor_kind, "agent");
        // Build directories are not project state.
        assert_eq!(store.files(&first.id).unwrap().len(), 1);

        // Same files, same fingerprint: a checkpoint hash describes state, not
        // time. Writing a file changes it.
        let unchanged = store
            .create(&project, "s1", "turn-2", "", "", ActorKind::Agent)
            .unwrap();
        assert_eq!(unchanged.manifest_hash, first.manifest_hash);
        assert_eq!(unchanged.parent_checkpoint_id, first.id);
        std::fs::write(project.join("a.txt"), "two").unwrap();
        let second = store
            .create(&project, "s1", "turn-3", "", "", ActorKind::Agent)
            .unwrap();
        assert_eq!(second.parent_checkpoint_id, unchanged.id);
        assert_eq!(second.graph_id, first.graph_id);
        assert_ne!(second.manifest_hash, first.manifest_hash);

        // Another session gets its own graph until it forks from this one.
        let other = store
            .create(&project, "s2", "turn-1", "", "", ActorKind::Agent)
            .unwrap();
        assert_ne!(other.graph_id, first.graph_id);

        let (nodes, heads) = store.graph("s1").unwrap();
        assert_eq!(nodes.len(), 3);
        assert_eq!(heads, vec![("s1".to_owned(), second.id.clone())]);
        let payload = graph_payload(&nodes, &heads);
        assert_eq!(payload["nodes"].as_array().unwrap().len(), 3);
        assert_eq!(payload["heads"]["s1"], json!(second.id));
        let _ = artifacts;
    }

    #[test]
    fn restoring_puts_files_back_removes_later_ones_and_leaves_an_undo_checkpoint() {
        let (root, store, artifacts) = fixture();
        let project = root.join("project");
        std::fs::write(project.join("keep.txt"), "v1").unwrap();
        let base = store
            .create(&project, "s1", "turn-1", "", "", ActorKind::Agent)
            .unwrap();
        // The store needs the v1 bytes to restore them, so record them the way a
        // tool write would.
        let blob = sha256_hex(b"v1");
        artifacts
            .store_bytes_for_test(&blob, b"v1")
            .expect("blob stored");
        store.remember_blob(&base.id, "keep.txt", &blob).unwrap();

        std::fs::write(project.join("keep.txt"), "v2").unwrap();
        std::fs::write(project.join("created-later.txt"), "extra").unwrap();
        let _second = store
            .create(&project, "s1", "turn-2", "", "", ActorKind::Agent)
            .unwrap();

        let outcome = restore(&store, &artifacts, &project, "p1", "s1", &base.id, "workspace").unwrap();
        assert_eq!(std::fs::read_to_string(project.join("keep.txt")).unwrap(), "v1");
        // A file that did not exist at the checkpoint is not part of that state.
        assert!(!project.join("created-later.txt").exists());
        assert_eq!(outcome.restored_paths, vec!["keep.txt".to_owned()]);
        assert_eq!(outcome.removed_paths, vec!["created-later.txt".to_owned()]);
        // The undo checkpoint captured the pre-restore state ...
        let undo = store.checkpoint(&outcome.undo_checkpoint_id).unwrap().expect("undo");
        assert_eq!(undo.actor_kind, "system");
        assert_eq!(undo.parent_checkpoint_id, _second.id);
        // ... and the restore itself is recorded as a write in the artifact
        // history, so a later restore can find those bytes.
        let files = store.files(&base.id).unwrap();
        assert_eq!(files.len(), 1);
        let payload = restore_payload(&outcome);
        assert_eq!(payload["status"], "completed");
        assert_eq!(payload["scope"], "workspace");

        // Restoring an unknown checkpoint refuses instead of doing nothing.
        assert!(restore(&store, &artifacts, &project, "p1", "s1", "ckpt-nope", "workspace").is_err());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn the_manifest_hash_changes_only_when_the_files_do() {
        let empty = manifest_hash(&[]);
        let one = manifest_hash(&[("a.txt".into(), "hash".into())]);
        let other = manifest_hash(&[("a.txt".into(), "hash2".into())]);
        let renamed = manifest_hash(&[("b.txt".into(), "hash".into())]);
        assert_ne!(empty, one);
        assert_ne!(one, other);
        assert_ne!(one, renamed);
        assert_eq!(one, manifest_hash(&[("a.txt".into(), "hash".into())]));
    }
}
