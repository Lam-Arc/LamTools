//! Session checkpoint listing for the mobile host.
//!
//! 检查点只用来标出对话的回合边界：手机端的撤回/恢复在会话库里截断对话上下文，
//! 永不回退文件（文件与成果没有历史版本）。这里保留图与列表的读取；旧库里文件
//! 清单相关的内容原样留着，不再写入也不再回放。
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;


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

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::Connection;

    fn store_with_legacy_rows() -> CheckpointStore {
        let store = CheckpointStore {
            connection: Connection::open_in_memory().expect("in-memory checkpoints"),
        };
        store.migrate().expect("checkpoints schema");
        for (id, session, graph, parent, created) in [
            ("ckpt-1", "s1", "graph-1", "", "2026-10-01T00:00:00Z"),
            ("ckpt-2", "s1", "graph-1", "ckpt-1", "2026-10-01T01:00:00Z"),
            ("ckpt-3", "s2", "graph-2", "", "2026-10-01T02:00:00Z"),
        ] {
            store
                .connection
                .execute(
                    "insert into checkpoints (id, graph_id, root_session_id, session_id, parent_checkpoint_id,
                        edge_kind, turn_id, actor_kind, reason, label, work_root, manifest_hash, status, created_at)
                     values (?1, ?2, ?3, ?3, ?4, 'turn', 'turn-1', 'agent', '', '', '', '', 'ready', ?5)",
                    rusqlite::params![id, graph, session, parent, created],
                )
                .expect("legacy row");
        }
        store
    }

    #[test]
    fn listing_and_graph_read_legacy_checkpoints_without_touching_files() {
        let store = store_with_legacy_rows();
        let nodes = store.list("s1").expect("list");
        assert_eq!(nodes.len(), 2);
        assert_eq!(nodes[0].id, "ckpt-1");
        assert_eq!(nodes[1].parent_checkpoint_id, "ckpt-1");

        let (all, heads) = store.graph("s2").expect("graph");
        assert_eq!(all.len(), 1);
        assert_eq!(heads, vec![("s2".to_owned(), "ckpt-3".to_owned())]);
        let payload = graph_payload(&all, &heads);
        assert_eq!(payload["nodes"].as_array().unwrap().len(), 1);
        assert_eq!(payload["heads"]["s2"], serde_json::json!("ckpt-3"));

        assert!(store.checkpoint("ckpt-nope").expect("query").is_none());
    }

    #[test]
    fn opening_the_store_creates_only_schema() {
        let root = std::env::temp_dir().join(format!("sunday-checkpoints-{}", std::process::id()));
        let store = CheckpointStore::open(&root.join("checkpoints.db")).expect("open");
        assert!(store.list("s1").expect("list").is_empty());
        drop(store);
        let _ = std::fs::remove_dir_all(&root);
    }
}
