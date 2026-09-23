use lamtools_runtime::study::{NoteWriter, StudyScope, StudyStore};
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use std::fs;
use uuid::Uuid;

#[test]
fn legacy_migration_preserves_unindexed_markdown_at_generated_path() {
    let root = std::env::temp_dir().join(format!("sunday-study-note-migration-{}", Uuid::new_v4()));
    fs::create_dir_all(&root).unwrap();
    let database_path = root.join("study.db");
    let scope = StudyScope::local_compatibility();

    let db = Connection::open(&database_path).unwrap();
    db.execute_batch(
        "CREATE TABLE study_scope_meta(scope_key TEXT NOT NULL,key TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(scope_key,key));
         CREATE TABLE study_notes(scope_key TEXT NOT NULL,id TEXT NOT NULL,title TEXT NOT NULL,revision INTEGER NOT NULL,source_json TEXT NOT NULL,deleted_at TEXT,PRIMARY KEY(scope_key,id));
         CREATE TABLE study_note_blocks(scope_key TEXT NOT NULL,note_id TEXT NOT NULL,id TEXT NOT NULL,position INTEGER NOT NULL,author TEXT NOT NULL,content TEXT NOT NULL,locked INTEGER NOT NULL,revision INTEGER NOT NULL,source_json TEXT NOT NULL,PRIMARY KEY(scope_key,note_id,id));",
    )
    .unwrap();
    db.execute(
        "INSERT INTO study_notes VALUES(?1,'legacy-note','Legacy',3,'{}',NULL)",
        [scope.key()],
    )
    .unwrap();
    db.execute(
        "INSERT INTO study_note_blocks VALUES(?1,'legacy-note','block-1',0,'user','migrated body',1,1,'{}')",
        [scope.key()],
    )
    .unwrap();
    drop(db);

    let digest = format!("{:x}", Sha256::digest(scope.key().as_bytes()));
    let vault = root.join("study-notes").join(&digest[..24]);
    fs::create_dir_all(&vault).unwrap();
    let preexisting = vault.join("Legacy.md");
    fs::write(&preexisting, "unindexed user document; keep this content").unwrap();

    let store = StudyStore::open(&database_path, scope).unwrap();
    let note = store
        .notes(
            &serde_json::json!({"action":"get", "note_id":"legacy-note"}),
            lamtools_runtime::study::NoteWriter::User,
        )
        .unwrap();

    assert_eq!(
        fs::read_to_string(&preexisting).unwrap(),
        "unindexed user document; keep this content"
    );
    assert_eq!(note["note"]["body_md"], "migrated body");

    let _ = fs::remove_dir_all(root);
}

#[test]
fn note_vault_root_symlink_cannot_escape_database_directory() {
    let root = std::env::temp_dir().join(format!("sunday-study-note-symlink-{}", Uuid::new_v4()));
    let database_path = root.join("study.db");
    let scope = StudyScope::local_compatibility();
    let store = StudyStore::open(&database_path, scope.clone()).unwrap();
    let raw = store
        .capture_note_raw(
            Some("raw-1"),
            "node",
            "node-1",
            "snapshot",
            &serde_json::json!({}),
        )
        .unwrap();
    store
        .notes(
            &serde_json::json!({
                "action":"resource_create", "resource_id":"resource-1",
                "title":"Resource", "content":"Summary", "raw_ids":[raw["raw_id"]]
            }),
            NoteWriter::Agent,
        )
        .unwrap();

    let digest = format!("{:x}", Sha256::digest(scope.key().as_bytes()));
    let study_notes = root.join("study-notes");
    let vault = study_notes.join(&digest[..24]);
    let outside = root.join("outside-vault");
    fs::create_dir_all(&study_notes).unwrap();
    fs::create_dir_all(&outside).unwrap();
    #[cfg(windows)]
    let link_result = std::os::windows::fs::symlink_dir(&outside, &vault);
    #[cfg(unix)]
    let link_result = std::os::unix::fs::symlink(&outside, &vault);
    if link_result.is_err() {
        let _ = fs::remove_dir_all(&root);
        return;
    }

    let result = store.notes(
        &serde_json::json!({
            "action":"create", "note_id":"note-1", "title":"Note",
            "path":"note.md", "body_md":"body", "resource_ids":["resource-1"]
        }),
        NoteWriter::User,
    );

    assert!(result.is_err(), "a symlinked vault root must be rejected");
    assert!(
        !outside.join("note.md").exists(),
        "a note must never be written outside the database directory"
    );
    let _ = fs::remove_dir_all(root);
}
