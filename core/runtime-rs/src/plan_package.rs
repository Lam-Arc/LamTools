//! Durable plan packages (方案) for the embedded host.
//!
//! The desktop keeps these in `runtime/plan_package.py`; this module answers the
//! same payloads with the same wording and the same rules, in a small SQLite
//! database the mobile host opens beside its other host databases.
//! `core/protocol/plan-package-v1-fixtures.json`
//! is the contract of record and both hosts run it, so a field, a default or a
//! refusal cannot drift to one side.
//!
//! Semantics kept identical to the desktop:
//!
//! * **save is a patch** — a field the payload does not mention keeps its stored
//!   value, and a plan that does not exist yet takes defaults for the rest;
//! * **`expected_revision` is an optimistic-concurrency token** — given, it must
//!   match; absent, the write is not checked;
//! * **history only grows** — every accepted save records a snapshot, and
//!   `revert` writes old content as a new revision;
//! * **deletion is soft** — the record and its history survive, `restore` brings
//!   it back.
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Map, Value};
use std::collections::BTreeSet;
use std::path::Path;

pub const PLAN_STATUSES: [&str; 5] = ["draft", "ready", "executing", "done", "archived"];
const STEP_STATUSES: [&str; 6] = [
    "pending",
    "in_progress",
    "completed",
    "blocked",
    "skipped",
    "replaced",
];
const QUESTION_STATUSES: [&str; 2] = ["open", "answered"];
const RISK_SEVERITIES: [&str; 3] = ["low", "medium", "high"];
const DOC_KINDS: [&str; 6] = ["research", "spec", "design", "plan", "tasks", "notes"];
const PLAN_ID_PREFIX: &str = "plan_";

fn allowed_transitions(status: &str) -> &'static [&'static str] {
    match status {
        "draft" => &["ready", "archived"],
        "ready" => &["draft", "executing", "archived"],
        "executing" => &["done", "archived"],
        "done" => &["archived"],
        _ => &[],
    }
}

fn assert_status_transition(current: &str, target: &str) -> Result<(), String> {
    if current == target {
        return Ok(());
    }
    if allowed_transitions(current).contains(&target) {
        return Ok(());
    }
    Err(format!(
        "invalid plan status transition: {current} -> {target}"
    ))
}

/// String like the desktop's `_text`: trim, and treat a missing value as empty.
fn text(value: Option<&Value>) -> String {
    match value {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(item)) => item.trim().to_owned(),
        Some(other) => other.to_string().trim().to_owned(),
    }
}

fn text_list(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::Array(items)) => items
            .iter()
            .map(|item| text(Some(item)))
            .filter(|item| !item.is_empty())
            .collect(),
        _ => Vec::new(),
    }
}

/// The first non-empty of several spellings (`plan_id`, `planId`, `id`).
fn first_text(payload: &Map<String, Value>, keys: &[&str]) -> String {
    for key in keys {
        if let Some(value) = payload.get(*key) {
            let candidate = text(Some(value));
            if !candidate.is_empty() {
                return candidate;
            }
        }
    }
    String::new()
}

fn object_of(value: Option<&Value>) -> Map<String, Value> {
    match value {
        Some(Value::Object(map)) => map.clone(),
        _ => Map::new(),
    }
}

fn entries(value: Option<&Value>) -> Vec<Value> {
    match value {
        Some(Value::Array(items)) => items.clone(),
        _ => Vec::new(),
    }
}

/// Patch one nested object: keys the payload omits keep the stored value.
fn merge_object(existing: Map<String, Value>, incoming: Option<&Value>) -> Map<String, Value> {
    let mut merged = existing;
    if let Some(Value::Object(map)) = incoming {
        for (key, value) in map {
            merged.insert(key.clone(), value.clone());
        }
    }
    merged
}

/// A stored group, or the defaults a fresh plan starts from.
fn group(base: &Map<String, Value>, key: &str, defaults: Value) -> Map<String, Value> {
    match base.get(key).and_then(Value::as_object) {
        Some(map) => map.clone(),
        None => defaults.as_object().cloned().unwrap_or_default(),
    }
}

fn pick<'a>(
    payload: &'a Map<String, Value>,
    base: &'a Map<String, Value>,
    key: &str,
) -> Option<&'a Value> {
    payload.get(key).or_else(|| base.get(key))
}

