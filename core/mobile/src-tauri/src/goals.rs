//! Durable goals for the mobile host.
//!
//! The desktop keeps goals in `runtime/goal.py` (a frozen dataclass plus a store
//! with optimistic concurrency); the phone keeps the same fields, the same
//! status machine and the same validation messages in a small SQLite table, so
//! the panel in the shared UI behaves identically on both hosts.
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;

const TERMINAL_STATUSES: [&str; 1] = ["archived"];
const ALLOWED_TRANSITIONS: [(&str, [&str; 2]); 2] = [
    ("active", ["blocked", "archived"]),
    ("blocked", ["active", "archived"]),
];

/// One goal as the panel reads it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Goal {
    pub id: String,
    pub thread_id: String,
    pub objective: String,
    pub completion_criteria: Vec<String>,
    pub status: String,
    pub status_reason: String,
    pub metadata: Value,
    pub revision: i64,
    pub created_at: String,
    pub updated_at: String,
    pub completed_at: Option<String>,
}

impl Goal {
    fn to_value(&self) -> Value {
        json!({
            "id": self.id,
            "thread_id": self.thread_id,
            "objective": self.objective,
            "completion_criteria": self.completion_criteria,
            "status": self.status,
            "status_reason": self.status_reason,
            "metadata": self.metadata,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        })
    }
}

pub struct GoalStore {
    connection: Connection,
}

