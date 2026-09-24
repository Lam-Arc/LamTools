//! Durable Study exam boundary with public/private separation and versioned grading.
//!
//! Ported from the bundled plugin's `exams.py` and the `sign` path in
//! `store.py`.  The active Study agent authors questions and grading results;
//! this boundary checks durable structure, score ranges, node ownership and
//! version/idempotency invariants only.  It never compares answer wording and
//! never re-grades the agent's semantic judgement.

use super::{identifier, StudyError, StudyResult, StudyStore};
use rusqlite::Connection;
use serde_json::{json, Map, Number, Value};
use sha2::{Digest, Sha256};

const MAX_QUESTIONS: usize = 30;
const MAX_STEP_SCORES: usize = 50;
const MAX_PRIVATE_TEXT: usize = 4_000;
const MAX_REASON_CHARS: usize = 2_000;
const MAX_SCORE: f64 = 1_000.0;
const PASS_RATIO: f64 = 0.6;

fn private_id(exam_id: &str) -> String {
    format!("exam-private:{exam_id}")
}

fn fail(message: impl Into<String>) -> StudyError {
    StudyError::new(message)
}

/// Preserve Python's int-or-float rendering so ids and scores read the same.
fn number(value: f64) -> Value {
    if value.fract() == 0.0 && value.abs() < 9.0e15 {
        Value::Number(Number::from(value as i64))
    } else {
        Number::from_f64(value)
            .map(Value::Number)
            .unwrap_or(Value::Number(Number::from(0)))
    }
}

fn score_value(
    value: Option<&Value>,
    field: &str,
    positive: bool,
    maximum: f64,
) -> StudyResult<f64> {
    let Some(Value::Number(raw)) = value else {
        return Err(fail(format!("{field} must be a number")));
    };
    let Some(result) = raw.as_f64() else {
        return Err(fail(format!("{field} must be a number")));
    };
    if !result.is_finite() || result < 0.0 || result > maximum || (positive && result <= 0.0) {
        return Err(fail(format!("{field} is outside its allowed range")));
    }
    Ok(result)
}

fn text_field(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(text)) => text.clone(),
        Some(Value::Null) | None => String::new(),
        Some(other) => other.to_string(),
    }
}

fn required_text(value: Option<&Value>) -> String {
    text_field(value).trim().to_owned()
}

fn string_list(value: Option<&Value>) -> Option<Vec<String>> {
    let Value::Array(items) = value? else {
        return None;
    };
    Some(
        items
            .iter()
            .map(|item| item.as_str().unwrap_or("").to_owned())
            .collect(),
    )
}

fn dedupe(values: Vec<String>) -> Vec<String> {
    let mut result: Vec<String> = Vec::new();
    for value in values {
        if !result.contains(&value) {
            result.push(value);
        }
    }
    result
}

fn truncate(value: &str, limit: usize) -> String {
    value.chars().take(limit).collect()
}

fn payload_hash(value: &Value) -> String {
    let encoded = serde_json::to_string(value).unwrap_or_default();
    let digest = Sha256::digest(encoded.as_bytes());
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// Project a question onto fields that are safe for the learner.
///
/// Author output is untrusted, so this allowlists instead of removing known
/// private keys: a deny-list would leak fields such as `solution`.
fn public_question(raw: &Value, question_id: &str) -> Value {
    let node_ids = string_list(raw.get("node_ids")).unwrap_or_default();
    let question_type = raw
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    let mut question = Map::new();
    question.insert("type".into(), Value::String(question_type.clone()));
    question.insert(
        "prompt".into(),
        Value::String(
            raw.get("prompt")
                .and_then(Value::as_str)
                .unwrap_or("")
                .trim()
                .to_owned(),
        ),
    );
    question.insert(
        "node_ids".into(),
        Value::Array(
            node_ids
                .iter()
                .map(|value| Value::String(value.trim().to_owned()))
                .collect(),
        ),
    );
    question.insert("id".into(), Value::String(question_id.to_owned()));
    question.insert(
        "max_score".into(),
        raw.get("max_score").cloned().unwrap_or_else(|| number(1.0)),
    );
    if question_type == "choice" {
        let options = string_list(raw.get("options")).unwrap_or_default();
        question.insert(
            "options".into(),
            Value::Array(options.into_iter().map(Value::String).collect()),
        );
    }
    Value::Object(question)
}

/// Feedback is authored by the active agent after submission and may quote the
/// reference answer when that helps the learner.
fn public_reason(value: &str) -> Value {
    Value::String(truncate(value.trim(), MAX_REASON_CHARS))
}

fn normalize_step_scores(value: Option<&Value>, question_max: f64) -> StudyResult<Vec<Value>> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    let Value::Array(items) = value else {
        return Err(fail("step_scores must be an array with at most 50 items"));
    };
    if items.is_empty() {
        return Ok(Vec::new());
    }
    if items.len() > MAX_STEP_SCORES {
        return Err(fail("step_scores must be an array with at most 50 items"));
    }
    let mut normalized = Vec::new();
    for raw in items {
        let Value::Object(entries) = raw else {
            return Err(fail("Each step score must be an object"));
        };
        let label = entries
            .get("step")
            .or_else(|| entries.get("criterion"))
            .or_else(|| entries.get("name"))
            .or_else(|| entries.get("reason"))
            .map(|value| text_field(Some(value)).trim().to_owned())
            .unwrap_or_default();
        if label.is_empty() || label.chars().count() > 1_000 {
            return Err(fail("Each step score requires a bounded step description"));
        }
        let score = score_value(entries.get("score"), "step score", false, question_max)?;
        let step_max = match entries.get("max_score").filter(|value| !value.is_null()) {
            Some(value) => Some(score_value(
                Some(value),
                "step max_score",
                true,
                question_max,
            )?),
            None => None,
        };
        if step_max.is_some_and(|maximum| score > maximum) {
            return Err(fail("A step score cannot exceed its max_score"));
        }
        let mut entry = Map::new();
        entry.insert("step".into(), Value::String(label));
        entry.insert("score".into(), number(score));
        if let Some(step_max) = step_max {
            entry.insert("max_score".into(), number(step_max));
        }
        let detail = entries
            .get("detail")
            .or_else(|| entries.get("feedback"))
            .map(|value| text_field(Some(value)).trim().to_owned())
            .unwrap_or_default();
        if !detail.is_empty() {
            entry.insert(
                "detail".into(),
                Value::String(truncate(&detail, MAX_REASON_CHARS)),
            );
        }
        normalized.push(Value::Object(entry));
    }
    Ok(normalized)
}

fn merge_images(item: &mut Map<String, Value>, images: Option<&Value>) -> StudyResult<()> {
    let Some(images) = images else { return Ok(()) };
    let Value::Array(items) = images else {
        return Err(fail("Invalid answer image references"));
    };
    if items.is_empty() {
        return Ok(());
    }
    if items.len() > 20 {
        return Err(fail("Invalid answer image references"));
    }
    let mut merged: Vec<String> = item
        .get("image_ids")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default();
    for image in items {
        let Some(image_id) = image.as_str() else {
            return Err(fail("Invalid answer image references"));
        };
        let trimmed = image_id.trim();
        if trimmed.is_empty()
            || trimmed.chars().count() > 256
            || trimmed.chars().any(|character| (character as u32) < 32)
            || trimmed.contains('/')
            || trimmed.contains('\\')
        {
            return Err(fail("Invalid answer image references"));
        }
        merged.push(trimmed.to_owned());
    }
    merged = dedupe(merged);
    item.insert(
        "image_ids".into(),
        Value::Array(merged.into_iter().map(Value::String).collect()),
    );
    Ok(())
}

