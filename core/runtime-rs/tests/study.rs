//! Contract tests for the shared Study knowledge workspace.
//!
//! These run against the real SQLite store and assert the behaviour the
//! bundled Python plugin defines, so a native host cannot silently drift.

use lamtools_runtime::{
    study::{dictionary, study_tool_definitions, StudyScope, StudyStore, StudyTools},
    DeviceCapabilities, Message, ModelBackend, ModelTurn, RuntimeError, ToolCall, ToolDefinition,
    ToolPermission, ToolRuntime, TurnOptions,
};
use serde_json::{json, Map, Value};

fn temp_store(name: &str) -> StudyStore {
    let root = std::env::temp_dir().join(format!("lamtools-study-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    StudyStore::open(root.join("study.db"), StudyScope::local_compatibility()).unwrap()
}

fn seed_operations() -> Value {
    json!([
        {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "微积分"}},
        {"action": "create", "kind": "module", "id": "module-a", "data": {"name": "极限", "course_id": "course-a"}},
        {"action": "create", "kind": "node", "id": "node-a", "data": {"name": "极限定义", "type": "concept", "course_ids": ["course-a"], "module_ids": ["module-a"]}},
        {"action": "create", "kind": "node", "id": "node-b", "data": {"name": "导数", "type": "concept", "course_ids": ["course-a"], "module_ids": ["module-a"]}},
        {"action": "create", "kind": "relation", "id": "relation-a", "data": {"source": "node-a", "target": "node-b", "type": "prerequisite"}}
    ])
}

#[test]
fn build_and_read_keep_one_scoped_revisioned_graph() {
    let store = temp_store("graph");
    let request = json!({
        "revision": 0,
        "request_id": "req-1",
        "operations": seed_operations(),
    });
    let built = store.build(&request).unwrap();
    assert_eq!(built["revision"], json!(1));
    assert_eq!(built["changed"].as_array().unwrap().len(), 5);
    assert_eq!(built["scope"]["compatibility_fallback"], json!(true));

    let retry = store.build(&request).unwrap();
    assert_eq!(retry, built);

    let conflict = store.build(&json!({
        "revision": 0,
        "request_id": "req-1",
        "operations": [{"action": "create", "kind": "course", "id": "course-z", "data": {"name": "其他"}}],
    }));
    assert!(conflict.is_err(), "a conflicting retry must fail closed");

    let overview = store.read(&json!({})).unwrap();
    assert_eq!(overview["total"], json!(1));
    assert_eq!(overview["progress"]["total"], json!(2));
    assert_eq!(overview["courses"][0]["name"], json!("微积分"));

    // Only the module layer is listed while no module is selected, so the
    // course page shows the module and leaves its children to the module view.
    let course_view = store.read(&json!({"course_id": "course-a"})).unwrap();
    assert_eq!(course_view["total"], json!(1));
    assert_eq!(course_view["items"][0]["entity"], json!("module"));
    assert_eq!(course_view["relations_total"], json!(0));

    let node_view = store.read(&json!({"node_id": "node-a"})).unwrap();
    assert_eq!(node_view["total"], json!(1));
    assert_eq!(node_view["neighbors"].as_array().unwrap().len(), 2);

    let module_view = store
        .read(&json!({"course_id": "course-a", "module_id": "module-a"}))
        .unwrap();
    assert_eq!(module_view["total"], json!(2));

    let outbox = store.outbox(&[], 50).unwrap();
    assert_eq!(outbox["events"].as_array().unwrap().len(), 1);
    assert_eq!(outbox["events"][0]["kind"], json!("study.graph.changed"));
    assert_eq!(store.integrity().unwrap()["integrity_check"], json!("ok"));
}

#[test]
fn deep_offsets_require_a_revision_bound_cursor() {
    let store = temp_store("cursor");
    store
        .build(&json!({
            "revision": 0,
            "operations": [
                {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "课程"}},
                {"action": "create", "kind": "node", "id": "node-1", "data": {"name": "A", "type": "concept", "course_ids": ["course-a"]}},
                {"action": "create", "kind": "node", "id": "node-2", "data": {"name": "B", "type": "concept", "course_ids": ["course-a"]}},
                {"action": "create", "kind": "node", "id": "node-3", "data": {"name": "C", "type": "concept", "course_ids": ["course-a"]}}
            ],
        }))
        .unwrap();
    assert!(store
        .read(&json!({"course_id": "course-a", "offset": 1}))
        .is_err());

    let first = store
        .read(&json!({"course_id": "course-a", "limit": 2}))
        .unwrap();
    assert_eq!(first["items"].as_array().unwrap().len(), 2);
    assert_eq!(first["has_more"], json!(true));
    let cursor = first["next_cursor"].as_str().unwrap().to_owned();

    let second = store
        .read(&json!({"course_id": "course-a", "limit": 2, "cursor": cursor.clone()}))
        .unwrap();
    assert_eq!(second["items"].as_array().unwrap().len(), 1);
    assert_eq!(second["has_more"], json!(false));
    assert_eq!(second["next_cursor"], Value::Null);

    assert!(store
        .read(&json!({"course_id": "course-a", "cursor": "not-a-cursor"}))
        .is_err());

    // A cursor bound to a previous revision must not silently page new data.
    store
        .build(&json!({
            "revision": 1,
            "operations": [{"action": "update", "kind": "node", "id": "node-1", "data": {"description": "更新"}}],
        }))
        .unwrap();
    assert!(store
        .read(&json!({"course_id": "course-a", "limit": 2, "cursor": cursor}))
        .is_err());
    assert!(store
        .read(&json!({"course_id": "course-a", "expected_structure_revision": 1}))
        .is_err());
    assert!(store
        .read(&json!({"course_id": "course-a", "expected_structure_revision": 2}))
        .is_ok());
}

