use lamtools_runtime::{
    fetch_tools::WebFetchTools,
    plan_tools::PlanTools,
    hooks::{HookEngine, HookListPayload, HookRegistry, HookRunContext},
    mcp::{load_server_configs, CompositeToolRuntime, McpLoadReport, McpServerConfig, McpToolRuntime},
    memory::{dream_with_model, DreamingConfig, DreamingOutcome},
    project_tools::ProjectFileTools,
    provider::{HttpModelBackend, ProviderConfig, RetryPolicy},
    skills::{CombinedSkillTools, SkillTools},
    study::{
        immutable_raw_id, NoteWriter, StudyScope, StudySearchMessage, StudySearchSession,
        StudyStore, StudyTools,
    },
    study_skills::{self, BundledStudySkillTools, StudySkillRecord},
    sub_agent::{
        SubAgentHub, SubAgentMail, SubAgentModelEntry, SubAgentParentConfig, SubAgentRecord,
        SubAgentStore,
    },
    workflow_ops,
    workflow_store::WorkflowStore,
    image_gen::{GenerateImageTools, ImageGenConfig, ImageSink},
    web_search::WebSearchTools,
    AgentContext, AgentRuntime, ApprovalResponse, DeviceCapabilities, Message, ModelBackend,
    ToolCall, ToolObserver, ToolRuntime, TurnContinuation, TurnOptions, TurnProgress, TurnRequest,
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
mod artifacts;
mod checkpoints;
mod goals;
mod attachments;
mod context_loader;
use cancellation::{RegisterError, TurnCancellationRegistry};
use attachments::{AttachmentMetadata, AttachmentStore};
use context_loader::load_project_context;

/// Stage events contain only an opaque turn id and fixed stage names.
/// Message text, request bodies, provider URLs and credentials stay out of the
/// progress event.
fn emit_agent_stage(app: &tauri::AppHandle, turn_id: &str, stage: &'static str) {
    let _ = app.emit(
        "sunday-agent-stage",
        serde_json::json!({ "turnId": turn_id, "stage": stage }),
    );
}

/// Tool payloads can carry whole files. The transcript only needs a readable
/// preview, and an unbounded copy would bloat every stream event and the
/// persisted snapshot.
///
/// The bound is the desktop's (`event/runtime_projection.py`:
/// `DEFAULT_RUNTIME_PREVIEW_CHARS = 25565`, applied per string). It used to be
/// 4000 here, so the phone showed a shorter preview of the same tool step than
/// the desktop did.
const MAX_TOOL_STREAM_CHARS: usize = 25_565;

fn bounded_tool_text(value: &Value) -> String {
    let text = match value {
        Value::String(text) => text.clone(),
        other => serde_json::to_string(other).unwrap_or_default(),
    };
    if text.chars().count() <= MAX_TOOL_STREAM_CHARS {
        return text;
    }
    let mut bounded = text.chars().take(MAX_TOOL_STREAM_CHARS).collect::<String>();
    bounded.push_str("\n…（内容过长已截断）");
    bounded
}

/// Streams each tool step so the transcript can show the work while the turn is
/// still running. The runtime reports coarse stages only, so tool progress needs
/// this narrower channel.
struct MobileToolObserver {
    app: tauri::AppHandle,
    turn_id: String,
    /// Set so a successful project-file write can be recorded as an artifact
    /// revision; the desktop gets the same fact from its event stream.
    project_root: std::path::PathBuf,
    project_id: String,
    session_id: String,
}

impl ToolObserver for MobileToolObserver {
    fn started(&self, call: &ToolCall) {
        let _ = self.app.emit(
            "sunday-agent-stream",
            serde_json::json!({
                "turnId": self.turn_id,
                "kind": "tool_call",
                "data": {
                    "id": call.id,
                    "name": call.name,
                    "arguments": bounded_tool_text(&call.arguments),
                },
            }),
        );
    }

    fn finished(&self, call: &ToolCall, result: &Value, ok: bool) {
        if ok {
            record_tool_artifact(
                &self.app,
                &self.project_root,
                &self.project_id,
                &self.session_id,
                &self.turn_id,
                call,
            );
        }
        let _ = self.app.emit(
            "sunday-agent-stream",
            serde_json::json!({
                "turnId": self.turn_id,
                "kind": "tool_result",
                "data": {
                    "id": call.id,
                    "name": call.name,
                    "ok": ok,
                    "preview": bounded_tool_text(result),
                },
            }),
        );
    }
}

/// Stores generated images as session attachments so they render in the
/// conversation and open with the existing attachment plumbing.
struct MobileImageSink {
    app: tauri::AppHandle,
    session_id: String,
}

#[async_trait::async_trait]
impl ImageSink for MobileImageSink {
    async fn save_image(
        &self,
        filename: &str,
        mime: &str,
        bytes: &[u8],
    ) -> Result<String, lamtools_runtime::RuntimeError> {
        let store = native_attachment_store(&self.app)
            .map_err(lamtools_runtime::RuntimeError::Tool)?;
        let bytes = bytes.to_vec();
        let session_id = self.session_id.clone();
        let filename = filename.to_owned();
        let mime = mime.to_owned();
        // Hashing and writing are blocking; keep them off the runtime's loop.
        let metadata = tokio::task::spawn_blocking(move || {
            store
                .save(&session_id, &filename, &mime, &bytes)
                .map_err(|error| error.to_string())
        })
        .await
        .map_err(|error| lamtools_runtime::RuntimeError::Tool(error.to_string()))?
        .map_err(lamtools_runtime::RuntimeError::Tool)?;
        Ok(format!("附件 {} ({})", metadata.filename, metadata.id))
    }
}

fn mcp_load_warnings(report: &McpLoadReport) -> Vec<String> {
    if report.errors.is_empty() {
        return Vec::new();
    }
    // MCP startup errors may contain executable paths or child stderr. Keep
    // the UI warning useful without copying untrusted payloads or secrets.
    let mut kinds = BTreeSet::new();
    for error in &report.errors {
        let kind = if error.contains("timed out") {
            "响应超时"
        } else if error.contains("could not start") {
            "启动失败"
        } else if error.contains("closed the connection") {
            "连接中断"
        } else if error.contains("invalid JSON") {
            "返回数据无效"
        } else {
            "工具发现失败"
        };
        kinds.insert(kind);
    }
    vec![format!(
        "{} 个 MCP 服务未就绪（{}）；请检查扩展配置。",
        report.errors.len(),
        kinds.into_iter().collect::<Vec<_>>().join("、")
    )]
}

fn append_runtime_warnings(progress: &mut TurnProgress, warnings: &[String]) {
    if warnings.is_empty() {
        return;
    }
    match progress {
        TurnProgress::Completed { result } => {
            for warning in warnings {
                if !result.runtime_warnings.contains(warning) {
                    result.runtime_warnings.push(warning.clone());
                }
            }
        }
        TurnProgress::ApprovalRequired { continuation, .. } => {
            for warning in warnings {
                if !continuation.runtime_warnings.contains(warning) {
                    continuation.runtime_warnings.push(warning.clone());
                }
            }
        }
    }
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
struct MobileDiagnosticsShare<R: Runtime>(PluginHandle<R>);

#[cfg(target_os = "android")]
struct MobileAttachmentOpen<R: Runtime>(PluginHandle<R>);

// Wrapped as an app command so it passes the IPC ACL: plugin commands invoked
// straight from the webview are rejected unless the capability grants a
// permission, and this inline plugin has no permission manifest
// (2026-09-25 审计 P2 — every other Android plugin here is wrapped the same way).
#[cfg(target_os = "android")]
struct MobileLanDiscovery<R: Runtime>(PluginHandle<R>);

#[cfg(target_os = "android")]
#[derive(Deserialize)]
struct AttachmentCacheDirectory {
    path: String,
}

/// The host hands finished work to the system: external links, and the update
/// APK to the package installer.
#[cfg(target_os = "android")]
struct MobileShell<R: Runtime>(PluginHandle<R>);

/// The download Android is running for us, remembered across process death:
/// that is the whole point of handing it to the system service.
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedSystemDownload {
    download_id: String,
    file_name: String,
    directory: String,
    sha256: String,
    #[serde(default)]
    verified: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ShellDownloadStarted {
    id: String,
    file_name: String,
    directory: String,
}

/// The system download's own report, mapped by the plugin.
#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ShellDownloadState {
    state: String,
    received: i64,
    total: i64,
    reason: String,
}

#[cfg(target_os = "android")]
fn persisted_download_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    let directory = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("state");
    std::fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
    Ok(directory.join("update-download.json"))
}

#[cfg(target_os = "android")]
fn read_persisted_download(app: &tauri::AppHandle) -> Option<PersistedSystemDownload> {
    let path = persisted_download_path(app).ok()?;
    let text = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&text).ok()
}

#[cfg(target_os = "android")]
fn write_persisted_download(app: &tauri::AppHandle, value: &PersistedSystemDownload) {
    if let Ok(path) = persisted_download_path(app) {
        if let Ok(text) = serde_json::to_string(value) {
            let _ = std::fs::write(path, text);
        }
    }
}

#[cfg(target_os = "android")]
fn clear_persisted_download(app: &tauri::AppHandle) {
    if let Ok(path) = persisted_download_path(app) {
        let _ = std::fs::remove_file(path);
    }
}

/// Live update-download state: the UI polls it for progress, and the install
/// hand-off refuses anything that is not a download this process verified.
#[derive(Default)]
struct UpdateDownloadState {
    inner: std::sync::Mutex<UpdateDownloadStatus>,
}

#[derive(Clone, Default, Serialize)]
#[serde(rename_all = "camelCase")]
struct UpdateDownloadStatus {
    /// idle | downloading | verified | failed
    state: String,
    received: u64,
    total: Option<u64>,
    file_name: String,
    sha256: String,
    error: String,
}

/// One line the UI can show verbatim; the desktop host composes the same text.
#[cfg(target_os = "android")]
fn update_status_message(status: &UpdateDownloadStatus) -> String {
    match status.state.as_str() {
        "downloading" => match status.total {
            Some(total) if total > 0 => {
                let percent = (status.received.saturating_mul(100) / total).min(100);
                format!(
                    "正在下载 {percent}%（{:.1} MB / {:.1} MB）",
                    status.received as f64 / (1024.0 * 1024.0),
                    total as f64 / (1024.0 * 1024.0)
                )
            }
            _ => format!(
                "正在下载（{:.1} MB）",
                status.received as f64 / (1024.0 * 1024.0)
            ),
        },
        "verified" => format!("已下载并校验 {}", status.file_name),
        _ => String::new(),
    }
}

#[cfg(target_os = "android")]
#[derive(Serialize)]
struct ShellUrlRequest<'a> {
    url: &'a str,
}

#[cfg(target_os = "android")]
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ShellFileRequest<'a> {
    file_name: &'a str,
}

#[cfg(target_os = "android")]
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ShellDownloadRequest<'a> {
    url: &'a str,
    file_name: &'a str,
}

#[cfg(target_os = "android")]
#[derive(Serialize)]
struct ShellDownloadIdRequest<'a> {
    id: &'a str,
}

#[cfg(target_os = "android")]
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct AttachmentOpenRequest<'a> {
    file_name: &'a str,
    mime_type: &'a str,
}

#[cfg(target_os = "android")]
#[derive(Serialize)]
struct DiagnosticsShareRequest<'a> {
    contents: &'a str,
}

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

/// Attachment bytes travel as base64, not as a JSON array of numbers.
///
/// The same bytes as `[1,2,3,…]` cost several times their size on the wire and
/// again in the webview's JSON parser, which is what made attaching a large
/// photo slow enough to notice. Every other byte-carrying command in this host
/// (`sunday_artifact_file`, `project_file_read_raw`) already sends base64.
#[derive(Serialize)]
struct MobileAttachmentData {
    metadata: AttachmentMetadata,
    data_base64: String,
}