fn normalize_suggestions(
    raw_suggestions: Option<&Value>,
    questions: &Map<String, Value>,
    results: &[Value],
    version: i64,
) -> StudyResult<Option<Vec<Value>>> {
    let Some(raw_suggestions) = raw_suggestions else {
        return Ok(None);
    };
    let Value::Array(items) = raw_suggestions else {
        return Err(fail("suggestions must be an array"));
    };
    let mut result_by_question: Map<String, Value> = Map::new();
    for result in results {
        if let Some(question_id) = result.get("question_id").and_then(Value::as_str) {
            result_by_question.insert(question_id.to_owned(), result.clone());
        }
    }
    let mut known_nodes: Vec<String> = Vec::new();
    for question in questions.values() {
        for node_id in string_list(question.get("node_ids")).unwrap_or_default() {
            if !known_nodes.contains(&node_id) {
                known_nodes.push(node_id);
            }
        }
    }
    let mut normalized = Vec::new();
    let mut seen: Vec<String> = Vec::new();
    for raw in items {
        let Value::Object(entries) = raw else {
            return Err(fail("Each suggestion must be an object"));
        };
        let node_id = required_text(entries.get("node_id"));
        if node_id.is_empty() || !known_nodes.contains(&node_id) || seen.contains(&node_id) {
            return Err(fail(
                "Each suggestion must identify one unique assessed node",
            ));
        }
        let Some(question_ids) = string_list(entries.get("question_ids")) else {
            return Err(fail(
                "Suggestion question_ids must reference graded questions",
            ));
        };
        if question_ids.is_empty()
            || question_ids
                .iter()
                .any(|question_id| !result_by_question.contains_key(question_id))
        {
            return Err(fail(
                "Suggestion question_ids must reference graded questions",
            ));
        }
        let question_ids = dedupe(question_ids);
        for question_id in &question_ids {
            let result = result_by_question
                .get(question_id)
                .cloned()
                .unwrap_or(Value::Null);
            let assesses = string_list(result.get("assessed_node_ids"))
                .unwrap_or_default()
                .contains(&node_id);
            let helped = result.get("helped").and_then(Value::as_bool) == Some(true);
            let uncertain = result.get("state").and_then(Value::as_str) == Some("uncertain");
            if !assesses || helped || uncertain {
                return Err(fail(
                    "Suggestions require independent assessed question evidence",
                ));
            }
        }
        let passed = entries.get("passed").and_then(Value::as_bool);
        let mastery = match entries.get("mastery") {
            None | Some(Value::Null) => None,
            Some(Value::String(value)) => Some(value.clone()),
            Some(_) => return Err(fail("Each suggestion requires passed, mastery and reason")),
        };
        let reason = required_text(entries.get("reason"));
        if passed.is_none()
            || mastery
                .as_deref()
                .is_some_and(|value| !["low", "medium", "high"].contains(&value))
            || reason.is_empty()
        {
            return Err(fail("Each suggestion requires passed, mastery and reason"));
        }
        let passed = passed.unwrap_or(false);
        if (passed && mastery.is_none()) || (!passed && mastery.is_some()) {
            return Err(fail("Suggestion mastery must match its passed state"));
        }
        normalized.push(json!({
            "node_id": node_id,
            "passed": passed,
            "mastery": mastery,
            "reason": truncate(&reason, MAX_REASON_CHARS),
            "question_ids": question_ids,
            "grading_version": version,
        }));
        seen.push(node_id);
    }
    Ok(Some(normalized))
}

pub fn public_exam(
    item: &Value,
    help_question_id: Option<&str>,
    private_questions: Option<&Value>,
) -> Value {
    let mut public = item.as_object().cloned().unwrap_or_default();
    public.remove("_last_grading_hash");
    public.remove("_grading_receipts");
    let questions: Vec<Value> = public
        .get("questions")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
        .iter()
        .enumerate()
        .filter(|(_, question)| question.is_object())
        .map(|(index, question)| {
            let question_id = question
                .get("id")
                .map(|value| text_field(Some(value)))
                .filter(|value| !value.is_empty())
                .unwrap_or_else(|| (index + 1).to_string());
            public_question(question, &question_id)
        })
        .collect();
    public.insert("questions".into(), Value::Array(questions));
    let all_help = public.remove("help").unwrap_or_else(|| json!({}));
    let all_help = all_help.as_object().cloned().unwrap_or_default();
    if let Some(private_questions) = private_questions.and_then(Value::as_object) {
        for result in public
            .get_mut("results")
            .and_then(Value::as_array_mut)
            .into_iter()
            .flatten()
        {
            if let Some(entries) = result.as_object_mut() {
                let state = entries
                    .get("state")
                    .and_then(Value::as_str)
                    .unwrap_or("uncertain");
                let reason = text_field(entries.get("reason"));
                let _ = private_questions;
                entries.insert("reason".into(), public_reason_for(state, &reason));
            }
        }
        if let Some(history) = public
            .get_mut("grading_history")
            .and_then(Value::as_array_mut)
        {
            for entry in history.iter_mut() {
                let Some(results) = entry.get_mut("results").and_then(Value::as_array_mut) else {
                    continue;
                };
                for result in results.iter_mut() {
                    let Some(entries) = result.as_object_mut() else {
                        continue;
                    };
                    let state = entries
                        .get("state")
                        .and_then(Value::as_str)
                        .unwrap_or("uncertain")
                        .to_owned();
                    let reason = text_field(entries.get("reason"));
                    entries.insert("reason".into(), public_reason_for(&state, &reason));
                }
            }
        }
    }
    if let Some(question_id) = help_question_id {
        let mut trimmed = Map::new();
        trimmed.insert(
            question_id.to_owned(),
            all_help
                .get(question_id)
                .map(|entries| {
                    Value::Array(
                        entries
                            .as_array()
                            .cloned()
                            .unwrap_or_default()
                            .into_iter()
                            .filter(|entry| entry.is_object())
                            .map(|mut entry| {
                                if let Some(entries) = entry.as_object_mut() {
                                    let disclosure = text_field(entries.get("disclosure"));
                                    entries.insert(
                                        "disclosure".into(),
                                        Value::String(truncate(&disclosure, MAX_REASON_CHARS)),
                                    );
                                }
                                entry
                            })
                            .collect(),
                    )
                })
                .unwrap_or_else(|| json!([])),
        );
        public.insert("help".into(), Value::Object(trimmed));
    }
    Value::Object(public)
}

fn public_reason_for(_state: &str, reason: &str) -> Value {
    public_reason(reason)
}

pub fn exam(store: &StudyStore, payload: &Value) -> StudyResult<Value> {
    let action = required_text(payload.get("action"));
    let connection = store.connect()?;
    let transaction = connection.unchecked_transaction()?;
    let outcome = run_exam(store, &transaction, &action, payload);
    if outcome.is_ok() {
        transaction.commit()?;
    }
    outcome
}