#[test]
fn build_guards_learning_status_cycles_and_duplicates() {
    let store = temp_store("guards");
    store
        .build(&json!({
            "revision": 0,
            "operations": [
                {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "课程"}},
                {"action": "create", "kind": "node", "id": "node-1", "data": {"name": "A", "type": "concept", "course_ids": ["course-a"]}},
                {"action": "create", "kind": "node", "id": "node-2", "data": {"name": "B", "type": "concept", "course_ids": ["course-a"]}}
            ],
        }))
        .unwrap();

    assert!(
        store
            .build(&json!({
                "revision": 1,
                "operations": [{"action": "update", "kind": "node", "id": "node-1", "data": {"passed": true}}],
            }))
            .is_err(),
        "learning status must only move through sign"
    );
    assert!(
        store
            .build(&json!({
                "revision": 1,
                "operations": [{"action": "create", "kind": "node", "id": "node-3", "data": {"name": "A", "type": "concept", "course_ids": ["course-a"]}}],
            }))
            .is_err(),
        "a duplicate name and type in one scope is rejected"
    );

    store
        .build(&json!({
            "revision": 1,
            "operations": [
                {"action": "create", "kind": "relation", "data": {"source": "node-1", "target": "node-2", "type": "prerequisite"}}
            ],
        }))
        .unwrap();
    assert!(
        store
            .build(&json!({
                "revision": 2,
                "operations": [
                    {"action": "create", "kind": "relation", "data": {"source": "node-2", "target": "node-1", "type": "prerequisite"}}
                ],
            }))
            .is_err(),
        "a prerequisite cycle is rejected"
    );
    assert!(
        store
            .build(&json!({
                "revision": 2,
                "operations": [{"action": "create", "kind": "node", "id": "node-4", "data": {"name": "孤立", "type": "concept"}}],
            }))
            .is_err(),
        "a node without a course must be explicitly orphaned"
    );
    assert!(
        store
            .build(&json!({
                "revision": 0,
                "operations": [{"action": "create", "kind": "course", "id": "course-b", "data": {"name": "其他"}}],
            }))
            .is_err(),
        "a stale revision is refused before any write"
    );
    // Soft-deleted nodes are hidden from reads but stay restorable.
    store
        .build(&json!({
            "revision": 2,
            "operations": [{"action": "delete", "kind": "node", "id": "node-2"}],
        }))
        .unwrap();
    let overview = store.read(&json!({})).unwrap();
    assert_eq!(overview["progress"]["total"], json!(1));
    assert!(store.read(&json!({"node_id": "node-2"})).is_err());
    store
        .build(&json!({
            "revision": 3,
            "operations": [{"action": "restore", "kind": "node", "id": "node-2"}],
        }))
        .unwrap();
    assert!(store.read(&json!({"node_id": "node-2"})).is_ok());
}