fn pick_text(payload: &Map<String, Value>, base: &Map<String, Value>, key: &str) -> String {
    text(pick(payload, base, key))
}

fn normalize_step(raw: &Value, index: usize) -> Result<Value, String> {
    let source = object_of(Some(raw));
    let id = match text(source.get("id")) {
        value if value.is_empty() => format!("s{}", index + 1),
        value => value,
    };
    let description = text(source.get("description"));
    if description.is_empty() {
        return Err(format!("plan step description is required: {id}"));
    }
    let status = match text(source.get("status")) {
        value if value.is_empty() => "pending".to_owned(),
        value => value,
    };
    if !STEP_STATUSES.contains(&status.as_str()) {
        return Err(format!("invalid plan step status: {status}"));
    }
    Ok(json!({
        "id": id,
        "description": description,
        "deliverables": text_list(source.get("deliverables")),
        "status": status,
    }))
}

fn normalize_question(raw: &Value, index: usize) -> Result<Option<Value>, String> {
    let source = object_of(Some(raw));
    let question = text(source.get("question"));
    if question.is_empty() {
        // A question with no text carries nothing; the panel's empty row is
        // dropped rather than refused.
        return Ok(None);
    }
    let id = match text(source.get("id")) {
        value if value.is_empty() => format!("q{}", index + 1),
        value => value,
    };
    let status = match text(source.get("status")) {
        value if value.is_empty() => "open".to_owned(),
        value => value,
    };
    if !QUESTION_STATUSES.contains(&status.as_str()) {
        return Err(format!("invalid plan question status: {status}"));
    }
    Ok(Some(json!({
        "id": id,
        "question": question,
        "status": status,
        "answer": text(source.get("answer")),
    })))
}

fn normalize_risk(raw: &Value) -> Result<Option<Value>, String> {
    let source = object_of(Some(raw));
    let risk = text(source.get("risk"));
    if risk.is_empty() {
        return Ok(None);
    }
    let severity = match text(source.get("severity")) {
        value if value.is_empty() => "medium".to_owned(),
        value => value,
    };
    if !RISK_SEVERITIES.contains(&severity.as_str()) {
        return Err(format!("invalid plan risk severity: {severity}"));
    }
    Ok(Some(json!({
        "risk": risk,
        "severity": severity,
        "mitigation": text(source.get("mitigation")),
    })))
}

fn normalize_doc(raw: &Value) -> Result<Option<Value>, String> {
    let source = object_of(Some(raw));
    let raw_path = text(source.get("path"));
    if raw_path.is_empty() {
        return Ok(None);
    }
    let path = raw_path.replace('\\', "/");
    let segments: Vec<&str> = path
        .split('/')
        .filter(|segment| !segment.is_empty() && *segment != ".")
        .collect();
    let mut chars = path.chars();
    let drive_letter = matches!((chars.next(), chars.next()), (Some(first), Some(':')) if first.is_ascii_alphabetic());
    if path.starts_with('/') || drive_letter || segments.contains(&"..") || segments.is_empty() {
        return Err(format!("plan doc path must be relative: {raw_path}"));
    }
    let kind = match text(source.get("kind")) {
        value if value.is_empty() => "notes".to_owned(),
        value => value,
    };
    if !DOC_KINDS.contains(&kind.as_str()) {
        return Err(format!("unknown plan doc kind: {kind}"));
    }
    Ok(Some(json!({
        "path": path,
        "kind": kind,
        "title": text(source.get("title")),
    })))
}

fn normalize_execution(value: Option<&Value>) -> Result<Value, String> {
    match value {
        None | Some(Value::Null) => Ok(Value::Null),
        Some(other) => {
            let source = object_of(Some(other));
            let thread_id = match text(source.get("thread_id")) {
                value if value.is_empty() => text(source.get("threadId")),
                value => value,
            };
            if thread_id.is_empty() {
                return Err("plan execution thread is required".to_owned());
            }
            let revision = match source.get("revision") {
                None | Some(Value::Null) => 0,
                Some(Value::Number(number)) => number.as_i64().unwrap_or(0).max(0),
                Some(Value::String(item)) if item.trim().is_empty() => 0,
                Some(_) => return Err("plan execution revision must be a number".to_owned()),
            };
            let started_at = match text(source.get("started_at")) {
                value if value.is_empty() => text(source.get("startedAt")),
                value => value,
            };
            Ok(json!({
                "thread_id": thread_id,
                "revision": revision,
                "started_at": started_at,
            }))
        }
    }
}