fn run_exam(
    store: &StudyStore,
    db: &Connection,
    action: &str,
    payload: &Value,
) -> StudyResult<Value> {
    if action == "create" {
        return create_exam(store, db, payload);
    }
    if action == "list" {
        let items = store.rows(db, "exam")?;
        let offset = int_field(payload.get("offset"), 0).max(0) as usize;
        let limit = int_field(payload.get("limit"), 30).clamp(1, 30) as usize;
        let mut listed: Vec<Value> = items
            .iter()
            .rev()
            .skip(offset)
            .take(limit)
            .map(|entry| {
                json!({
                    "id": entry.get("id").cloned().unwrap_or(Value::Null),
                    "title": entry.get("title").cloned().unwrap_or(Value::Null),
                    "status": entry.get("status").cloned().unwrap_or(Value::Null),
                    "node_ids": entry.get("node_ids").cloned().unwrap_or_else(|| json!([])),
                    "grading_version": entry.get("grading_version").cloned().unwrap_or(json!(0)),
                })
            })
            .collect();
        listed.shrink_to_fit();
        return Ok(json!({
            "exams": listed,
            "total": items.len(),
            "offset": offset,
            "limit": limit,
        }));
    }
    let exam_id = required_text(payload.get("exam_id"));
    if exam_id.is_empty() {
        return Err(fail("exam_id is required"));
    }
    let mut item = store.get(db, &exam_id, Some("exam"))?;
    let questions: Map<String, Value> = {
        let mut map = Map::new();
        for question in item
            .get("questions")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
        {
            let question_id = question
                .get("id")
                .map(|value| text_field(Some(value)))
                .unwrap_or_default();
            map.insert(question_id, question);
        }
        map
    };
    match action {
        "get" => {
            let question_id = required_text(payload.get("question_id"));
            let private = private_questions(store, db, &exam_id)?;
            return Ok(json!({
                "exam": public_exam(
                    &item,
                    if question_id.is_empty() { None } else { Some(question_id.as_str()) },
                    Some(&private),
                )
            }));
        }
        "reference" => {
            let private = private_questions(store, db, &exam_id)?;
            let private_entries = private.as_object().cloned().unwrap_or_default();
            let mut reference_questions = Vec::new();
            for (question_id, question) in &questions {
                let grading = private_entries
                    .get(question_id)
                    .and_then(Value::as_object)
                    .cloned()
                    .unwrap_or_default();
                let answer = grading.get("answer").cloned().unwrap_or_else(|| json!(""));
                let rubric = grading
                    .get("rubric")
                    .cloned()
                    .unwrap_or_else(|| answer.clone());
                let mut projected = public_question(question, question_id);
                if let Some(entries) = projected.as_object_mut() {
                    entries.insert("answer".into(), answer);
                    entries.insert("rubric".into(), rubric);
                    entries.insert(
                        "grading_steps".into(),
                        grading
                            .get("grading_steps")
                            .cloned()
                            .unwrap_or_else(|| json!([])),
                    );
                }
                reference_questions.push(projected);
            }
            return Ok(json!({
                "reference": {
                    "exam_id": exam_id,
                    "title": item.get("title").cloned().unwrap_or_else(|| json!("考试")),
                    "status": item.get("status").cloned().unwrap_or(Value::Null),
                    "grading_version": item.get("grading_version").cloned().unwrap_or(json!(0)),
                    "questions": reference_questions,
                    "student_answers": item.get("answers").cloned().unwrap_or_else(|| json!({})),
                    "image_ids": item.get("image_ids").cloned().unwrap_or_else(|| json!([])),
                    "uncertain": item.get("uncertain").cloned().unwrap_or_else(|| json!({})),
                    "help": item.get("help").cloned().unwrap_or_else(|| json!({})),
                }
            }));
        }
        "save_answers" | "save" => {
            let status = item.get("status").and_then(Value::as_str).unwrap_or("");
            if !matches!(status, "open" | "in_progress") {
                return Err(fail("Answers can only be saved before submission"));
            }
            let Some(answers) = payload.get("answers").and_then(Value::as_object) else {
                return Err(fail("answers must map question ids to draft answers"));
            };
            if answers.is_empty() {
                return Err(fail("answers must map question ids to draft answers"));
            }
            if answers.keys().any(|key| !questions.contains_key(key)) {
                return Err(fail("Answers reference unknown question ids"));
            }
            let mut merged_answers = item
                .get("answers")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            for (key, value) in answers {
                merged_answers.insert(key.clone(), value.clone());
            }
            item["answers"] = Value::Object(merged_answers);
            if let Some(uncertain) = payload.get("uncertain").and_then(Value::as_object) {
                if !uncertain.is_empty() {
                    if uncertain.keys().any(|key| !questions.contains_key(key)) {
                        return Err(fail("uncertain must reference exam question ids"));
                    }
                    let mut merged = item
                        .get("uncertain")
                        .and_then(Value::as_object)
                        .cloned()
                        .unwrap_or_default();
                    for (key, value) in uncertain {
                        merged.insert(
                            key.clone(),
                            Value::String(truncate(&text_field(Some(value)), 500)),
                        );
                    }
                    item["uncertain"] = Value::Object(merged);
                }
            }
            if let Some(entries) = item.as_object_mut() {
                merge_images(entries, payload.get("image_ids"))?;
            }
            item["status"] = json!("in_progress");
        }
        "submit" => {
            let status = item.get("status").and_then(Value::as_str).unwrap_or("");
            if !matches!(status, "open" | "in_progress") {
                return Err(fail("Only an open or in-progress exam can be submitted"));
            }
            match payload.get("answers") {
                Some(Value::Object(answers)) => {
                    if answers.keys().any(|key| !questions.contains_key(key)) {
                        return Err(fail("Answers reference unknown question ids"));
                    }
                    let mut merged = item
                        .get("answers")
                        .and_then(Value::as_object)
                        .cloned()
                        .unwrap_or_default();
                    for (key, value) in answers {
                        merged.insert(key.clone(), value.clone());
                    }
                    item["answers"] = Value::Object(merged);
                }
                Some(Value::String(text)) if !text.trim().is_empty() => {
                    let mut merged = item
                        .get("answers")
                        .and_then(Value::as_object)
                        .cloned()
                        .unwrap_or_default();
                    merged.insert("_sheet".into(), Value::String(text.trim().to_owned()));
                    item["answers"] = Value::Object(merged);
                }
                _ => {}
            }
            if let Some(entries) = item.as_object_mut() {
                merge_images(entries, payload.get("image_ids"))?;
            }
            let has_answers = item
                .get("answers")
                .and_then(Value::as_object)
                .is_some_and(|answers| !answers.is_empty());
            let has_images = item
                .get("image_ids")
                .and_then(Value::as_array)
                .is_some_and(|images| !images.is_empty());
            if !has_answers && !has_images {
                return Err(fail(
                    "Submit the answer sheet after saving text or image answers",
                ));
            }
            item["status"] = json!("submitted");
        }
        "help" => {
            let status = item.get("status").and_then(Value::as_str).unwrap_or("");
            if !matches!(status, "open" | "in_progress") {
                return Err(fail("Help is only available while answering"));
            }
            let question_id = text_field(payload.get("question_id"));
            let level = payload
                .get("level")
                .and_then(Value::as_str)
                .unwrap_or("hint")
                .to_owned();
            let disclosure = required_text(payload.get("disclosure"));
            if !questions.contains_key(&question_id) {
                return Err(fail("question_id must belong to this exam"));
            }
            if !matches!(level.as_str(), "hint" | "strategy" | "solution") || disclosure.is_empty()
            {
                return Err(fail("Help requires a valid level and disclosure"));
            }
            let mut help = item
                .get("help")
                .and_then(Value::as_object)
                .cloned()
                .unwrap_or_default();
            let mut history = help
                .get(&question_id)
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            history.push(json!({
                "id": identifier(),
                "level": level,
                "disclosure": truncate(&disclosure, MAX_REASON_CHARS),
            }));
            help.insert(question_id.clone(), Value::Array(history.clone()));
            item["help"] = Value::Object(help);
            item["status"] = json!("in_progress");
            store.put(db, "exam", &item)?;
            store.bump(db, false)?;
            return Ok(json!({
                "exam_id": exam_id,
                "question_id": question_id,
                "help": history,
            }));
        }
        "grade" | "review" => {
            grade_exam(store, db, action, payload, &exam_id, &mut item, &questions)?;
        }
        other => return Err(fail(format!("Unknown exam action: {other}"))),
    }
    let private_for_public = private_questions(store, db, &exam_id).ok();
    let public = public_exam(&item, None, private_for_public.as_ref());
    store.put(db, "exam", &item)?;
    store.bump(db, false)?;
    Ok(json!({ "exam": public }))
}