#[test]
fn removing_a_course_keeps_evidence_and_orphans_shared_nodes() {
    let store = temp_store("remove-course");
    store
        .build(&json!({
            "revision": 0,
            "operations": [
                {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "课程A"}},
                {"action": "create", "kind": "course", "id": "course-b", "data": {"name": "课程B"}},
                {"action": "create", "kind": "module", "id": "module-a", "data": {"name": "模块", "course_id": "course-a"}},
                {"action": "create", "kind": "node", "id": "shared", "data": {"name": "共享", "type": "concept", "course_ids": ["course-a", "course-b"], "module_ids": ["module-a"]}},
                {"action": "create", "kind": "node", "id": "only-a", "data": {"name": "仅A", "type": "concept", "course_ids": ["course-a"], "module_ids": ["module-a"]}}
            ],
        }))
        .unwrap();

    let removed = store
        .build(&json!({
            "revision": 1,
            "operations": [{"action": "delete", "kind": "course", "id": "course-a"}],
        }))
        .unwrap();
    let impact = &removed["impact"];
    assert_eq!(impact["course_id"], json!("course-a"));
    assert_eq!(impact["detached_node_ids"].as_array().unwrap().len(), 2);
    assert_eq!(impact["orphaned_node_ids"], json!(["only-a"]));
    assert_eq!(impact["preserved_session_binding_count"], json!(0));
    assert_eq!(impact["preserved_shared_knowledge"], json!(true));

    let overview = store.read(&json!({})).unwrap();
    assert_eq!(overview["total"], json!(1));
    assert!(
        store.node("only-a").is_ok(),
        "detached knowledge stays recoverable"
    );

    let restored = store
        .build(&json!({
            "revision": 2,
            "operations": [{"action": "restore", "kind": "course", "id": "course-a"}],
        }))
        .unwrap();
    assert_eq!(restored["impact"]["restored_node_count"], json!(2));
    assert_eq!(restored["impact"]["restored_module_count"], json!(1));
    assert_eq!(store.node("only-a").unwrap()["orphaned"], json!(false));
}

#[test]
fn merging_nodes_rewrites_edges_and_resolves_aliases() {
    let store = temp_store("merge");
    store
        .build(&json!({
            "revision": 0,
            "operations": [
                {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "课程"}},
                {"action": "create", "kind": "node", "id": "node-1", "data": {"name": "A", "type": "concept", "course_ids": ["course-a"]}},
                {"action": "create", "kind": "node", "id": "node-2", "data": {"name": "B", "type": "concept", "course_ids": ["course-a"]}},
                {"action": "create", "kind": "node", "id": "node-3", "data": {"name": "C", "type": "concept", "course_ids": ["course-a"]}},
                {"action": "create", "kind": "relation", "id": "edge-1", "data": {"source": "node-1", "target": "node-3", "type": "prerequisite"}}
            ],
        }))
        .unwrap();
    let merged = store
        .build(&json!({
            "revision": 1,
            "operations": [{"action": "merge", "kind": "node", "id": "node-1", "target_id": "node-2"}],
        }))
        .unwrap();
    assert_eq!(merged["changed"], json!(["node-2"]));
    // The alias keeps historical references resolvable.
    assert_eq!(
        store.node("node-2").unwrap()["merged_ids"],
        json!(["node-1"])
    );
    let node_view = store.read(&json!({"node_id": "node-2"})).unwrap();
    assert_eq!(node_view["total"], json!(1));
    assert_eq!(store.read(&json!({"node_id": "node-1"})).is_err(), true);
    assert!(store
        .build(&json!({
            "revision": 2,
            "operations": [{"action": "merge", "kind": "node", "id": "node-3", "target_id": "node-3"}],
        }))
        .is_err());
}