/// Merge a save payload onto the stored plan and validate the result.
///
/// The returned object is the package in the shared shape: `body()` plus the
/// host-local envelope (`project_id`, `source`, `revision`, timestamps).
fn normalize(
    payload: &Map<String, Value>,
    existing: Option<&Value>,
    source: &str,
) -> Result<Value, String> {
    let mut base = match existing {
        Some(value) => object_of(Some(value)),
        None => Map::new(),
    };
    if existing.is_some() {
        // A patch still has to keep the host-local project when it does not
        // name one.
        base.insert(
            "project_id".into(),
            base.get("project_id").cloned().unwrap_or(Value::Null),
        );
    }
    let requirement = merge_object(
        group(
            &base,
            "requirement",
            json!({"restatement": "", "success_looks_like": "", "non_goals": [], "assumptions": []}),
        ),
        payload.get("requirement"),
    );
    let approach = merge_object(
        group(
            &base,
            "approach",
            json!({"chosen": "", "why": "", "rejected": []}),
        ),
        payload.get("approach"),
    );
    let checklist = merge_object(
        group(
            &base,
            "checklist",
            json!({"design_summary": "", "steps": [], "files": []}),
        ),
        payload.get("checklist"),
    );
    let goal = merge_object(
        group(
            &base,
            "goal",
            json!({"objective": "", "completion_criteria": []}),
        ),
        payload.get("goal"),
    );

    let project_id = pick_text(payload, &base, "project_id");
    if project_id.is_empty() {
        return Err("plan project is required".to_owned());
    }
    let title = pick_text(payload, &base, "title");
    if title.is_empty() {
        return Err("plan title is required".to_owned());
    }
    let restatement = text(requirement.get("restatement"));
    if restatement.is_empty() {
        return Err("plan requirement is required".to_owned());
    }
    let chosen = text(approach.get("chosen"));
    if chosen.is_empty() {
        return Err("plan approach is required".to_owned());
    }

    let mut steps: Vec<Value> = Vec::new();
    let mut seen: BTreeSet<String> = BTreeSet::new();
    for (index, raw) in entries(checklist.get("steps")).iter().enumerate() {
        let step = normalize_step(raw, index)?;
        let id = text(step.get("id"));
        if !seen.insert(id.clone()) {
            return Err(format!("duplicate plan step id: {id}"));
        }
        steps.push(step);
    }

    let mut questions: Vec<Value> = Vec::new();
    for (index, raw) in entries(pick(payload, &base, "open_questions"))
        .iter()
        .enumerate()
    {
        if let Some(question) = normalize_question(raw, index)? {
            questions.push(question);
        }
    }

    let mut risks: Vec<Value> = Vec::new();
    for raw in entries(pick(payload, &base, "risks")).iter() {
        if let Some(risk) = normalize_risk(raw)? {
            risks.push(risk);
        }
    }

    let mut docs: Vec<Value> = Vec::new();
    for raw in entries(pick(payload, &base, "docs")).iter() {
        if let Some(doc) = normalize_doc(raw)? {
            docs.push(doc);
        }
    }

    let goal_objective = text(goal.get("objective"));
    let goal_criteria = text_list(goal.get("completion_criteria"));
    if goal_objective.is_empty() && !goal_criteria.is_empty() {
        return Err("plan goal objective is required".to_owned());
    }

    let status = match pick_text(payload, &base, "status") {
        value if value.is_empty() => "draft".to_owned(),
        value => value,
    };
    if !PLAN_STATUSES.contains(&status.as_str()) {
        return Err(format!("invalid plan status: {status}"));
    }
    let execution = normalize_execution(pick(payload, &base, "execution"))?;

    let now = now_iso();
    let (id, revision, created_at, deleted_at) = match existing {
        Some(_) => (
            base.get("plan_id").map(|value| text(Some(value))).unwrap_or_default(),
            base.get("revision").and_then(Value::as_i64).unwrap_or(1) + 1,
            text(base.get("created_at")),
            base.get("deleted_at").cloned().unwrap_or(Value::Null),
        ),
        None => (
            match first_text(payload, &["plan_id", "planId", "id"]) {
                value if value.is_empty() => format!("{PLAN_ID_PREFIX}{}", short_id()),
                value => value,
            },
            1,
            now.clone(),
            Value::Null,
        ),
    };

    let mut package = json!({
        "schema_version": 1,
        "plan_id": id,
        "title": title,
        "status": status,
        "summary": pick_text(payload, &base, "summary"),
        "requirement": {
            "restatement": restatement,
            "success_looks_like": text(requirement.get("success_looks_like")),
            "non_goals": text_list(requirement.get("non_goals")),
            "assumptions": text_list(requirement.get("assumptions")),
        },
        "open_questions": questions,
        "approach": {
            "chosen": chosen,
            "why": text(approach.get("why")),
            "rejected": entries(approach.get("rejected"))
                .iter()
                .filter_map(|raw| {
                    let source = object_of(Some(raw));
                    let option = text(source.get("option"));
                    if option.is_empty() {
                        return None;
                    }
                    Some(json!({"option": option, "why": text(source.get("why"))}))
                })
                .collect::<Vec<Value>>(),
        },
        "checklist": {
            "design_summary": text(checklist.get("design_summary")),
            "steps": steps,
            "files": text_list(checklist.get("files")),
        },
        "goal": {
            "objective": goal_objective,
            "completion_criteria": goal_criteria,
        },
        "risks": risks,
        "docs": docs,
        "execution": execution,
        "project_id": project_id,
        "source": source,
        "revision": revision,
        "created_at": created_at,
        "updated_at": now,
        "deleted_at": deleted_at,
    });
    Ok(package)
}