fn create_exam(store: &StudyStore, db: &Connection, payload: &Value) -> StudyResult<Value> {
    let Some(raw_questions) = payload.get("questions").and_then(Value::as_array) else {
        return Err(fail("A complete small exam requires 1–30 questions"));
    };
    if raw_questions.is_empty() || raw_questions.len() > MAX_QUESTIONS {
        return Err(fail("A complete small exam requires 1–30 questions"));
    }
    let exam_id = identifier();
    let mut public_questions = Vec::new();
    let mut private_questions: Map<String, Value> = Map::new();
    let mut all_ids: Vec<String> = Vec::new();
    for (index, raw) in raw_questions.iter().enumerate() {
        let Value::Object(entries) = raw else {
            return Err(fail("Each question must be an object"));
        };
        let mut question = entries.clone();
        let answer = question
            .remove("answer")
            .map(|value| text_field(Some(&value)).trim().to_owned())
            .unwrap_or_default();
        let rubric = question
            .remove("rubric")
            .map(|value| text_field(Some(&value)))
            .unwrap_or_else(|| answer.clone());
        let rubric = if rubric.trim().is_empty() {
            answer.clone()
        } else {
            rubric.trim().to_owned()
        };
        let grading_steps = question
            .remove("grading_steps")
            .or_else(|| question.remove("step_scores"))
            .unwrap_or_else(|| json!([]));
        let grading_steps = if grading_steps.is_null() {
            json!([])
        } else {
            grading_steps
        };
        let Value::Array(steps) = &grading_steps else {
            return Err(fail(
                "Private grading_steps must be an array with at most 50 items",
            ));
        };
        if steps.len() > MAX_STEP_SCORES {
            return Err(fail(
                "Private grading_steps must be an array with at most 50 items",
            ));
        }
        if serde_json::to_string(&grading_steps)
            .unwrap_or_default()
            .chars()
            .count()
            > 20_000
        {
            return Err(fail("Private grading_steps are too long"));
        }
        let question_max = score_value(
            question.get("max_score").or(Some(&number(1.0))),
            "question max_score",
            true,
            MAX_SCORE,
        )?;
        let node_ids = string_list(question.get("node_ids")).unwrap_or_default();
        let question_type = question.get("type").and_then(Value::as_str).unwrap_or("");
        let prompt = question
            .get("prompt")
            .map(|value| text_field(Some(value)))
            .unwrap_or_default();
        if !matches!(question_type, "choice" | "written")
            || prompt.trim().is_empty()
            || answer.is_empty()
            || node_ids.is_empty()
            || node_ids.iter().any(|node_id| node_id.trim().is_empty())
            || dedupe(node_ids.clone()).len() != node_ids.len()
        {
            return Err(fail(
                "Each question needs type, prompt, private answer/rubric and node_ids",
            ));
        }
        if answer.chars().count() > MAX_PRIVATE_TEXT || rubric.chars().count() > MAX_PRIVATE_TEXT {
            return Err(fail("Private answer and rubric are too long"));
        }
        if question_type == "choice"
            && question
                .get("options")
                .and_then(Value::as_array)
                .is_none_or(|options| options.len() < 2)
        {
            return Err(fail("Choice questions need at least two options"));
        }
        let node_ids: Vec<String> = node_ids
            .into_iter()
            .map(|node_id| node_id.trim().to_owned())
            .collect();
        for node_id in &node_ids {
            store.get(db, node_id, Some("node"))?;
            if !all_ids.contains(node_id) {
                all_ids.push(node_id.clone());
            }
        }
        let question_id = (index + 1).to_string();
        question.insert(
            "node_ids".into(),
            Value::Array(node_ids.iter().cloned().map(Value::String).collect()),
        );
        question.insert("max_score".into(), number(question_max));
        public_questions.push(public_question(
            &Value::Object(question.clone()),
            &question_id,
        ));
        private_questions.insert(
            question_id,
            json!({
                "answer": answer,
                "rubric": rubric,
                "grading_steps": grading_steps,
                "max_score": number(question_max),
            }),
        );
    }
    let mut sorted_ids = all_ids;
    sorted_ids.sort();
    let max_score: f64 = public_questions
        .iter()
        .map(|question| {
            question
                .get("max_score")
                .and_then(Value::as_f64)
                .unwrap_or_default()
        })
        .sum();
    let item = json!({
        "id": exam_id,
        "title": payload
            .get("title")
            .map(|value| text_field(Some(value)))
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| "考试".into()),
        "questions": public_questions,
        "node_ids": sorted_ids,
        "status": "open",
        "answers": {},
        "image_ids": [],
        "uncertain": {},
        "help": {},
        "results": [],
        "suggestions": [],
        "grading_version": 0,
        "grading_history": [],
        "max_score": number(max_score),
    });
    let private = Value::Object(private_questions);
    store.put(
        db,
        "exam_private",
        &json!({ "id": private_id(&exam_id), "questions": private }),
    )?;
    let public = public_exam(&item, None, Some(&private));
    store.put(db, "exam", &item)?;
    store.bump(db, false)?;
    Ok(json!({ "exam": public }))
}

fn private_questions(store: &StudyStore, db: &Connection, exam_id: &str) -> StudyResult<Value> {
    let record = store.get(db, &private_id(exam_id), Some("exam_private"))?;
    Ok(record
        .get("questions")
        .cloned()
        .unwrap_or_else(|| json!({})))
}

fn int_field(value: Option<&Value>, fallback: i64) -> i64 {
    match value {
        Some(Value::Number(raw)) => raw.as_i64().unwrap_or(fallback),
        Some(Value::String(text)) => text.trim().parse::<i64>().unwrap_or(fallback),
        _ => fallback,
    }
}

fn resolve_alias(store: &StudyStore, db: &Connection, node_id: &str) -> StudyResult<String> {
    let mut resolved = node_id.to_owned();
    let mut seen: Vec<String> = Vec::new();
    while !seen.contains(&resolved) {
        seen.push(resolved.clone());
        match store.meta(db, &format!("alias:{resolved}"))? {
            Some(alias) => {
                resolved = serde_json::from_str::<Value>(&alias)
                    .ok()
                    .and_then(|value| value.as_str().map(str::to_owned))
                    .unwrap_or(alias);
            }
            None => break,
        }
    }
    Ok(resolved)
}