#[test]
fn marks_are_deduplicated_and_carry_the_current_prompt_version() {
    let store = temp_store("marks");
    let anchor = json!({
        "document_id": "doc-1",
        "block_id": "block-1",
        "start": 0,
        "end": 3,
        "quote": "run",
        "prefix": "p".repeat(300),
        "suffix": "s".repeat(300),
    });
    let created = store
        .marks(&json!({"action": "create", "anchor": anchor}))
        .unwrap();
    assert_eq!(created["mark"]["prompt_version"], json!(3));
    assert_eq!(
        created["mark"]["anchor"]["prefix"]
            .as_str()
            .unwrap()
            .chars()
            .count(),
        240
    );
    let repeated = store
        .marks(&json!({"action": "create", "anchor": anchor}))
        .unwrap();
    assert_eq!(repeated["mark"]["id"], created["mark"]["id"]);
    assert_eq!(
        store.marks(&json!({"action": "list"})).unwrap()["total"],
        json!(1)
    );
    assert!(store
        .marks(&json!({"action": "create", "anchor": {"document_id": "d"}}))
        .is_err());
    assert!(store
        .marks(&json!({"action": "create", "anchor": {"document_id": "d", "block_id": "b", "quote": "x", "start": 5, "end": 5}}))
        .is_err());

    assert_eq!(dictionary("Running").unwrap()["word"], json!("run"));
    assert_eq!(dictionary("matrices").unwrap()["word"], json!("matrix"));
    assert_eq!(dictionary("studies").unwrap()["word"], json!("study"));
    assert!(dictionary("two words").is_none());
    assert!(dictionary("zzzz").is_none());
}

struct FixtureModel;

#[async_trait::async_trait]
impl ModelBackend for FixtureModel {
    async fn complete(
        &self,
        _model_record_id: &str,
        messages: &[Message],
        _tools: &[ToolDefinition],
        options: &TurnOptions,
    ) -> Result<ModelTurn, RuntimeError> {
        assert!(
            matches!(&messages[0], Message::System { content } if content.contains("SELECTED TEXT"))
        );
        assert!(
            matches!(&messages[1], Message::User { content } if content.contains("<<<BEGIN SELECTED TEXT>>>"))
        );
        assert_eq!(options.max_output_tokens, Some(600));
        Ok(ModelTurn::Text {
            text: "这是选中文本的解释。".into(),
            reasoning: String::new(),
            provider_state: Value::Null,
        })
    }
}

#[tokio::test]
async fn text_actions_use_the_lexicon_or_the_configured_model() {
    let store = temp_store("text");
    let anchor = json!({"document_id": "d", "block_id": "b", "start": 0, "end": 3, "quote": "run"});
    let created = store
        .marks(&json!({"action": "create", "anchor": anchor}))
        .unwrap();
    let id = created["mark"]["id"].as_str().unwrap().to_owned();

    let translated = store
        .answer(
            &json!({"id": id, "action": "translate"}),
            None::<&dyn ModelBackend>,
            "",
            "",
        )
        .await
        .unwrap();
    assert_eq!(translated["mark"]["dictionary"]["word"], json!("run"));
    assert!(translated["mark"]["translate"]
        .as_str()
        .unwrap()
        .contains("跑；运行"));

    let explained = store
        .answer(
            &json!({"id": id, "action": "explain"}),
            Some(&FixtureModel),
            "fixture-model",
            "fixture-model",
        )
        .await
        .unwrap();
    assert_eq!(explained["mark"]["explain"], json!("这是选中文本的解释。"));

    assert!(
        store
            .answer(
                &json!({"id": id, "action": "explain"}),
                None::<&dyn ModelBackend>,
                "",
                "",
            )
            .await
            .is_err(),
        "explain without a model must not cache an empty answer"
    );

    // A deleted mark is never resurrected by an in-flight answer.
    store.marks(&json!({"action": "delete", "id": id})).unwrap();
    assert!(store
        .answer(
            &json!({"id": id, "action": "translate"}),
            None::<&dyn ModelBackend>,
            "",
            "",
        )
        .await
        .is_err());
}

