use lamtools_runtime::{
    hooks::{HookEngine, HookListPayload, HookRegistry, HookRunContext},
    mcp::{load_server_configs, CompositeToolRuntime, McpServerConfig, McpToolRuntime},
    memory::{dream_with_model, DreamingConfig, DreamingOutcome},
    project_tools::ProjectFileTools,
    provider::{HttpModelBackend, ProviderConfig},
    study::{immutable_raw_id, NoteWriter, StudyScope, StudyStore, StudyTools},
    sub_agent::{
        SubAgentHub, SubAgentMail, SubAgentModelEntry, SubAgentParentConfig, SubAgentRecord,
        SubAgentStore,
    },
    workflow_ops,
    workflow_store::WorkflowStore,
    AgentContext, AgentRuntime, ApprovalResponse, DeviceCapabilities, Message, ModelBackend,
    ToolRuntime, TurnContinuation, TurnOptions, TurnProgress, TurnRequest,
};
use rusqlite::{Connection, OpenFlags, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::BTreeSet,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};
use tauri::Emitter;
use tauri::Manager;

mod cancellation;
use cancellation::{RegisterError, TurnCancellationRegistry};

/// Stage events contain only an opaque turn id and fixed stage names.
/// Message text, request bodies, provider URLs and credentials stay out of the
/// progress event.
fn emit_agent_stage(app: &tauri::AppHandle, turn_id: &str, stage: &'static str) {
    let _ = app.emit(
        "sunday-agent-stage",
        serde_json::json!({ "turnId": turn_id, "stage": stage }),
    );
}

#[cfg(target_os = "android")]
use tauri::{plugin::PluginHandle, Runtime};

// MainActivity calls this before Tauri starts Rust or any model request.
#[cfg(target_os = "android")]
#[no_mangle]
pub unsafe extern "system" fn Java_com_lamtools_mobile_RustTlsVerifier_initialize(
    raw_env: *mut jni::sys::JNIEnv,
    _instance: jni::sys::jobject,
    context: jni::sys::jobject,
) {
    let mut unowned_env = unsafe { jni::EnvUnowned::from_raw(raw_env) };
    unowned_env
        .with_env(|env| -> Result<(), jni::errors::Error> {
            let context = unsafe { jni::objects::JObject::from_raw(env, context) };
            rustls_platform_verifier::android::init_with_env(env, context)
        })
        .resolve::<jni::errors::ThrowRuntimeExAndDefault>();
}

#[cfg(target_os = "android")]
mod window_insets;

#[cfg(target_os = "android")]
struct MobileSecureStorage<R: Runtime>(PluginHandle<R>);

#[cfg(target_os = "android")]
#[derive(serde::Serialize)]
struct SecureKeyRequest<'a> {
    key: &'a str,
}

#[cfg(target_os = "android")]
#[derive(serde::Serialize)]
struct SecureSetRequest<'a> {
    key: &'a str,
    value: &'a str,
}

#[cfg(target_os = "android")]
#[derive(serde::Deserialize)]
struct SecureGetResponse {
    value: Option<String>,
}

struct MobileAgentState {
    sub_agents: Arc<SubAgentHub>,
    dreaming: Arc<SqliteDreamStateStore>,
    turn_cancellations: TurnCancellationRegistry,
}

struct SqliteSubAgentStore {
    path: PathBuf,
}

impl SqliteSubAgentStore {
    fn new(path: PathBuf) -> Result<Self, String> {
        let store = Self { path };
        let connection = store.open()?;
        Self::ensure_schema(&connection)?;
        Ok(store)
    }

    fn open(&self) -> Result<Connection, String> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let connection = Connection::open(&self.path).map_err(|error| error.to_string())?;
        connection
            .busy_timeout(std::time::Duration::from_secs(5))
            .map_err(|error| error.to_string())?;
        Ok(connection)
    }

    fn ensure_schema(connection: &Connection) -> Result<(), String> {
        connection
            .execute_batch(
                "PRAGMA journal_mode=WAL;
                 PRAGMA synchronous=FULL;
                 CREATE TABLE IF NOT EXISTS sub_agent_records (
                   parent_thread_id TEXT NOT NULL,
                   name TEXT NOT NULL,
                   record_json TEXT NOT NULL,
                   updated_at INTEGER NOT NULL,
                   PRIMARY KEY (parent_thread_id, name)
                 );
                 CREATE TABLE IF NOT EXISTS sub_agent_mail (
                   id TEXT PRIMARY KEY NOT NULL,
                   parent_thread_id TEXT NOT NULL,
                   name TEXT NOT NULL,
                   direction TEXT NOT NULL,
                   body TEXT NOT NULL,
                   message_key TEXT NOT NULL,
                   created_at INTEGER NOT NULL,
                   delivered_at INTEGER,
                   UNIQUE (parent_thread_id, name, direction, message_key)
                 );
                 CREATE INDEX IF NOT EXISTS idx_sub_agent_mail_pending
                   ON sub_agent_mail(parent_thread_id, direction, name, delivered_at, created_at);",
            )
            .map_err(|error| error.to_string())
    }
}

impl SubAgentStore for SqliteSubAgentStore {
    fn recover_running(&self, parent_thread_id: &str) -> Result<(), String> {
        let now = unix_time_ms();
        for mut record in self.list(parent_thread_id)? {
            if record.status == "running" {
                record.status = "interrupted".into();
                record.completed_at = Some(now);
                record.elapsed_ms = record.started_at.map(|started| now.saturating_sub(started));
                self.save(&record)?;
            }
        }
        Ok(())
    }

    fn load(&self, parent_thread_id: &str, name: &str) -> Result<Option<SubAgentRecord>, String> {
        let connection = self.open()?;
        Self::ensure_schema(&connection)?;
        let raw = connection
            .query_row(
                "SELECT record_json FROM sub_agent_records
                 WHERE parent_thread_id = ?1 AND name = ?2",
                rusqlite::params![parent_thread_id, name],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        raw.map(|value| serde_json::from_str(&value).map_err(|error| error.to_string()))
            .transpose()
    }

    fn save(&self, record: &SubAgentRecord) -> Result<(), String> {
        let connection = self.open()?;
        Self::ensure_schema(&connection)?;
        let record_json = serde_json::to_string(record).map_err(|error| error.to_string())?;
        connection
            .execute(
                "INSERT INTO sub_agent_records(parent_thread_id, name, record_json, updated_at)
                 VALUES (?1, ?2, ?3, ?4)
                 ON CONFLICT(parent_thread_id, name) DO UPDATE SET
                   record_json = excluded.record_json,
                   updated_at = excluded.updated_at",
                rusqlite::params![
                    record.parent_thread_id,
                    record.name,
                    record_json,
                    unix_time_ms() as i64
                ],
            )
            .map(|_| ())
            .map_err(|error| error.to_string())
    }

    fn list(&self, parent_thread_id: &str) -> Result<Vec<SubAgentRecord>, String> {
        let connection = self.open()?;
        Self::ensure_schema(&connection)?;
        let mut statement = connection
            .prepare(
                "SELECT record_json FROM sub_agent_records
                 WHERE parent_thread_id = ?1 ORDER BY updated_at DESC, name ASC",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([parent_thread_id], |row| row.get::<_, String>(0))
            .map_err(|error| error.to_string())?;
        let mut records = Vec::new();
        for row in rows {
            let raw = row.map_err(|error| error.to_string())?;
            records.push(serde_json::from_str(&raw).map_err(|error| error.to_string())?);
        }
        Ok(records)
    }

    fn insert_mail(&self, mail: &SubAgentMail) -> Result<bool, String> {
        let connection = self.open()?;
        Self::ensure_schema(&connection)?;
        connection
            .execute(
                "INSERT OR IGNORE INTO sub_agent_mail(
                   id, parent_thread_id, name, direction, body, message_key, created_at, delivered_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                rusqlite::params![
                    mail.id,
                    mail.parent_thread_id,
                    mail.name,
                    mail.direction,
                    mail.body,
                    mail.message_key,
                    mail.created_at as i64,
                    mail.delivered_at.map(|value| value as i64),
                ],
            )
            .map(|changed| changed > 0)
            .map_err(|error| error.to_string())
    }

    fn undelivered(
        &self,
        parent_thread_id: &str,
        name: Option<&str>,
        direction: &str,
    ) -> Result<Vec<SubAgentMail>, String> {
        let connection = self.open()?;
        Self::ensure_schema(&connection)?;
        let sql = if name.is_some() {
            "SELECT id, parent_thread_id, name, direction, body, message_key, created_at, delivered_at
             FROM sub_agent_mail
             WHERE parent_thread_id = ?1 AND name = ?2 AND direction = ?3 AND delivered_at IS NULL
             ORDER BY created_at ASC, id ASC"
        } else {
            "SELECT id, parent_thread_id, name, direction, body, message_key, created_at, delivered_at
             FROM sub_agent_mail
             WHERE parent_thread_id = ?1 AND direction = ?2 AND delivered_at IS NULL
             ORDER BY created_at ASC, id ASC"
        };
        let mut statement = connection.prepare(sql).map_err(|error| error.to_string())?;
        let map_row = |row: &rusqlite::Row<'_>| -> rusqlite::Result<SubAgentMail> {
            Ok(SubAgentMail {
                id: row.get(0)?,
                parent_thread_id: row.get(1)?,
                name: row.get(2)?,
                direction: row.get(3)?,
                body: row.get(4)?,
                message_key: row.get(5)?,
                created_at: row.get::<_, i64>(6)? as u64,
                delivered_at: row.get::<_, Option<i64>>(7)?.map(|value| value as u64),
            })
        };
        let rows = match name {
            Some(name) => statement.query_map(
                rusqlite::params![parent_thread_id, name, direction],
                map_row,
            ),
            None => statement.query_map(rusqlite::params![parent_thread_id, direction], map_row),
        }
        .map_err(|error| error.to_string())?;
        let mut mail = Vec::new();
        for row in rows {
            mail.push(row.map_err(|error| error.to_string())?);
        }
        Ok(mail)
    }

    fn mark_delivered(&self, ids: &[String], delivered_at: u64) -> Result<(), String> {
        if ids.is_empty() {
            return Ok(());
        }
        let mut connection = self.open()?;
        Self::ensure_schema(&connection)?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        for id in ids {
            transaction
                .execute(
                    "UPDATE sub_agent_mail SET delivered_at = ?1 WHERE id = ?2",
                    rusqlite::params![delivered_at as i64, id],
                )
                .map_err(|error| error.to_string())?;
        }
        transaction.commit().map_err(|error| error.to_string())
    }
}

fn unix_time_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or_default()
}