#[allow(clippy::too_many_arguments)]
fn grade_exam(
    store: &StudyStore,
    db: &Connection,
    action: &str,
    payload: &Value,
    exam_id: &str,
    item: &mut Value,
    questions: &Map<String, Value>,
) -> StudyResult<()> {
    let status = item.get("status").and_then(Value::as_str).unwrap_or("");
    if action == "grade" && !matches!(status, "submitted" | "graded") {
        return Err(fail("Submit the entire exam before grading"));
    }
    if action == "review" && status != "graded" {
        return Err(fail("Only a graded exam can be reviewed"));
    }
    let Some(results) = payload.get("results").and_then(Value::as_array) else {
        return Err(fail("Grade every question exactly once"));
    };
    if results.iter().any(|result| !result.is_object()) || results.len() != questions.len() {
        return Err(fail("Grade every question exactly once"));
    }
    let graded_ids: Vec<String> = results
        .iter()
        .map(|result| text_field(result.get("question_id")))
        .collect();
    if dedupe(graded_ids.clone()).len() != questions.len()
        || graded_ids.iter().any(|id| !questions.contains_key(id))
    {
        return Err(fail("Grade every question exactly once"));
    }
    let grading_hash = payload_hash(&json!({
        "action": action,
        "results": results,
        "suggestions": payload.get("suggestions").cloned().unwrap_or(Value::Null),
    }));
    let request_id = required_text(payload.get("request_id"));
    if !request_id.is_empty()
        && (request_id.chars().count() > 256
            || request_id.chars().any(|character| (character as u32) < 32))
    {
        return Err(fail("Invalid grading request_id"));
    }
    let receipts = item
        .get("_grading_receipts")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    if !request_id.is_empty() {
        if let Some(receipt) = receipts.get(&request_id) {
            if receipt.get("payload_hash").and_then(Value::as_str) != Some(grading_hash.as_str()) {
                return Err(fail("Conflicting retry for grading request_id"));
            }
            return Ok(());
        }
    }
    if item.get("_last_grading_hash").and_then(Value::as_str) == Some(grading_hash.as_str())
        && item.get("status").and_then(Value::as_str) == Some("graded")
    {
        return Ok(());
    }
    let current_version = item
        .get("grading_version")
        .and_then(Value::as_i64)
        .unwrap_or(0);
    if let Some(expected) = payload
        .get("expected_grading_version")
        .filter(|v| !v.is_null())
    {
        if expected.as_i64() != Some(current_version) {
            return Err(fail("Grading version conflict"));
        }
    }
    if action == "grade" && status != "submitted" {
        return Err(fail("Submit the entire exam before grading"));
    }
    let private = private_questions(store, db, exam_id)?;
    let private_entries = private.as_object().cloned().unwrap_or_default();
    let mut evidence: Vec<(String, Vec<(f64, f64, String)>)> = Vec::new();
    let mut normalized = Vec::new();
    for raw in results {
        let Value::Object(entries) = raw else {
            return Err(fail("Each result must be an object"));
        };
        let question_id = text_field(entries.get("question_id"));
        let question = questions
            .get(&question_id)
            .cloned()
            .unwrap_or_else(|| json!({}));
        let question_max = score_value(
            question.get("max_score").or(Some(&number(1.0))),
            "question max_score",
            true,
            MAX_SCORE,
        )?;
        if let Some(supplied) = entries.get("max_score").filter(|value| !value.is_null()) {
            let supplied = score_value(Some(supplied), "result max_score", true, MAX_SCORE)?;
            if supplied != question_max {
                return Err(fail(format!(
                    "Result max_score does not match question {question_id}"
                )));
            }
        }
        let mut state = entries
            .get("state")
            .map(|value| text_field(Some(value)).trim().to_owned())
            .unwrap_or_default();
        let score = if state == "uncertain" {
            None
        } else {
            let score = match entries.get("score").filter(|value| !value.is_null()) {
                Some(_) => score_value(entries.get("score"), "result score", false, question_max)?,
                None => {
                    if state == "correct"
                        || entries.get("correct").and_then(Value::as_bool) == Some(true)
                    {
                        question_max
                    } else if state == "incorrect"
                        || entries.get("correct").and_then(Value::as_bool) == Some(false)
                    {
                        0.0
                    } else {
                        return Err(fail("Each certain result requires a score"));
                    }
                }
            };
            if score > question_max {
                return Err(fail(format!(
                    "Score exceeds max_score for question {question_id}"
                )));
            }
            if !state.is_empty() && !matches!(state.as_str(), "correct" | "partial" | "incorrect") {
                return Err(fail(
                    "Each result state must be correct, partial, incorrect or uncertain",
                ));
            }
            // Scores are authoritative; a stale state is normalized instead of
            // rejecting a semantically valid model grade.
            state = if score == question_max {
                "correct".into()
            } else if score == 0.0 {
                "incorrect".into()
            } else {
                "partial".into()
            };
            Some(score)
        };
        let reason = required_text(entries.get("reason"));
        if reason.is_empty() {
            return Err(fail("Each result requires grading feedback"));
        }
        let step_scores = normalize_step_scores(
            entries
                .get("step_scores")
                .or_else(|| entries.get("grading_steps"))
                .or_else(|| entries.get("steps")),
            question_max,
        )?;
        let raw_failed = entries
            .get("incorrect_node_ids")
            .cloned()
            .unwrap_or_else(|| json!([]));
        let raw_assessed = entries
            .get("assessed_node_ids")
            .cloned()
            .unwrap_or_else(|| {
                question
                    .get("node_ids")
                    .cloned()
                    .unwrap_or_else(|| json!([]))
            });
        let (Some(failed), Some(assessed)) = (
            string_list(Some(&raw_failed)),
            string_list(Some(&raw_assessed)),
        ) else {
            return Err(fail("Assessed/incorrect node ids must be arrays"));
        };
        let failed = dedupe(
            failed
                .into_iter()
                .map(|value| value.trim().to_owned())
                .filter(|value| !value.is_empty())
                .collect(),
        );
        let assessed = dedupe(
            assessed
                .into_iter()
                .map(|value| value.trim().to_owned())
                .filter(|value| !value.is_empty())
                .collect(),
        );
        let question_nodes = string_list(question.get("node_ids")).unwrap_or_default();
        if failed.iter().any(|node| !assessed.contains(node))
            || assessed.iter().any(|node| !question_nodes.contains(node))
        {
            return Err(fail("Assessed/incorrect nodes must belong to the question"));
        }
        if state != "uncertain" && assessed.is_empty() {
            return Err(fail("A certain result requires assessed node evidence"));
        }
        let (assessed, failed, step_scores) = if state == "uncertain" {
            (Vec::new(), Vec::new(), Vec::new())
        } else {
            (assessed, failed, step_scores)
        };
        let helped = item
            .get("help")
            .and_then(Value::as_object)
            .is_some_and(|help| help.contains_key(&question_id));
        if !helped && state != "uncertain" {
            let score = score.unwrap_or_default();
            for node_id in &assessed {
                let node_score = if failed.is_empty() || failed.contains(node_id) {
                    score
                } else {
                    question_max
                };
                match evidence.iter_mut().find(|(id, _)| id == node_id) {
                    Some((_, marks)) => marks.push((node_score, question_max, question_id.clone())),
                    None => evidence.push((
                        node_id.clone(),
                        vec![(node_score, question_max, question_id.clone())],
                    )),
                }
            }
        }
        let _ = private_entries.get(&question_id);
        normalized.push(json!({
            "question_id": question_id,
            "state": state,
            "correct": if state == "uncertain" { Value::Null } else { Value::Bool(state == "correct") },
            "score": score.map(number).unwrap_or(Value::Null),
            "max_score": number(question_max),
            "reason": public_reason(&reason),
            "step_scores": step_scores,
            "node_ids": question.get("node_ids").cloned().unwrap_or_else(|| json!([])),
            "assessed_node_ids": assessed,
            "incorrect_node_ids": failed,
            "helped": helped,
        }));
    }
    let version = current_version + 1;
    let suggestions = match normalize_suggestions(
        payload.get("suggestions"),
        questions,
        &normalized,
        version,
    )? {
        Some(suggestions) => suggestions,
        None => {
            let mut derived = Vec::new();
            for (node_id, marks) in &evidence {
                let earned: f64 = marks.iter().map(|mark| mark.0).sum();
                let possible: f64 = marks.iter().map(|mark| mark.1).sum();
                let ratio = if possible > 0.0 {
                    earned / possible
                } else {
                    0.0
                };
                let passed = ratio >= PASS_RATIO;
                let prior_success = store.rows(db, "assessment")?.iter().any(|assessment| {
                    assessment.get("node_id").and_then(Value::as_str) == Some(node_id.as_str())
                        && assessment
                            .get("exam_id")
                            .and_then(Value::as_str)
                            .is_some_and(|value| value != exam_id)
                        && assessment.get("passed").and_then(Value::as_bool) == Some(true)
                });
                let mastery = if ratio == 1.0 && marks.len() >= 2 && prior_success {
                    "high"
                } else if ratio >= 0.8 && marks.len() >= 2 {
                    "medium"
                } else {
                    "low"
                };
                let question_ids = dedupe(marks.iter().map(|mark| mark.2.clone()).collect());
                derived.push(json!({
                    "node_id": node_id,
                    "passed": passed,
                    "mastery": if passed { json!(mastery) } else { Value::Null },
                    "reason": format!("独立评分证据 {}/{} 分", format_score(earned), format_score(possible)),
                    "question_ids": question_ids,
                    "grading_version": version,
                }));
            }
            derived
        }
    };
    if item
        .get("grading_version")
        .and_then(Value::as_i64)
        .is_some_and(|value| value != 0)
    {
        let mut history = item
            .get("grading_history")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        history.push(json!({
            "grading_version": item.get("grading_version").cloned().unwrap_or(json!(0)),
            "results": item.get("results").cloned().unwrap_or_else(|| json!([])),
            "suggestions": item.get("suggestions").cloned().unwrap_or_else(|| json!([])),
            "score": item.get("score").cloned().unwrap_or(Value::Null),
            "earned_score": item.get("earned_score").cloned().unwrap_or(Value::Null),
            "max_score": item.get("max_score").cloned().unwrap_or(Value::Null),
        }));
        item["grading_history"] = Value::Array(history);
    }
    let counted: Vec<&Value> = normalized
        .iter()
        .filter(|result| result.get("state").and_then(Value::as_str) != Some("uncertain"))
        .collect();
    let earned_score: f64 = counted
        .iter()
        .map(|result| {
            result
                .get("score")
                .and_then(Value::as_f64)
                .unwrap_or_default()
        })
        .sum();
    let max_score: f64 = counted
        .iter()
        .map(|result| {
            result
                .get("max_score")
                .and_then(Value::as_f64)
                .unwrap_or_default()
        })
        .sum();
    let ratio = if max_score > 0.0 {
        Some(earned_score / max_score)
    } else {
        None
    };
    item["status"] = json!("graded");
    item["results"] = Value::Array(normalized);
    item["suggestions"] = Value::Array(suggestions);
    item["grading_version"] = json!(version);
    item["passed"] = Value::Bool(ratio.is_some_and(|value| value >= PASS_RATIO));
    item["score"] = ratio.map(number).unwrap_or(Value::Null);
    item["earned_score"] = number(earned_score);
    item["max_score"] = number(max_score);
    item["_last_grading_hash"] = json!(grading_hash);
    if !request_id.is_empty() {
        let mut receipts = receipts;
        receipts.insert(
            request_id,
            json!({ "payload_hash": grading_hash, "grading_version": version }),
        );
        item["_grading_receipts"] = Value::Object(receipts);
    }
    Ok(())
}