#[test]
fn pins_bindings_and_layout_are_scoped_and_durable() {
    let store = temp_store("state");
    store
        .build(&json!({
            "revision": 0,
            "operations": [
                {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "课程"}},
                {"action": "create", "kind": "node", "id": "node-1", "data": {"name": "A", "type": "concept", "course_ids": ["course-a"]}}
            ],
        }))
        .unwrap();
    let mut sessions = Map::new();
    sessions.insert(
        "study:main".into(),
        json!({"id": "study:main", "title": "知识图谱"}),
    );

    let pinned = store
        .pins(
            &json!({"action": "add", "entity_type": "node", "entity_id": "node-1"}),
            &sessions,
        )
        .unwrap();
    assert_eq!(pinned["pins"][0]["title"], json!("A"));
    let pinned = store
        .pins(
            &json!({"action": "add", "kind": "session", "id": "study:main"}),
            &sessions,
        )
        .unwrap();
    assert_eq!(pinned["pins"].as_array().unwrap().len(), 2);
    assert!(
        store
            .pins(
                &json!({"action": "add", "entity_type": "node", "entity_id": "missing"}),
                &sessions
            )
            .is_err(),
        "an unknown node can never become a pin"
    );
    assert!(
        store
            .pins(
                &json!({"action": "add", "entity_type": "note", "entity_id": "note-1"}),
                &sessions
            )
            .is_err(),
        "a note pin fails closed while the note vault is absent"
    );
    let removed = store
        .pins(
            &json!({"action": "remove", "entity_type": "node", "entity_id": "node-1"}),
            &sessions,
        )
        .unwrap();
    assert_eq!(removed["pins"].as_array().unwrap().len(), 1);

    let binding = store
        .ensure_binding("node", "study:node:node-1", Some("node-1"), false)
        .unwrap();
    assert_eq!(binding["created"], json!(true));
    let repeated = store
        .ensure_binding("node", "study:node:node-1", Some("node-1"), false)
        .unwrap();
    assert_eq!(repeated["created"], json!(false));
    assert!(
        store
            .ensure_binding("map", "study:node:node-1", None, false)
            .is_err(),
        "one session cannot serve two Study resources"
    );
    assert!(store
        .primary_binding("node", Some("node-1"))
        .unwrap()
        .is_some());
    assert!(store
        .ensure_binding("node", "study:node:x", None, false)
        .is_err());

    store
        .layout(&json!({"scope": "overview", "value": {"zoom": 2}}))
        .unwrap();
    assert_eq!(
        store.layout(&json!({"scope": "overview"})).unwrap()["value"],
        json!({"zoom": 2})
    );
    assert_eq!(
        store.layout(&json!({"scope": "graph"})).unwrap()["value"],
        Value::Null
    );
    assert_eq!(store.current(None).unwrap()["current"], Value::Null);
    store.current(Some("node-1")).unwrap();
    assert_eq!(store.current(None).unwrap()["current"]["name"], json!("A"));
    assert_eq!(
        store.state("layout:overview", None).unwrap(),
        Some(json!({"zoom": 2}))
    );
}