impl GoalStore {
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
                "create table if not exists goals (
                    id text primary key,
                    thread_id text not null,
                    objective text not null,
                    completion_criteria text not null default '[]',
                    status text not null default 'active',
                    status_reason text not null default '',
                    metadata text not null default '{}',
                    revision integer not null default 1,
                    created_at text not null,
                    updated_at text not null,
                    completed_at text
                );
                create index if not exists idx_goals_thread on goals(thread_id, status);",
            )
            .map_err(|error| error.to_string())
    }

    pub fn create(
        &self,
        thread_id: &str,
        objective: &str,
        completion_criteria: &[String],
        metadata: Value,
        goal_id: &str,
    ) -> Result<Goal, String> {
        let thread_id = thread_id.trim();
        let objective = objective.trim();
        if thread_id.is_empty() {
            return Err("thread_id is required".into());
        }
        if objective.is_empty() {
            return Err("goal objective is required".into());
        }
        let id = if goal_id.trim().is_empty() {
            format!("goal_{}", short_id())
        } else {
            goal_id.trim().to_owned()
        };
        if self.goal(&id)?.is_some() {
            return Err(format!("Goal already exists: {id}"));
        }
        let criteria: Vec<String> = completion_criteria
            .iter()
            .map(|value| value.trim().to_owned())
            .filter(|value| !value.is_empty())
            .collect();
        let now = now_iso();
        let goal = Goal {
            id,
            thread_id: thread_id.to_owned(),
            objective: objective.to_owned(),
            completion_criteria: criteria,
            status: "active".into(),
            status_reason: String::new(),
            metadata,
            revision: 1,
            created_at: now.clone(),
            updated_at: now,
            completed_at: None,
        };
        self.connection
            .execute(
                "insert into goals (id, thread_id, objective, completion_criteria, status, status_reason,
                    metadata, revision, created_at, updated_at)
                 values (?1, ?2, ?3, ?4, 'active', '', ?5, 1, ?6, ?6)",
                params![
                    goal.id,
                    goal.thread_id,
                    goal.objective,
                    serde_json::to_string(&goal.completion_criteria).unwrap_or_else(|_| "[]".into()),
                    serde_json::to_string(&goal.metadata).unwrap_or_else(|_| "{}".into()),
                    goal.created_at,
                ],
            )
            .map_err(|error| error.to_string())?;
        Ok(goal)
    }

    pub fn goal(&self, goal_id: &str) -> Result<Option<Goal>, String> {
        self.connection
            .query_row(
                "select id, thread_id, objective, completion_criteria, status, status_reason, metadata,
                        revision, created_at, updated_at, completed_at
                 from goals where id = ?1",
                params![goal_id.trim()],
                read_goal_row,
            )
            .optional()
            .map_err(|error| error.to_string())
    }

    pub fn list(&self, thread_id: Option<&str>, status: Option<&str>) -> Result<Vec<Goal>, String> {
        let mut statement = self
            .connection
            .prepare(
                "select id, thread_id, objective, completion_criteria, status, status_reason, metadata,
                        revision, created_at, updated_at, completed_at
                 from goals
                 where (?1 = '' or thread_id = ?1) and (?2 = '' or status = ?2)
                 order by created_at desc, id",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(
                params![thread_id.unwrap_or_default(), status.unwrap_or_default()],
                read_goal_row,
            )
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    /// Apply one update, refusing exactly what the desktop refuses.
    ///
    /// `None` means "not sent", which is different from an empty value: the
    /// panel can clear a status reason without clearing the objective.
    pub fn update(
        &self,
        goal_id: &str,
        objective: Option<&str>,
        completion_criteria: Option<&[String]>,
        status: Option<&str>,
        status_reason: Option<&str>,
        metadata: Option<Value>,
    ) -> Result<Goal, String> {
        let current = self
            .goal(goal_id)?
            .ok_or_else(|| format!("Goal not found: {}", goal_id.trim()))?;
        if TERMINAL_STATUSES.contains(&current.status.as_str()) {
            let untouched = (status.is_none() || status == Some(current.status.as_str()))
                && objective.is_none()
                && completion_criteria.is_none()
                && status_reason.is_none()
                && metadata.is_none();
            if untouched {
                return Ok(current);
            }
            return Err(format!(
                "Goal is terminal and cannot be updated: {}",
                goal_id.trim()
            ));
        }
        let next_status = status.unwrap_or(current.status.as_str()).trim();
        if !matches!(next_status, "active" | "blocked" | "archived") {
            return Err(format!("Invalid Goal status: {next_status}"));
        }
        if next_status != current.status
            && !ALLOWED_TRANSITIONS
                .iter()
                .find(|(from, _)| *from == current.status)
                .is_some_and(|(_, allowed)| allowed.contains(&next_status))
        {
            return Err(format!(
                "Invalid Goal transition: {} -> {next_status}",
                current.status
            ));
        }
        let next_objective = match objective {
            Some(value) => value.trim().to_owned(),
            None => current.objective.clone(),
        };
        if next_objective.is_empty() {
            return Err("goal objective is required".into());
        }
        let criteria = match completion_criteria {
            Some(values) => values
                .iter()
                .map(|value| value.trim().to_owned())
                .filter(|value| !value.is_empty())
                .collect::<Vec<_>>(),
            None => current.completion_criteria.clone(),
        };
        let now = now_iso();
        let updated = Goal {
            objective: next_objective,
            completion_criteria: criteria,
            status: next_status.to_owned(),
            status_reason: match status_reason {
                Some(value) => value.trim().to_owned(),
                None => current.status_reason.clone(),
            },
            metadata: metadata.unwrap_or_else(|| current.metadata.clone()),
            revision: current.revision + 1,
            updated_at: now.clone(),
            completed_at: if next_status == "archived" {
                Some(now)
            } else {
                current.completed_at.clone()
            },
            ..current
        };
        // Optimistic concurrency: another writer may have moved the revision on.
        let changed = self
            .connection
            .execute(
                "update goals set objective = ?2, completion_criteria = ?3, status = ?4, status_reason = ?5,
                    metadata = ?6, revision = ?7, updated_at = ?8, completed_at = ?9
                 where id = ?1 and revision = ?10",
                params![
                    updated.id,
                    updated.objective,
                    serde_json::to_string(&updated.completion_criteria).unwrap_or_else(|_| "[]".into()),
                    updated.status,
                    updated.status_reason,
                    serde_json::to_string(&updated.metadata).unwrap_or_else(|_| "{}".into()),
                    updated.revision,
                    updated.updated_at,
                    updated.completed_at,
                    current.revision,
                ],
            )
            .map_err(|error| error.to_string())?;
        if changed == 0 {
            return Err(format!("Goal revision conflict: {}", updated.id));
        }
        Ok(updated)
    }
}

fn read_goal_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Goal> {
    let criteria: String = row.get(3)?;
    let metadata: String = row.get(6)?;
    Ok(Goal {
        id: row.get(0)?,
        thread_id: row.get(1)?,
        objective: row.get(2)?,
        completion_criteria: serde_json::from_str(&criteria).unwrap_or_default(),
        status: row.get(4)?,
        status_reason: row.get(5)?,
        metadata: serde_json::from_str(&metadata).unwrap_or(Value::Null),
        revision: row.get(7)?,
        created_at: row.get(8)?,
        updated_at: row.get(9)?,
        completed_at: row.get(10)?,
    })
}

/// A short random-ish id; goals do not need cryptographic ids, only uniqueness.
fn short_id() -> String {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or_default();
    format!("{nanos:x}")
}

fn now_iso() -> String {
    super::timestamp_iso()
}