fn format_score(value: f64) -> String {
    if value.fract() == 0.0 && value.abs() < 9.0e15 {
        format!("{}", value as i64)
    } else {
        format!("{value}")
    }
}

/// Write evaluated/passed/mastery only from a graded exam suggestion.
///
/// Requires `exam_id`, the current `grading_version` and exact supporting
/// `question_ids`.  Retries are idempotent; a review replaces current evidence
/// while retaining history.
pub fn sign(store: &StudyStore, payload: &Value) -> StudyResult<Value> {
    let Some(updates) = payload.get("updates").and_then(Value::as_array) else {
        return Err(fail("Provide 1–100 node assessments"));
    };
    if updates.is_empty() || updates.len() > 100 {
        return Err(fail("Provide 1–100 node assessments"));
    }
    let exam_id = required_text(payload.get("exam_id"));
    if exam_id.is_empty() {
        return Err(fail("Exam-backed assessment requires exam_id"));
    }
    let Some(grading_version) = payload.get("grading_version").and_then(Value::as_i64) else {
        return Err(fail(
            "Exam-backed assessment requires the current grading_version",
        ));
    };
    let connection = store.connect()?;
    let transaction = connection.unchecked_transaction()?;
    let outcome = run_sign(store, &transaction, updates, &exam_id, grading_version);
    if outcome.is_ok() {
        transaction.commit()?;
    }
    outcome
}

