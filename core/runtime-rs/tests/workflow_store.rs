use lamtools_runtime::workflow_document::document_from_workflow_def;
use lamtools_runtime::workflow_store::{
    WorkflowRuntimeBucket, WorkflowStore, WorkflowStoreError,
};
use serde_json::{json, Value};
use std::fs;
use std::path::Path;
use uuid::Uuid;

struct Fixture(std::path::PathBuf);
impl Fixture {
    fn new() -> Self {
        let dir = std::env::temp_dir().join(format!("lamtools-workflow-store-{}", Uuid::new_v4()));
        fs::create_dir_all(&dir).unwrap();
        Self(dir)
    }
    fn path(&self) -> &Path {
        &self.0
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn document(name: &str) -> Value {
    document_from_workflow_def(&json!({
        "name": name, "nodes": [], "edges": [], "revision": 0,
    }))
    .unwrap()
}

#[test]
fn save_conflict_and_atomic_overwrite() {
    let fixture = Fixture::new();
    let store = WorkflowStore::new(fixture.path().join("global"));
    let first = store
        .save_document(&document("alpha"), None, Some(0))
        .unwrap();
    assert_eq!(first["resource"]["revision"], 1);
    let stale = store.save_document(&first, None, Some(0)).unwrap_err();
    assert!(matches!(
        stale,
        WorkflowStoreError::Conflict {
            expected: 0,
            current: 1
        }
    ));
    let mut edited = first.clone();
    edited["resource"]["description"] = json!("updated");
    let second = store.save_document(&edited, None, Some(1)).unwrap();
    assert_eq!(second["resource"]["revision"], 2);
    assert_eq!(second["resource"]["id"], first["resource"]["id"]);
    assert_eq!(
        store.get("alpha", None).unwrap().unwrap()["resource"]["description"],
        "updated"
    );
    let folder = fixture.path().join("global/workflows/alpha");
    assert!(folder.join("workflow.json").is_file());
    assert!(folder.join("config.json").is_file());
    assert_eq!(
        fs::read_dir(&folder)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|item| item.file_name().to_string_lossy().ends_with(".tmp"))
            .count(),
        0
    );
}

#[test]
fn runtime_queue_records_are_durable_and_scoped_separately_from_documents() {
    let fixture = Fixture::new();
    let global = WorkflowStore::new(fixture.path().join("global"));
    let project_root = fixture.path().join("project");

    global
        .mutate_runtime_records(WorkflowRuntimeBucket::Queue, None, |items| {
            items.push(json!({"queue_id":"global-run", "status":"completed"}));
        })
        .unwrap();
    global
        .mutate_runtime_records(
            WorkflowRuntimeBucket::Queue,
            Some(&project_root),
            |items| items.push(json!({"queue_id":"project-run", "status":"queued"})),
        )
        .unwrap();

    let reopened = WorkflowStore::new(fixture.path().join("global"));
    assert_eq!(
        reopened
            .runtime_records(WorkflowRuntimeBucket::Queue, None)
            .unwrap(),
        vec![json!({"queue_id":"global-run", "status":"completed"})]
    );
    assert_eq!(
        reopened
            .runtime_records(WorkflowRuntimeBucket::Queue, Some(&project_root))
            .unwrap(),
        vec![json!({"queue_id":"project-run", "status":"queued"})]
    );
    assert!(reopened.list(None).unwrap().is_empty());
    assert!(fixture
        .path()
        .join("global/workflow/queue.json")
        .is_file());
    assert!(project_root
        .join(".lam/workflow/queue.json")
        .is_file());
}

#[test]
fn rename_keeps_identity_and_rejects_name_collision() {
    let fixture = Fixture::new();
    let store = WorkflowStore::new(fixture.path().join("global"));
    let first = store
        .save_document(&document("before"), None, None)
        .unwrap();
    let second = store
        .save_document(&document("occupied"), None, None)
        .unwrap();
    let mut rename = first.clone();
    rename["resource"]["name"] = json!("after");
    let renamed = store.save_document(&rename, None, Some(1)).unwrap();
    assert_eq!(renamed["resource"]["id"], first["resource"]["id"]);
    assert_eq!(renamed["resource"]["revision"], 2);
    assert!(store.get("before", None).unwrap().is_none());
    assert!(store.get("after", None).unwrap().is_some());
    assert!(!fixture.path().join("global/workflows/before").exists());
    rename["resource"]["name"] = json!("occupied");
    assert!(matches!(
        store.save_document(&rename, None, Some(2)),
        Err(WorkflowStoreError::Collision)
    ));
    assert_eq!(
        store.get("occupied", None).unwrap().unwrap()["resource"]["id"],
        second["resource"]["id"]
    );
}

#[test]
fn independent_stores_cannot_both_commit_the_same_revision() {
    let fixture = Fixture::new();
    let root = fixture.path().join("global");
    let store = WorkflowStore::new(root.clone());
    let first = store
        .save_document(&document("shared"), None, None)
        .unwrap();
    let handles = (0..2)
        .map(|_| {
            let root = root.clone();
            let first = first.clone();
            std::thread::spawn(move || {
                WorkflowStore::new(root).save_document(&first, None, Some(1))
            })
        })
        .collect::<Vec<_>>();
    let outcomes = handles
        .into_iter()
        .map(|h| h.join().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(outcomes.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        outcomes
            .iter()
            .filter(|result| matches!(
                result,
                Err(WorkflowStoreError::Conflict {
                    expected: 1,
                    current: 2
                })
            ))
            .count(),
        1
    );
}

#[test]
fn project_scope_does_not_read_or_delete_global_workflow() {
    let fixture = Fixture::new();
    let project = fixture.path().join("project");
    let store = WorkflowStore::new(fixture.path().join("global"));
    let global = store
        .save_document(&document("shared"), None, None)
        .unwrap();
    assert!(store.get("shared", Some(&project)).unwrap().is_none());
    let local = store
        .save_document(&document("shared"), Some(&project), None)
        .unwrap();
    assert_ne!(global["resource"]["id"], local["resource"]["id"]);
    assert_eq!(store.list(Some(&project)).unwrap().len(), 2);
    assert!(store.delete("shared", Some(&project)).unwrap());
    assert!(store.get("shared", Some(&project)).unwrap().is_none());
    assert!(store.get("shared", None).unwrap().is_some());
}

#[test]
fn embedded_work_root_cannot_redirect_a_global_save() {
    let fixture = Fixture::new();
    let outside = fixture.path().join("outside-project");
    let store = WorkflowStore::new(fixture.path().join("global"));
    let mut payload = document("confined");
    payload["resource"]["work_root"] = json!(outside.to_string_lossy().into_owned());

    let saved = store.save_document(&payload, None, Some(0)).unwrap();
    assert_eq!(saved["resource"]["work_root"], "");
    assert!(fixture
        .path()
        .join("global/workflows/confined/workflow.json")
        .is_file());
    assert!(!outside
        .join(".lam/workflows/confined/workflow.json")
        .exists());
    assert!(store.get("confined", None).unwrap().is_some());
    assert!(store.get("confined", Some(&outside)).unwrap().is_none());
    assert!(!store.delete("confined", Some(&outside)).unwrap());

    let saved_project = store
        .save_document(&payload, Some(&outside), Some(0))
        .unwrap();
    assert_eq!(
        saved_project["resource"]["work_root"],
        outside.to_string_lossy().as_ref()
    );
    assert!(outside
        .join(".lam/workflows/confined/workflow.json")
        .is_file());
}

#[test]
fn legacy_folder_and_single_json_read_without_mutation() {
    let fixture = Fixture::new();
    let root = fixture.path().join("global/workflows");
    fs::create_dir_all(root.join("old_folder")).unwrap();
    fs::write(
        root.join("old_folder/config.json"),
        serde_json::to_vec(&json!({"name":"folder", "revision":4, "edges":[]})).unwrap(),
    )
    .unwrap();
    fs::write(
        root.join("old_folder/node.json"),
        serde_json::to_vec(&json!({"id":"n", "kind":"content", "ports":[]})).unwrap(),
    )
    .unwrap();
    fs::write(
        root.join("single.json"),
        serde_json::to_vec(&json!({"name":"single", "nodes":[], "edges":[]})).unwrap(),
    )
    .unwrap();
    let store = WorkflowStore::new(fixture.path().join("global"));
    assert_eq!(
        store.get("folder", None).unwrap().unwrap()["resource"]["revision"],
        4
    );
    assert_eq!(
        store.get("folder", None).unwrap().unwrap()["graph"]["nodes"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert!(store.get("single", None).unwrap().is_some());
    let first_id = store.get("folder", None).unwrap().unwrap()["resource"]["id"].clone();
    assert_eq!(
        first_id,
        store.get("folder", None).unwrap().unwrap()["resource"]["id"]
    );
    let old_doc = store.get("folder", None).unwrap().unwrap();
    let saved = store.save_document(&old_doc, None, Some(4)).unwrap();
    assert_eq!(saved["resource"]["id"], first_id);
    assert_eq!(saved["resource"]["revision"], 5);
    assert!(root.join("old_folder/workflow.json").exists());
    assert!(!root.join("single/workflow.json").exists());
}

#[test]
fn legacy_map_is_used_only_when_edges_are_absent() {
    let fixture = Fixture::new();
    let folder = fixture.path().join("global/workflows/legacy_map");
    fs::create_dir_all(&folder).unwrap();
    fs::write(
        folder.join("config.json"),
        serde_json::to_vec(
            &json!({"name":"mapped", "map":"a.out.string -> b.input.string\ninvalid mapping"}),
        )
        .unwrap(),
    )
    .unwrap();
    fs::write(
        folder.join("a.json"),
        serde_json::to_vec(
            &json!({"id":"a", "kind":"content", "outputs":[{"name":"out", "type":"string"}]}),
        )
        .unwrap(),
    )
    .unwrap();
    fs::write(
        folder.join("b.json"),
        serde_json::to_vec(
            &json!({"id":"b", "kind":"command", "inputs":[{"name":"input", "type":"string"}]}),
        )
        .unwrap(),
    )
    .unwrap();
    let store = WorkflowStore::new(fixture.path().join("global"));
    let found = store.get("mapped", None).unwrap().unwrap();
    assert_eq!(found["graph"]["links"].as_array().unwrap().len(), 1);
}

#[test]
fn unsafe_display_name_is_confined_to_workflow_directory() {
    let fixture = Fixture::new();
    let store = WorkflowStore::new(fixture.path().join("global"));
    store
        .save_document(&document("../outside"), None, None)
        .unwrap();
    assert!(!fixture.path().join("outside").exists());
    let entries = fs::read_dir(fixture.path().join("global/workflows"))
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .collect::<Vec<_>>();
    assert_eq!(entries.len(), 1);
    assert!(entries[0].join("workflow.json").is_file());
    assert!(store.get("../outside", None).unwrap().is_some());
}

#[test]
fn canonical_document_blocks_stale_legacy_fallback_and_slug_collision() {
    let fixture = Fixture::new();
    let store = WorkflowStore::new(fixture.path().join("global"));
    store
        .save_document(&document("lam的小实验"), None, None)
        .unwrap();
    store
        .save_document(&document("lam____"), None, None)
        .unwrap();
    assert!(store.get("lam", None).unwrap().is_none());
    let folder = fixture.path().join("global/workflows/lam的小实验");
    fs::write(folder.join("workflow.json"), "{bad").unwrap();
    assert!(store.get("lam的小实验", None).unwrap().is_none());
}

#[cfg(unix)]
#[test]
fn symlinked_workflow_directory_cannot_escape_scope() {
    use std::os::unix::fs::symlink;
    let fixture = Fixture::new();
    let external = fixture.path().join("external");
    fs::create_dir_all(&external).unwrap();
    let root = fixture.path().join("global/workflows");
    fs::create_dir_all(&root).unwrap();
    symlink(&external, root.join("evil")).unwrap();
    let store = WorkflowStore::new(fixture.path().join("global"));
    let saved = store.save_document(&document("evil"), None, None).unwrap();
    assert_eq!(saved["resource"]["name"], "evil");
    assert!(!external.join("workflow.json").exists());
}