fn native_attachment_store(app: &tauri::AppHandle) -> Result<AttachmentStore, String> {
    let root = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("attachments");
    AttachmentStore::new(root).map_err(|error| error.to_string())
}

#[tauri::command]
async fn sunday_attachment_save(
    app: tauri::AppHandle,
    session_id: String,
    filename: String,
    mime: String,
    data_base64: String,
) -> Result<AttachmentMetadata, String> {
    use base64::Engine;
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(data_base64.as_bytes())
        .map_err(|error| format!("attachment payload is not valid base64: {error}"))?;
    tokio::task::spawn_blocking(move || {
        native_attachment_store(&app)?
            .save(&session_id, &filename, &mime, &bytes)
            .map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn sunday_attachment_read(
    app: tauri::AppHandle,
    id: String,
) -> Result<MobileAttachmentData, String> {
    tokio::task::spawn_blocking(move || {
        use base64::Engine;
        let data = native_attachment_store(&app)?
            .read(&id)
            .map_err(|error| error.to_string())?;
        Ok(MobileAttachmentData {
            metadata: data.metadata,
            data_base64: base64::engine::general_purpose::STANDARD.encode(&data.bytes),
        })
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn sunday_attachment_list(
    app: tauri::AppHandle,
    session_id: String,
) -> Result<Vec<AttachmentMetadata>, String> {
    tokio::task::spawn_blocking(move || {
        native_attachment_store(&app)?
            .list(&session_id)
            .map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn sunday_attachment_delete(
    app: tauri::AppHandle,
    id: String,
) -> Result<bool, String> {
    tokio::task::spawn_blocking(move || {
        native_attachment_store(&app)?
            .delete(&id)
            .map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())?
}

#[cfg(target_os = "android")]
#[tauri::command]
async fn sunday_attachment_open(
    app: tauri::AppHandle,
    opener: tauri::State<'_, MobileAttachmentOpen<tauri::Wry>>,
    id: String,
) -> Result<(), String> {
    let directory = opener
        .0
        .run_mobile_plugin::<AttachmentCacheDirectory>("cacheDirectory", serde_json::json!({}))
        .map_err(|_| "无法准备附件缓存".to_owned())?;
    let (file_name, mime_type) = tokio::task::spawn_blocking(move || {
        native_attachment_store(&app)?
            .write_open_cache(&id, std::path::Path::new(&directory.path))
            .map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())??;
    opener
        .0
        .run_mobile_plugin::<Value>(
            "open",
            AttachmentOpenRequest {
                file_name: &file_name,
                mime_type: &mime_type,
            },
        )
        .map(|_| ())
        .map_err(|_| "无法使用系统应用打开附件".to_owned())
}

/// An update artifact name the installer hand-off will accept.
#[cfg(target_os = "android")]
fn validate_update_file_name(value: &str) -> Result<String, String> {
    let trimmed = value.trim();
    let valid = !trimmed.is_empty()
        && trimmed.len() <= 120
        && trimmed.ends_with(".apk")
        && trimmed.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '.' | '_' | '-')
        });
    if !valid {
        return Err("更新文件名无效".into());
    }
    Ok(trimmed.to_owned())
}

/// Start downloading the update the manifest pointed at.
///
/// The transfer goes to Android's own download service, so it keeps running when
/// the app is backgrounded or killed and shows up in the notification shade; the
/// app only needs to be alive again to verify and install it. If the service
/// refuses, the host downloads it in-process instead — the same transfer, minus
/// the survival.
#[cfg(target_os = "android")]
#[tauri::command]
fn sunday_update_download(
    app: tauri::AppHandle,
    shell: tauri::State<'_, MobileShell<tauri::Wry>>,
    url: String,
    sha256: String,
    file_name: String,
) -> Result<Value, String> {
    let file_name = validate_update_file_name(&file_name)?;
    {
        let state = app.state::<UpdateDownloadState>();
        let current = state.inner.lock().map_err(|_| "更新状态不可用".to_owned())?;
        if current.state == "downloading" {
            return Ok(serde_json::json!({
                "ok": true, "state": "downloading", "fileName": current.file_name,
            }));
        }
    }
    // Android may already be downloading one from before this process started;
    // watch that instead of asking for a second copy.
    if let Some(persisted) = read_persisted_download(&app) {
        return Ok(serde_json::json!({
            "ok": true,
            "state": if persisted.verified { "verified" } else { "downloading" },
            "fileName": persisted.file_name,
        }));
    }
    match shell.0.run_mobile_plugin::<ShellDownloadStarted>(
        "startDownload",
        ShellDownloadRequest { url: &url, file_name: &file_name },
    ) {
        Ok(started) => {
            write_persisted_download(
                &app,
                &PersistedSystemDownload {
                    download_id: started.id,
                    file_name: started.file_name.clone(),
                    directory: started.directory,
                    sha256: sha256.clone(),
                    verified: false,
                },
            );
            let state = app.state::<UpdateDownloadState>();
            let mut current = state.inner.lock().map_err(|_| "更新状态不可用".to_owned())?;
            *current = UpdateDownloadStatus {
                state: "downloading".into(),
                file_name: started.file_name.clone(),
                sha256,
                ..Default::default()
            };
            return Ok(serde_json::json!({
                "ok": true, "state": "downloading", "fileName": started.file_name,
            }));
        }
        Err(_) => {
            // No system service: fall back to the in-process download.
        }
    }
    let directory = shell
        .0
        .run_mobile_plugin::<AttachmentCacheDirectory>("updatesDirectory", serde_json::json!({}))
        .map_err(|_| "无法准备更新缓存".to_owned())?
        .path;
    {
        let state = app.state::<UpdateDownloadState>();
        let mut current = state.inner.lock().map_err(|_| "更新状态不可用".to_owned())?;
        *current = UpdateDownloadStatus {
            state: "downloading".into(),
            file_name: file_name.clone(),
            ..Default::default()
        };
    }
    let task_app = app.clone();
    let task_file_name = file_name.clone();
    tauri::async_runtime::spawn(async move {
        let destination = std::path::Path::new(&directory).join(&task_file_name);
        let progress_app = task_app.clone();
        let progress = move |received: u64, total: Option<u64>| {
            if let Some(state) = progress_app.try_state::<UpdateDownloadState>() {
                if let Ok(mut current) = state.inner.lock() {
                    current.received = received;
                    current.total = total;
                }
            }
            let _ = progress_app.emit(
                "sunday-update-progress",
                serde_json::json!({ "received": received, "total": total }),
            );
        };
        let outcome = lamtools_runtime::update_manifest::download_update(
            &url,
            &destination,
            &sha256,
            Some(&progress),
        )
        .await;
        if let Some(state) = task_app.try_state::<UpdateDownloadState>() {
            if let Ok(mut current) = state.inner.lock() {
                match outcome {
                    Ok(done) => {
                        current.state = "verified".into();
                        current.received = done.bytes;
                        current.total = Some(done.bytes);
                        current.sha256 = done.sha256;
                        current.error.clear();
                    }
                    Err(error) => {
                        current.state = "failed".into();
                        current.error = error.to_string();
                    }
                }
            }
        }
    });
    Ok(serde_json::json!({
        "ok": true, "state": "downloading", "fileName": file_name,
    }))
}

/// One JSON shape for the in-process and the system download, so the UI reads
/// progress the same way whichever one ran.
#[cfg(target_os = "android")]
fn download_status_json(status: &UpdateDownloadStatus) -> Value {
    serde_json::json!({
        "ok": true,
        "state": status.state,
        "received": status.received,
        "total": status.total,
        "fileName": status.file_name,
        "sha256": status.sha256,
        "error": status.error,
        "message": update_status_message(status),
    })
}

#[cfg(target_os = "android")]
fn failed_status(message: String) -> Value {
    let status = UpdateDownloadStatus {
        state: "failed".into(),
        error: message.clone(),
        ..Default::default()
    };
    download_status_json(&status)
}

/// How far the download has come, for the progress line in the UI.
///
/// A system download outlives this process, so the persisted record is consulted
/// first: after a restart the only way to know how it went is to ask Android and
/// then verify the bytes it wrote.
#[cfg(target_os = "android")]
#[tauri::command]
async fn sunday_update_status(
    app: tauri::AppHandle,
    shell: tauri::State<'_, MobileShell<tauri::Wry>>,
) -> Result<Value, String> {
    let persisted = read_persisted_download(&app);
    if let Some(persisted) = persisted {
        let report = shell
            .0
            .run_mobile_plugin::<ShellDownloadState>(
                "downloadState",
                ShellDownloadIdRequest { id: &persisted.download_id },
            )
            .map_err(|_| "无法读取下载进度".to_owned())?;
        // Already checked in an earlier poll: do not hash 60 MB again — but do
        // confirm the file is still there. Android cleans its own external
        // directory, and offering an install for a file that is gone just
        // strands the user on a button that always fails.
        if persisted.verified && report.state == "successful" {
            let path = std::path::Path::new(&persisted.directory).join(&persisted.file_name);
            if !path.is_file() {
                clear_persisted_download(&app);
                return Ok(failed_status("安装包已不存在，请重新下载".into()));
            }
            let bytes = std::fs::metadata(&path).map(|meta| meta.len()).unwrap_or(0);
            let status = UpdateDownloadStatus {
                state: "verified".into(),
                received: bytes,
                total: Some(bytes),
                file_name: persisted.file_name.clone(),
                sha256: persisted.sha256.clone(),
                error: String::new(),
            };
            return Ok(download_status_json(&status));
        }
        match report.state.as_str() {
            "successful" => {
                let path = std::path::Path::new(&persisted.directory).join(&persisted.file_name);
                let expected = persisted.sha256.clone();
                // Hashing 60 MB is blocking work: keep it off the runtime's loop.
                let verified = tauri::async_runtime::spawn_blocking(move || {
                    lamtools_runtime::update_manifest::verify_file_sha256(&path, &expected)
                        .map(|digest| (digest, path))
                })
                .await
                .map_err(|error| error.to_string())?;
                match verified {
                    Ok((digest, path)) => {
                        let bytes = std::fs::metadata(&path).map(|meta| meta.len()).unwrap_or(0);
                        let mut record = persisted.clone();
                        record.verified = true;
                        record.sha256 = digest.clone();
                        write_persisted_download(&app, &record);
                        // Keep the in-memory view in step for this process.
                        let state = app.state::<UpdateDownloadState>();
                        let mut current = state
                            .inner
                            .lock()
                            .map_err(|_| "更新状态不可用".to_owned())?;
                        current.state = "verified".into();
                        current.received = bytes;
                        current.total = Some(bytes);
                        current.file_name = persisted.file_name.clone();
                        current.sha256 = digest.clone();
                        current.error.clear();
                        drop(current);
                        let status = UpdateDownloadStatus {
                            state: "verified".into(),
                            received: bytes,
                            total: Some(bytes),
                            file_name: persisted.file_name.clone(),
                            sha256: digest,
                            error: String::new(),
                        };
                        return Ok(download_status_json(&status));
                    }
                    Err(error) => {
                        // Whatever Android downloaded is not what the manifest
                        // described: drop it instead of offering it.
                        let _ = std::fs::remove_file(
                            std::path::Path::new(&persisted.directory).join(&persisted.file_name),
                        );
                        clear_persisted_download(&app);
                        return Ok(failed_status(error.to_string()));
                    }
                }
            }
            "failed" => {
                clear_persisted_download(&app);
                return Ok(failed_status(format!(
                    "系统下载失败（原因代码 {}），请重试",
                    report.reason
                )));
            }
            "unknown" => {
                clear_persisted_download(&app);
                return Ok(failed_status("下载记录已失效，请重新下载".into()));
            }
            _ => {
                let status = UpdateDownloadStatus {
                    state: "downloading".into(),
                    received: report.received.max(0) as u64,
                    total: (report.total > 0).then_some(report.total as u64),
                    file_name: persisted.file_name.clone(),
                    sha256: persisted.sha256.clone(),
                    error: String::new(),
                };
                return Ok(download_status_json(&status));
            }
        }
    }
    let status = {
        let state = app.state::<UpdateDownloadState>();
        let current = state
            .inner
            .lock()
            .map_err(|_| "更新状态不可用".to_owned())?;
        current.clone()
    };
    Ok(download_status_json(&status))
}

/// The file name of a download this host verified, system-owned or in-process.
///
/// The persisted record comes first: after the app was killed mid-download, the
/// system finished it and there is no in-memory state left to consult.
#[cfg(target_os = "android")]
fn verified_update_file(app: &tauri::AppHandle) -> Option<String> {
    if let Some(persisted) = read_persisted_download(app) {
        if persisted.verified {
            return Some(persisted.file_name);
        }
    }
    let state = app.state::<UpdateDownloadState>();
    let current = state.inner.lock().ok()?;
    if current.state == "verified" {
        return Some(current.file_name.clone());
    }
    None
}

/// Hand the verified APK to Android's package installer. The user confirms
/// there — Android has no silent install for an ordinary app.
///
/// Takes no arguments: the file name comes from the download this process
/// verified, so the UI cannot point the installer at anything else.
#[cfg(target_os = "android")]
#[tauri::command]
fn sunday_update_install(
    app: tauri::AppHandle,
    shell: tauri::State<'_, MobileShell<tauri::Wry>>,
) -> Result<Value, String> {
    let file_name = verified_update_file(&app).ok_or_else(|| "尚未下载并校验安装包".to_owned())?;
    let file_name = validate_update_file_name(&file_name)?;
    shell
        .0
        .run_mobile_plugin::<Value>("installApk", ShellFileRequest { file_name: &file_name })
        .map_err(|_| "无法启动系统安装器".to_owned())?;
    Ok(serde_json::json!({
        "ok": true,
        "message": "已交给系统安装器；请在系统界面确认安装",
    }))
}

/// Open an external http(s) link in the system browser.
#[cfg(target_os = "android")]
#[tauri::command]
fn sunday_open_external_url(
    shell: tauri::State<'_, MobileShell<tauri::Wry>>,
    url: String,
) -> Result<Value, String> {
    let trimmed = url.trim();
    if !(trimmed.starts_with("https://") || trimmed.starts_with("http://")) {
        return Err("仅支持 http(s) 链接".into());
    }
    shell
        .0
        .run_mobile_plugin::<Value>("openUrl", ShellUrlRequest { url: trimmed })
        .map_err(|_| "无法打开链接".to_owned())
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
    retry_config: Value,
    #[serde(default)]
    models: Vec<SubAgentModelEntry>,
    history: Vec<Message>,
    #[serde(default)]
    context: AgentContext,
    #[serde(default)]
    load_context_config: Value,
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
    #[serde(default)]
    disabled_skill_names: Vec<String>,
    /// Bundled plugins the user switched off. Plugin tools must respect it, or
    /// the switch would be a control that changes nothing.
    #[serde(default)]
    disabled_plugin_names: Vec<String>,
    /// `core.imagegen` settings; the host resolves them so the runtime can stay
    /// unaware of where a platform keeps configuration.
    #[serde(default)]
    imagegen_config: Value,
    /// `core.websearch` settings, shaped like the bundled websearch plugin's
    /// schema (provider / fallback_providers / limit / timeout).
    #[serde(default)]
    websearch_config: Value,
}

#[tauri::command]
fn sunday_study_skill_catalog() -> Vec<StudySkillRecord> {
    study_skills::catalog()
}

/// Bundled plugin tool inventory for the extensions panel.
///
/// Derived from the manifests and the runtimes this host actually assembles, so
/// the panel cannot advertise a tool the agent would refuse to run.
/// The project's AGENTS.md, the same file the desktop project panel edits.
/// The desktop serves it under `GET|PUT /projects/{id}/agents-md`; the mobile
/// host has no HTTP server for the WebView, so the transport exposes this
/// command on that path instead. The path is validated by
/// [`safe_project_relative_path`].
#[tauri::command]
async fn project_agents_md(
    app: tauri::AppHandle,
    project_id: String,
    content: Option<String>,
) -> Result<Value, String> {
    tokio::task::spawn_blocking(move || {
        let root = native_project_root(&app, &project_id)?;
        let target = safe_project_relative_path(&root, "AGENTS.md", false)?;
        if let Some(content) = content {
            std::fs::write(&target, content.as_bytes()).map_err(|error| error.to_string())?;
            return Ok(serde_json::json!({"content": content, "exists": true}));
        }
        match std::fs::read_to_string(&target) {
            Ok(existing) => Ok(serde_json::json!({"content": existing, "exists": true})),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                Ok(serde_json::json!({"content": "", "exists": false}))
            }
            Err(error) => Err(error.to_string()),
        }
    })
    .await
    .map_err(|error| error.to_string())?
}

#[tauri::command]
fn sunday_plugin_inventory() -> Vec<lamtools_runtime::plugin_catalog::PluginInventory> {
    lamtools_runtime::plugin_catalog::bundled_plugin_inventory()
}

/// The in-app update manifest, fetched by the host rather than the WebView.
///
/// The app's WebView origin is cross-origin to the release site, so a `fetch`
/// from the app depends on the site's CORS headers and reports a missing one as
/// a bare `Failed to fetch` with no status. The host reports the real one.
#[tauri::command]
async fn sunday_update_manifest(url: String) -> Result<Value, String> {
    lamtools_runtime::update_manifest::fetch_update_manifest(&url)
        .await
        .map_err(|error| error.to_string())
}

/// An ISO-8601 UTC timestamp, shared by the stores that record one.
fn timestamp_iso() -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_secs())
        .unwrap_or_default();
    let days = (seconds / 86_400) as i64;
    let time = seconds % 86_400;
    let (hour, minute, second) = (time / 3600, (time % 3600) / 60, time % 60);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { year + 1 } else { year };
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

/// The artifact store lives beside the other host databases.
fn native_artifact_store(app: &tauri::AppHandle) -> Result<artifacts::ArtifactStore, String> {
    let data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    artifacts::ArtifactStore::open(&data.join("artifacts.db"), &data.join("blobs"))
}

/// Record a write the agent just made as an artifact revision.
///
/// The desktop derives the same fact from its event stream; the phone has no
/// projector, so the observation of the tool call is the source. Only tools that
/// produce project files are recorded, and an unchanged write is not a new
/// revision (the store decides that).
fn record_tool_artifact(
    app: &tauri::AppHandle,
    project_root: &std::path::Path,
    project_id: &str,
    thread_id: &str,
    turn_id: &str,
    call: &ToolCall,
) {
    if !matches!(call.name.as_str(), "write_file" | "edit_file") {
        return;
    }
    let Some(path) = call.arguments.get("path").and_then(Value::as_str) else {
        return;
    };
    let Ok(store) = native_artifact_store(app) else {
        return;
    };
    let origin = artifacts::ArtifactOrigin {
        thread_id: thread_id.to_owned(),
        turn_id: turn_id.to_owned(),
        item_id: call.id.clone(),
        tool_name: call.name.clone(),
    };
    let _ = store.record_file(project_id, project_root, path, origin);
}

#[tauri::command]
async fn sunday_artifact_list(
    app: tauri::AppHandle,
    project_id: String,
    include_deleted: Option<bool>,
) -> Result<Value, String> {
    let store = native_artifact_store(&app)?;
    let records = store.list(&project_id, include_deleted.unwrap_or(false))?;
    Ok(serde_json::json!({"artifacts": records}))
}

#[tauri::command]
async fn sunday_artifact_revisions(
    app: tauri::AppHandle,
    project_id: String,
    artifact_id: String,
) -> Result<Value, String> {
    let store = native_artifact_store(&app)?;
    let artifact = store
        .artifact(&artifact_id)?
        .filter(|record| record.project_id == project_id)
        .ok_or_else(|| "Artifact not found".to_owned())?;
    let revisions = store.revisions(&artifact_id)?;
    Ok(serde_json::json!({"artifact": artifact, "revisions": revisions}))
}

#[tauri::command]
async fn sunday_artifact_set_deleted(
    app: tauri::AppHandle,
    project_id: String,
    artifact_ids: Vec<String>,
    deleted: bool,
) -> Result<Value, String> {
    if artifact_ids.is_empty() {
        return Err("artifact_ids is required".into());
    }
    let store = native_artifact_store(&app)?;
    let changed = store.set_deleted(&project_id, &artifact_ids, deleted)?;
    Ok(if deleted {
        serde_json::json!({"deleted": changed})
    } else {
        serde_json::json!({"restored": changed})
    })
}

#[tauri::command]
async fn sunday_artifact_restore_revision(
    app: tauri::AppHandle,
    project_id: String,
    artifact_id: String,
    revision_id: String,
) -> Result<Value, String> {
    let store = native_artifact_store(&app)?;
    let root = native_project_root(&app, &project_id)?;
    let record = store.restore_revision(&project_id, &root, &artifact_id, &revision_id)?;
    Ok(serde_json::json!({"artifact": record}))
}

/// Hand one artifact revision to the system's default application.
///
/// Android-only for the same reason the attachment opener is: it goes through
/// the mobile plugin handle that only exists there.
///
/// Android cannot give another app a path inside app-private storage, so the
/// bytes are written to the plugin's cache directory and opened from there —
/// the same route the attachment panel uses. Attachment-backed artifacts are
/// refused, as the desktop refuses them.
#[cfg(target_os = "android")]
#[tauri::command]
async fn sunday_artifact_open(
    app: tauri::AppHandle,
    opener: tauri::State<'_, MobileAttachmentOpen<tauri::Wry>>,
    project_id: String,
    artifact_id: String,
    revision_id: Option<String>,
) -> Result<Value, String> {
    let store = native_artifact_store(&app)?;
    let record = store
        .artifact(&artifact_id)?
        .filter(|record| record.project_id == project_id)
        .ok_or_else(|| "Artifact not found".to_owned())?;
    if record.path.starts_with("attachment://") {
        return Err("附件型成果请使用附件打开".into());
    }
    let (bytes, mime_type) = store.revision_bytes(&record, revision_id.as_deref())?;
    let directory = opener
        .0
        .run_mobile_plugin::<AttachmentCacheDirectory>("cacheDirectory", serde_json::json!({}))
        .map_err(|_| "无法准备打开缓存".to_owned())?;
    let file_name = if record.name.trim().is_empty() {
        "artifact".to_owned()
    } else {
        record.name.clone()
    };
    let target = std::path::Path::new(&directory.path).join(&file_name);
    std::fs::write(&target, &bytes).map_err(|error| error.to_string())?;
    opener
        .0
        .run_mobile_plugin::<Value>(
            "open",
            AttachmentOpenRequest {
                file_name: &file_name,
                mime_type: &mime_type,
            },
        )
        .map(|_| ())
        .map_err(|_| "无法使用系统应用打开成果".to_owned())?;
    Ok(serde_json::json!({"status": "opened", "path": record.path}))
}

/// Bytes of one artifact revision; `null` when the artifact is not this project's.
#[tauri::command]
async fn sunday_artifact_file(
    app: tauri::AppHandle,
    project_id: String,
    artifact_id: String,
    revision_id: Option<String>,
) -> Result<Option<Value>, String> {
    let store = native_artifact_store(&app)?;
    let Some(record) = store
        .artifact(&artifact_id)?
        .filter(|record| record.project_id == project_id)
    else {
        return Ok(None);
    };
    let (bytes, mime_type) = store.revision_bytes(&record, revision_id.as_deref())?;
    use base64::Engine;
    Ok(Some(serde_json::json!({
        "path": record.path,
        "mimeType": mime_type,
        "dataBase64": base64::engine::general_purpose::STANDARD.encode(&bytes),
    })))
}

/// The goal store, beside the other host databases.
fn native_goal_store(app: &tauri::AppHandle) -> Result<goals::GoalStore, String> {
    let data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    goals::GoalStore::open(&data.join("goals.db"))
}

#[tauri::command]
async fn sunday_goal_create(
    app: tauri::AppHandle,
    thread_id: String,
    objective: String,
    completion_criteria: Option<Vec<String>>,
    metadata: Option<Value>,
    goal_id: Option<String>,
) -> Result<Value, String> {
    let store = native_goal_store(&app)?;
    let goal = store.create(
        &thread_id,
        &objective,
        &completion_criteria.unwrap_or_default(),
        metadata.unwrap_or(Value::Null),
        goal_id.as_deref().unwrap_or_default(),
    )?;
    Ok(goals::goal_payload(&goal))
}

#[tauri::command]
async fn sunday_goal_get(app: tauri::AppHandle, goal_id: String) -> Result<Value, String> {
    let store = native_goal_store(&app)?;
    let goal = store
        .goal(&goal_id)?
        .ok_or_else(|| "Goal not found".to_owned())?;
    Ok(goals::goal_payload(&goal))
}

#[tauri::command]
async fn sunday_goal_list(
    app: tauri::AppHandle,
    thread_id: Option<String>,
    status: Option<String>,
) -> Result<Value, String> {
    let store = native_goal_store(&app)?;
    let goals = store.list(thread_id.as_deref(), status.as_deref())?;
    Ok(serde_json::json!({
        "goals": goals.iter().map(|goal| goal).map(serde_json::to_value).collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())?,
    }))
}

/// Patch semantics: an omitted field keeps its stored value, so the panel can
/// clear a status reason without clearing the objective.
#[tauri::command]
async fn sunday_goal_update(
    app: tauri::AppHandle,
    goal_id: String,
    objective: Option<String>,
    completion_criteria: Option<Vec<String>>,
    status: Option<String>,
    status_reason: Option<String>,
    metadata: Option<Value>,
) -> Result<Value, String> {
    let store = native_goal_store(&app)?;
    let goal = store.update(
        &goal_id,
        objective.as_deref(),
        completion_criteria.as_deref(),
        status.as_deref(),
        status_reason.as_deref(),
        metadata,
    )?;
    Ok(goals::goal_payload(&goal))
}

/// The checkpoint store, beside the other host databases.
fn native_checkpoint_store(app: &tauri::AppHandle) -> Result<checkpoints::CheckpointStore, String> {
    let data = app.path().app_data_dir().map_err(|error| error.to_string())?;
    checkpoints::CheckpointStore::open(&data.join("checkpoints.db"))
}

/// Record a checkpoint for one turn, at the turn boundary.
fn record_turn_checkpoint(
    app: &tauri::AppHandle,
    project_root: &std::path::Path,
    session_id: &str,
    turn_id: &str,
) {
    let Ok(store) = native_checkpoint_store(app) else {
        return;
    };
    let _ = store.create(
        project_root,
        session_id,
        turn_id,
        "",
        "",
        checkpoints::ActorKind::Agent,
    );
}

#[tauri::command]
async fn sunday_checkpoint_create(
    app: tauri::AppHandle,
    session_id: String,
    turn_id: Option<String>,
    label: Option<String>,
    reason: Option<String>,
) -> Result<Value, String> {
    let store = native_checkpoint_store(&app)?;
    let root = native_project_root(&app, &String::new())?;
    let record = store.create(
        &root,
        &session_id,
        turn_id.as_deref().unwrap_or_default(),
        label.as_deref().unwrap_or_default(),
        reason.as_deref().unwrap_or_default(),
        checkpoints::ActorKind::User,
    )?;
    Ok(serde_json::json!({"checkpoint": record, "nodes": [record]}))
}

#[tauri::command]
async fn sunday_checkpoint_get(app: tauri::AppHandle, checkpoint_id: String) -> Result<Value, String> {
    let store = native_checkpoint_store(&app)?;
    let record = store
        .checkpoint(&checkpoint_id)?
        .ok_or_else(|| format!("检查点不存在: {checkpoint_id}"))?;
    Ok(serde_json::json!({"checkpoint": record}))
}

#[tauri::command]
async fn sunday_checkpoint_graph(app: tauri::AppHandle, session_id: String) -> Result<Value, String> {
    let store = native_checkpoint_store(&app)?;
    let (nodes, heads) = store.graph(&session_id)?;
    Ok(checkpoints::graph_payload(&nodes, &heads))
}

#[tauri::command]
async fn sunday_checkpoint_list(app: tauri::AppHandle, session_id: String) -> Result<Value, String> {
    let store = native_checkpoint_store(&app)?;
    let nodes = store.list(&session_id)?;
    Ok(serde_json::json!({"nodes": nodes}))
}

#[tauri::command]
async fn sunday_checkpoint_restore(
    app: tauri::AppHandle,
    project_id: String,
    session_id: String,
    checkpoint_id: String,
    scope: Option<String>,
) -> Result<Value, String> {
    let store = native_checkpoint_store(&app)?;
    let artifacts = native_artifact_store(&app)?;
    let root = native_project_root(&app, &project_id)?;
    let outcome = checkpoints::restore(
        &store,
        &artifacts,
        &root,
        &project_id,
        &session_id,
        &checkpoint_id,
        scope.as_deref().unwrap_or("workspace"),
    )?;
    Ok(checkpoints::restore_payload(&outcome))
}

/// Every tool this host can advertise, for the mode tool-set editor.
///
/// The desktop answers `config.loadtools.get` with a catalog derived from its
/// tool specs; the mobile transport answers the same call from this side,
/// because only the host knows which runtimes are assembled.
#[tauri::command]
fn sunday_tool_catalog() -> Vec<lamtools_runtime::tool_catalog::CatalogTool> {
    lamtools_runtime::tool_catalog::catalog_tools()
}

/// Config schema each bundled plugin declares, for the plugin config panel.
///
/// The desktop discovers these by scanning the plugin's `config/schema.jsonc`;
/// the mobile host has no plugin loader, so the same files are embedded and
/// parsed here. A plugin with no schema is reported without one, and the panel
/// then shows no configuration entry rather than an empty form.
#[tauri::command]
fn sunday_plugin_schemas() -> Value {
    let schemas = [
        ("imagegen", include_str!("../../../src/lamtools_core/plugins/bundled/imagegen/config/schema.jsonc")),
        ("websearch", include_str!("../../../src/lamtools_core/plugins/bundled/websearch/config/schema.jsonc")),
    ];
    let mut payload = serde_json::Map::new();
    for (name, raw) in schemas {
        let Ok(schema) = json5::from_str::<Value>(raw) else {
            continue;
        };
        payload.insert(
            name.to_owned(),
            serde_json::json!({
                "schema": schema,
                "path": format!("bundled://{name}/config/schema.jsonc"),
            }),
        );
    }
    Value::Object(payload)
}

/// Tool names the bundled Study plugin grants its own mode (`study:study`).
#[tauri::command]
fn sunday_plugin_mode_tools(mode: String) -> Vec<String> {
    if mode == "study:study" {
        return lamtools_runtime::tool_catalog::study_mode_tools();
    }
    Vec::new()
}

/// The bundled websearch settings, resolved the way the desktop resolves the
/// plugin's `config/schema.jsonc`: provider, fallback order, result limit and
/// timeout. Missing or malformed values keep the runtime defaults.
fn web_search_tools(config: &Value) -> WebSearchTools {
    let provider = config
        .get("provider")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let fallback: Vec<String> = config
        .get("fallback_providers")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default();
    WebSearchTools::new().with_config(
        provider,
        &fallback,
        config.get("limit").and_then(Value::as_u64),
        config.get("timeout").and_then(Value::as_u64),
    )
}

fn apply_study_skill_context(context: &mut AgentContext, disabled: &[String]) {
    if !context
        .mode_context
        .contains(lamtools_runtime::study::STUDY_SYSTEM_PROMPT.trim())
    {
        if !context.mode_context.trim().is_empty() {
            context.mode_context.push_str("\n\n");
        }
        context
            .mode_context
            .push_str(lamtools_runtime::study::STUDY_SYSTEM_PROMPT.trim());
    }
    context.mode_context.push_str("\n\n");
    context
        .mode_context
        .push_str(&study_skills::catalog_prompt(disabled));
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
    if payload.study_tools {
        apply_study_skill_context(&mut context, &payload.disabled_skill_names);
    } else {
        context = load_project_context(&project_root, context, &payload.load_context_config)?;
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
    let (mcp_configs, invalid_mcp_configs) =
        load_mobile_mcp_configs(&project_root, &payload.mcp_config).await;
    let mcp_runtime = Arc::new(McpToolRuntime::load(mcp_configs).await);
    let mut mcp_warnings = mcp_load_warnings(mcp_runtime.report());
    if invalid_mcp_configs > 0 {
        mcp_warnings.push(format!(
            "{} 个 MCP 配置缺少可执行命令或格式无效，请检查扩展配置。",
            invalid_mcp_configs
        ));
    }
    emit_agent_stage(
        &app,
        &trace_turn_id,
        if mcp_warnings.is_empty() {
            "native_mcp_ready"
        } else {
            "native_mcp_partial"
        },
    );
    let hook_engine = Arc::new(HookEngine::new(hooks).with_mcp_caller(mcp_runtime.clone()));
    let project_runtime: Arc<dyn ToolRuntime> =
        Arc::new(ProjectFileTools::new(project_root.clone()));
    let (skill_runtime, skill_prompt): (Arc<dyn ToolRuntime>, String) = if payload.study_tools {
        let skills = CombinedSkillTools::new(payload.disabled_skill_names.clone(), Vec::new());
        let prompt = SkillTools::new(payload.disabled_skill_names.clone(), Vec::new())
            .catalog_prompt_for(&capabilities);
        (Arc::new(skills), prompt)
    } else {
        let skills = SkillTools::new(payload.disabled_skill_names.clone(), Vec::new());
        let prompt = skills.catalog_prompt_for(&capabilities);
        (Arc::new(skills), prompt)
    };
    if !skill_prompt.is_empty() {
        context.mode_context.push_str("\n\n");
        context.mode_context.push_str(&skill_prompt);
    }
    // Web search needs only the network, and the desktop host offers it in Study
    // sessions too, so it is not gated on the Study workspace. The runtime drops
    // the definition when the device reports no network.
    // Fetching a URL is a network action the user approves per call, so it is
    // registered wherever the network exists rather than gated on Study.
    let mut shared_tools: Vec<Arc<dyn ToolRuntime>> = vec![
        project_runtime,
        mcp_runtime,
        skill_runtime,
        // The checklist and the question the model can ask the user; both are
        // model-facing control tools on the desktop too.
        Arc::new(PlanTools::new()),
        Arc::new(WebFetchTools::new()),
    ];
    if !payload
        .disabled_plugin_names
        .iter()
        .any(|name| name == "websearch")
    {
        shared_tools.push(Arc::new(web_search_tools(&payload.websearch_config)));
    }
    if !payload
        .disabled_plugin_names
        .iter()
        .any(|name| name == "imagegen")
    {
        // Unconfigured image generation hides itself from the model, so the
        // runtime stays the single gate for what the model can see.
        let config: ImageGenConfig =
            serde_json::from_value(payload.imagegen_config.clone()).unwrap_or_default();
        shared_tools.push(Arc::new(GenerateImageTools::new(
            config,
            Arc::new(MobileImageSink {
                app: app.clone(),
                session_id: parent_thread_id.clone(),
            }),
        )));
    }
    if payload.study_tools {
        shared_tools.push(Arc::new(StudyTools::new(native_study_store(&app)?)));
    }
    let child_tools: Arc<dyn ToolRuntime> =
        Arc::new(CompositeToolRuntime::new(&capabilities, shared_tools.clone()));
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
    let mut tool_runtimes = shared_tools;
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
        HttpModelBackend::with_retry_policy(
            payload.provider,
            RetryPolicy::from_config(&payload.retry_config),
        )
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
        .with_guidance_source(agent_state.sub_agents.parent_guidance(parent_thread_id.clone()))
        .with_tool_observer(Arc::new(MobileToolObserver {
            app: app.clone(),
            turn_id: trace_turn_id.clone(),
            project_root: project_root.clone(),
            project_id: payload.project_id.clone(),
            session_id: parent_thread_id.clone(),
        }))
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
    append_runtime_warnings(&mut progress, &mcp_warnings);
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
    record_turn_checkpoint(&app, &project_root, &parent_thread_id, &trace_turn_id);
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
    retry_config: Value,
    #[serde(default)]
    load_context_config: Value,
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
    #[serde(default)]
    disabled_skill_names: Vec<String>,
    /// Bundled plugins the user switched off. Plugin tools must respect it, or
    /// the switch would be a control that changes nothing.
    #[serde(default)]
    disabled_plugin_names: Vec<String>,
    /// `core.imagegen` settings; the host resolves them so the runtime can stay
    /// unaware of where a platform keeps configuration.
    #[serde(default)]
    imagegen_config: Value,
    /// `core.websearch` settings, shaped like the bundled websearch plugin's
    /// schema (provider / fallback_providers / limit / timeout).
    #[serde(default)]
    websearch_config: Value,
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
    let (mcp_configs, invalid_mcp_configs) =
        load_mobile_mcp_configs(&project_root, &payload.mcp_config).await;
    let mcp_runtime = Arc::new(McpToolRuntime::load(mcp_configs).await);
    let mut mcp_warnings = mcp_load_warnings(mcp_runtime.report());
    if invalid_mcp_configs > 0 {
        mcp_warnings.push(format!(
            "{} 个 MCP 配置缺少可执行命令或格式无效，请检查扩展配置。",
            invalid_mcp_configs
        ));
    }
    emit_agent_stage(
        &app,
        &trace_turn_id,
        if mcp_warnings.is_empty() {
            "native_mcp_ready"
        } else {
            "native_mcp_partial"
        },
    );
    let hook_engine = Arc::new(HookEngine::new(hooks).with_mcp_caller(mcp_runtime.clone()));
    let project_runtime: Arc<dyn ToolRuntime> =
        Arc::new(ProjectFileTools::new(project_root.clone()));
    let mut context = payload.continuation.context.clone();
    // Continuations saved before context persistence need a one-time rebuild.
    if context == AgentContext::default() {
        if payload.study_tools {
            apply_study_skill_context(&mut context, &payload.disabled_skill_names);
        } else {
            context = load_project_context(&project_root, context, &payload.load_context_config)?;
        }
        apply_sub_agent_context(
            &mut context,
            payload.sub_agent_enabled,
            &payload.sub_agent_guide,
        );
        let skill_prompt = SkillTools::new(payload.disabled_skill_names.clone(), Vec::new())
            .catalog_prompt_for(&capabilities);
        if !skill_prompt.is_empty() {
            context.mode_context.push_str("\n\n");
            context.mode_context.push_str(&skill_prompt);
        }
    }
    let skill_runtime: Arc<dyn ToolRuntime> = if payload.study_tools {
        Arc::new(CombinedSkillTools::new(
            payload.disabled_skill_names.clone(),
            Vec::new(),
        ))
    } else {
        Arc::new(SkillTools::new(
            payload.disabled_skill_names.clone(),
            Vec::new(),
        ))
    };
    // Web search needs only the network, and the desktop host offers it in Study
    // sessions too, so it is not gated on the Study workspace. The runtime drops
    // the definition when the device reports no network.
    // Needed by the image sink, and read from the payload only.
    let parent_thread_id = if payload.session_id.trim().is_empty() {
        payload.continuation.hook_context.session_id.clone()
    } else {
        payload.session_id.clone()
    };
    // Fetching a URL is a network action the user approves per call, so it is
    // registered wherever the network exists rather than gated on Study.
    let mut shared_tools: Vec<Arc<dyn ToolRuntime>> = vec![
        project_runtime,
        mcp_runtime,
        skill_runtime,
        // The checklist and the question the model can ask the user; both are
        // model-facing control tools on the desktop too.
        Arc::new(PlanTools::new()),
        Arc::new(WebFetchTools::new()),
    ];
    if !payload
        .disabled_plugin_names
        .iter()
        .any(|name| name == "websearch")
    {
        shared_tools.push(Arc::new(web_search_tools(&payload.websearch_config)));
    }
    if !payload
        .disabled_plugin_names
        .iter()
        .any(|name| name == "imagegen")
    {
        // Unconfigured image generation hides itself from the model, so the
        // runtime stays the single gate for what the model can see.
        let config: ImageGenConfig =
            serde_json::from_value(payload.imagegen_config.clone()).unwrap_or_default();
        shared_tools.push(Arc::new(GenerateImageTools::new(
            config,
            Arc::new(MobileImageSink {
                app: app.clone(),
                session_id: parent_thread_id.clone(),
            }),
        )));
    }
    if payload.study_tools {
        shared_tools.push(Arc::new(StudyTools::new(native_study_store(&app)?)));
    }
    let child_tools: Arc<dyn ToolRuntime> =
        Arc::new(CompositeToolRuntime::new(&capabilities, shared_tools.clone()));
    let models = with_active_model(
        payload.models,
        &payload.continuation.model_record_id,
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
                context,
                options: payload.continuation.options.clone(),
                hook_context: payload.continuation.hook_context.clone(),
                hooks: Some(hook_engine.clone()),
            },
        )
        .await?;
    emit_agent_stage(&app, &trace_turn_id, "native_subagents_ready");
    let mut tool_runtimes = shared_tools;
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
        HttpModelBackend::with_retry_policy(
            payload.provider,
            RetryPolicy::from_config(&payload.retry_config),
        )
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
        .with_guidance_source(agent_state.sub_agents.parent_guidance(parent_thread_id.clone()))
        .with_tool_observer(Arc::new(MobileToolObserver {
            app: app.clone(),
            turn_id: trace_turn_id.clone(),
            project_root: project_root.clone(),
            project_id: payload.project_id.clone(),
            session_id: parent_thread_id.clone(),
        }))
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
    append_runtime_warnings(&mut progress, &mcp_warnings);
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
    record_turn_checkpoint(&app, &project_root, &parent_thread_id, &trace_turn_id);
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
    #[serde(default)]
    retry_config: Value,
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
    let search_sessions = if payload.method == "study.search" {
        mobile_study_search_sessions(&app).map_err(study_failure)?
    } else {
        Vec::new()
    };
    dispatch_study_with_sessions(
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
        &search_sessions,
        &payload.retry_config,
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
    let message = mobile_messages(&state).into_iter().find(|message| {
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
        let session_id = message_thread_id(&message);
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

fn mobile_messages(state: &Value) -> Vec<Value> {
    let mut result = Vec::new();
    let mut seen = BTreeSet::new();
    if let Some(messages) = state.get("messages").and_then(Value::as_object) {
        for (key, message) in messages {
            if message.get("deleted").and_then(Value::as_bool) == Some(true) {
                continue;
            }
            let id = message.get("id").and_then(Value::as_str).unwrap_or(key);
            let thread_id = message_thread_id(message);
            if !id.is_empty() && !thread_id.is_empty() && seen.insert((thread_id.to_owned(), id.to_owned())) {
                result.push(message.clone());
            }
        }
    }
    if let Some(snapshots) = state.get("snapshots").and_then(Value::as_object) {
        for (thread_id, snapshot) in snapshots {
            let core = snapshot.get("core").unwrap_or(snapshot);
            let Some(items) = core.get("items").and_then(Value::as_object) else { continue };
            for (key, item) in items {
                if item.get("status").and_then(Value::as_str) == Some("cancelled") { continue; }
                let payload = item.get("payload").unwrap_or(&Value::Null);
                let (role, content) = match payload.get("type").and_then(Value::as_str) {
                    Some("userMessage") => (
                        "user",
                        payload.get("content").and_then(Value::as_array).map(|parts| {
                            parts.iter()
                                .filter(|part| part.get("type").and_then(Value::as_str) == Some("text"))
                                .filter_map(|part| part.get("text").and_then(Value::as_str))
                                .collect::<Vec<_>>().join("\n")
                        }).unwrap_or_default(),
                    ),
                    Some("agentMessage") => (
                        "assistant",
                        payload.get("content").or_else(|| item.get("content"))
                            .and_then(Value::as_str).unwrap_or("").to_owned(),
                    ),
                    _ => continue,
                };
                let id = item.get("id").and_then(Value::as_str).unwrap_or(key);
                if id.is_empty() || content.is_empty() || !seen.insert((thread_id.to_owned(), id.to_owned())) {
                    continue;
                }
                result.push(serde_json::json!({
                    "id": id, "threadId": thread_id, "role": role, "content": content,
                }));
            }
        }
    }
    result
}

fn message_thread_id(message: &Value) -> &str {
    message
        .get("threadId")
        .or_else(|| message.get("thread_id"))
        .and_then(Value::as_str)
        .unwrap_or("")
}

fn mobile_study_search_sessions(
    app: &tauri::AppHandle,
) -> Result<Vec<StudySearchSession>, lamtools_runtime::study::StudyError> {
    let path = native_state_path(app, "lamtools-mobile")
        .map_err(lamtools_runtime::study::StudyError::new)?;
    let Some(state) = read_native_state(&path, None)
        .map_err(lamtools_runtime::study::StudyError::new)?
    else {
        return Ok(Vec::new());
    };
    Ok(study_search_sessions_from_state(&state))
}

fn study_search_sessions_from_state(state: &Value) -> Vec<StudySearchSession> {
    let mut sessions = Vec::new();
    let Some(threads) = state.get("threads").and_then(Value::as_object) else {
        return sessions;
    };
    for (thread_key, thread) in threads {
        if thread.get("deleted").and_then(Value::as_bool) == Some(true) {
            continue;
        }
        let Some(metadata) = thread.get("metadata").and_then(Value::as_object) else {
            continue;
        };
        if metadata.get("owner_plugin").and_then(Value::as_str) != Some("study") {
            continue;
        }
        let id = thread.get("id").and_then(Value::as_str).unwrap_or(thread_key);
        if id.is_empty() {
            continue;
        }
        let mut messages = Vec::new();
        let mut seen = BTreeSet::new();
        if let Some(stored) = state.get("messages").and_then(Value::as_object) {
            for (key, message) in stored {
                if message_thread_id(message) != id
                    || message.get("deleted").and_then(Value::as_bool) == Some(true)
                {
                    continue;
                }
                let message_id = message.get("id").and_then(Value::as_str).unwrap_or(key);
                let content = message.get("content").and_then(Value::as_str).unwrap_or("");
                if !content.is_empty() && seen.insert(message_id.to_owned()) {
                    messages.push(StudySearchMessage {
                        id: message_id.to_owned(),
                        content: content.to_owned(),
                    });
                }
            }
        }
        // Standalone sessions write Core snapshots, while paired sessions may
        // write the separate messages map. Search both trusted state sources.
        if let Some(snapshot) = state.get("snapshots").and_then(|snapshots| snapshots.get(id)) {
            let core = snapshot.get("core").unwrap_or(snapshot);
            if let Some(items) = core.get("items").and_then(Value::as_object) {
                for (key, item) in items {
                    if item.get("status").and_then(Value::as_str) == Some("cancelled") {
                        continue;
                    }
                    let payload = item.get("payload").unwrap_or(&Value::Null);
                    let kind = payload.get("type").and_then(Value::as_str).unwrap_or("");
                    let content = match kind {
                        "userMessage" => payload
                            .get("content")
                            .and_then(Value::as_array)
                            .map(|parts| {
                                parts
                                    .iter()
                                    .filter(|part| part.get("type").and_then(Value::as_str) == Some("text"))
                                    .filter_map(|part| part.get("text").and_then(Value::as_str))
                                    .collect::<Vec<_>>()
                                    .join("\n")
                            })
                            .unwrap_or_default(),
                        "agentMessage" => payload
                            .get("content")
                            .or_else(|| item.get("content"))
                            .and_then(Value::as_str)
                            .unwrap_or("")
                            .to_owned(),
                        _ => String::new(),
                    };
                    let message_id = item.get("id").and_then(Value::as_str).unwrap_or(key);
                    if !content.is_empty() && seen.insert(message_id.to_owned()) {
                        messages.push(StudySearchMessage {
                            id: message_id.to_owned(),
                            content,
                        });
                    }
                }
            }
        }
        sessions.push(StudySearchSession {
            scope: StudyScope::local_compatibility(),
            id: id.to_owned(),
            title: thread.get("title").and_then(Value::as_str).unwrap_or(id).to_owned(),
            node_name: metadata
                .get("study_node_name")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned(),
            messages,
        });
    }
    sessions
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
    dispatch_study_with_sessions(
        store,
        method,
        raw_params,
        session_metadata,
        session_targets,
        provider,
        &[],
        &Value::Null,
    )
    .await
}

async fn dispatch_study_with_sessions(
    store: &StudyStore,
    method: &str,
    raw_params: &Value,
    session_metadata: Option<&serde_json::Map<String, Value>>,
    session_targets: &serde_json::Map<String, Value>,
    provider: Option<ProviderConfig>,
    search_sessions: &[StudySearchSession],
    retry_config: &Value,
) -> Result<Value, lamtools_runtime::study::StudyError> {
    let params = if raw_params.is_null() {
        Value::Object(Default::default())
    } else {
        raw_params.clone()
    };
    match method {
        "study.get" => store.read(&params),
        "study.build" => store.build(&params),
        "study.search" => store.search_with_sessions(&params, search_sessions),
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
                    let backend = HttpModelBackend::with_retry_policy(
                        provider,
                        RetryPolicy::from_config(retry_config),
                    ).map_err(|error| {
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
        notifications: false,
        ..Default::default()
    }
}

async fn load_mobile_mcp_configs(
    project_root: &std::path::Path,
    global_config: &Value,
) -> (Vec<McpServerConfig>, usize) {
    let mut invalid_count = invalid_mcp_entries(global_config);
    let mut configs = load_server_configs(global_config)
        .into_iter()
        .map(|config| (config.name.clone(), config))
        .collect::<std::collections::BTreeMap<_, _>>();
    for path in [
        project_root.join(".lamtools").join("mcp.json"),
        project_root.join(".mcp.json"),
        project_root.join("mcp.json"),
    ] {
        let content = match tokio::fs::read_to_string(&path).await {
            Ok(content) => content,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => continue,
            Err(_) => {
                invalid_count += 1;
                continue;
            }
        };
        let Ok(value) = json5::from_str::<Value>(&content) else {
            invalid_count += 1;
            continue;
        };
        invalid_count += invalid_mcp_entries(&value);
        for config in load_server_configs(&value) {
            configs.insert(config.name.clone(), config);
        }
    }
    (configs.into_values().collect(), invalid_count)
}

fn invalid_mcp_entries(value: &Value) -> usize {
    value
        .get("mcpServers")
        .or_else(|| value.get("servers"))
        .unwrap_or(value)
        .as_object()
        .map(|servers| {
            servers
                .values()
                .filter(|entry| {
                    entry.get("enabled").and_then(Value::as_bool) != Some(false)
                        && entry
                            .get("command")
                            .and_then(Value::as_str)
                            .is_none_or(|command| command.trim().is_empty())
                })
                .count()
        })
        .unwrap_or(0)
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
    name: String,
    #[serde(rename = "type")]
    kind: &'static str,
    size: u64,
    ext: String,
}

async fn list_project_directory(
    root: &std::path::Path,
    path: &str,
) -> Result<Vec<NativeProjectFileEntry>, String> {
    let requested = safe_project_relative_path(root, path, true)?;
    let mut directory = tokio::fs::read_dir(&requested)
        .await
        .map_err(|error| error.to_string())?;
    let mut entries = Vec::new();
    while let Some(entry) = directory.next_entry().await.map_err(|error| error.to_string())? {
        // Do not expose a link as a traversable directory or follow it for size.
        let metadata = tokio::fs::symlink_metadata(entry.path())
            .await
            .map_err(|error| error.to_string())?;
        if metadata.file_type().is_symlink() || (!metadata.is_dir() && !metadata.is_file()) {
            continue;
        }
        let name = entry.file_name().to_string_lossy().into_owned();
        let is_dir = metadata.is_dir();
        entries.push(NativeProjectFileEntry {
            ext: if is_dir {
                String::new()
            } else {
                std::path::Path::new(&name)
                    .extension()
                    .map(|ext| ext.to_string_lossy().to_lowercase())
                    .unwrap_or_default()
            },
            name,
            kind: if is_dir { "directory" } else { "file" },
            size: if is_dir { 0 } else { metadata.len() },
        });
    }
    entries.sort_by(|left, right| {
        (left.kind != "directory")
            .cmp(&(right.kind != "directory"))
            .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
            .then_with(|| left.name.cmp(&right.name))
    });
    Ok(entries)
}

#[tauri::command]
async fn project_file_list(
    app: tauri::AppHandle,
    project_id: String,
    path: Option<String>,
) -> Result<Vec<NativeProjectFileEntry>, String> {
    let root = native_project_root(&app, &project_id)?;
    tokio_create_dir_all(&root).await?;
    list_project_directory(&root, path.as_deref().unwrap_or("")).await
}

#[derive(Debug, Serialize)]
struct NativeProjectDirectoryListing {
    path: String,
    entries: Vec<NativeProjectFileEntry>,
}

#[tauri::command]
async fn project_directory_browse(
    app: tauri::AppHandle,
    path: Option<String>,
) -> Result<NativeProjectDirectoryListing, String> {
    // The browser is deliberately limited to the app-private project tree.
    let requested = path.as_deref().unwrap_or("");
    let relative = requested.strip_prefix("mobile://").unwrap_or(requested);
    let relative = relative.trim_matches('/');
    let projects_root = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("projects");
    tokio_create_dir_all(&projects_root).await?;
    let entries = list_project_directory(&projects_root, relative).await?;
    Ok(NativeProjectDirectoryListing {
        path: if relative.is_empty() {
            "mobile://".into()
        } else {
            format!("mobile://{relative}")
        },
        entries,
    })
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
    let written = content.clone();
    tokio::task::spawn_blocking(move || write_memory_atomic(&resolved, written.as_bytes()))
        .await
        .map_err(|error| error.to_string())?
        .map_err(|error| error.to_string())?;
    Ok(NativeProjectFile { path, content })
}

/// Raw bytes of one project file, base64 encoded.
///
/// The desktop serves the same content under `GET /projects/{id}/files/raw`
/// (and its text twin under `/files/content`); the WebView cannot reach a local
/// HTTP server here, so the transport calls this command instead. Images and
/// other binaries only survive as bytes, which is why this is a separate
/// command from [`project_file_read`].
const MAX_PROJECT_RAW_FILE_BYTES: u64 = 32 * 1024 * 1024;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeProjectRawFile {
    path: String,
    mime_type: String,
    data_base64: String,
}

#[tauri::command]
async fn project_file_read_raw(
    app: tauri::AppHandle,
    project_id: String,
    path: String,
) -> Result<Option<NativeProjectRawFile>, String> {
    let root = native_project_root(&app, &project_id)?;
    let resolved = safe_project_relative_path(&root, &path, false)?;
    let metadata = match tokio::fs::metadata(&resolved).await {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.to_string()),
    };
    if !metadata.is_file() {
        return Err(format!("'{}' is not a file", path));
    }
    if metadata.len() > MAX_PROJECT_RAW_FILE_BYTES {
        return Err(format!(
            "文件超过 {} MiB 上限，无法在移动端预览",
            MAX_PROJECT_RAW_FILE_BYTES / (1024 * 1024)
        ));
    }
    let bytes = tokio::fs::read(&resolved)
        .await
        .map_err(|error| error.to_string())?;
    Ok(Some(NativeProjectRawFile {
        mime_type: project_file_mime_type(&resolved, &bytes),
        data_base64: {
            use base64::Engine;
            base64::engine::general_purpose::STANDARD.encode(&bytes)
        },
        path,
    }))
}

/// Extension first so a project file keeps its declared type even when the
/// content is a text format `infer` cannot see (`.md`, `.jsonc`, ...).
fn project_file_mime_type(path: &std::path::Path, bytes: &[u8]) -> String {
    let extension = path
        .extension()
        .map(|value| value.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    let extension_mime = match extension.as_str() {
        "md" => Some("text/markdown"),
        "txt" | "log" | "rst" => Some("text/plain"),
        "json" | "jsonc" => Some("application/json"),
        "csv" => Some("text/csv"),
        "html" | "htm" => Some("text/html"),
        "css" => Some("text/css"),
        "js" | "mjs" | "cjs" => Some("text/javascript"),
        "ts" | "tsx" => Some("text/typescript"),
        "vue" => Some("text/plain"),
        "yaml" | "yml" => Some("application/yaml"),
        "toml" => Some("application/toml"),
        "py" => Some("text/x-python"),
        "rs" => Some("text/x-rust"),
        "svg" => Some("image/svg+xml"),
        _ => None,
    };
    extension_mime
        .map(str::to_string)
        .or_else(|| infer::get(bytes).map(|kind| kind.mime_type().to_string()))
        .unwrap_or_else(|| "application/octet-stream".into())
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
fn mobile_diagnostics_share(
    share: tauri::State<'_, MobileDiagnosticsShare<tauri::Wry>>,
    contents: String,
) -> Result<(), String> {
    if contents.is_empty() || contents.len() > 256 * 1024 {
        return Err("invalid diagnostics export".into());
    }
    share
        .0
        .run_mobile_plugin::<Value>("share", DiagnosticsShareRequest { contents: &contents })
        .map(|_| ())
        .map_err(|_| "unable to share diagnostics".into())
}

#[cfg(target_os = "android")]
#[tauri::command]
fn lan_discovery_discover(
    discovery: tauri::State<'_, MobileLanDiscovery<tauri::Wry>>,
    timeout_ms: Option<u64>,
) -> Result<Value, String> {
    let timeout_ms = timeout_ms.unwrap_or(1200).clamp(250, 5000);
    discovery
        .0
        .run_mobile_plugin::<Value>("discover", serde_json::json!({ "timeoutMs": timeout_ms }))
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

/// User skills, in the desktop layout: `{root}/skills/<name>/SKILL.md`.
///
/// The desktop keeps them under `lam_home()`; the phone has no home directory,
/// so the app-private data directory takes its place and the same scanner finds
/// them. This root is what the 新建技能 panel writes and what the agent loads.
fn native_user_skill_root(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    Ok(app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?
        .join("skills"))
}

fn safe_skill_name(name: &str) -> Result<String, String> {
    let name = name.trim();
    if name.is_empty() {
        return Err("标题（name）是必填的".into());
    }
    if !name
        .chars()
        .all(|character| character.is_ascii_alphanumeric() || matches!(character, '.' | '_' | '-'))
    {
        return Err("技能名只允许字母/数字/._-（将作为目录名）".into());
    }
    Ok(name.to_owned())
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct NativeUserSkill {
    name: String,
    description: String,
    location: String,
}

/// Every skill in the app-private skill root.
///
/// Reads the same frontmatter the runtime's scanner reads (`description:`), so
/// the panel shows what the agent would load rather than a second opinion.
#[tauri::command]
async fn sunday_user_skills(app: tauri::AppHandle) -> Result<Vec<NativeUserSkill>, String> {
    list_user_skills(&native_user_skill_root(&app)?).await
}

async fn list_user_skills(root: &std::path::Path) -> Result<Vec<NativeUserSkill>, String> {
    if !root.is_dir() {
        return Ok(Vec::new());
    }
    let mut skills = Vec::new();
    let mut directories = tokio::fs::read_dir(&root)
        .await
        .map_err(|error| error.to_string())?;
    while let Some(entry) = directories
        .next_entry()
        .await
        .map_err(|error| error.to_string())?
    {
        let skill_file = entry.path().join("SKILL.md");
        let Ok(body) = tokio::fs::read_to_string(&skill_file).await else {
            continue;
        };
        skills.push(NativeUserSkill {
            name: entry.file_name().to_string_lossy().into_owned(),
            description: skill_description(&body),
            location: skill_file.display().to_string(),
        });
    }
    skills.sort_by(|left, right| left.name.cmp(&right.name));
    Ok(skills)
}

/// The frontmatter `description:` value, matching the runtime's parser.
fn skill_description(body: &str) -> String {
    body.lines()
        .skip(1)
        .take_while(|line| *line != "---")
        .find_map(|line| {
            line.strip_prefix("description:")
                .map(|value| value.trim().trim_matches(['\'', '"']).to_owned())
        })
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "Specialized capability.".into())
}

#[tauri::command]
async fn sunday_skill_create(
    app: tauri::AppHandle,
    name: String,
    description: String,
    content: String,
) -> Result<NativeUserSkill, String> {
    create_user_skill(&native_user_skill_root(&app)?, &name, &description, &content).await
}

async fn create_user_skill(
    root: &std::path::Path,
    name: &str,
    description: &str,
    content: &str,
) -> Result<NativeUserSkill, String> {
    let name = safe_skill_name(name)?;
    let description = description.trim().to_owned();
    let content = content.trim().to_owned();
    if description.is_empty() {
        return Err("描述（description）是必填的".into());
    }
    if content.is_empty() {
        return Err("内容（content）是必填的".into());
    }
    let skill_dir = root.join(&name);
    tokio_create_dir_all(root).await?;
    if skill_dir.exists() {
        return Err(format!("技能 '{name}' 已存在（{}）", skill_dir.display()));
    }
    tokio_create_dir_all(&skill_dir).await?;
    // Same document shape the desktop writes, so a skill copied between hosts
    // keeps its name and description.
    let body = format!("---\nname: {name}\ndescription: {description}\n---\n\n{content}\n");
    let target = skill_dir.join("SKILL.md");
    let written = body.clone();
    tokio::task::spawn_blocking(move || write_memory_atomic(&target, written.as_bytes()))
        .await
        .map_err(|error| error.to_string())?
        .map_err(|error| error.to_string())?;
    Ok(NativeUserSkill {
        name,
        description,
        location: skill_dir.join("SKILL.md").display().to_string(),
    })
}

#[tauri::command]
async fn sunday_skill_delete(app: tauri::AppHandle, name: String) -> Result<Value, String> {
    delete_user_skill(&native_user_skill_root(&app)?, &name).await
}

async fn delete_user_skill(root: &std::path::Path, name: &str) -> Result<Value, String> {
    let name = safe_skill_name(name)?;
    let skill_dir = root.join(&name);
    // Only the app-private skill root is deletable: bundled and plugin skills
    // live inside the binary and must not be reported as removable.
    if !skill_dir.is_dir() {
        return Err(format!("技能 '{name}' 不存在或不可删除"));
    }
    tokio::fs::remove_dir_all(&skill_dir)
        .await
        .map_err(|error| format!("删除失败: {error}"))?;
    Ok(serde_json::json!({
        "name": name,
        "location": skill_dir.join("SKILL.md").display().to_string(),
        "deleted": true,
    }))
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
    let mut resolved = root.to_path_buf();
    for component in relative.components() {
        resolved.push(component);
        match std::fs::symlink_metadata(&resolved) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                return Err("project path cannot follow a symbolic link".into())
            }
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => break,
            Err(error) => return Err(error.to_string()),
        }
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
    #[cfg(target_os = "android")]
    let builder = builder.plugin(
        tauri::plugin::Builder::<tauri::Wry, ()>::new("lamtools-diagnostics-share")
            .setup(|app, api| {
                let handle = api.register_android_plugin(
                    "com.lamtools.mobile",
                    "LamToolsDiagnosticsSharePlugin",
                )?;
                app.manage(MobileDiagnosticsShare(handle));
                Ok(())
            })
            .build(),
    );
    #[cfg(target_os = "android")]
    let builder = builder.plugin(
        tauri::plugin::Builder::<tauri::Wry, ()>::new("lamtools-attachment-open")
            .setup(|app, api| {
                let handle = api.register_android_plugin(
                    "com.lamtools.mobile",
                    "LamToolsAttachmentOpenPlugin",
                )?;
                app.manage(MobileAttachmentOpen(handle));
                Ok(())
            })
            .build(),
    );
    #[cfg(target_os = "android")]
    let builder = builder.plugin(
        tauri::plugin::Builder::<tauri::Wry, ()>::new("lamtools-shell")
            .setup(|app, api| {
                let handle =
                    api.register_android_plugin("com.lamtools.mobile", "LamToolsShellPlugin")?;
                app.manage(MobileShell(handle));
                Ok(())
            })
            .build(),
    );
    #[cfg(target_os = "android")]
    let builder = builder.plugin(
        tauri::plugin::Builder::<tauri::Wry, ()>::new("lamtools-lan-discovery")
            .setup(|app, api| {
                let handle = api.register_android_plugin(
                    "com.lamtools.mobile",
                    "LamToolsLanDiscoveryPlugin",
                )?;
                app.manage(MobileLanDiscovery(handle));
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
        app.manage(UpdateDownloadState::default());
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
        sunday_study_skill_catalog,
        sunday_plugin_inventory,
        sunday_update_manifest,
        sunday_update_download,
        sunday_update_status,
        sunday_update_install,
        sunday_open_external_url,
        sunday_tool_catalog,
        sunday_plugin_mode_tools,
        sunday_plugin_schemas,
        sunday_checkpoint_create,
        sunday_checkpoint_get,
        sunday_checkpoint_graph,
        sunday_checkpoint_list,
        sunday_checkpoint_restore,
        sunday_goal_create,
        sunday_goal_get,
        sunday_goal_list,
        sunday_goal_update,
        sunday_artifact_list,
        sunday_artifact_revisions,
        sunday_artifact_set_deleted,
        sunday_artifact_restore_revision,
        sunday_artifact_file,
        sunday_user_skills,
        sunday_skill_create,
        sunday_skill_delete,
        project_agents_md,
        sunday_workflow_rpc,
        load_legacy_mobile_state,
        local_state_read,
        local_state_write,
        sunday_attachment_save,
        sunday_attachment_read,
        sunday_attachment_list,
        sunday_attachment_delete,
        sunday_attachment_open,
        sunday_artifact_open,
        lan_discovery_discover,
        project_file_list,
        project_directory_browse,
        project_file_read,
        project_file_read_raw,
        project_file_write,
        secure_storage_get,
        mobile_diagnostics_share,
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
        sunday_study_skill_catalog,
        sunday_plugin_inventory,
        sunday_update_manifest,
        sunday_tool_catalog,
        sunday_plugin_mode_tools,
        sunday_plugin_schemas,
        sunday_checkpoint_create,
        sunday_checkpoint_get,
        sunday_checkpoint_graph,
        sunday_checkpoint_list,
        sunday_checkpoint_restore,
        sunday_goal_create,
        sunday_goal_get,
        sunday_goal_list,
        sunday_goal_update,
        sunday_artifact_list,
        sunday_artifact_revisions,
        sunday_artifact_set_deleted,
        sunday_artifact_restore_revision,
        sunday_artifact_file,
        sunday_user_skills,
        sunday_skill_create,
        sunday_skill_delete,
        project_agents_md,
        sunday_workflow_rpc,
        load_legacy_mobile_state,
        local_state_read,
        local_state_write,
        sunday_attachment_save,
        sunday_attachment_read,
        sunday_attachment_list,
        sunday_attachment_delete,
        project_file_list,
        project_directory_browse,
        project_file_read,
        project_file_read_raw,
        project_file_write
    ]);
    builder
        .run(tauri::generate_context!())
        .expect("error while running Sunday mobile");
}

#[cfg(test)]
mod tests {
    use super::*;
    use lamtools_runtime::{study_skills::catalog_prompt, ModelTurn, ToolCall};
    use serde_json::json;
    use std::sync::atomic::AtomicUsize;

    #[test]
    fn bundled_schemas_parse_and_the_search_settings_reach_the_runtime() {
        let schemas = sunday_plugin_schemas();
        // The panel only offers a configuration entry where a schema exists, so
        // both plugins that have one must survive parsing (they are JSONC).
        for name in ["imagegen", "websearch"] {
            let entry = schemas.get(name).unwrap_or_else(|| panic!("missing {name}"));
            assert_eq!(
                entry["path"],
                Value::String(format!("bundled://{name}/config/schema.jsonc"))
            );
            assert!(entry["schema"]["properties"].is_object());
        }
        assert!(schemas.get("git").is_none(), "git declares no schema");

        // Settings shaped like the websearch schema must select the kernel the
        // panel chose, and missing settings must keep search usable.
        let configured = web_search_tools(&serde_json::json!({
            "provider": "bing",
            "fallback_providers": ["baidu", "unknown"],
            "limit": 9,
            "timeout": 4,
        }));
        assert_eq!(configured.limit(), 9);
        assert_eq!(configured.timeout_secs(), 4);
        let empty = web_search_tools(&Value::Null);
        assert_eq!(empty.limit(), 5);
        assert_eq!(empty.timeout_secs(), 30);
    }

    #[tokio::test]
    async fn user_skills_round_trip_in_the_layout_the_runtime_scans() {
        let root = std::env::temp_dir().join(format!("sunday-skills-{}", uuid::Uuid::new_v4()));
        assert!(list_user_skills(&root).await.unwrap().is_empty());

        let created = create_user_skill(
            &root,
            "my-skill",
            "何时使用这个技能",
            "加载后应遵循的指引",
        )
        .await
        .unwrap();
        assert_eq!(created.name, "my-skill");
        // The scanner reads `{root}/<name>/SKILL.md` and takes the description
        // from the frontmatter, so both have to be what the panel shows.
        let body = std::fs::read_to_string(root.join("my-skill").join("SKILL.md")).unwrap();
        assert!(body.starts_with("---
name: my-skill
description: 何时使用这个技能
---
"));
        assert!(body.contains("加载后应遵循的指引"));

        let listed = list_user_skills(&root).await.unwrap();
        assert_eq!(listed.len(), 1);
        assert_eq!(listed[0].description, "何时使用这个技能");
        assert!(listed[0].location.ends_with("SKILL.md"));

        // A duplicate, an empty field and a path-shaped name are refused.
        assert!(create_user_skill(&root, "my-skill", "d", "c").await.is_err());
        assert!(create_user_skill(&root, "other", "", "c").await.is_err());
        assert!(create_user_skill(&root, "other", "d", "  ").await.is_err());
        assert!(create_user_skill(&root, "../escape", "d", "c").await.is_err());
        assert!(create_user_skill(&root, "", "d", "c").await.is_err());

        let deleted = delete_user_skill(&root, "my-skill").await.unwrap();
        assert_eq!(deleted["deleted"], Value::Bool(true));
        assert!(list_user_skills(&root).await.unwrap().is_empty());
        // Deleting again reports the miss instead of pretending.
        assert!(delete_user_skill(&root, "my-skill").await.is_err());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn skill_frontmatter_description_matches_the_runtime_parser() {
        assert_eq!(
            skill_description("---
name: a
description: 说明
---

body"),
            "说明"
        );
        assert_eq!(
            skill_description("---
description: \"quoted\"
---
"),
            "quoted"
        );
        // Missing or empty descriptions fall back exactly like the runtime.
        assert_eq!(skill_description("---
name: a
---
"), "Specialized capability.");
        assert_eq!(skill_description("no frontmatter"), "Specialized capability.");
    }

    #[test]
    fn the_mode_editor_catalog_and_study_mode_come_from_the_runtime() {
        let catalog = sunday_tool_catalog();
        let names: Vec<String> = catalog.iter().map(|tool| tool.name.clone()).collect();
        // The host command must be the runtime's list, not a second one.
        assert_eq!(
            names,
            lamtools_runtime::tool_catalog::catalog_tools()
                .into_iter()
                .map(|tool| tool.name)
                .collect::<Vec<_>>()
        );
        assert!(names.iter().any(|name| name == "read_file"));
        assert!(catalog.iter().all(|tool| !tool.category.is_empty()));

        let study = sunday_plugin_mode_tools("study:study".into());
        assert!(study.iter().any(|name| name == "notes"));
        assert!(study.iter().any(|name| name == "read_file"));
        // An unknown mode must not invent a whitelist.
        assert!(sunday_plugin_mode_tools("other:mode".into()).is_empty());
    }

    #[test]
    fn project_file_mime_type_prefers_the_declared_extension() {
        // Text formats `infer` cannot see must keep their real type, otherwise
        // the preview pane refuses to render them as text.
        assert_eq!(
            project_file_mime_type(std::path::Path::new("a/b/AGENTS.md"), b"# hi"),
            "text/markdown"
        );
        assert_eq!(
            project_file_mime_type(std::path::Path::new("notes.jsonc"), b"{}"),
            "application/json"
        );
        // A binary keeps whatever the magic bytes say.
        let png = [0x89u8, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0];
        assert_eq!(
            project_file_mime_type(std::path::Path::new("shot.bin"), &png),
            "image/png"
        );
        // Unknown extension and unknown content stays octet-stream.
        assert_eq!(
            project_file_mime_type(std::path::Path::new("data.weird"), b"\x00\x01"),
            "application/octet-stream"
        );
    }

    #[test]
    fn study_search_collects_only_trusted_study_sessions_and_snapshot_messages() {
        let state = json!({
            "threads": {
                "study-1": {"id":"study-1","title":"Geometry","metadata":{"owner_plugin":"study","study_node_name":"Angles"}},
                "other": {"id":"other","title":"Secret","metadata":{"owner_plugin":"other"}}
            },
            "messages": {
                "m1": {"id":"m1","threadId":"study-1","content":"stored needle"},
                "m2": {"id":"m2","threadId":"other","content":"private needle"}
            },
            "snapshots": {
                "study-1": {"core":{"items":{
                    "i1":{"id":"i1","payload":{"type":"userMessage","content":[{"type":"text","text":"snapshot needle"}]}},
                    "i2":{"id":"i2","payload":{"type":"agentMessage","content":"reply needle"}},
                    "i3":{"id":"i3","status":"cancelled","payload":{"type":"agentMessage","content":"cancelled"}}
                }}}
            }
        });
        let sessions = study_search_sessions_from_state(&state);
        assert_eq!(sessions.len(), 1);
        assert_eq!(sessions[0].title, "Geometry");
        assert_eq!(sessions[0].node_name, "Angles");
        assert_eq!(sessions[0].messages.len(), 3);
        assert!(sessions[0].messages.iter().any(|message| message.content == "snapshot needle"));
        assert!(!sessions[0].messages.iter().any(|message| message.content == "private needle"));
        let raw_messages = mobile_messages(&state);
        assert!(raw_messages.iter().any(|message| {
            message.get("id").and_then(Value::as_str) == Some("i1")
                && message.get("content").and_then(Value::as_str) == Some("snapshot needle")
        }));
    }

    #[test]
    fn invalid_mcp_config_is_reported_without_leaking_command_text() {
        assert_eq!(invalid_mcp_entries(&json!({
            "mcpServers": {
                "missing": {"url":"https://example.invalid"},
                "disabled": {"enabled":false},
                "valid": {"command":"mcp-server"}
            }
        })), 1);
        let warnings = mcp_load_warnings(&McpLoadReport {
            servers: Vec::new(), tools: Vec::new(),
            errors: vec!["MCP server 'private' could not start '/secret/path': token".into()],
        });
        assert_eq!(warnings.len(), 1);
        assert!(warnings[0].contains("启动失败"));
        assert!(!warnings[0].contains("/secret/path"));
        assert!(!warnings[0].contains("token"));
    }

    struct ScriptedStudyModel {
        step: AtomicUsize,
    }

    #[async_trait::async_trait]
    impl ModelBackend for ScriptedStudyModel {
        async fn complete(
            &self,
            _: &str,
            messages: &[Message],
            tools: &[lamtools_runtime::ToolDefinition],
            _: &TurnOptions,
        ) -> Result<ModelTurn, lamtools_runtime::RuntimeError> {
            let step = self.step.fetch_add(1, Ordering::SeqCst);
            if step == 0 {
                let Message::System { content } = &messages[0] else {
                    panic!("missing system message")
                };
                assert!(content.contains(lamtools_runtime::study::STUDY_SYSTEM_PROMPT.trim()));
                assert!(content.contains(&catalog_prompt(&[])));
                for name in [
                    "get_knowledge_net",
                    "build_knowledge_net",
                    "sign",
                    "exam",
                    "notes",
                    "load_skill",
                    "read_skill_reference",
                ] {
                    assert!(tools.iter().any(|tool| tool.name == name), "missing {name}");
                }
            }
            let (name, arguments) = match step {
                0 => ("load_skill", json!({"name":"build-map"})),
                1 => {
                    assert!(
                        matches!(messages.last(), Some(Message::Tool { content, .. }) if content.contains("<skill_content name=\\\"build-map\\\">"))
                    );
                    (
                        "read_skill_reference",
                        json!({"name":"build-map","path":"references/curriculum.md"}),
                    )
                }
                2 => {
                    assert!(
                        matches!(messages.last(), Some(Message::Tool { content, .. }) if content.contains("curriculum"))
                    );
                    (
                        "build_knowledge_net",
                        json!({"revision":0,"operations":[{"action":"create","kind":"course","id":"course-a","data":{"name":"Linear Algebra"}}]}),
                    )
                }
                3 => {
                    assert!(
                        matches!(messages.last(), Some(Message::Tool { content, .. }) if content.contains("revision"))
                    );
                    ("get_knowledge_net", json!({}))
                }
                _ => {
                    assert!(
                        matches!(messages.last(), Some(Message::Tool { content, .. }) if content.contains("Linear Algebra"))
                    );
                    return Ok(ModelTurn::Text {
                        text: "done".into(),
                        reasoning: String::new(),
                        provider_state: Value::Null,
                    });
                }
            };
            Ok(ModelTurn::ToolCalls {
                text: String::new(),
                calls: vec![ToolCall {
                    id: format!("call-{step}"),
                    name: name.into(),
                    arguments,
                }],
                provider_state: Value::Null,
            })
        }
    }

    #[tokio::test]
    async fn study_agent_request_loads_skill_reference_and_builds_graph() {
        let store = temp_study_store("agent-skills");
        let capabilities = DeviceCapabilities {
            platform: "android".into(),
            project_files: true,
            ..Default::default()
        };
        let tools = CompositeToolRuntime::new(
            &capabilities,
            vec![
                Arc::new(StudyTools::new(store)),
                Arc::new(BundledStudySkillTools::new(Vec::new())),
            ],
        );
        let mut context = AgentContext::default();
        apply_study_skill_context(&mut context, &[]);
        let result = AgentRuntime::new(
            ScriptedStudyModel {
                step: AtomicUsize::new(0),
            },
            tools,
        )
        .run_turn(TurnRequest {
            turn_id: "study-turn".into(),
            model_record_id: "fixture".into(),
            history: vec![Message::User {
                content: "Build a linear algebra map".into(),
            }],
            capabilities,
            context,
            hook_context: Default::default(),
            options: Default::default(),
        })
        .await
        .unwrap();
        assert_eq!(result.text, "done");
        assert_eq!(result.tool_rounds, 4);
    }

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

    #[tokio::test]
    async fn project_directory_listing_is_immediate_and_skips_links() {
        let root = std::env::temp_dir().join(format!(
            "lamtools-project-tree-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(root.join("notes/deep")).unwrap();
        std::fs::write(root.join("README.MD"), "root").unwrap();
        std::fs::write(root.join("notes/a.txt"), "hello").unwrap();
        std::fs::write(root.join("notes/deep/b.txt"), "nested").unwrap();

        let top = list_project_directory(&root, "").await.unwrap();
        assert_eq!(top.len(), 2);
        assert_eq!((top[0].name.as_str(), top[0].kind, top[0].size), ("notes", "directory", 0));
        assert_eq!((top[1].name.as_str(), top[1].kind, top[1].ext.as_str()), ("README.MD", "file", "md"));
        let nested = list_project_directory(&root, "notes").await.unwrap();
        assert_eq!(nested.len(), 2);
        assert_eq!(nested[0].name, "deep");
        assert_eq!((nested[1].name.as_str(), nested[1].size), ("a.txt", 5));
        assert!(list_project_directory(&root, "../outside").await.is_err());
        assert!(list_project_directory(&root, "README.MD").await.is_err());

        #[cfg(unix)]
        {
            std::os::unix::fs::symlink(root.parent().unwrap(), root.join("escape")).unwrap();
            assert!(list_project_directory(&root, "escape").await.is_err());
            assert!(!list_project_directory(&root, "")
                .await
                .unwrap()
                .iter()
                .any(|entry| entry.name == "escape"));
        }
        #[cfg(windows)]
        if std::os::windows::fs::symlink_dir(root.parent().unwrap(), root.join("escape")).is_ok() {
            assert!(list_project_directory(&root, "escape").await.is_err());
            assert!(!list_project_directory(&root, "")
                .await
                .unwrap()
                .iter()
                .any(|entry| entry.name == "escape"));
        }
        std::fs::remove_dir_all(root).unwrap();
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