fn short_id() -> String {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or_default();
    format!("{nanos:x}")
}

fn now_iso() -> String {
    chrono::Utc::now().to_rfc3339()
}

pub struct PlanStore {
    connection: Connection,
}

impl PlanStore {
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
    pub fn open_in_memory() -> Result<Self, String> {
        let store = Self {
            connection: Connection::open_in_memory().map_err(|error| error.to_string())?,
        };
        store.migrate()?;
        Ok(store)
    }

    fn migrate(&self) -> Result<(), String> {
        self.connection
            .execute_batch(
                "create table if not exists plans (
                    id text primary key,
                    project_id text not null default '',
                    title text not null default '',
                    status text not null default 'draft',
                    source text not null default '',
                    revision integer not null default 1,
                    package text not null,
                    created_at text not null,
                    updated_at text not null,
                    deleted_at text
                );
                create index if not exists idx_plans_project on plans(project_id, status);
                create table if not exists plan_revisions (
                    plan_id text not null,
                    revision integer not null,
                    package text not null,
                    created_at text not null,
                    primary key (plan_id, revision)
                );",
            )
            .map_err(|error| error.to_string())
    }

    /// Create or revise a plan. Patch semantics, with optional concurrency check.
    pub fn save(
        &self,
        payload: &Value,
        source: &str,
        expected_revision: Option<i64>,
    ) -> Result<Value, String> {
        let payload = object_of(Some(payload));
        let plan_id = first_text(&payload, &["plan_id", "planId", "id"]);
        let stored = if plan_id.is_empty() {
            None
        } else {
            self.plan(&plan_id)?
        };
        if expected_revision.is_some() && stored.is_none() {
            return Err(format!("Plan not found: {plan_id}"));
        }
        let package = normalize(&payload, stored.as_ref(), source)?;
        let package = match &stored {
            Some(current) => {
                if let Some(expected) = expected_revision {
                    let revision = current.get("revision").and_then(Value::as_i64).unwrap_or(1);
                    if revision != expected {
                        return Err(format!(
                            "plan revision conflict: {}",
                            text(current.get("plan_id"))
                        ));
                    }
                }
                assert_status_transition(
                    &text(current.get("status")),
                    &text(package.get("status")),
                )?;
                self.assert_ready_has_steps(&package)?;
                let id = text(current.get("plan_id"));
                let expected = current.get("revision").and_then(Value::as_i64).unwrap_or(1);
                let changed = self
                    .write_package(&package, Some((&id, expected)))?
                    .is_some();
                if !changed {
                    return Err(format!("plan revision conflict: {id}"));
                }
                package
            }
            None => {
                let id = text(package.get("plan_id"));
                if self.plan(&id)?.is_some() {
                    return Err(format!("Plan already exists: {id}"));
                }
                assert_status_transition("draft", &text(package.get("status")))?;
                self.assert_ready_has_steps(&package)?;
                self.write_package(&package, None)?;
                package
            }
        };
        self.record_revision(&package)?;
        Ok(package)
    }

    fn assert_ready_has_steps(&self, package: &Value) -> Result<(), String> {
        if text(package.get("status")) != "ready" {
            return Ok(());
        }
        let steps = entries(
            package
                .get("checklist")
                .and_then(|value| value.get("steps")),
        );
        if steps.is_empty() {
            return Err("plan needs at least one step before it is ready".to_owned());
        }
        Ok(())
    }

    /// Write the row, or compare-and-set it when `expected` is given.
    ///
    /// Returns `None` when the compare-and-set did not match, which is how the
    /// caller learns another writer moved the revision on.
    fn write_package(
        &self,
        package: &Value,
        expected: Option<(&str, i64)>,
    ) -> Result<Option<()>, String> {
        let id = text(package.get("plan_id"));
        let values = self.row_values(package);
        match expected {
            None => {
                self.connection
                    .execute(
                        "insert into plans (id, project_id, title, status, source, revision, package,
                            created_at, updated_at, deleted_at)
                         values (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
                        params![
                            id,
                            values.0,
                            values.1,
                            values.2,
                            values.3,
                            values.4,
                            values.5,
                            values.6,
                            values.7,
                            values.8,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                Ok(Some(()))
            }
            Some((id, revision)) => {
                let changed = self
                    .connection
                    .execute(
                        "update plans set project_id = ?2, title = ?3, status = ?4, source = ?5,
                            revision = ?6, package = ?7, created_at = ?8, updated_at = ?9,
                            deleted_at = ?10
                         where id = ?1 and revision = ?11",
                        params![
                            id,
                            values.0,
                            values.1,
                            values.2,
                            values.3,
                            values.4,
                            values.5,
                            values.6,
                            values.7,
                            values.8,
                            revision,
                        ],
                    )
                    .map_err(|error| error.to_string())?;
                Ok((changed == 1).then_some(()))
            }
        }
    }

    #[allow(clippy::type_complexity)]
    fn row_values(&self, package: &Value) -> (String, String, String, String, i64, String, String, String, Option<String>) {
        (
            text(package.get("project_id")),
            text(package.get("title")),
            text(package.get("status")),
            text(package.get("source")),
            package.get("revision").and_then(Value::as_i64).unwrap_or(1),
            package.to_string(),
            text(package.get("created_at")),
            text(package.get("updated_at")),
            match package.get("deleted_at") {
                None | Some(Value::Null) => None,
                Some(value) => Some(text(Some(value))),
            },
        )
    }

    pub fn record_revision(&self, package: &Value) -> Result<(), String> {
        self.connection
            .execute(
                "insert or replace into plan_revisions (plan_id, revision, package, created_at)
                 values (?1, ?2, ?3, ?4)",
                params![
                    text(package.get("plan_id")),
                    package.get("revision").and_then(Value::as_i64).unwrap_or(1),
                    package.to_string(),
                    text(package.get("updated_at")),
                ],
            )
            .map_err(|error| error.to_string())?;
        Ok(())
    }

    pub fn plan(&self, plan_id: &str) -> Result<Option<Value>, String> {
        self.connection
            .query_row(
                "select package from plans where id = ?1",
                params![plan_id.trim()],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?
            .map(|package| serde_json::from_str(&package).map_err(|error| error.to_string()))
            .transpose()
    }

    /// Plans newest first, with the id as a tiebreaker: two plans saved inside
    /// the same second still come back in a stable order.
    pub fn list(
        &self,
        project_id: Option<&str>,
        status: Option<&str>,
        include_deleted: bool,
    ) -> Result<Vec<Value>, String> {
        let mut statement = self
            .connection
            .prepare(
                "select package from plans
                 where (?1 = '' or project_id = ?1) and (?2 = '' or status = ?2)
                   and (?3 = 1 or deleted_at is null)
                 order by created_at desc, id desc",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(
                params![
                    project_id.unwrap_or_default(),
                    status.unwrap_or_default(),
                    i64::from(include_deleted),
                ],
                |row| row.get::<_, String>(0),
            )
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())?
            .iter()
            .map(|package| serde_json::from_str(package).map_err(|error| error.to_string()))
            .collect()
    }

    pub fn set_deleted(&self, plan_id: &str, deleted: bool) -> Result<Value, String> {
        let key = plan_id.trim();
        let current = self
            .plan(key)?
            .ok_or_else(|| format!("Plan not found: {key}"))?;
        let mut updated = object_of(Some(&current));
        let now = now_iso();
        updated.insert(
            "deleted_at".into(),
            if deleted {
                Value::String(now.clone())
            } else {
                Value::Null
            },
        );
        updated.insert("updated_at".into(), Value::String(now));
        let updated = Value::Object(updated);
        let revision = updated.get("revision").and_then(Value::as_i64).unwrap_or(1);
        // Deletion is bookkeeping, not a plan edit: the revision does not move
        // and the recorded history stays content-only.
        if self
            .write_package(&updated, Some((key, revision)))?
            .is_none()
        {
            return Err(format!("plan revision conflict: {key}"));
        }
        Ok(updated)
    }

    /// Restore an earlier revision's content as a new revision.
    pub fn revert(&self, plan_id: &str, revision: i64, source: &str) -> Result<Value, String> {
        let key = plan_id.trim();
        let current = self
            .plan(key)?
            .ok_or_else(|| format!("Plan not found: {key}"))?;
        let target = self
            .revision(key, revision)?
            .ok_or_else(|| format!("plan revision not found: {key}@{revision}"))?;
        // A revert restores content verbatim, so the status machine is not
        // re-applied — only the identity, the new revision number and the
        // host-local execution record come from the present.
        let mut restored = object_of(Some(&target));
        let current_revision = current.get("revision").and_then(Value::as_i64).unwrap_or(1);
        let now = now_iso();
        restored.insert("plan_id".into(), current.get("plan_id").cloned().unwrap_or(Value::Null));
        restored.insert("revision".into(), json!(current_revision + 1));
        restored.insert(
            "source".into(),
            Value::String(match source.trim() {
                "" => text(current.get("source")),
                value => value.to_owned(),
            }),
        );
        restored.insert(
            "project_id".into(),
            current.get("project_id").cloned().unwrap_or(Value::Null),
        );
        restored.insert(
            "execution".into(),
            current.get("execution").cloned().unwrap_or(Value::Null),
        );
        restored.insert(
            "created_at".into(),
            current.get("created_at").cloned().unwrap_or(Value::Null),
        );
        restored.insert(
            "deleted_at".into(),
            current.get("deleted_at").cloned().unwrap_or(Value::Null),
        );
        restored.insert("updated_at".into(), Value::String(now));
        let restored = Value::Object(restored);
        if self
            .write_package(&restored, Some((key, current_revision)))?
            .is_none()
        {
            return Err(format!("plan revision conflict: {key}"));
        }
        self.record_revision(&restored)?;
        Ok(restored)
    }

    pub fn revision(&self, plan_id: &str, revision: i64) -> Result<Option<Value>, String> {
        self.connection
            .query_row(
                "select package from plan_revisions where plan_id = ?1 and revision = ?2",
                params![plan_id.trim(), revision],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?
            .map(|package| serde_json::from_str(&package).map_err(|error| error.to_string()))
            .transpose()
    }

    /// Every recorded revision, oldest first.
    pub fn revisions(&self, plan_id: &str) -> Result<Vec<Value>, String> {
        let mut statement = self
            .connection
            .prepare(
                "select package from plan_revisions where plan_id = ?1 order by revision asc",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(params![plan_id.trim()], |row| row.get::<_, String>(0))
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())?
            .iter()
            .map(|package| serde_json::from_str(package).map_err(|error| error.to_string()))
            .collect()
    }
}

/// The summaries `plan.revisions` answers with.
pub fn revision_summaries(history: &[Value]) -> Value {
    Value::Array(
        history
            .iter()
            .map(|item| {
                json!({
                    "revision": item.get("revision").cloned().unwrap_or(json!(1)),
                    "title": item.get("title").cloned().unwrap_or(json!("")),
                    "status": item.get("status").cloned().unwrap_or(json!("draft")),
                    "source": item.get("source").cloned().unwrap_or(json!("")),
                    "created_at": item.get("updated_at").cloned().unwrap_or(json!("")),
                })
            })
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    const FIXTURES: &str = include_str!("../../protocol/plan-package-v1-fixtures.json");

    fn fixtures() -> Value {
        serde_json::from_str(FIXTURES).expect("fixtures parse")
    }

    fn compared_fields(contract: &Value) -> Vec<String> {
        contract["contract"]["compared_fields"]
            .as_array()
            .expect("compared_fields")
            .iter()
            .map(|field| field.as_str().unwrap_or_default().to_owned())
            .collect()
    }

    fn project(plan: &Value, fields: &[String]) -> Value {
        let mut projected = Map::new();
        for field in fields {
            projected.insert(field.clone(), plan.get(field).cloned().unwrap_or(Value::Null));
        }
        Value::Object(projected)
    }

    struct Step {
        ok: bool,
        error: String,
        plan: Value,
        listed: Vec<String>,
        revisions: Vec<Value>,
    }

    fn apply(store: &PlanStore, action: &str, payload: &Value) -> Step {
        let payload_map = object_of(Some(payload));
        let mut step = Step {
            ok: true,
            error: String::new(),
            plan: Value::Null,
            listed: Vec::new(),
            revisions: Vec::new(),
        };
        let outcome: Result<Option<Value>, String> = match action {
            "save" => {
                let expected = payload_map
                    .get("expected_revision")
                    .and_then(Value::as_i64);
                store
                    .save(payload, "mobile", expected)
                    .map(Some)
            }
            "revert" => {
                let revision = payload_map.get("revision").and_then(Value::as_i64).unwrap_or(0);
                store
                    .revert(&first_text(&payload_map, &["plan_id", "planId", "id"]), revision, "mobile")
                    .map(Some)
            }
            "delete" => store
                .set_deleted(&first_text(&payload_map, &["plan_id", "planId", "id"]), true)
                .map(Some),
            "restore" => store
                .set_deleted(&first_text(&payload_map, &["plan_id", "planId", "id"]), false)
                .map(Some),
            "list" => {
                let project_id = text(payload_map.get("project_id"));
                let status = text(payload_map.get("status"));
                store
                    .list(
                        (!project_id.is_empty()).then_some(project_id.as_str()),
                        (!status.is_empty()).then_some(status.as_str()),
                        payload_map
                            .get("include_deleted")
                            .and_then(Value::as_bool)
                            .unwrap_or(false),
                    )
                    .map(|plans| {
                        step.listed = plans
                            .iter()
                            .map(|plan| text(plan.get("plan_id")))
                            .collect();
                        None
                    })
            }
            "revisions" => {
                let history = store
                    .revisions(&first_text(&payload_map, &["plan_id", "planId", "id"]))
                    .unwrap();
                step.revisions = history
                    .iter()
                    .map(|item| json!({"revision": item["revision"], "title": item["title"]}))
                    .collect();
                Ok(None)
            }
            other => panic!("unknown fixture action: {other}"),
        };
        match outcome {
            Ok(Some(plan)) => {
                step.plan = plan;
                step.listed = store
                    .list(None, None, false)
                    .unwrap()
                    .iter()
                    .map(|item| text(item.get("plan_id")))
                    .collect();
            }
            Ok(None) => {}
            Err(error) => {
                step.ok = false;
                step.error = error;
            }
        }
        step
    }

    fn run_case(store: &PlanStore, case: &Value, fields: &[String]) {
        let name = case["name"].as_str().unwrap_or_default();
        for given in entries(case.get("given")) {
            let action = given
                .get("action")
                .and_then(Value::as_str)
                .unwrap_or("save");
            let payload = given.get("payload").cloned().unwrap_or(json!({}));
            let step = apply(store, action, &payload);
            assert!(step.ok, "{name}: given step failed: {}", step.error);
        }
        let action = case["action"].as_str().unwrap_or("save");
        let payload = case.get("payload").cloned().unwrap_or(json!({}));
        let step = apply(store, action, &payload);
        let expect = &case["expect"];

        assert_eq!(
            step.ok,
            expect["ok"].as_bool().unwrap_or(false),
            "{name}: ok mismatch ({})",
            step.error
        );
        if !step.ok {
            assert_eq!(
                step.error,
                expect["error"].as_str().unwrap_or_default(),
                "{name}: refusal wording drifted"
            );
            return;
        }
        if let Some(revision) = expect.get("revision").and_then(Value::as_i64) {
            assert_eq!(step.plan["revision"].as_i64(), Some(revision), "{name}: revision");
        }
        if let Some(status) = expect.get("status").and_then(Value::as_str) {
            assert_eq!(text(step.plan.get("status")), status, "{name}: status");
        }
        if let Some(prefix) = expect.get("plan_id_prefix").and_then(Value::as_str) {
            assert!(
                text(step.plan.get("plan_id")).starts_with(prefix),
                "{name}: generated id"
            );
        }
        if let Some(expected) = expect.get("plan") {
            assert_eq!(
                project(&step.plan, fields),
                *expected,
                "{name}: package drifted"
            );
        }
        if let Some(listed) = expect.get("listed").and_then(Value::as_array) {
            let expected: Vec<String> = listed
                .iter()
                .map(|item| item.as_str().unwrap_or_default().to_owned())
                .collect();
            assert_eq!(step.listed, expected, "{name}: list");
        }
        if let Some(revisions) = expect.get("revisions") {
            assert_eq!(
                Value::Array(step.revisions.clone()),
                *revisions,
                "{name}: revision history"
            );
        }
    }

    #[test]
    fn shared_fixtures_hold_for_the_mobile_store() {
        let contract = fixtures();
        let fields = compared_fields(&contract);
        // Every case is self-contained: its `given` steps build the state it
        // needs, so a fresh store per case keeps one case out of another's list.
        for case in entries(contract.get("cases")) {
            let store = PlanStore::open_in_memory().unwrap();
            run_case(&store, &case, &fields);
        }
    }

    #[test]
    fn a_stored_plan_survives_a_reopen_with_its_history() {
        let directory = std::env::temp_dir().join(format!("plans-reopen-{}", short_id()));
        std::fs::create_dir_all(&directory).unwrap();
        let database = directory.join("plans.db");
        {
            let store = PlanStore::open(&database).unwrap();
            store
                .save(
                    &json!({
                        "plan_id": "plan_reopen",
                        "project_id": "proj-1",
                        "title": "存了再开",
                        "requirement": {"restatement": "重启不丢"},
                        "approach": {"chosen": "落库"},
                        "checklist": {"steps": [{"id": "s1", "description": "写下去"}]},
                    }),
                    "mobile",
                    None,
                )
                .unwrap();
            store
                .save(
                    &json!({"plan_id": "plan_reopen", "expected_revision": 1, "status": "ready"}),
                    "mobile",
                    Some(1),
                )
                .unwrap();
        }

        let store = PlanStore::open(&database).unwrap();
        let plan = store.plan("plan_reopen").unwrap().unwrap();
        assert_eq!(text(plan.get("title")), "存了再开");
        assert_eq!(text(plan.get("status")), "ready");
        assert_eq!(plan["revision"].as_i64(), Some(2));
        let history = store.revisions("plan_reopen").unwrap();
        assert_eq!(
            history
                .iter()
                .map(|item| (item["revision"].as_i64(), text(item.get("status"))))
                .collect::<Vec<_>>(),
            vec![(Some(1), "draft".to_owned()), (Some(2), "ready".to_owned())]
        );
        std::fs::remove_dir_all(&directory).ok();
    }

    #[test]
    fn deletion_keeps_the_revision_and_restore_brings_the_plan_back() {
        let store = PlanStore::open_in_memory().unwrap();
        store
            .save(
                &json!({
                    "plan_id": "plan_del",
                    "project_id": "proj-1",
                    "title": "软删除",
                    "requirement": {"restatement": "x"},
                    "approach": {"chosen": "y"},
                }),
                "mobile",
                None,
            )
            .unwrap();
        let deleted = store.set_deleted("plan_del", true).unwrap();
        assert_eq!(deleted["revision"].as_i64(), Some(1));
        assert!(deleted["deleted_at"].is_string());
        assert!(store.list(None, None, false).unwrap().is_empty());
        assert_eq!(store.list(None, None, true).unwrap().len(), 1);

        let restored = store.set_deleted("plan_del", false).unwrap();
        assert!(restored["deleted_at"].is_null());
        assert_eq!(store.list(None, None, false).unwrap().len(), 1);
    }
}