struct SqliteDreamStateStore {
    path: PathBuf,
}

impl SqliteDreamStateStore {
    fn new(path: PathBuf) -> Result<Self, String> {
        let store = Self { path };
        let connection = store.open()?;
        Self::ensure_schema(&connection)?;
        Ok(store)
    }

    fn open(&self) -> Result<Connection, String> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let connection = Connection::open(&self.path).map_err(|error| error.to_string())?;
        connection
            .busy_timeout(std::time::Duration::from_secs(5))
            .map_err(|error| error.to_string())?;
        Ok(connection)
    }

    fn ensure_schema(connection: &Connection) -> Result<(), String> {
        connection
            .execute_batch(
                "PRAGMA journal_mode=WAL;
                 PRAGMA synchronous=FULL;
                 CREATE TABLE IF NOT EXISTS dreaming_state (
                   scope TEXT PRIMARY KEY NOT NULL,
                   turns_since_dream INTEGER NOT NULL,
                   last_counted_turn_id TEXT NOT NULL,
                   updated_at INTEGER NOT NULL
                 );",
            )
            .map_err(|error| error.to_string())
    }

    fn register_turn(
        &self,
        scope: &str,
        turn_id: &str,
        min_turns: u32,
        worthy: bool,
    ) -> Result<bool, String> {
        let mut connection = self.open()?;
        Self::ensure_schema(&connection)?;
        let transaction = connection
            .transaction()
            .map_err(|error| error.to_string())?;
        let current = transaction
            .query_row(
                "SELECT turns_since_dream, last_counted_turn_id FROM dreaming_state WHERE scope = ?1",
                [scope],
                |row| Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        let count = match current {
            Some((count, previous)) if previous == turn_id => count.max(0) as u32,
            Some((count, _)) => count.max(0).saturating_add(1) as u32,
            None => 1,
        };
        transaction
            .execute(
                "INSERT INTO dreaming_state(scope, turns_since_dream, last_counted_turn_id, updated_at)
                 VALUES (?1, ?2, ?3, ?4)
                 ON CONFLICT(scope) DO UPDATE SET
                   turns_since_dream = excluded.turns_since_dream,
                   last_counted_turn_id = excluded.last_counted_turn_id,
                   updated_at = excluded.updated_at",
                rusqlite::params![scope, count, turn_id, unix_time_ms() as i64],
            )
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(worthy && count >= min_turns.max(1))
    }

    fn mark_dreamed(&self, scope: &str) -> Result<(), String> {
        let connection = self.open()?;
        Self::ensure_schema(&connection)?;
        connection
            .execute(
                "UPDATE dreaming_state SET turns_since_dream = 0, updated_at = ?2 WHERE scope = ?1",
                rusqlite::params![scope, unix_time_ms() as i64],
            )
            .map(|_| ())
            .map_err(|error| error.to_string())
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MobileTurnPayload {
    #[serde(default)]
    turn_id: String,
    #[serde(default)]
    session_id: String,
    project_id: String,
    model_record_id: String,
    provider: ProviderConfig,
    #[serde(default)]
    models: Vec<SubAgentModelEntry>,
    history: Vec<Message>,
    #[serde(default)]
    context: AgentContext,
    #[serde(default)]
    options: TurnOptions,
    #[serde(default)]
    hook_config: Value,
    #[serde(default)]
    trusted_hook_hashes: Vec<String>,
    #[serde(default)]
    mcp_config: Value,
    #[serde(default)]
    dreaming: DreamingConfig,
    #[serde(default = "default_true")]
    sub_agent_enabled: bool,
    #[serde(default)]
    sub_agent_guide: String,
    /// True while the session runs in the Study workspace.  The transport owns
    /// this decision because it reads the session's Study metadata.
    #[serde(default)]
    study_tools: bool,
}

#[tauri::command]
async fn sunday_agent_turn(
    app: tauri::AppHandle,
    agent_state: tauri::State<'_, MobileAgentState>,
    payload: MobileTurnPayload,
) -> Result<TurnProgress, String> {
    emit_agent_stage(&app, &payload.turn_id, "native_received");
    let cancellation = agent_state
        .turn_cancellations
        .register(&payload.turn_id)
        .map_err(register_error_message)?;
    emit_agent_stage(&app, &payload.turn_id, "native_registered");
    cancellation
        .run(sunday_agent_turn_inner(app, agent_state.inner(), payload))
        .await
        .map_err(|_| "turn cancelled".to_owned())?
}

async fn sunday_agent_turn_inner(
    app: tauri::AppHandle,
    agent_state: &MobileAgentState,
    payload: MobileTurnPayload,
) -> Result<TurnProgress, String> {
    let trace_turn_id = payload.turn_id.clone();
    let project_root = native_project_root(&app, &payload.project_id)?;
    tokio_create_dir_all(&project_root).await?;
    let mut context = payload.context;
    if context.project_instructions.trim().is_empty() {
        context.project_instructions = read_optional_utf8(project_root.join("AGENTS.md")).await?;
    }
    if context.memory.trim().is_empty() {
        context.memory = read_optional_utf8(project_root.join("MEMORY.md")).await?;
    }
    emit_agent_stage(&app, &trace_turn_id, "native_project_ready");
    apply_sub_agent_context(
        &mut context,
        payload.sub_agent_enabled,
        &payload.sub_agent_guide,
    );
    let parent_thread_id = if payload.session_id.trim().is_empty() {
        payload.turn_id.clone()
    } else {
        payload.session_id.clone()
    };
    let hook_context = HookRunContext {
        session_id: parent_thread_id.clone(),
        run_id: payload.turn_id.clone(),
        cwd: project_root.to_string_lossy().into_owned(),
        project_root: project_root.to_string_lossy().into_owned(),
        ..Default::default()
    };
    let hooks = load_mobile_hooks(
        &project_root,
        &payload.hook_config,
        &payload.trusted_hook_hashes,
    )
    .await;
    emit_agent_stage(&app, &trace_turn_id, "native_hooks_ready");
    let capabilities = android_capabilities();
    emit_agent_stage(&app, &trace_turn_id, "native_mcp_start");
    let mcp_runtime = Arc::new(
        McpToolRuntime::load(load_mobile_mcp_configs(&project_root, &payload.mcp_config).await)
            .await,
    );
    emit_agent_stage(&app, &trace_turn_id, "native_mcp_ready");
    let hook_engine = Arc::new(HookEngine::new(hooks).with_mcp_caller(mcp_runtime.clone()));
    let project_runtime: Arc<dyn ToolRuntime> =
        Arc::new(ProjectFileTools::new(project_root.clone()));
    let child_tools: Arc<dyn ToolRuntime> = Arc::new(CompositeToolRuntime::new(
        &capabilities,
        vec![project_runtime.clone(), mcp_runtime.clone()],
    ));
    let models = with_active_model(
        payload.models,
        &payload.model_record_id,
        payload.provider.clone(),
    );
    agent_state
        .sub_agents
        .configure_parent(
            &parent_thread_id,
            SubAgentParentConfig {
                models,
                child_tools,
                capabilities: capabilities.clone(),
                context: context.clone(),
                options: payload.options.clone(),
                hook_context: hook_context.clone(),
                hooks: Some(hook_engine.clone()),
            },
        )
        .await?;
    emit_agent_stage(&app, &trace_turn_id, "native_subagents_ready");
    let mut tool_runtimes: Vec<Arc<dyn ToolRuntime>> = vec![project_runtime, mcp_runtime];
    if payload.study_tools {
        tool_runtimes.push(Arc::new(StudyTools::new(native_study_store(&app)?)));
    }
    if payload.sub_agent_enabled {
        tool_runtimes.push(Arc::new(
            agent_state.sub_agents.tools(parent_thread_id.clone()),
        ));
    }
    let tools = CompositeToolRuntime::new(&capabilities, tool_runtimes);
    let progress_app = app.clone();
    let progress_turn_id = trace_turn_id.clone();
    let foreground_model = Arc::new(AtomicBool::new(false));
    let model = Arc::new(
        HttpModelBackend::new(payload.provider)
            .map_err(|error| error.to_string())?
            .with_progress(move |stage| {
                emit_agent_stage(&progress_app, &progress_turn_id, stage);
            })
            .with_stream({
                let stream_app = app.clone();
                let stream_turn_id = trace_turn_id.clone();
                let foreground_model = foreground_model.clone();
                move |kind, delta| {
                    if !foreground_model.load(Ordering::Relaxed) {
                        return;
                    }
                    let _ = stream_app.emit(
                        "sunday-agent-stream",
                        serde_json::json!({
                            "turnId": stream_turn_id, "kind": kind, "delta": delta,
                        }),
                    );
                }
            }),
    );
    let runtime_progress_app = app.clone();
    let runtime_progress_turn_id = trace_turn_id.clone();
    let runtime_foreground_model = foreground_model.clone();
    let runtime = AgentRuntime::new(model.clone(), tools)
        .with_hook_executor(hook_engine)
        .with_guidance_source(agent_state.sub_agents.parent_guidance(parent_thread_id))
        .with_progress(move |stage| {
            emit_agent_stage(&runtime_progress_app, &runtime_progress_turn_id, stage);
            if stage == "runtime_model_start" {
                runtime_foreground_model.store(true, Ordering::Relaxed);
                let _ = runtime_progress_app.emit(
                    "sunday-agent-stream",
                    serde_json::json!({
                        "turnId": runtime_progress_turn_id, "kind": "reset",
                    }),
                );
            } else if stage == "runtime_model_done" {
                runtime_foreground_model.store(false, Ordering::Relaxed);
            }
        });
    let turn_id = payload.turn_id.clone();
    let model_record_id = payload.model_record_id.clone();
    let dreaming_options = payload.options.clone();
    emit_agent_stage(&app, &trace_turn_id, "native_runtime_start");
    let mut progress = runtime
        .run_turn_progress(TurnRequest {
            turn_id: payload.turn_id,
            model_record_id: payload.model_record_id,
            history: payload.history,
            capabilities,
            context,
            hook_context,
            options: payload.options,
        })
        .await
        .map_err(|error| error.to_string())?;
    emit_agent_stage(&app, &trace_turn_id, "native_runtime_done");
    apply_dreaming_with_options(
        agent_state,
        &project_root,
        &turn_id,
        &model_record_id,
        model.as_ref(),
        &payload.dreaming,
        &dreaming_options,
        &mut progress,
    )
    .await;
    emit_agent_stage(&app, &trace_turn_id, "native_dreaming_done");
    Ok(progress)
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MobileResumePayload {
    #[serde(default)]
    session_id: String,
    project_id: String,
    provider: ProviderConfig,
    #[serde(default)]
    models: Vec<SubAgentModelEntry>,
    continuation: TurnContinuation,
    response: ApprovalResponse,
    #[serde(default)]
    hook_config: Value,
    #[serde(default)]
    trusted_hook_hashes: Vec<String>,
    #[serde(default)]
    mcp_config: Value,
    #[serde(default)]
    dreaming: DreamingConfig,
    #[serde(default = "default_true")]
    sub_agent_enabled: bool,
    #[serde(default)]
    sub_agent_guide: String,
    /// True while the session runs in the Study workspace.  The transport owns
    /// this decision because it reads the session's Study metadata.
    #[serde(default)]
    study_tools: bool,
}

#[tauri::command]
async fn sunday_agent_resume(
    app: tauri::AppHandle,
    agent_state: tauri::State<'_, MobileAgentState>,
    payload: MobileResumePayload,
) -> Result<TurnProgress, String> {
    let turn_id = payload.continuation.turn_id.clone();
    emit_agent_stage(&app, &turn_id, "native_received");
    let cancellation = agent_state
        .turn_cancellations
        .register(&turn_id)
        .map_err(register_error_message)?;
    emit_agent_stage(&app, &turn_id, "native_registered");
    cancellation
        .run(sunday_agent_resume_inner(app, agent_state.inner(), payload))
        .await
        .map_err(|_| "turn cancelled".to_owned())?
}

async fn sunday_agent_resume_inner(
    app: tauri::AppHandle,
    agent_state: &MobileAgentState,
    payload: MobileResumePayload,
) -> Result<TurnProgress, String> {
    let trace_turn_id = payload.continuation.turn_id.clone();
    let project_root = native_project_root(&app, &payload.project_id)?;
    tokio_create_dir_all(&project_root).await?;
    emit_agent_stage(&app, &trace_turn_id, "native_project_ready");
    let hooks = load_mobile_hooks(
        &project_root,
        &payload.hook_config,
        &payload.trusted_hook_hashes,
    )
    .await;
    emit_agent_stage(&app, &trace_turn_id, "native_hooks_ready");
    let capabilities = payload.continuation.capabilities.clone();
    emit_agent_stage(&app, &trace_turn_id, "native_mcp_start");
    let mcp_runtime = Arc::new(
        McpToolRuntime::load(load_mobile_mcp_configs(&project_root, &payload.mcp_config).await)
            .await,
    );
    emit_agent_stage(&app, &trace_turn_id, "native_mcp_ready");
    let hook_engine = Arc::new(HookEngine::new(hooks).with_mcp_caller(mcp_runtime.clone()));
    let project_runtime: Arc<dyn ToolRuntime> =
        Arc::new(ProjectFileTools::new(project_root.clone()));
    let child_tools: Arc<dyn ToolRuntime> = Arc::new(CompositeToolRuntime::new(
        &capabilities,
        vec![project_runtime.clone(), mcp_runtime.clone()],
    ));
    let parent_thread_id = if payload.session_id.trim().is_empty() {
        payload.continuation.hook_context.session_id.clone()
    } else {
        payload.session_id.clone()
    };
    let models = with_active_model(
        payload.models,
        &payload.continuation.model_record_id,
        payload.provider.clone(),
    );
    let mut child_context = AgentContext::default();
    apply_sub_agent_context(
        &mut child_context,
        payload.sub_agent_enabled,
        &payload.sub_agent_guide,
    );
    agent_state
        .sub_agents
        .configure_parent(
            &parent_thread_id,
            SubAgentParentConfig {
                models,
                child_tools,
                capabilities: capabilities.clone(),
                context: child_context,
                options: payload.continuation.options.clone(),
                hook_context: payload.continuation.hook_context.clone(),
                hooks: Some(hook_engine.clone()),
            },
        )
        .await?;
    emit_agent_stage(&app, &trace_turn_id, "native_subagents_ready");
    let mut tool_runtimes: Vec<Arc<dyn ToolRuntime>> = vec![project_runtime, mcp_runtime];
    if payload.study_tools {
        tool_runtimes.push(Arc::new(StudyTools::new(native_study_store(&app)?)));
    }
    if payload.sub_agent_enabled {
        tool_runtimes.push(Arc::new(
            agent_state.sub_agents.tools(parent_thread_id.clone()),
        ));
    }
    let tools = CompositeToolRuntime::new(&capabilities, tool_runtimes);
    let progress_app = app.clone();
    let progress_turn_id = trace_turn_id.clone();
    let foreground_model = Arc::new(AtomicBool::new(false));
    let model = Arc::new(
        HttpModelBackend::new(payload.provider)
            .map_err(|error| error.to_string())?
            .with_progress(move |stage| {
                emit_agent_stage(&progress_app, &progress_turn_id, stage);
            })
            .with_stream({
                let stream_app = app.clone();
                let stream_turn_id = trace_turn_id.clone();
                let foreground_model = foreground_model.clone();
                move |kind, delta| {
                    if !foreground_model.load(Ordering::Relaxed) {
                        return;
                    }
                    let _ = stream_app.emit(
                        "sunday-agent-stream",
                        serde_json::json!({
                            "turnId": stream_turn_id, "kind": kind, "delta": delta,
                        }),
                    );
                }
            }),
    );
    let runtime_progress_app = app.clone();
    let runtime_progress_turn_id = trace_turn_id.clone();
    let runtime_foreground_model = foreground_model.clone();
    let runtime = AgentRuntime::new(model.clone(), tools)
        .with_hook_executor(hook_engine)
        .with_guidance_source(agent_state.sub_agents.parent_guidance(parent_thread_id))
        .with_progress(move |stage| {
            emit_agent_stage(&runtime_progress_app, &runtime_progress_turn_id, stage);
            if stage == "runtime_model_start" {
                runtime_foreground_model.store(true, Ordering::Relaxed);
                let _ = runtime_progress_app.emit(
                    "sunday-agent-stream",
                    serde_json::json!({
                        "turnId": runtime_progress_turn_id, "kind": "reset",
                    }),
                );
            } else if stage == "runtime_model_done" {
                runtime_foreground_model.store(false, Ordering::Relaxed);
            }
        });
    let turn_id = payload.continuation.turn_id.clone();
    let model_record_id = payload.continuation.model_record_id.clone();
    let options = payload.continuation.options.clone();
    emit_agent_stage(&app, &trace_turn_id, "native_runtime_start");
    let mut progress = runtime
        .resume_turn(payload.continuation, payload.response)
        .await
        .map_err(|error| error.to_string())?;
    emit_agent_stage(&app, &trace_turn_id, "native_runtime_done");
    apply_dreaming_with_options(
        agent_state,
        &project_root,
        &turn_id,
        &model_record_id,
        model.as_ref(),
        &payload.dreaming,
        &options,
        &mut progress,
    )
    .await;
    emit_agent_stage(&app, &trace_turn_id, "native_dreaming_done");
    Ok(progress)
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MobileCancelPayload {
    turn_id: String,
}

#[tauri::command]
fn sunday_agent_cancel(
    agent_state: tauri::State<'_, MobileAgentState>,
    payload: MobileCancelPayload,
) -> Result<bool, String> {
    let turn_id = payload.turn_id.trim();
    if turn_id.is_empty() {
        return Err("turn id is required".into());
    }
    Ok(agent_state.turn_cancellations.cancel(turn_id))
}

fn register_error_message(error: RegisterError) -> String {
    error.to_string()
}

fn with_active_model(
    mut models: Vec<SubAgentModelEntry>,
    model_record_id: &str,
    provider: ProviderConfig,
) -> Vec<SubAgentModelEntry> {
    if !models.iter().any(|model| model.id == model_record_id) {
        models.push(SubAgentModelEntry {
            id: model_record_id.to_owned(),
            display_name: model_record_id.to_owned(),
            provider,
        });
    }
    models
}

fn apply_sub_agent_context(context: &mut AgentContext, enabled: bool, guide: &str) {
    let section = if enabled {
        format!(
            "[Sub-agent policy]\n{}",
            if guide.trim().is_empty() {
                "Reusable sub-agents are available for bounded independent work."
            } else {
                guide.trim()
            }
        )
    } else {
        "[Sub-agent policy]\nDelegation is disabled for this project.".into()
    };
    if !context.mode_context.trim().is_empty() {
        context.mode_context.push_str("\n\n");
    }
    context.mode_context.push_str(&section);
}

const fn default_true() -> bool {
    true
}

async fn apply_dreaming_with_options<M: ModelBackend + ?Sized>(
    state: &MobileAgentState,
    project_root: &std::path::Path,
    turn_id: &str,
    model_record_id: &str,
    model: &M,
    config: &DreamingConfig,
    options: &TurnOptions,
    progress: &mut TurnProgress,
) {
    if !config.enabled {
        return;
    }
    let TurnProgress::Completed { result } = progress else {
        return;
    };
    let worthy = result.tool_rounds > 0 || result.compaction.is_some();
    let scope = project_root.to_string_lossy();
    let should_dream =
        match state
            .dreaming
            .register_turn(&scope, turn_id, config.min_turns.max(1), worthy)
        {
            Ok(value) => value,
            Err(error) => {
                result.dreaming = Some(DreamingOutcome {
                    status: "failed".into(),
                    summary: format!("dreaming state failed: {error}"),
                    memory_updated: false,
                });
                return;
            }
        };
    if !should_dream {
        return;
    }
    let memory_path = project_root.join("MEMORY.md");
    let existing = match read_optional_utf8(memory_path.clone()).await {
        Ok(value) => value,
        Err(error) => {
            result.dreaming = Some(DreamingOutcome {
                status: "failed".into(),
                summary: format!("dreaming memory read failed: {error}"),
                memory_updated: false,
            });
            return;
        }
    };
    match dream_with_model(
        model,
        model_record_id,
        &existing,
        &result.runtime_history,
        options,
    )
    .await
    {
        Ok(updated) => {
            let changed = updated != existing;
            if changed {
                if let Err(error) = write_memory_atomic(&memory_path, updated.as_bytes()) {
                    result.dreaming = Some(DreamingOutcome {
                        status: "failed".into(),
                        summary: format!("dreaming memory write failed: {error}"),
                        memory_updated: false,
                    });
                    return;
                }
            }
            if let Err(error) = state.dreaming.mark_dreamed(&scope) {
                result.dreaming = Some(DreamingOutcome {
                    status: "failed".into(),
                    summary: format!("dreaming checkpoint failed: {error}"),
                    memory_updated: changed,
                });
                return;
            }
            result.dreaming = Some(DreamingOutcome {
                status: if changed { "completed" } else { "no_changes" }.into(),
                summary: if changed {
                    "Durable memory was appended to MEMORY.md.".into()
                } else {
                    "No new durable memory was found.".into()
                },
                memory_updated: changed,
            });
        }
        Err(error) => {
            result.dreaming = Some(DreamingOutcome {
                status: "failed".into(),
                summary: error,
                memory_updated: false,
            });
        }
    }
}

/// Replace MEMORY.md from a fully written sibling file. A failed replacement
/// leaves the committed document intact, including on Windows.
fn write_memory_atomic(path: &std::path::Path, contents: &[u8]) -> std::io::Result<()> {
    use std::io::Write;

    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("MEMORY.md");
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or(0);
    let temporary = path.with_file_name(format!(".{name}.{}.{}.tmp", std::process::id(), nonce));
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)?;
    let write_result = file.write_all(contents).and_then(|_| file.sync_all());
    drop(file);
    if let Err(error) = write_result {
        let _ = std::fs::remove_file(&temporary);
        return Err(error);
    }
    if let Err(error) = std::fs::rename(&temporary, path) {
        let _ = std::fs::remove_file(&temporary);
        return Err(error);
    }
    Ok(())
}

#[cfg(test)]
mod memory_write_tests {
    use super::write_memory_atomic;

    #[test]
    fn atomic_memory_write_replaces_existing_document() {
        let root = std::env::temp_dir().join(format!(
            "lamtools-memory-write-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&root).unwrap();
        let path = root.join("MEMORY.md");
        write_memory_atomic(&path, b"# Memory\nold\n").unwrap();
        write_memory_atomic(&path, b"# Memory\nnew\n").unwrap();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "# Memory\nnew\n");
        std::fs::remove_file(path).unwrap();
        std::fs::remove_dir(root).unwrap();
    }
}

/// Open the shared Study store this device owns.
///
/// Mobile is a single-user local host, so it always runs under the local
/// compatibility scope the bundled plugin also falls back to.
fn native_study_store(app: &tauri::AppHandle) -> Result<StudyStore, String> {
    let path = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("state")
        .join("study.db");
    StudyStore::open(path, StudyScope::local_compatibility()).map_err(|error| error.to_string())
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MobileWorkflowRpcPayload {
    method: String,
    #[serde(default)]
    params: Value,
    /// A project id resolved from the host's local repository. Arbitrary
    /// work_root values inside params never select a filesystem scope.
    #[serde(default)]
    project_id: Option<String>,
}

fn workflow_project_scope(data_dir: &std::path::Path, project_id: &str) -> Result<PathBuf, String> {
    Ok(data_dir.join("projects").join(safe_project_id(project_id)?))
}

#[tauri::command]
fn sunday_workflow_rpc(
    app: tauri::AppHandle,
    payload: MobileWorkflowRpcPayload,
) -> Result<Value, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    let project_scope = payload
        .project_id
        .as_deref()
        .map(|id| workflow_project_scope(&data_dir, id))
        .transpose()?;
    let store = WorkflowStore::new(data_dir.join(".lam"));
    workflow_ops::dispatch(
        &store,
        &payload.method,
        &payload.params,
        project_scope.as_deref(),
    )
    .map_err(|error| error.to_string())
}

/// Study failures cross the boundary as a JSON payload so the shared UI keeps
/// the structured `error`/`reason` fields it already reads.
fn study_failure(error: lamtools_runtime::study::StudyError) -> String {
    serde_json::to_string(&error.payload())
        .unwrap_or_else(|_| format!("{{\"error\":\"{}\"}}", error.message().replace('"', "'")))
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MobileStudyRpcPayload {
    method: String,
    #[serde(default)]
    params: Value,
    /// Host-owned session metadata.  The transport looks it up in its own
    /// repository so a tool payload can never supply it.
    #[serde(default)]
    session_metadata: Option<Value>,
    #[serde(default)]
    session_targets: Option<Value>,
    #[serde(default)]
    provider: Option<ProviderConfig>,
}

#[tauri::command]
async fn sunday_study_rpc(
    app: tauri::AppHandle,
    payload: MobileStudyRpcPayload,
) -> Result<Value, String> {
    let store = native_study_store(&app)?;
    if payload.method == "study.notes" {
        let action = payload
            .params
            .get("action")
            .and_then(Value::as_str)
            .unwrap_or("list");
        if action == "raw_capture" {
            return capture_mobile_note_raw(&app, &store, &payload.params).map_err(study_failure);
        }
        if action == "raw_list" {
            sync_mobile_note_messages(
                &app,
                &store,
                payload.session_targets.as_ref().and_then(Value::as_object),
            )
            .map_err(study_failure)?;
        }
    }
    dispatch_study(
        &store,
        &payload.method,
        &payload.params,
        payload.session_metadata.as_ref().and_then(Value::as_object),
        &payload
            .session_targets
            .as_ref()
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default(),
        payload.provider.clone(),
    )
    .await
    .map_err(study_failure)
}

fn capture_mobile_note_raw(
    app: &tauri::AppHandle,
    store: &StudyStore,
    params: &Value,
) -> Result<Value, lamtools_runtime::study::StudyError> {
    let kind = params.get("kind").and_then(Value::as_str).unwrap_or("");
    let origin_id = params
        .get("origin_id")
        .and_then(Value::as_str)
        .unwrap_or("");
    let raw_id = params.get("raw_id").and_then(Value::as_str);
    if kind != "session_message" {
        return store.capture_note_record_raw(raw_id, kind, origin_id);
    }
    let session_id = params
        .get("session_id")
        .and_then(Value::as_str)
        .unwrap_or("");
    let state = read_mobile_local_state(app)?;
    let message = mobile_messages(&state).find(|message| {
        message.get("id").and_then(Value::as_str) == Some(origin_id)
            && message_thread_id(message) == session_id
    });
    let message =
        message.ok_or_else(|| lamtools_runtime::study::StudyError::new("UNKNOWN_RAW_SOURCE"))?;
    let content = message.get("content").and_then(Value::as_str).unwrap_or("");
    store.capture_note_raw(
        raw_id,
        kind,
        origin_id,
        content,
        &serde_json::json!({
            "session_id": session_id,
            "role": message.get("role").and_then(Value::as_str).unwrap_or("")
        }),
    )
}

fn sync_mobile_note_messages(
    app: &tauri::AppHandle,
    store: &StudyStore,
    session_targets: Option<&serde_json::Map<String, Value>>,
) -> Result<(), lamtools_runtime::study::StudyError> {
    let Some(targets) = session_targets else {
        return Ok(());
    };
    if targets.is_empty() {
        return Ok(());
    }
    let state = read_mobile_local_state(app)?;
    for message in mobile_messages(&state) {
        let message_id = message.get("id").and_then(Value::as_str).unwrap_or("");
        let session_id = message_thread_id(message);
        if message_id.is_empty() || !targets.contains_key(session_id) {
            continue;
        }
        let content = message.get("content").and_then(Value::as_str).unwrap_or("");
        let raw_id = immutable_raw_id("session_message", message_id, content);
        match store.capture_note_raw(
            Some(&raw_id),
            "session_message",
            message_id,
            content,
            &serde_json::json!({
                "session_id": session_id,
                "role": message.get("role").and_then(Value::as_str).unwrap_or("")
            }),
        ) {
            Ok(_) => {}
            Err(error) if error.message() == "RAW_EXISTS" => {}
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

fn read_mobile_local_state(
    app: &tauri::AppHandle,
) -> Result<Value, lamtools_runtime::study::StudyError> {
    let path = native_state_path(app, "lamtools-mobile")
        .map_err(lamtools_runtime::study::StudyError::new)?;
    read_native_state(&path, None)
        .map_err(lamtools_runtime::study::StudyError::new)?
        .ok_or_else(|| lamtools_runtime::study::StudyError::new("UNKNOWN_RAW_SOURCE"))
}

fn mobile_messages(state: &Value) -> impl Iterator<Item = &Value> {
    state
        .get("messages")
        .and_then(Value::as_object)
        .into_iter()
        .flat_map(|messages| messages.values())
}

fn message_thread_id(message: &Value) -> &str {
    message
        .get("threadId")
        .or_else(|| message.get("thread_id"))
        .and_then(Value::as_str)
        .unwrap_or("")
}

/// Route one Study operation onto the shared store.
///
/// The trusted host selects the note writer identity.  Caller payloads cannot
/// elevate a UI write into an Agent Resource write or trusted Raw capture.
async fn dispatch_study(
    store: &StudyStore,
    method: &str,
    raw_params: &Value,
    session_metadata: Option<&serde_json::Map<String, Value>>,
    session_targets: &serde_json::Map<String, Value>,
    provider: Option<ProviderConfig>,
) -> Result<Value, lamtools_runtime::study::StudyError> {
    let params = if raw_params.is_null() {
        Value::Object(Default::default())
    } else {
        raw_params.clone()
    };
    match method {
        "study.get" => store.read(&params),
        "study.build" => store.build(&params),
        "study.search" => store.search(&params),
        "study.pin" => store.pins(&params, &session_targets),
        "study.layout" => store.layout(&params),
        "study.current" => store.current(params.get("node_id").and_then(Value::as_str)),
        "study.outbox" => store.outbox(
            &params
                .get("mark_delivered")
                .and_then(Value::as_array)
                .map(|ids| {
                    ids.iter()
                        .filter_map(Value::as_str)
                        .map(str::to_owned)
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default(),
            params.get("limit").and_then(Value::as_i64).unwrap_or(50),
        ),
        "study.context" => store.context(&params, session_metadata),
        "study.marks" => store.marks(&params),
        "study.exam" => store.exam(&params),
        "study.sign" => store.sign(&params),
        "study.notes" => store.notes(&params, NoteWriter::User),
        "study.binding.ensure" => store.ensure_binding(
            params.get("kind").and_then(Value::as_str).unwrap_or("map"),
            params
                .get("session_id")
                .and_then(Value::as_str)
                .unwrap_or(""),
            params.get("node_id").and_then(Value::as_str),
            params
                .get("replace_primary")
                .and_then(Value::as_bool)
                .unwrap_or(false),
        ),
        "study.binding.primary" => store
            .primary_binding(
                params.get("kind").and_then(Value::as_str).unwrap_or("map"),
                params.get("node_id").and_then(Value::as_str),
            )
            .map(|binding| serde_json::json!({ "binding": binding })),
        "study.text" => {
            let model_id = params
                .get("model_id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned();
            match provider {
                Some(provider) => {
                    let backend = HttpModelBackend::new(provider).map_err(|error| {
                        lamtools_runtime::study::StudyError::new(error.to_string())
                    })?;
                    store.answer(&params, Some(&backend), &model_id, "").await
                }
                None => {
                    store
                        .answer(&params, None::<&HttpModelBackend>, &model_id, "")
                        .await
                }
            }
        }
        other => Err(lamtools_runtime::study::StudyError::new(format!(
            "未知的 Study 操作：{other}"
        ))),
    }
}

#[tauri::command]
fn sunday_hook_list(config: Value, trusted_hook_hashes: Vec<String>) -> HookListPayload {
    let trusted = trusted_hook_hashes.into_iter().collect::<BTreeSet<_>>();
    let hooks = HookRegistry::load_value(
        "mobile://config/hooks.json",
        "user",
        "config",
        "",
        "",
        &config,
        &trusted,
    );
    HookRegistry::list_payload(&hooks)
}

#[tauri::command]
fn sunday_sub_agent_list(
    agent_state: tauri::State<'_, MobileAgentState>,
    parent_thread_id: String,
) -> Result<Value, String> {
    let items = agent_state.sub_agents.list(&parent_thread_id)?;
    Ok(serde_json::json!({ "items": items }))
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MobileSubAgentApprovalPayload {
    parent_thread_id: String,
    name: String,
    response: ApprovalResponse,
}

#[tauri::command]
async fn sunday_sub_agent_approval(
    agent_state: tauri::State<'_, MobileAgentState>,
    payload: MobileSubAgentApprovalPayload,
) -> Result<Value, String> {
    agent_state
        .sub_agents
        .respond_approval(&payload.parent_thread_id, &payload.name, payload.response)
        .await?;
    Ok(serde_json::json!({ "accepted": true }))
}

async fn load_mobile_hooks(
    project_root: &std::path::Path,
    config: &Value,
    trusted_hook_hashes: &[String],
) -> Vec<lamtools_runtime::hooks::HookDefinition> {
    let trusted = trusted_hook_hashes.iter().cloned().collect::<BTreeSet<_>>();
    let mut hooks = HookRegistry::load_value(
        "mobile://config/hooks.json",
        "user",
        "config",
        "",
        "",
        config,
        &trusted,
    );
    let project_config_path = project_root.join(".lamtools").join("hooks.json");
    if let Ok(content) = tokio::fs::read_to_string(&project_config_path).await {
        if let Ok(project_config) = serde_json::from_str::<Value>(&content) {
            hooks.extend(HookRegistry::load_value(
                &project_config_path.to_string_lossy(),
                "project",
                "project",
                "",
                "",
                &project_config,
                &trusted,
            ));
        }
    }
    hooks
}

fn android_capabilities() -> DeviceCapabilities {
    DeviceCapabilities {
        platform: "android".into(),
        project_files: true,
        network: true,
        notifications: true,
        ..Default::default()
    }
}

async fn load_mobile_mcp_configs(
    project_root: &std::path::Path,
    global_config: &Value,
) -> Vec<McpServerConfig> {
    let mut configs = load_server_configs(global_config)
        .into_iter()
        .map(|config| (config.name.clone(), config))
        .collect::<std::collections::BTreeMap<_, _>>();
    for path in [
        project_root.join(".lamtools").join("mcp.json"),
        project_root.join(".mcp.json"),
        project_root.join("mcp.json"),
    ] {
        let Ok(content) = tokio::fs::read_to_string(&path).await else {
            continue;
        };
        let Ok(value) = json5::from_str::<Value>(&content) else {
            continue;
        };
        for config in load_server_configs(&value) {
            configs.insert(config.name.clone(), config);
        }
    }
    configs.into_values().collect()
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeProjectFile {
    path: String,
    content: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeProjectFileEntry {
    path: String,
    size: u64,
}

#[tauri::command]
async fn project_file_list(
    app: tauri::AppHandle,
    project_id: String,
    path: Option<String>,
) -> Result<Vec<NativeProjectFileEntry>, String> {
    let root = native_project_root(&app, &project_id)?;
    tokio_create_dir_all(&root).await?;
    let requested = safe_project_relative_path(&root, path.as_deref().unwrap_or(""), true)?;
    let mut pending = vec![requested];
    let mut files = Vec::new();
    while let Some(directory) = pending.pop() {
        let mut entries = match tokio::fs::read_dir(&directory).await {
            Ok(entries) => entries,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(error) => return Err(error.to_string()),
        };
        while let Some(entry) = entries
            .next_entry()
            .await
            .map_err(|error| error.to_string())?
        {
            let metadata = entry.metadata().await.map_err(|error| error.to_string())?;
            if metadata.is_dir() {
                pending.push(entry.path());
                continue;
            }
            if !metadata.is_file() {
                continue;
            }
            let relative = entry
                .path()
                .strip_prefix(&root)
                .map_err(|error| error.to_string())?
                .to_string_lossy()
                .replace('\\', "/");
            files.push(NativeProjectFileEntry {
                path: relative,
                size: metadata.len(),
            });
        }
    }
    files.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(files)
}

#[tauri::command]
async fn project_file_read(
    app: tauri::AppHandle,
    project_id: String,
    path: String,
) -> Result<Option<NativeProjectFile>, String> {
    let root = native_project_root(&app, &project_id)?;
    let resolved = safe_project_relative_path(&root, &path, false)?;
    match tokio::fs::read_to_string(resolved).await {
        Ok(content) => Ok(Some(NativeProjectFile { path, content })),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.to_string()),
    }
}

#[tauri::command]
async fn project_file_write(
    app: tauri::AppHandle,
    project_id: String,
    path: String,
    content: String,
) -> Result<NativeProjectFile, String> {
    let root = native_project_root(&app, &project_id)?;
    let resolved = safe_project_relative_path(&root, &path, false)?;
    if let Some(parent) = resolved.parent() {
        tokio_create_dir_all(parent).await?;
    }
    tokio::fs::write(resolved, content.as_bytes())
        .await
        .map_err(|error| error.to_string())?;
    Ok(NativeProjectFile { path, content })
}

#[tauri::command]
async fn load_legacy_mobile_state(app: tauri::AppHandle) -> Result<Option<Value>, String> {
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    let candidates = legacy_database_candidates(&app_data);
    read_legacy_state(&candidates)
}

#[tauri::command]
async fn local_state_read(
    app: tauri::AppHandle,
    database: String,
    scope: Option<String>,
) -> Result<Option<Value>, String> {
    let path = native_state_path(&app, &database)?;
    tauri::async_runtime::spawn_blocking(move || read_native_state(&path, scope.as_deref()))
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn local_state_write(
    app: tauri::AppHandle,
    database: String,
    scope: String,
    state: Value,
) -> Result<(), String> {
    let path = native_state_path(&app, &database)?;
    tauri::async_runtime::spawn_blocking(move || write_native_state(&path, &scope, &state))
        .await
        .map_err(|error| error.to_string())?
}

fn native_state_path(app: &tauri::AppHandle, database: &str) -> Result<std::path::PathBuf, String> {
    if database.is_empty()
        || !database
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
    {
        return Err("invalid local database name".into());
    }
    let root = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("state");
    std::fs::create_dir_all(&root).map_err(|error| error.to_string())?;
    Ok(root.join(format!("{database}.db")))
}

fn ensure_native_state_schema(connection: &Connection) -> Result<(), String> {
    connection
        .execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA synchronous=FULL;
             CREATE TABLE IF NOT EXISTS local_state_scopes (
               scope TEXT PRIMARY KEY NOT NULL,
               state_json TEXT NOT NULL,
               updated_at TEXT NOT NULL
             );
             CREATE TABLE IF NOT EXISTS local_state_active (
               id INTEGER PRIMARY KEY CHECK (id = 1),
               scope TEXT NOT NULL,
               state_json TEXT NOT NULL,
               updated_at TEXT NOT NULL
             );",
        )
        .map_err(|error| error.to_string())
}

fn read_native_state(path: &std::path::Path, scope: Option<&str>) -> Result<Option<Value>, String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let connection = Connection::open(path).map_err(|error| error.to_string())?;
    connection
        .busy_timeout(std::time::Duration::from_secs(5))
        .map_err(|error| error.to_string())?;
    ensure_native_state_schema(&connection)?;
    let raw: Option<String> = match scope {
        Some(scope) => connection
            .query_row(
                "SELECT state_json FROM local_state_scopes WHERE scope = ?1",
                [scope],
                |row| row.get(0),
            )
            .optional(),
        None => connection
            .query_row(
                "SELECT state_json FROM local_state_active WHERE id = 1",
                [],
                |row| row.get(0),
            )
            .optional(),
    }
    .map_err(|error| error.to_string())?;
    raw.map(|text| serde_json::from_str(&text).map_err(|error| error.to_string()))
        .transpose()
}

fn write_native_state(path: &std::path::Path, scope: &str, state: &Value) -> Result<(), String> {
    if scope.is_empty() {
        return Err("local state scope cannot be empty".into());
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let mut connection = Connection::open(path).map_err(|error| error.to_string())?;
    connection
        .busy_timeout(std::time::Duration::from_secs(5))
        .map_err(|error| error.to_string())?;
    ensure_native_state_schema(&connection)?;
    let transaction = connection
        .transaction()
        .map_err(|error| error.to_string())?;
    let state_json = serde_json::to_string(state).map_err(|error| error.to_string())?;
    let updated_at = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_millis()
        .to_string();
    transaction
        .execute(
            "INSERT INTO local_state_scopes (scope, state_json, updated_at)
             VALUES (?1, ?2, ?3)
             ON CONFLICT(scope) DO UPDATE SET
               state_json = excluded.state_json,
               updated_at = excluded.updated_at",
            rusqlite::params![scope, state_json, updated_at],
        )
        .map_err(|error| error.to_string())?;
    transaction
        .execute(
            "INSERT INTO local_state_active (id, scope, state_json, updated_at)
             VALUES (1, ?1, ?2, ?3)
             ON CONFLICT(id) DO UPDATE SET
               scope = excluded.scope,
               state_json = excluded.state_json,
               updated_at = excluded.updated_at",
            rusqlite::params![scope, state_json, updated_at],
        )
        .map_err(|error| error.to_string())?;
    transaction.commit().map_err(|error| error.to_string())
}

fn legacy_database_candidates(app_data: &std::path::Path) -> Vec<std::path::PathBuf> {
    let mut roots = Vec::new();
    for root in app_data.ancestors().take(5) {
        let databases = root.join("databases");
        if !roots.contains(&databases) {
            roots.push(databases);
        }
    }
    roots
        .into_iter()
        .flat_map(|root| {
            [
                root.join("lamtools-mobile-localSQLite.db"),
                root.join("lamtools-mobile-local.db"),
            ]
        })
        .collect()
}

fn read_legacy_state(candidates: &[std::path::PathBuf]) -> Result<Option<Value>, String> {
    for path in candidates {
        if !path.is_file() {
            continue;
        }
        let connection = Connection::open_with_flags(&path, OpenFlags::SQLITE_OPEN_READ_ONLY)
            .map_err(|error| format!("无法打开旧移动端数据库 {}: {error}", path.display()))?;
        connection
            .busy_timeout(std::time::Duration::from_secs(5))
            .map_err(|error| error.to_string())?;
        let raw: Option<String> = connection
            .query_row(
                "SELECT state_json FROM local_state WHERE id = 1",
                [],
                |row| row.get(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        return raw
            .map(|text| serde_json::from_str(&text).map_err(|error| error.to_string()))
            .transpose();
    }
    Ok(None)
}

#[cfg(target_os = "android")]
#[tauri::command]
fn secure_storage_get(
    storage: tauri::State<'_, MobileSecureStorage<tauri::Wry>>,
    key: String,
) -> Result<Option<String>, String> {
    storage
        .0
        .run_mobile_plugin::<SecureGetResponse>("get", SecureKeyRequest { key: &key })
        .map(|response| response.value)
        .map_err(|error| error.to_string())
}

#[cfg(target_os = "android")]
#[tauri::command]
fn secure_storage_set(
    storage: tauri::State<'_, MobileSecureStorage<tauri::Wry>>,
    key: String,
    value: String,
) -> Result<(), String> {
    storage
        .0
        .run_mobile_plugin::<Value>(
            "set",
            SecureSetRequest {
                key: &key,
                value: &value,
            },
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[cfg(target_os = "android")]
#[tauri::command]
fn secure_storage_remove(
    storage: tauri::State<'_, MobileSecureStorage<tauri::Wry>>,
    key: String,
) -> Result<(), String> {
    storage
        .0
        .run_mobile_plugin::<Value>("remove", SecureKeyRequest { key: &key })
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn safe_project_id(value: &str) -> Result<&str, String> {
    if value.is_empty()
        || !value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
    {
        return Err("invalid project id".into());
    }
    Ok(value)
}

fn native_project_root(
    app: &tauri::AppHandle,
    project_id: &str,
) -> Result<std::path::PathBuf, String> {
    let project_id = safe_project_id(project_id)?;
    Ok(app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("projects")
        .join(project_id))
}

fn safe_project_relative_path(
    root: &std::path::Path,
    value: &str,
    allow_empty: bool,
) -> Result<std::path::PathBuf, String> {
    let relative = std::path::Path::new(value);
    if (!allow_empty && value.trim().is_empty())
        || relative.is_absolute()
        || relative.components().any(|component| {
            matches!(
                component,
                std::path::Component::ParentDir
                    | std::path::Component::RootDir
                    | std::path::Component::Prefix(_)
            )
        })
    {
        return Err("path must stay inside the current project".into());
    }
    Ok(root.join(relative))
}

async fn tokio_create_dir_all(path: &std::path::Path) -> Result<(), String> {
    tokio::fs::create_dir_all(path)
        .await
        .map_err(|error| error.to_string())
}

async fn read_optional_utf8(path: std::path::PathBuf) -> Result<String, String> {
    match tokio::fs::read_to_string(path).await {
        Ok(value) => Ok(value),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(String::new()),
        Err(error) => Err(error.to_string()),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default();
    #[cfg(target_os = "android")]
    let builder = builder.plugin(
        tauri::plugin::Builder::<tauri::Wry, ()>::new("lamtools-secure-storage")
            .setup(|app, api| {
                let handle = api.register_android_plugin(
                    "com.lamtools.mobile",
                    "LamToolsSecureStoragePlugin",
                )?;
                app.manage(MobileSecureStorage(handle));
                Ok(())
            })
            .build(),
    );
    #[cfg(target_os = "android")]
    let builder = builder.plugin(
        tauri::plugin::Builder::<tauri::Wry, ()>::new("lamtools-window-insets")
            .setup(|app, api| {
                let handle = api
                    .register_android_plugin("com.lamtools.mobile", "LamToolsWindowInsetsPlugin")?;
                app.manage(window_insets::MobileWindowInsets(handle));
                Ok(())
            })
            .build(),
    );
    let builder = builder.setup(|app| {
        let database_path = app
            .path()
            .app_data_dir()
            .map_err(|error| error.to_string())?
            .join("state")
            .join("sub-agents.db");
        let store = Arc::new(SqliteSubAgentStore::new(database_path)?);
        let dreaming_path = app
            .path()
            .app_data_dir()
            .map_err(|error| error.to_string())?
            .join("state")
            .join("dreaming.db");
        app.manage(MobileAgentState {
            sub_agents: SubAgentHub::new(store),
            dreaming: Arc::new(SqliteDreamStateStore::new(dreaming_path)?),
            turn_cancellations: TurnCancellationRegistry::default(),
        });
        Ok(())
    });
    #[cfg(target_os = "android")]
    let builder = builder.invoke_handler(tauri::generate_handler![
        sunday_agent_turn,
        sunday_agent_resume,
        sunday_agent_cancel,
        sunday_hook_list,
        sunday_sub_agent_list,
        sunday_sub_agent_approval,
        sunday_study_rpc,
        sunday_workflow_rpc,
        load_legacy_mobile_state,
        local_state_read,
        local_state_write,
        project_file_list,
        project_file_read,
        project_file_write,
        secure_storage_get,
        secure_storage_set,
        secure_storage_remove,
        window_insets::window_insets_get,
    ]);
    #[cfg(not(target_os = "android"))]
    let builder = builder.invoke_handler(tauri::generate_handler![
        sunday_agent_turn,
        sunday_agent_resume,
        sunday_agent_cancel,
        sunday_hook_list,
        sunday_sub_agent_list,
        sunday_sub_agent_approval,
        sunday_study_rpc,
        sunday_workflow_rpc,
        load_legacy_mobile_state,
        local_state_read,
        local_state_write,
        project_file_list,
        project_file_read,
        project_file_write
    ]);
    builder
        .run(tauri::generate_context!())
        .expect("error while running Sunday mobile");
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn project_ids_cannot_escape_app_storage() {
        assert_eq!(safe_project_id("project-123"), Ok("project-123"));
        assert!(safe_project_id("../outside").is_err());
        assert!(safe_project_id("").is_err());
    }

    #[test]
    fn workflow_native_scope_uses_only_host_project_ids() {
        let root = std::env::temp_dir().join("workflow-native-scope");
        assert_eq!(
            workflow_project_scope(&root, "project-123").unwrap(),
            root.join("projects").join("project-123")
        );
        assert!(workflow_project_scope(&root, "../outside").is_err());
        assert!(workflow_project_scope(&root, "").is_err());
    }

    #[test]
    fn project_file_paths_cannot_escape_app_storage() {
        let root = std::path::Path::new("/app/projects/p1");
        assert_eq!(
            safe_project_relative_path(root, "notes/a.txt", false).unwrap(),
            root.join("notes/a.txt")
        );
        assert!(safe_project_relative_path(root, "../outside.txt", false).is_err());
        assert!(safe_project_relative_path(root, "/outside.txt", false).is_err());
        assert!(safe_project_relative_path(root, "", false).is_err());
        assert_eq!(safe_project_relative_path(root, "", true).unwrap(), root);
    }

    #[test]
    fn reads_capacitor_state_without_copying_an_active_sqlite_database() {
        let root =
            std::env::temp_dir().join(format!("lamtools-legacy-state-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("lamtools-mobile-localSQLite.db");
        let connection = Connection::open(&path).unwrap();
        connection
            .execute(
                "CREATE TABLE local_state (id INTEGER PRIMARY KEY, state_json TEXT NOT NULL)",
                [],
            )
            .unwrap();
        connection
            .execute(
                "INSERT INTO local_state (id, state_json) VALUES (1, ?1)",
                [r#"{"projects":{"p1":{"id":"p1"}}}"#],
            )
            .unwrap();
        drop(connection);

        let value = read_legacy_state(&[path]).unwrap().unwrap();
        assert_eq!(value["projects"]["p1"]["id"], "p1");
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn native_state_is_atomic_scoped_and_restart_safe() {
        let root = std::env::temp_dir().join(format!("sunday-native-state-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("state.db");
        write_native_state(&path, "workspace:a", &serde_json::json!({"value":"A"})).unwrap();
        write_native_state(&path, "workspace:b", &serde_json::json!({"value":"B"})).unwrap();
        assert_eq!(
            read_native_state(&path, Some("workspace:a")).unwrap(),
            Some(serde_json::json!({"value":"A"}))
        );
        assert_eq!(
            read_native_state(&path, Some("workspace:b")).unwrap(),
            Some(serde_json::json!({"value":"B"}))
        );
        assert_eq!(
            read_native_state(&path, None).unwrap(),
            Some(serde_json::json!({"value":"B"}))
        );
        std::fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn legacy_candidates_cover_android_package_database_sibling() {
        let app_data = std::path::Path::new("/data/user/0/com.lamtools.mobile/files");
        let candidates = legacy_database_candidates(app_data);
        assert!(candidates.contains(&std::path::PathBuf::from(
            "/data/user/0/com.lamtools.mobile/databases/lamtools-mobile-localSQLite.db"
        )));
    }

    #[test]
    fn sub_agents_and_mail_survive_process_reopen() {
        let root = std::env::temp_dir().join(format!("sunday-sub-agents-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("sub-agents.db");
        let store = SqliteSubAgentStore::new(path.clone()).unwrap();
        store
            .save(&SubAgentRecord {
                parent_thread_id: "parent".into(),
                agent_type: "execute".into(),
                name: "worker".into(),
                model_id: "model-a".into(),
                reasoning_level: "high".into(),
                status: "running".into(),
                summary: String::new(),
                started_at: Some(1),
                completed_at: None,
                elapsed_ms: None,
                sub_session_id: "parent:sub:worker".into(),
                source_call_id: "call-1".into(),
                source_run_id: String::new(),
                source_turn_id: String::new(),
                history: Vec::new(),
                continuation: None,
                approval_request: None,
            })
            .unwrap();
        let mail = SubAgentMail {
            id: "mail-1".into(),
            parent_thread_id: "parent".into(),
            name: "worker".into(),
            direction: "child_to_parent".into(),
            body: "done".into(),
            message_key: "completed:1".into(),
            created_at: 2,
            delivered_at: None,
        };
        assert!(store.insert_mail(&mail).unwrap());
        assert!(!store.insert_mail(&mail).unwrap());
        drop(store);

        let reopened = SqliteSubAgentStore::new(path).unwrap();
        reopened.recover_running("parent").unwrap();
        let record = reopened.load("parent", "worker").unwrap().unwrap();
        assert_eq!(record.status, "interrupted");
        let pending = reopened
            .undelivered("parent", None, "child_to_parent")
            .unwrap();
        assert_eq!(pending.len(), 1);
        reopened
            .mark_delivered(&[pending[0].id.clone()], 3)
            .unwrap();
        assert!(reopened
            .undelivered("parent", None, "child_to_parent")
            .unwrap()
            .is_empty());
        std::fs::remove_dir_all(root).unwrap();
    }

    fn temp_study_store(name: &str) -> StudyStore {
        let root =
            std::env::temp_dir().join(format!("sunday-study-rpc-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        StudyStore::open(root.join("study.db"), StudyScope::local_compatibility()).unwrap()
    }

    fn empty_targets() -> serde_json::Map<String, Value> {
        serde_json::Map::new()
    }

    #[tokio::test]
    async fn study_rpc_routes_operations_and_rejects_unknown_ones() {
        let store = temp_study_store("routing");
        let unknown = dispatch_study(
            &store,
            "study.unknown",
            &json!({}),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap_err();
        assert!(unknown.message().contains("未知的 Study 操作"));

        // A real graph write and read round-trip through the same boundary.
        let built = dispatch_study(
            &store,
            "study.build",
            &json!({
                "revision": 0,
                "operations": [
                    {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "线性代数"}}
                ],
            }),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        assert_eq!(built["revision"], json!(1));

        let read = dispatch_study(
            &store,
            "study.get",
            &json!({}),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        assert_eq!(read["total"], json!(1));
        assert_eq!(read["courses"][0]["name"], json!("线性代数"));

        let missing = dispatch_study(
            &store,
            "study.get",
            &json!({"node_id": "absent"}),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap_err();
        assert!(missing.message().starts_with("Unknown node"));
    }

    #[tokio::test]
    async fn study_rpc_round_trips_the_markdown_note_vault_as_a_user_writer() {
        let store = temp_study_store("notes-rpc");
        store
            .capture_note_raw(
                Some("raw-1"),
                "node",
                "node-1",
                "host snapshot",
                &json!({"record_kind":"node"}),
            )
            .unwrap();
        store
            .notes(
                &json!({
                    "action":"resource_create", "resource_id":"resource-1",
                    "title":"Agent resource", "content":"grounded summary", "raw_ids":["raw-1"]
                }),
                NoteWriter::Agent,
            )
            .unwrap();

        let created = dispatch_study(
            &store,
            "study.notes",
            &json!({
                "action":"create", "note_id":"note-1", "title":"Mobile Note",
                "path":"mobile/note.md", "body_md":"# Note\n\nBody",
                "resource_ids":["resource-1"]
            }),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        assert_eq!(created["revision"], 1);

        let note = dispatch_study(
            &store,
            "study.notes",
            &json!({"action":"get", "note_id":"note-1"}),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        assert_eq!(note["note"]["body_md"], "# Note\n\nBody");
        assert_eq!(note["note"]["resource_ids"], json!(["resource-1"]));

        let forbidden = dispatch_study(
            &store,
            "study.notes",
            &json!({
                "action":"resource_create", "title":"forged", "content":"forged",
                "raw_ids":["raw-1"]
            }),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap_err();
        assert_eq!(forbidden.message(), "RESOURCE_AGENT_ONLY");
    }

    #[tokio::test]
    async fn study_rpc_round_trips_an_exam_and_its_signed_evidence() {
        let store = temp_study_store("exam-rpc");
        dispatch_study(
            &store,
            "study.build",
            &json!({
                "revision": 0,
                "operations": [
                    {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "课程"}},
                    {"action": "create", "kind": "node", "id": "node-1", "data": {"name": "极限", "type": "concept", "course_ids": ["course-a"]}}
                ],
            }),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        let created = dispatch_study(
            &store,
            "study.exam",
            &json!({
                "action": "create",
                "questions": [{
                    "type": "written", "prompt": "解释极限", "node_ids": ["node-1"],
                    "answer": "ε-δ", "max_score": 10,
                }],
            }),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        let exam_id = created["exam"]["id"].as_str().unwrap().to_owned();

        // An ordinary exam read never carries the reference answer.
        let public = dispatch_study(
            &store,
            "study.exam",
            &json!({"action": "get", "exam_id": exam_id}),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        assert!(public["exam"]["questions"][0].get("answer").is_none());

        dispatch_study(
            &store,
            "study.exam",
            &json!({"action": "submit", "exam_id": exam_id, "answers": {"1": "我的答案"}}),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        let graded = dispatch_study(
            &store,
            "study.exam",
            &json!({
                "action": "grade",
                "exam_id": exam_id,
                "results": [{
                    "question_id": "1", "state": "correct", "score": 10, "reason": "完整",
                    "assessed_node_ids": ["node-1"], "incorrect_node_ids": [],
                }],
            }),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        let suggestion = graded["exam"]["suggestions"][0].clone();

        let signed = dispatch_study(
            &store,
            "study.sign",
            &json!({
                "exam_id": exam_id,
                "grading_version": 1,
                "updates": [{
                    "node_id": "node-1",
                    "passed": suggestion["passed"],
                    "mastery": suggestion["mastery"],
                    "reason": suggestion["reason"],
                    "question_ids": suggestion["question_ids"],
                }],
            }),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        assert_eq!(signed["updated"], json!(1));
        assert_eq!(store.node("node-1").unwrap()["assessment"], json!("pass"));
    }

    #[tokio::test]
    async fn study_rpc_uses_host_metadata_and_session_targets_only() {
        let store = temp_study_store("metadata");
        dispatch_study(
            &store,
            "study.build",
            &json!({
                "revision": 0,
                "operations": [
                    {"action": "create", "kind": "course", "id": "course-a", "data": {"name": "课程"}},
                    {"action": "create", "kind": "node", "id": "node-1", "data": {"name": "矩阵", "type": "concept", "course_ids": ["course-a"]}}
                ],
            }),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        dispatch_study(
            &store,
            "study.current",
            &json!({"node_id": "node-1"}),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();

        let mut metadata = serde_json::Map::new();
        metadata.insert("study_scope".into(), json!("node"));
        let context = dispatch_study(
            &store,
            "study.context",
            &json!({"session_id": "study:node:node-1"}),
            Some(&metadata),
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        assert!(context["instructions"].as_str().unwrap().contains("Study"));
        assert_eq!(
            context["latest_context"]["selected_node_id"],
            json!("node-1")
        );

        let mut targets = serde_json::Map::new();
        targets.insert(
            "study:main".into(),
            json!({"id": "study:main", "title": "知识图谱"}),
        );
        let pinned = dispatch_study(
            &store,
            "study.pin",
            &json!({"action": "add", "entity_type": "session", "entity_id": "study:main"}),
            None,
            &targets,
            None,
        )
        .await
        .unwrap();
        assert_eq!(pinned["pins"][0]["title"], json!("知识图谱"));
        // A session the host does not own cannot be pinned.
        let rejected = dispatch_study(
            &store,
            "study.pin",
            &json!({"action": "add", "entity_type": "session", "entity_id": "foreign"}),
            None,
            &targets,
            None,
        )
        .await
        .unwrap_err();
        assert!(rejected.message().contains("Unknown Study session"));

        let binding = dispatch_study(
            &store,
            "study.binding.ensure",
            &json!({"kind": "map", "session_id": "study:main"}),
            None,
            &targets,
            None,
        )
        .await
        .unwrap();
        assert_eq!(binding["created"], json!(true));
        let primary = dispatch_study(
            &store,
            "study.binding.primary",
            &json!({"kind": "map"}),
            None,
            &targets,
            None,
        )
        .await
        .unwrap();
        assert_eq!(primary["binding"]["session_id"], json!("study:main"));

        // A text action without a provider still works through the dictionary.
        let mark = dispatch_study(
            &store,
            "study.marks",
            &json!({"action": "create", "anchor": {"document_id": "d", "block_id": "b", "start": 0, "end": 3, "quote": "run"}}),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap();
        let mark_id = mark["mark"]["id"].as_str().unwrap().to_owned();
        let explained = dispatch_study(
            &store,
            "study.text",
            &json!({"id": mark_id, "action": "explain"}),
            None,
            &empty_targets(),
            None,
        )
        .await
        .unwrap_err();
        assert!(explained.message().contains("Configure a model first"));
    }

    #[test]
    fn dreaming_throttle_is_durable_and_turn_idempotent() {
        let root = std::env::temp_dir().join(format!("sunday-dreaming-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("dreaming.db");
        let store = SqliteDreamStateStore::new(path.clone()).unwrap();
        assert!(!store.register_turn("scope", "turn-1", 2, true).unwrap());
        drop(store);

        let reopened = SqliteDreamStateStore::new(path).unwrap();
        assert!(reopened.register_turn("scope", "turn-2", 2, true).unwrap());
        assert!(reopened.register_turn("scope", "turn-2", 2, true).unwrap());
        reopened.mark_dreamed("scope").unwrap();
        assert!(!reopened.register_turn("scope", "turn-3", 2, true).unwrap());
        std::fs::remove_dir_all(root).unwrap();
    }
}