#[test]
fn search_stays_inside_the_trusted_scope() {
    let store = temp_store("search");
    store
        .build(&json!({
            "revision": 0,
            "operations": [
                {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "课程"}},
                {"action": "create", "kind": "node", "id": "node-1", "data": {"name": "极限定义", "description": "用 ε-δ 描述趋近", "type": "concept", "course_ids": ["course-a"]}}
            ],
        }))
        .unwrap();
    let found = store.search(&json!({"query": "ε-δ"})).unwrap();
    assert_eq!(found["total"], json!(1));
    assert_eq!(found["results"][0]["target"]["kind"], json!("node"));
    assert_eq!(
        store.search(&json!({"query": "缺失"})).unwrap()["total"],
        json!(0)
    );
    assert!(store.search(&json!({"query": "x".repeat(201)})).is_err());

    // Another trusted scope shares the file but not the records.
    let other = store.scoped(StudyScope::new("u", "e", "l"));
    assert_eq!(other.read(&json!({})).unwrap()["total"], json!(0));
    assert!(matches!(
        other.read(&json!({"node_id": "node-1"})),
        Err(error) if error.message().starts_with("Unknown node")
    ));
}

#[test]
fn context_reports_the_study_prompt_and_the_selected_node() {
    let store = temp_store("context");
    store
        .build(&json!({
            "revision": 0,
            "operations": [
                {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "线性代数"}},
                {"action": "create", "kind": "node", "id": "node-1", "data": {"name": "矩阵", "type": "concept", "course_ids": ["course-a"]}}
            ],
        }))
        .unwrap();
    store.current(Some("node-1")).unwrap();
    let mut metadata = Map::new();
    metadata.insert("study_scope".into(), json!("node"));
    metadata.insert("preferred_language".into(), json!("zh"));
    let context = store
        .context(&json!({"session_id": "study:node:node-1"}), Some(&metadata))
        .unwrap();
    assert!(context["instructions"].as_str().unwrap().contains("Study"));
    assert_eq!(context["latest_context"]["preferred_language"], json!("zh"));
    assert_eq!(
        context["latest_context"]["selected_node_id"],
        json!("node-1")
    );
    assert_eq!(
        context["latest_context"]["current_course"]["name"],
        json!("线性代数")
    );
    assert!(context["request_local_late_context"]
        .as_str()
        .unwrap()
        .starts_with("[Study latest context]"));

    // A notes session deliberately ignores the mutable graph selection.
    let mut notes_metadata = Map::new();
    notes_metadata.insert("study_scope".into(), json!("notes"));
    let notes = store
        .context(&json!({"session_id": "study:notes"}), Some(&notes_metadata))
        .unwrap();
    assert_eq!(notes["latest_context"].get("selected_node_id"), None);
}

#[tokio::test]
async fn study_tools_expose_only_implemented_operations() {
    let definitions = study_tool_definitions();
    let names: Vec<&str> = definitions.iter().map(|tool| tool.name.as_str()).collect();
    assert_eq!(
        names,
        [
            "get_knowledge_net",
            "build_knowledge_net",
            "sign",
            "notes",
            "exam"
        ]
    );
    assert!(definitions
        .iter()
        .all(|tool| tool.input_schema.get("properties").is_some()));
    assert!(definitions.iter().all(|tool| !tool.description.is_empty()));

    let tools = StudyTools::new(temp_store("tools"));
    let build = ToolCall {
        id: "call-1".into(),
        name: "build_knowledge_net".into(),
        arguments: json!({
            "revision": 0,
            "operations": [
                {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "课程"}}
            ],
        }),
    };
    assert_eq!(tools.permission(&build), ToolPermission::AutoAllow);
    assert_eq!(tools.definitions(&DeviceCapabilities::default()).len(), 5);
    assert_eq!(tools.execute(&build).await.unwrap()["revision"], json!(1));

    let read = ToolCall {
        id: "call-2".into(),
        name: "get_knowledge_net".into(),
        arguments: json!({}),
    };
    assert_eq!(tools.execute(&read).await.unwrap()["total"], json!(1));

    let raw = tools
        .execute(&ToolCall {
            id: "call-3".into(),
            name: "notes".into(),
            arguments: json!({"action":"raw_list"}),
        })
        .await
        .unwrap();
    assert!(raw["raw_sources"].is_array());

    // Operations outside the manifest remain unavailable.
    assert!(tools
        .execute(&ToolCall {
            id: "call-4".into(),
            name: "study_text".into(),
            arguments: json!({}),
        })
        .await
        .is_err());
}