/// Payload for `goal.create` / `goal.get` / `goal.update`.
pub fn goal_payload(goal: &Goal) -> Value {
    json!({"goal": goal.to_value()})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn creating_requires_a_thread_and_an_objective() {
        let store = GoalStore::open_in_memory().unwrap();
        assert!(store.create("", "do it", &[], Value::Null, "").is_err());
        assert!(store.create("thread-1", "   ", &[], Value::Null, "").is_err());
        let goal = store
            .create("thread-1", "  完成移动端对齐  ", &["a".into(), "  ".into()], Value::Null, "")
            .unwrap();
        assert_eq!(goal.objective, "完成移动端对齐");
        // Blank criteria are dropped, not stored as empties.
        assert_eq!(goal.completion_criteria, vec!["a".to_owned()]);
        assert_eq!(goal.status, "active");
        assert_eq!(goal.revision, 1);
        assert!(goal.completed_at.is_none());
        assert!(goal.id.starts_with("goal_"));
    }

    #[test]
    fn the_status_machine_and_optimistic_concurrency_match_the_desktop() {
        let store = GoalStore::open_in_memory().unwrap();
        let goal = store.create("thread-1", "目标", &[], Value::Null, "").unwrap();

        // active -> archived is allowed and stamps completed_at.
        let archived = store.update(&goal.id, None, None, Some("archived"), None, None).unwrap();
        assert_eq!(archived.status, "archived");
        assert!(archived.completed_at.is_some());
        assert_eq!(archived.revision, 2);
        // archived is terminal: a no-op read-back is fine, any change is not.
        let again = store.update(&goal.id, None, None, Some("archived"), None, None).unwrap();
        assert_eq!(again.revision, 2);
        assert!(store.update(&goal.id, Some("改目标"), None, None, None, None).is_err());
        // An update that sends nothing is a read-back, exactly as the desktop
        // treats it; anything that would change the goal is refused above.
        let untouched = store.update(&goal.id, None, None, None, None, None).unwrap();
        assert_eq!(untouched, archived);

        // archived -> active is not a legal transition at all.
        let other = store.create("thread-1", "另一个", &[], Value::Null, "").unwrap();
        assert!(store.update(&other.id, None, None, Some("archived"), None, None).is_ok());
        assert!(store.update(&other.id, None, None, Some("active"), None, None).is_err());

        // On a live goal, blocked can go back to active and a reason can be
        // cleared (the panel's “恢复” path).
        let live = store.create("thread-1", "活在其中的目标", &[], Value::Null, "").unwrap();
        let blocked = store
            .update(&live.id, None, None, Some("blocked"), Some("等用户"), None)
            .unwrap();
        assert_eq!(blocked.status, "blocked");
        assert_eq!(blocked.status_reason, "等用户");
        let unblocked = store
            .update(&live.id, None, None, Some("active"), Some(""), None)
            .unwrap();
        assert_eq!(unblocked.status, "active");
        assert_eq!(unblocked.status_reason, "");

        // An objective update keeps the rest, and an empty one is refused.
        let renamed = store
            .update(&live.id, Some("新目标"), Some(&["标准".to_owned()]), None, None, None)
            .unwrap();
        assert_eq!(renamed.objective, "新目标");
        assert_eq!(renamed.completion_criteria, vec!["标准".to_owned()]);
        assert_eq!(renamed.status, "active");
        assert!(store.update(&live.id, Some("  "), None, None, None, None).is_err());
        assert!(store.update(&live.id, None, None, Some("完成"), None, None).is_err());
        assert!(store.update("goal_missing", None, None, None, None, None).is_err());
    }

    #[test]
    fn listing_filters_by_thread_and_status() {
        let store = GoalStore::open_in_memory().unwrap();
        let first = store.create("thread-1", "一", &[], Value::Null, "").unwrap();
        store.create("thread-1", "二", &[], Value::Null, "").unwrap();
        store.create("thread-2", "三", &[], Value::Null, "").unwrap();
        store.update(&first.id, None, None, Some("archived"), None, None).unwrap();

        assert_eq!(store.list(Some("thread-1"), None).unwrap().len(), 2);
        assert_eq!(store.list(Some("thread-2"), None).unwrap().len(), 1);
        assert_eq!(store.list(None, None).unwrap().len(), 3);
        assert_eq!(store.list(None, Some("archived")).unwrap().len(), 1);
        assert_eq!(store.list(Some("thread-1"), Some("active")).unwrap().len(), 1);
        assert!(store.list(Some("thread-3"), None).unwrap().is_empty());
    }
}
