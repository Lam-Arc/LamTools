//! Contract tests for the shared Study exam and assessment boundary.
//!
//! These mirror the bundled plugin's `exams.py` behaviour: public/private
//! separation, score and node-ownership validation, grading versions and
//! idempotent retries, and evidence-checked `sign` writes.

use lamtools_runtime::study::{StudyScope, StudyStore};
use serde_json::{json, Value};

fn temp_store(name: &str) -> StudyStore {
    let root = std::env::temp_dir().join(format!("lamtools-exam-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    StudyStore::open(root.join("study.db"), StudyScope::local_compatibility()).unwrap()
}

fn seed_node(store: &StudyStore, node_id: &str) {
    let revision = store.read(&json!({})).unwrap()["revision"]
        .as_i64()
        .unwrap();
    let mut operations = vec![json!({
        "action": "create",
        "kind": "node",
        "id": node_id,
        "data": {"name": node_id, "type": "concept", "course_ids": ["course-a"], "orphaned": true},
    })];
    if revision == 0 {
        operations.insert(
            0,
            json!({"action": "create", "kind": "course", "id": "course-a", "data": {"name": "课程"}}),
        );
    }
    store
        .build(&json!({ "revision": revision, "operations": operations }))
        .unwrap();
}

fn create_exam(store: &StudyStore, node_id: &str) -> String {
    let created = store
        .exam(&json!({
            "action": "create",
            "title": "第一章测验",
            "questions": [
                {
                    "type": "written",
                    "prompt": "解释极限的定义",
                    "node_ids": [node_id],
                    "answer": "ε-δ 定义",
                    "rubric": "提到 ε 与 δ 的关系",
                    "max_score": 10,
                },
                {
                    "type": "choice",
                    "prompt": "导数描述什么",
                    "options": ["变化率", "面积", "概率"],
                    "node_ids": [node_id],
                    "answer": "变化率",
                    "max_score": 10,
                }
            ],
        }))
        .unwrap();
    created["exam"]["id"].as_str().unwrap().to_owned()
}

fn grade_arguments(exam_id: &str, second_score: f64) -> Value {
    json!({
        "action": "grade",
        "exam_id": exam_id,
        "results": [
            {
                "question_id": "1",
                "state": "correct",
                "score": 10,
                "reason": "定义完整",
                "assessed_node_ids": ["node-1"],
                "incorrect_node_ids": [],
            },
            {
                "question_id": "2",
                "state": "partial",
                "score": second_score,
                "reason": "选项对但解释不足",
                "assessed_node_ids": ["node-1"],
                "incorrect_node_ids": ["node-1"],
            }
        ],
    })
}

#[test]
fn exam_creation_keeps_private_material_out_of_public_reads() {
    let store = temp_store("create");
    seed_node(&store, "node-1");
    let exam_id = create_exam(&store, "node-1");

    let public = store
        .exam(&json!({"action": "get", "exam_id": exam_id}))
        .unwrap();
    let question = &public["exam"]["questions"][0];
    assert_eq!(question["prompt"], json!("解释极限的定义"));
    assert_eq!(question["max_score"], json!(10));
    // The reference answer and rubric never appear in an ordinary read.
    assert!(question.get("answer").is_none());
    assert!(question.get("rubric").is_none());
    assert_eq!(public["exam"]["max_score"], json!(20));

    let reference = store
        .exam(&json!({"action": "reference", "exam_id": exam_id}))
        .unwrap();
    assert_eq!(
        reference["reference"]["questions"][0]["answer"],
        json!("ε-δ 定义")
    );
    assert_eq!(
        reference["reference"]["questions"][0]["rubric"],
        json!("提到 ε 与 δ 的关系")
    );

    // Help is only projected for the requested question.
    let help = store
        .exam(&json!({
            "action": "help",
            "exam_id": exam_id,
            "question_id": "1",
            "level": "hint",
            "disclosure": "先写邻域",
        }))
        .unwrap();
    assert_eq!(help["question_id"], json!("1"));
    assert_eq!(help["help"].as_array().unwrap().len(), 1);
    let scoped = store
        .exam(&json!({"action": "get", "exam_id": exam_id, "question_id": "2"}))
        .unwrap();
    assert!(scoped["exam"]["help"].get("1").is_none());

    let listed = store.exam(&json!({"action": "list"})).unwrap();
    assert_eq!(listed["total"], json!(1));
    assert_eq!(listed["exams"][0]["status"], json!("in_progress"));
}

#[test]
fn exam_creation_rejects_incomplete_and_foreign_questions() {
    let store = temp_store("create-guards");
    seed_node(&store, "node-1");
    // A missing reference answer is refused.
    assert!(store
        .exam(&json!({
            "action": "create",
            "questions": [{"type": "written", "prompt": "x", "node_ids": ["node-1"], "max_score": 1}],
        }))
        .is_err());
    // A choice question without two options is refused.
    assert!(store
        .exam(&json!({
            "action": "create",
            "questions": [{
                "type": "choice", "prompt": "x", "options": ["a"],
                "node_ids": ["node-1"], "answer": "a", "max_score": 1,
            }],
        }))
        .is_err());
    // The assessed node must exist in this scope.
    assert!(store
        .exam(&json!({
            "action": "create",
            "questions": [{
                "type": "written", "prompt": "x",
                "node_ids": ["missing"], "answer": "a", "max_score": 1,
            }],
        }))
        .is_err());
    // A non-positive max_score is outside its range.
    assert!(store
        .exam(&json!({
            "action": "create",
            "questions": [{
                "type": "written", "prompt": "x",
                "node_ids": ["node-1"], "answer": "a", "max_score": 0,
            }],
        }))
        .is_err());
}

#[test]
fn grading_requires_a_submission_and_every_question_exactly_once() {
    let store = temp_store("grading-guards");
    seed_node(&store, "node-1");
    let exam_id = create_exam(&store, "node-1");

    // Grading before submission is refused.
    assert!(store.exam(&grade_arguments(&exam_id, 5.0)).is_err());

    store
        .exam(&json!({
            "action": "save_answers",
            "exam_id": exam_id,
            "answers": {"1": "我的答案"},
            "uncertain": {"2": "不确定"},
        }))
        .unwrap();
    store
        .exam(&json!({"action": "submit", "exam_id": exam_id}))
        .unwrap();

    // Unknown question ids are refused.
    assert!(store
        .exam(&json!({"action": "grade", "exam_id": exam_id, "results": [{"question_id": "9"}]}))
        .is_err());
    // A partial results list is refused.
    assert!(store
        .exam(&json!({
            "action": "grade",
            "exam_id": exam_id,
            "results": [{
                "question_id": "1", "state": "correct", "score": 10, "reason": "ok",
                "assessed_node_ids": ["node-1"], "incorrect_node_ids": [],
            }],
        }))
        .is_err());
    // A score above the question maximum is refused.
    assert!(store
        .exam(&json!({
            "action": "grade",
            "exam_id": exam_id,
            "results": [
                {"question_id": "1", "state": "correct", "score": 11, "reason": "ok",
                 "assessed_node_ids": ["node-1"], "incorrect_node_ids": []},
                {"question_id": "2", "state": "correct", "score": 10, "reason": "ok",
                 "assessed_node_ids": ["node-1"], "incorrect_node_ids": []},
            ],
        }))
        .is_err());
}

#[test]
fn grading_derives_mastery_and_is_idempotent() {
    let store = temp_store("grading");
    seed_node(&store, "node-1");
    let exam_id = create_exam(&store, "node-1");
    store
        .exam(&json!({"action": "save_answers", "exam_id": exam_id, "answers": {"1": "答案"}}))
        .unwrap();
    store
        .exam(&json!({"action": "submit", "exam_id": exam_id}))
        .unwrap();

    let graded = store.exam(&grade_arguments(&exam_id, 5.0)).unwrap();
    assert_eq!(graded["exam"]["status"], json!("graded"));
    assert_eq!(graded["exam"]["grading_version"], json!(1));
    // 15 of 20 clears the 0.6 exam-level pass ratio.
    assert_eq!(graded["exam"]["passed"], json!(true));
    let suggestions = graded["exam"]["suggestions"].as_array().unwrap();
    assert_eq!(suggestions.len(), 1);
    assert_eq!(suggestions[0]["node_id"], json!("node-1"));
    assert_eq!(suggestions[0]["passed"], json!(true));
    assert_eq!(suggestions[0]["mastery"], json!("low"));
    // Node evidence is quoted per question.
    assert_eq!(suggestions[0]["question_ids"], json!(["1", "2"]));

    // An exact retry returns the same graded document without a new version.
    let retried = store.exam(&grade_arguments(&exam_id, 5.0)).unwrap();
    assert_eq!(retried["exam"]["grading_version"], json!(1));
    assert_eq!(
        retried["exam"]["grading_history"].as_array().unwrap().len(),
        0
    );

    // A review creates the next grading version and keeps history.
    let reviewed = store
        .exam(&json!({
            "action": "review",
            "exam_id": exam_id,
            "expected_grading_version": 1,
            "results": [
                {"question_id": "1", "state": "correct", "score": 10, "reason": "定义完整",
                 "assessed_node_ids": ["node-1"], "incorrect_node_ids": []},
                {"question_id": "2", "state": "correct", "score": 10, "reason": "选项与解释都正确",
                 "assessed_node_ids": ["node-1"], "incorrect_node_ids": []},
            ],
        }))
        .unwrap();
    assert_eq!(reviewed["exam"]["grading_version"], json!(2));
    assert_eq!(
        reviewed["exam"]["grading_history"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
    assert_eq!(reviewed["exam"]["passed"], json!(true));
    let mastery = reviewed["exam"]["suggestions"][0]["mastery"].clone();
    assert_eq!(mastery, json!("medium"));

    // A stale expected version is refused instead of silently re-grading.
    assert!(store
        .exam(&json!({
            "action": "review",
            "exam_id": exam_id,
            "expected_grading_version": 1,
            "results": [],
        }))
        .is_err());
}

#[test]
fn grading_normalizes_stale_states_and_excludes_helped_questions() {
    let store = temp_store("grading-states");
    seed_node(&store, "node-1");
    let exam_id = create_exam(&store, "node-1");
    store
        .exam(&json!({
            "action": "save_answers", "exam_id": exam_id, "answers": {"1": "答案"},
        }))
        .unwrap();
    // Help marks question 1 as not independent evidence.
    store
        .exam(&json!({
            "action": "help", "exam_id": exam_id, "question_id": "1",
            "level": "solution", "disclosure": "完整解法如下",
        }))
        .unwrap();
    store
        .exam(&json!({"action": "submit", "exam_id": exam_id}))
        .unwrap();
    let graded = store
        .exam(&json!({
            "action": "grade",
            "exam_id": exam_id,
            "results": [
                // A coarse "correct" state with a partial score is normalized.
                {"question_id": "1", "state": "correct", "score": 4, "reason": "有提示才答对",
                 "assessed_node_ids": ["node-1"], "incorrect_node_ids": ["node-1"]},
                {"question_id": "2", "state": "correct", "score": 10, "reason": "完全正确",
                 "assessed_node_ids": ["node-1"], "incorrect_node_ids": []},
            ],
        }))
        .unwrap();
    assert_eq!(graded["exam"]["results"][0]["state"], json!("partial"));
    assert_eq!(graded["exam"]["results"][0]["helped"], json!(true));
    // Only the unhelped question contributes independent mastery evidence.
    let suggestion = &graded["exam"]["suggestions"][0];
    assert_eq!(suggestion["question_ids"], json!(["2"]));
    assert_eq!(suggestion["passed"], json!(true));
    assert_eq!(suggestion["mastery"], json!("low"));
}

#[test]
fn sign_writes_mastery_only_from_graded_evidence() {
    let store = temp_store("sign");
    seed_node(&store, "node-1");
    let exam_id = create_exam(&store, "node-1");
    store
        .exam(&json!({"action": "save_answers", "exam_id": exam_id, "answers": {"1": "答案"}}))
        .unwrap();
    store
        .exam(&json!({"action": "submit", "exam_id": exam_id}))
        .unwrap();

    // Signing before grading is refused.
    assert!(store
        .sign(&json!({
            "exam_id": exam_id,
            "grading_version": 0,
            "updates": [{
                "node_id": "node-1", "passed": true, "mastery": "medium",
                "reason": "看起来会", "question_ids": ["1"],
            }],
        }))
        .is_err());

    store.exam(&grade_arguments(&exam_id, 5.0)).unwrap();
    let graded = store
        .exam(&json!({"action": "get", "exam_id": exam_id}))
        .unwrap();
    let suggestion = graded["exam"]["suggestions"][0].clone();

    // A caller-invented field is refused.
    assert!(store
        .sign(&json!({
            "exam_id": exam_id,
            "grading_version": 1,
            "updates": [{
                "node_id": "node-1", "passed": true, "mastery": "medium",
                "reason": "会了", "question_ids": ["1"], "score": 999,
            }],
        }))
        .is_err());
    // Evidence that contradicts the graded suggestion is refused.
    assert!(store
        .sign(&json!({
            "exam_id": exam_id,
            "grading_version": 1,
            "updates": [{
                "node_id": "node-1", "passed": true, "mastery": "medium",
                "reason": "会了", "question_ids": ["1"],
            }],
        }))
        .is_err());
    // A mastered pass without the matching mastery is refused.
    assert!(store
        .sign(&json!({
            "exam_id": exam_id,
            "grading_version": 1,
            "updates": [{
                "node_id": "node-1", "passed": true, "mastery": Value::Null,
                "reason": suggestion["reason"], "question_ids": suggestion["question_ids"],
            }],
        }))
        .is_err());

    let signed = store
        .sign(&json!({
            "exam_id": exam_id,
            "grading_version": 1,
            "updates": [{
                "node_id": "node-1",
                "passed": suggestion["passed"],
                "mastery": suggestion["mastery"],
                "reason": suggestion["reason"],
                "question_ids": suggestion["question_ids"],
            }],
        }))
        .unwrap();
    assert_eq!(signed["updated"], json!(1));
    assert_eq!(signed["idempotent"], json!(true));

    let node = store.node("node-1").unwrap();
    assert_eq!(node["passed"], json!(true));
    assert_eq!(node["evaluated"], json!(true));
    assert_eq!(node["assessment"], json!("pass"));
    assert_eq!(node["mastery"], suggestion["mastery"]);
    assert_eq!(node["state_revision"], json!(1));

    // An exact retry is a receipt, not a second assessment.
    let retried = store
        .sign(&json!({
            "exam_id": exam_id,
            "grading_version": 1,
            "updates": [{
                "node_id": "node-1",
                "passed": suggestion["passed"],
                "mastery": suggestion["mastery"],
                "reason": suggestion["reason"],
                "question_ids": suggestion["question_ids"],
            }],
        }))
        .unwrap();
    // The receipt replays the original result, so the retry reports the same
    // single update without writing a second assessment.
    assert_eq!(retried["updated"], json!(1));
    assert_eq!(store.node("node-1").unwrap()["state_revision"], json!(1));
}

#[test]
fn sign_refuses_helped_or_uncertain_evidence() {
    let store = temp_store("sign-evidence");
    seed_node(&store, "node-1");
    let exam_id = create_exam(&store, "node-1");
    store
        .exam(&json!({"action": "save_answers", "exam_id": exam_id, "answers": {"1": "答案"}}))
        .unwrap();
    store
        .exam(&json!({
            "action": "help", "exam_id": exam_id, "question_id": "2",
            "level": "hint", "disclosure": "提示",
        }))
        .unwrap();
    store
        .exam(&json!({"action": "submit", "exam_id": exam_id}))
        .unwrap();
    // Both questions correct, but question 2 was helped, so it is excluded.
    let graded = store
        .exam(&json!({
            "action": "grade",
            "exam_id": exam_id,
            "results": [
                {"question_id": "1", "state": "correct", "score": 10, "reason": "正确",
                 "assessed_node_ids": ["node-1"], "incorrect_node_ids": []},
                {"question_id": "2", "state": "correct", "score": 10, "reason": "提示后正确",
                 "assessed_node_ids": ["node-1"], "incorrect_node_ids": []},
            ],
        }))
        .unwrap();
    let suggestion = graded["exam"]["suggestions"][0].clone();
    assert_eq!(suggestion["question_ids"], json!(["1"]));

    // Claiming the helped question as evidence does not match the suggestion.
    assert!(store
        .sign(&json!({
            "exam_id": exam_id,
            "grading_version": 1,
            "updates": [{
                "node_id": "node-1",
                "passed": suggestion["passed"],
                "mastery": suggestion["mastery"],
                "reason": suggestion["reason"],
                "question_ids": ["1", "2"],
            }],
        }))
        .is_err());

    let signed = store
        .sign(&json!({
            "exam_id": exam_id,
            "grading_version": 1,
            "updates": [{
                "node_id": "node-1",
                "passed": suggestion["passed"],
                "mastery": suggestion["mastery"],
                "reason": suggestion["reason"],
                "question_ids": suggestion["question_ids"],
            }],
        }))
        .unwrap();
    assert_eq!(signed["updated"], json!(1));
    assert_eq!(store.node("node-1").unwrap()["passed"], json!(true));
}

#[test]
fn exam_actions_reject_unknown_ids_and_actions() {
    let store = temp_store("unknown");
    seed_node(&store, "node-1");
    assert!(store
        .exam(&json!({"action": "get", "exam_id": "missing"}))
        .is_err());
    assert!(store.exam(&json!({"action": "get"})).is_err());
    assert!(store
        .exam(&json!({"action": "open", "exam_id": "x"}))
        .is_err());
    assert!(store
        .exam(&json!({"action": "reference", "exam_id": "missing"}))
        .is_err());
    assert!(store
        .sign(&json!({"exam_id": "missing", "grading_version": 1, "updates": []}))
        .is_err());
}