fn run_sign(
    store: &StudyStore,
    db: &Connection,
    updates: &[Value],
    exam_id: &str,
    grading_version: i64,
) -> StudyResult<Value> {
    let exam = store.get(db, exam_id, Some("exam"))?;
    if exam.get("status").and_then(Value::as_str) != Some("graded") {
        return Err(fail("Exam has not been graded"));
    }
    if exam.get("grading_version").and_then(Value::as_i64) != Some(grading_version) {
        return Err(fail(
            "Exam-backed assessment requires the current grading_version",
        ));
    }
    let raw_suggestions = exam
        .get("suggestions")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if raw_suggestions.is_empty() {
        return Err(fail("The graded exam has no signable evidence"));
    }
    let raw_results = exam
        .get("results")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if raw_results.is_empty() {
        return Err(fail("The graded exam has no saved question evidence"));
    }
    let uncertain_questions = exam
        .get("uncertain")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();

    let mut results: Map<String, Value> = Map::new();
    for result in &raw_results {
        let Value::Object(entries) = result else {
            return Err(fail("Saved exam evidence is invalid"));
        };
        let question_id = required_text(entries.get("question_id"));
        if question_id.is_empty() || results.contains_key(&question_id) {
            return Err(fail("Saved exam evidence has duplicate question ids"));
        }
        results.insert(question_id, result.clone());
    }
    let mut suggestions: Map<String, Value> = Map::new();
    for suggestion in &raw_suggestions {
        let Value::Object(entries) = suggestion else {
            return Err(fail("Saved exam suggestion is invalid"));
        };
        let node_id = required_text(entries.get("node_id"));
        if node_id.is_empty() || suggestions.contains_key(&node_id) {
            return Err(fail("Saved exam suggestions have duplicate node ids"));
        }
        suggestions.insert(node_id, suggestion.clone());
    }

    const ALLOWED_UPDATE_KEYS: [&str; 6] = [
        "node_id",
        "passed",
        "mastery",
        "reason",
        "question_ids",
        "grading_version",
    ];
    let mut validated: Vec<Value> = Vec::new();
    let mut seen_nodes: Vec<String> = Vec::new();
    for raw_update in updates {
        let Value::Object(entries) = raw_update else {
            return Err(fail("Each assessment must be an object"));
        };
        if entries
            .keys()
            .any(|key| !ALLOWED_UPDATE_KEYS.contains(&key.as_str()))
        {
            return Err(fail("Caller-provided evidence fields are not accepted"));
        }
        let raw_node_id = required_text(entries.get("node_id"));
        if raw_node_id.is_empty() {
            return Err(fail("Each assessment requires a scoped node_id"));
        }
        let resolved_node_id = resolve_alias(store, db, &raw_node_id)?;
        if seen_nodes.contains(&resolved_node_id) {
            return Err(fail("Each node may be assessed only once per sign request"));
        }
        seen_nodes.push(resolved_node_id.clone());

        let passed = entries.get("passed").and_then(Value::as_bool);
        let mastery = match entries.get("mastery") {
            None | Some(Value::Null) => None,
            Some(Value::String(value)) => Some(value.clone()),
            Some(_) => None,
        };
        let reason = text_field(entries.get("reason"));
        if passed.is_none()
            || (passed == Some(true)
                && !mastery
                    .as_deref()
                    .is_some_and(|value| ["low", "medium", "high"].contains(&value)))
            || (passed == Some(false) && mastery.is_some())
            || reason.trim().is_empty()
        {
            return Err(fail(
                "Assessment requires passed, mastery and explicit reason",
            ));
        }
        let passed = passed.unwrap_or(false);
        if let Some(value) = entries
            .get("grading_version")
            .filter(|value| !value.is_null())
        {
            if value.as_i64() != Some(grading_version) {
                return Err(fail("Assessment grading_version does not match the exam"));
            }
        }
        let Some(question_ids) = string_list(entries.get("question_ids")) else {
            return Err(fail(
                "Exam-backed assessment requires exact supporting question_ids",
            ));
        };
        if question_ids.is_empty()
            || question_ids
                .iter()
                .any(|question_id| question_id.trim().is_empty())
        {
            return Err(fail(
                "Exam-backed assessment requires exact supporting question_ids",
            ));
        }
        let question_ids: Vec<String> = question_ids
            .into_iter()
            .map(|question_id| question_id.trim().to_owned())
            .collect();
        if dedupe(question_ids.clone()).len() != question_ids.len() {
            return Err(fail(
                "Exam-backed assessment requires exact supporting question_ids",
            ));
        }
        let suggestion = match suggestions.get(&raw_node_id) {
            Some(suggestion) => suggestion.clone(),
            None => {
                let mut matches = Vec::new();
                for candidate in suggestions.values() {
                    let candidate_node = required_text(candidate.get("node_id"));
                    if resolve_alias(store, db, &candidate_node)? == resolved_node_id {
                        matches.push(candidate.clone());
                    }
                }
                if matches.len() != 1 {
                    return Err(fail("Assessment must match the graded exam suggestion"));
                }
                matches.remove(0)
            }
        };
        let suggestion_node_id = required_text(suggestion.get("node_id"));
        let Some(expected_question_ids) = string_list(suggestion.get("question_ids")) else {
            return Err(fail("Saved exam suggestion has invalid question evidence"));
        };
        if expected_question_ids.is_empty()
            || expected_question_ids
                .iter()
                .any(|question_id| question_id.trim().is_empty())
        {
            return Err(fail("Saved exam suggestion has invalid question evidence"));
        }
        let expected_question_ids: Vec<String> = expected_question_ids
            .into_iter()
            .map(|question_id| question_id.trim().to_owned())
            .collect();
        let mut sorted_expected = expected_question_ids.clone();
        let mut sorted_given = question_ids.clone();
        sorted_expected.sort();
        sorted_given.sort();
        if dedupe(expected_question_ids.clone()).len() != expected_question_ids.len()
            || sorted_expected != sorted_given
        {
            return Err(fail(
                "Exam-backed assessment requires exact supporting question_ids",
            ));
        }
        let suggestion_mastery = match suggestion.get("mastery") {
            None | Some(Value::Null) => None,
            Some(Value::String(value)) => Some(value.clone()),
            Some(_) => None,
        };
        if suggestion.get("grading_version").and_then(Value::as_i64) != Some(grading_version)
            || suggestion.get("passed").and_then(Value::as_bool) != Some(passed)
            || suggestion_mastery != mastery
            || text_field(suggestion.get("reason")).trim() != reason.trim()
        {
            return Err(fail(
                "Conflicting retry: assessment must match the graded exam suggestion",
            ));
        }
        let evidence_node_ids = [
            raw_node_id.clone(),
            suggestion_node_id,
            resolved_node_id.clone(),
        ];
        for question_id in &expected_question_ids {
            let Some(result) = results.get(question_id) else {
                return Err(fail("Question evidence does not belong to the graded exam"));
            };
            let state = result.get("state").and_then(Value::as_str).unwrap_or("");
            if !matches!(state, "correct" | "partial" | "incorrect") {
                return Err(fail(
                    "Uncertain or unreadable question evidence cannot be signed",
                ));
            }
            let correct = result.get("correct").and_then(Value::as_bool);
            if correct != Some(state == "correct") {
                return Err(fail("Saved exam evidence has an invalid correctness state"));
            }
            if result.get("helped").and_then(Value::as_bool) != Some(false)
                || uncertain_questions.contains_key(question_id)
            {
                return Err(fail(
                    "Helped or uncertain question evidence cannot be signed",
                ));
            }
            let (Some(assessed_node_ids), Some(incorrect_node_ids), Some(question_node_ids)) = (
                string_list(result.get("assessed_node_ids")),
                string_list(result.get("incorrect_node_ids")),
                string_list(result.get("node_ids")),
            ) else {
                return Err(fail("Saved exam evidence has invalid node ids"));
            };
            if assessed_node_ids
                .iter()
                .chain(incorrect_node_ids.iter())
                .chain(question_node_ids.iter())
                .any(|node_id| node_id.trim().is_empty())
            {
                return Err(fail("Saved exam evidence has invalid node ids"));
            }
            let assessed: Vec<String> = assessed_node_ids
                .into_iter()
                .map(|value| value.trim().to_owned())
                .collect();
            let incorrect: Vec<String> = incorrect_node_ids
                .into_iter()
                .map(|value| value.trim().to_owned())
                .collect();
            let question_nodes: Vec<String> = question_node_ids
                .into_iter()
                .map(|value| value.trim().to_owned())
                .collect();
            if !evidence_node_ids
                .iter()
                .any(|node_id| assessed.contains(node_id))
                || !evidence_node_ids
                    .iter()
                    .any(|node_id| question_nodes.contains(node_id))
            {
                return Err(fail("Question evidence does not assess this node"));
            }
            if assessed
                .iter()
                .any(|node_id| !question_nodes.contains(node_id))
            {
                return Err(fail("Saved exam evidence has invalid assessed node ids"));
            }
            if incorrect.iter().any(|node_id| !assessed.contains(node_id)) {
                return Err(fail("Saved exam evidence has invalid incorrect node ids"));
            }
            if state == "correct" && !incorrect.is_empty() {
                return Err(fail(
                    "Saved exam evidence is inconsistent with a correct result",
                ));
            }
        }
        let node = store.get(db, &resolved_node_id, Some("node"))?;
        if !node.get("deleted_at").is_none_or(Value::is_null) {
            return Err(fail("Cannot assess a deleted node"));
        }
        validated.push(json!({
            "node_id": resolved_node_id,
            "passed": passed,
            "mastery": if passed { mastery.map(Value::String).unwrap_or(Value::Null) } else { Value::Null },
            "reason": reason.trim(),
            "question_ids": expected_question_ids,
            "grading_version": grading_version,
        }));
    }
    validated.sort_by_key(|update| {
        update
            .get("node_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned()
    });
    let canonical_payload = json!({
        "exam_id": exam_id,
        "grading_version": grading_version,
        "updates": validated,
    });
    let request_hash = {
        let encoded = serde_json::to_string(&canonical_payload).unwrap_or_default();
        Sha256::digest(encoded.as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    };
    let receipt: Option<String> = db
        .query_row(
            "SELECT result_json FROM study_sign_receipts WHERE scope_key=?1 AND request_hash=?2",
            rusqlite::params![store.scope().key(), request_hash],
            |row| row.get(0),
        )
        .ok();
    if let Some(result_json) = receipt {
        return serde_json::from_str(&result_json)
            .map_err(|error| StudyError::new(error.to_string()));
    }
    let mut plans: Vec<(Value, Option<Value>, String)> = Vec::new();
    for update in &validated {
        let node_id = update
            .get("node_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        let assessment_id = format!("assessment:{exam_id}:{node_id}");
        let previous = store
            .get(db, &assessment_id, Some("assessment"))
            .ok()
            .filter(|value| !value.is_null());
        if let Some(previous) = &previous {
            if previous.get("grading_version").and_then(Value::as_i64) == Some(grading_version) {
                let comparable = [
                    "node_id",
                    "passed",
                    "mastery",
                    "reason",
                    "question_ids",
                    "grading_version",
                ];
                let same = comparable
                    .iter()
                    .all(|key| previous.get(*key) == update.get(*key))
                    && previous.get("exam_id").and_then(Value::as_str) == Some(exam_id);
                if !same {
                    return Err(fail("Conflicting retry for the same exam grading version"));
                }
            }
        }
        plans.push((update.clone(), previous, assessment_id));
    }
    let mut changed = 0usize;
    for (update, previous, assessment_id) in plans {
        if previous
            .as_ref()
            .and_then(|value| value.get("grading_version"))
            .and_then(Value::as_i64)
            == Some(grading_version)
        {
            continue;
        }
        let node_id = update
            .get("node_id")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        let mut node = store.get(db, &node_id, Some("node"))?;
        if !node.get("deleted_at").is_none_or(Value::is_null) {
            return Err(fail("Cannot assess a deleted node"));
        }
        let passed = update.get("passed").and_then(Value::as_bool) == Some(true);
        let state_revision = node
            .get("state_revision")
            .and_then(Value::as_i64)
            .unwrap_or(0);
        if let Some(entries) = node.as_object_mut() {
            entries.insert("passed".into(), Value::Bool(passed));
            entries.insert(
                "mastery".into(),
                update.get("mastery").cloned().unwrap_or(Value::Null),
            );
            entries.insert(
                "assessment".into(),
                Value::String(if passed { "pass" } else { "fail" }.into()),
            );
            entries.insert("evaluated".into(), Value::Bool(true));
            entries.insert("state_revision".into(), json!(state_revision + 1));
        }
        store.put(db, "node", &node)?;
        let mut history = previous
            .as_ref()
            .and_then(|value| value.get("history"))
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        if let Some(previous) = &previous {
            if let Some(entries) = previous.as_object() {
                let mut record = Map::new();
                for (key, value) in entries {
                    if key != "id" && key != "history" {
                        record.insert(key.clone(), value.clone());
                    }
                }
                history.push(Value::Object(record));
            }
        }
        let mut record = update.as_object().cloned().unwrap_or_default();
        record.insert("id".into(), Value::String(assessment_id));
        record.insert("exam_id".into(), Value::String(exam_id.to_owned()));
        record.insert("history".into(), Value::Array(history));
        store.put(db, "assessment", &Value::Object(record))?;
        changed += 1;
    }
    if changed > 0 {
        store.bump(db, true)?;
        store.push_outbox(
            db,
            "study.mastery.changed",
            &json!({ "exam_id": exam_id, "updated": changed }),
        )?;
    }
    let result = json!({
        "updated": changed,
        "revision": store.revision(db)?,
        "state_revision": store.state_revision(db)?,
        "idempotent": true,
        "scope": store.scope().public(),
    });
    db.execute(
        "INSERT INTO study_sign_receipts(scope_key,request_hash,payload_hash,result_json)
         VALUES(?1,?2,?3,?4)",
        rusqlite::params![
            store.scope().key(),
            request_hash,
            request_hash,
            serde_json::to_string(&result).unwrap_or_default()
        ],
    )
    .map_err(|error| StudyError::new(error.to_string()))?;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A graded question map plus one result per question, in the shape the
    /// suggestion validator consumes.
    fn graded(
        node_ids: &[&str],
        state: &str,
        assessed: &[&str],
        helped: bool,
    ) -> (Map<String, Value>, Vec<Value>) {
        let mut questions = Map::new();
        questions.insert(
            "q1".into(),
            json!({
                "type": "written",
                "prompt": "解释一下",
                "node_ids": node_ids,
                "answer": "参考答案：因为并发",
                "rubric": "至少提到并发",
                "max_score": 10,
            }),
        );
        let results = vec![json!({
            "question_id": "q1",
            "state": state,
            "assessed_node_ids": assessed,
            "helped": helped,
        })];
        (questions, results)
    }

    #[test]
    fn score_values_reject_non_numbers_and_stay_inside_the_bound() {
        assert!(score_value(None, "score", false, 10.0).is_err());
        assert!(score_value(Some(&json!("7")), "score", false, 10.0).is_err());
        assert!(score_value(Some(&json!(-1)), "score", false, 10.0).is_err());
        assert!(score_value(Some(&json!(10.5)), "score", false, 10.0).is_err());
        // A positive score cannot be zero; a score that may be zero can.
        assert!(score_value(Some(&json!(0)), "score", true, 10.0).is_err());
        assert_eq!(score_value(Some(&json!(0)), "score", false, 10.0).unwrap(), 0.0);
        assert_eq!(score_value(Some(&json!(10)), "score", true, 10.0).unwrap(), 10.0);
    }

    #[test]
    fn the_public_question_projection_drops_every_grading_field() {
        let raw = json!({
            "type": "choice",
            "prompt": "选一个",
            "node_ids": ["n1"],
            "options": ["甲", "乙"],
            "answer": "甲",
            "rubric": "选甲给满分",
            "max_score": 5,
        });
        let public = public_question(&raw, "q1");
        let object = public.as_object().expect("object");
        for leaked in ["answer", "rubric"] {
            assert!(
                !object.contains_key(leaked),
                "the public projection must not carry '{leaked}'"
            );
        }
        assert_eq!(object["id"], json!("q1"));
        assert_eq!(object["options"], json!(["甲", "乙"]));
        assert_eq!(object["max_score"], json!(5));

        // A written question has no options key at all, rather than an empty one.
        let written = public_question(&json!({"type": "written", "prompt": "写"}), "q2");
        assert!(written.as_object().unwrap().get("options").is_none());
        // The default is one point; compare numerically rather than by the
        // JSON number representation.
        assert_eq!(written["max_score"].as_f64(), Some(1.0));
    }

    #[test]
    fn step_scores_are_bounded_by_the_question_maximum() {
        assert!(normalize_step_scores(Some(&json!("nope")), 10.0).is_err());
        assert!(normalize_step_scores(Some(&json!([1])), 10.0).is_err());
        assert!(
            normalize_step_scores(Some(&json!([{"step": "", "score": 1}])), 10.0).is_err(),
            "a step score needs a bounded description"
        );
        assert!(
            normalize_step_scores(Some(&json!([{"step": "思路", "score": 11}])), 10.0).is_err(),
            "a step cannot exceed its question's max_score"
        );
        let oversized = Value::Array(
            (0..(MAX_STEP_SCORES + 1))
                .map(|index| json!({"step": format!("s{index}"), "score": 1}))
                .collect(),
        );
        assert!(normalize_step_scores(Some(&oversized), 10.0).is_err());

        assert!(normalize_step_scores(None, 10.0).unwrap().is_empty());
        let normalized = normalize_step_scores(
            Some(&json!([{"criterion": "思路", "score": 4, "max_score": 5}])),
            10.0,
        )
        .expect("a valid step score is accepted");
        assert_eq!(normalized.len(), 1);
    }

    #[test]
    fn suggestions_require_independent_assessed_evidence() {
        // Marking the node without assessing it, or grading a helped or
        // uncertain answer, is not independent evidence.
        let (questions, results) = graded(&["n1"], "correct", &[], false);
        let error = normalize_suggestions(
            Some(&json!([{"node_id": "n1", "question_ids": ["q1"], "passed": true, "mastery": "high", "reason": "会了"}])),
            &questions,
            &results,
            1,
        )
        .expect_err("unassessed evidence must be rejected");
        assert!(error.to_string().contains("independent assessed question evidence"));

        let (_questions, helped) = graded(&["n1"], "correct", &["n1"], true);
        assert!(normalize_suggestions(
            Some(&json!([{"node_id": "n1", "question_ids": ["q1"], "passed": true, "mastery": "high", "reason": "会了"}])),
            &questions,
            &helped,
            1,
        )
        .is_err());

        let (_questions, uncertain) = graded(&["n1"], "uncertain", &["n1"], false);
        assert!(normalize_suggestions(
            Some(&json!([{"node_id": "n1", "question_ids": ["q1"], "passed": true, "mastery": "high", "reason": "会了"}])),
            &questions,
            &uncertain,
            1,
        )
        .is_err());

        // A graded, unassisted, assessed question is acceptable.
        let (_questions, solid) = graded(&["n1"], "correct", &["n1"], false);
        let accepted = normalize_suggestions(
            Some(&json!([{"node_id": "n1", "question_ids": ["q1"], "passed": true, "mastery": "high", "reason": "会了"}])),
            &questions,
            &solid,
            1,
        )
        .expect("independent evidence is accepted")
        .expect("some suggestions");
        assert_eq!(accepted.len(), 1);
        assert_eq!(accepted[0]["node_id"], json!("n1"));
    }

    #[test]
    fn suggestions_must_reference_graded_questions_and_known_nodes() {
        let (questions, results) = graded(&["n1"], "correct", &["n1"], false);
        for bad in [
            json!([{"node_id": "n9", "question_ids": ["q1"], "passed": true, "mastery": "high", "reason": "r"}]),
            json!([{"node_id": "n1", "question_ids": ["q404"], "passed": true, "mastery": "high", "reason": "r"}]),
            json!([{"node_id": "n1", "question_ids": [], "passed": true, "mastery": "high", "reason": "r"}]),
            // Mastery has to agree with the pass verdict in both directions.
            json!([{"node_id": "n1", "question_ids": ["q1"], "passed": true, "mastery": null, "reason": "r"}]),
            json!([{"node_id": "n1", "question_ids": ["q1"], "passed": false, "mastery": "high", "reason": "r"}]),
        ] {
            assert!(
                normalize_suggestions(Some(&bad), &questions, &results, 1).is_err(),
                "expected rejection for {bad}"
            );
        }
        assert!(normalize_suggestions(Some(&json!({})), &questions, &results, 1).is_err());
        assert!(normalize_suggestions(None, &questions, &results, 1).unwrap().is_none());
    }

    #[test]
    fn whole_scores_print_without_a_decimal_point() {
        assert_eq!(format_score(0.0), "0");
        assert_eq!(format_score(7.0), "7");
        assert_eq!(format_score(7.5), "7.5");
    }
}
