#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    collections::{HashMap, HashSet},
    env,
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use base64::Engine;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use serde::{Deserialize, Serialize};
use tauri::{
    menu::{Menu, MenuEvent, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager, WebviewWindow, WebviewWindowBuilder,
};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

const DESKTOP_PLUGIN_WINDOW_LABEL: &str = "desktop-plugin-host";
const TRAY_ID: &str = "lamtools-tray";
const TRAY_TOGGLE_PET_ID: &str = "tray-toggle-pet";
const TRAY_OPEN_MAIN_ID: &str = "tray-open-main";
const TRAY_QUIT_ID: &str = "tray-quit";
const MAX_DESKTOP_DROP_FILES: usize = 20;
const MAX_DESKTOP_DROP_FILE_BYTES: u64 = 50 * 1024 * 1024;
const MAX_DESKTOP_DROP_TOTAL_BYTES: u64 = 100 * 1024 * 1024;
const DESKTOP_PLUGIN_DOCK_THRESHOLD: i32 = 40;
static NEXT_DESKTOP_DROP_ID: AtomicU64 = AtomicU64::new(1);

struct BackendState {
    api_base: Mutex<Option<String>>,
    child: Mutex<Option<Child>>,
    desktop_windows: Mutex<HashMap<String, DesktopWindowRegistration>>,
    desktop_drops: Mutex<HashMap<String, Vec<PathBuf>>>,
    tray_pet_item: Mutex<Option<MenuItem<tauri::Wry>>>,
    quitting: AtomicBool,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DesktopWindowSpec {
    #[serde(default = "default_collapsed_width")]
    collapsed_width: f64,
    #[serde(default = "default_collapsed_height")]
    collapsed_height: f64,
    #[serde(default = "default_expanded_width")]
    expanded_width: f64,
    #[serde(default = "default_expanded_height")]
    expanded_height: f64,
    #[serde(default = "default_card_width")]
    card_width: f64,
    #[serde(default = "default_card_height")]
    card_height: f64,
    #[serde(default = "default_window_margin")]
    margin: f64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum HorizontalAnchor {
    Left,
    Right,
}

impl HorizontalAnchor {
    fn as_str(self) -> &'static str {
        match self {
            Self::Left => "left",
            Self::Right => "right",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum VerticalAnchor {
    Top,
    Bottom,
}

impl VerticalAnchor {
    fn as_str(self) -> &'static str {
        match self {
            Self::Top => "top",
            Self::Bottom => "bottom",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DesktopPluginViewMode {
    Pet,
    Card,
    Panel,
}

impl DesktopPluginViewMode {
    fn parse(value: &str) -> Option<Self> {
        match value {
            "pet" => Some(Self::Pet),
            "card" => Some(Self::Card),
            "panel" => Some(Self::Panel),
            _ => None,
        }
    }

    fn logical_size(self, spec: &DesktopWindowSpec) -> (f64, f64) {
        match self {
            Self::Pet => (spec.collapsed_width, spec.collapsed_height),
            Self::Card => (spec.card_width, spec.card_height),
            Self::Panel => (spec.expanded_width, spec.expanded_height),
        }
    }
}

#[derive(Clone, Debug)]
struct DesktopWindowRegistration {
    spec: DesktopWindowSpec,
    anchor: HorizontalAnchor,
    vertical_anchor: VerticalAnchor,
    ignoring_cursor_events: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopCursorPosition {
    x: f64,
    y: f64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopWindowTransition {
    anchor: &'static str,
    vertical_anchor: &'static str,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", default)]
struct DesktopPluginPlacement {
    monitor_name: Option<String>,
    x_ratio: f64,
    y_ratio: f64,
    dock: Option<String>,
}

impl Default for DesktopPluginPlacement {
    fn default() -> Self {
        Self {
            monitor_name: None,
            x_ratio: 1.0,
            y_ratio: 1.0,
            dock: None,
        }
    }
}

impl DesktopPluginPlacement {
    fn sanitized(&self) -> Self {
        Self {
            monitor_name: self
                .monitor_name
                .as_ref()
                .map(|name| name.trim().to_string())
                .filter(|name| !name.is_empty()),
            x_ratio: normalized_ratio(self.x_ratio, 1.0),
            y_ratio: normalized_ratio(self.y_ratio, 1.0),
            dock: normalized_dock(self.dock.as_deref()),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct DesktopWorkArea {
    x: i32,
    y: i32,
    width: u32,
    height: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct DesktopWindowGeometry {
    x: i32,
    y: i32,
    width: u32,
    height: u32,
}

impl DesktopWindowGeometry {
    fn right(self) -> i64 {
        i64::from(self.x) + i64::from(self.width)
    }

    fn bottom(self) -> i64 {
        i64::from(self.y) + i64::from(self.height)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct DesktopWindowTargetGeometry {
    geometry: DesktopWindowGeometry,
    anchor: HorizontalAnchor,
    vertical_anchor: VerticalAnchor,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopDropFileSummary {
    name: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopDropSummary {
    drop_id: String,
    files: Vec<DesktopDropFileSummary>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopDropFileData {
    name: String,
    size: u64,
    data_base64: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopDropData {
    drop_id: String,
    files: Vec<DesktopDropFileData>,
}

impl Default for DesktopWindowSpec {
    fn default() -> Self {
        Self {
            collapsed_width: default_collapsed_width(),
            collapsed_height: default_collapsed_height(),
            expanded_width: default_expanded_width(),
            expanded_height: default_expanded_height(),
            card_width: default_card_width(),
            card_height: default_card_height(),
            margin: default_window_margin(),
        }
    }
}

impl DesktopWindowSpec {
    fn sanitized(&self) -> Self {
        let collapsed_width = self.collapsed_width.clamp(96.0, 800.0);
        let collapsed_height = self.collapsed_height.clamp(96.0, 800.0);
        Self {
            collapsed_width,
            collapsed_height,
            expanded_width: self.expanded_width.clamp(collapsed_width, 1600.0),
            expanded_height: self.expanded_height.clamp(collapsed_height, 1200.0),
            card_width: self.card_width.clamp(collapsed_width, 1600.0),
            card_height: self.card_height.clamp(collapsed_height, 1200.0),
            margin: self.margin.clamp(0.0, 200.0),
        }
    }
}

fn default_collapsed_width() -> f64 {
    256.0
}
fn default_collapsed_height() -> f64 {
    288.0
}
fn default_expanded_width() -> f64 {
    400.0
}
fn default_expanded_height() -> f64 {
    568.0
}
fn default_card_width() -> f64 {
    376.0
}
fn default_card_height() -> f64 {
    360.0
}
fn default_window_margin() -> f64 {
    24.0
}

// ---------------------------------------------------------------------------
// Tauri commands exposed to the frontend
// ---------------------------------------------------------------------------

#[tauri::command]
fn get_api_base(state: tauri::State<'_, BackendState>) -> Result<String, String> {
    state
        .api_base
        .lock()
        .map_err(|_| "backend state lock failed".to_string())?
        .clone()
        .ok_or_else(|| "backend not yet started".to_string())
}

#[tauri::command]
fn minimize_window(window: tauri::WebviewWindow) {
    let _ = window.minimize();
}

#[tauri::command]
fn toggle_maximize_window(window: tauri::WebviewWindow) {
    let _ = if window.is_maximized().unwrap_or(false) {
        window.unmaximize()
    } else {
        window.maximize()
    };
}

#[tauri::command]
fn close_window(window: tauri::WebviewWindow) {
    let _ = window.close();
}

#[tauri::command]
fn start_window_dragging(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
) -> Result<(), String> {
    clear_desktop_plugin_dock(&app)?;
    window.start_dragging().map_err(|error| error.to_string())
}

#[tauri::command]
fn save_desktop_plugin_position(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
) -> Result<DesktopPluginPlacement, String> {
    let dock = load_desktop_plugin_placement(&app).and_then(|placement| placement.dock);
    let placement = desktop_plugin_placement_for_window(&window, dock)?;
    write_desktop_plugin_placement(&app, &placement)?;
    Ok(placement)
}

#[tauri::command]
fn get_desktop_plugin_dock_zone(
    window: tauri::WebviewWindow,
) -> Result<Option<&'static str>, String> {
    let monitor = desktop_plugin_monitor(&window)?;
    let geometry = desktop_window_geometry(&window)?;
    Ok(desktop_plugin_dock_zone_for_geometry(
        geometry,
        desktop_work_area_from_monitor(&monitor),
    ))
}

#[tauri::command]
fn set_desktop_plugin_dock(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    dock: String,
) -> Result<DesktopPluginPlacement, String> {
    let raw_dock = dock.trim().to_string();
    let dock = normalized_dock(Some(&raw_dock))
        .ok_or_else(|| format!("unknown desktop plugin dock zone: {raw_dock}"))?;
    let monitor = desktop_plugin_monitor(&window)?;
    let geometry = desktop_window_geometry(&window)?;
    let work_area = desktop_work_area_from_monitor(&monitor);
    let (x_ratio, y_ratio) = normalize_desktop_plugin_position(
        geometry.x,
        geometry.y,
        geometry.width,
        geometry.height,
        work_area,
    );
    let placement = DesktopPluginPlacement {
        monitor_name: monitor.name().cloned(),
        x_ratio,
        y_ratio,
        dock: Some(dock),
    };
    write_desktop_plugin_placement(&app, &placement)?;
    let position = desktop_plugin_position_from_placement(
        &placement,
        geometry.width,
        geometry.height,
        work_area,
    );
    window
        .set_position(tauri::PhysicalPosition::new(position.0, position.1))
        .map_err(|error| error.to_string())?;
    Ok(placement)
}

fn checked_desktop_drop_total(
    current_file_count: usize,
    current_total_bytes: u64,
    next_file_bytes: u64,
) -> Result<u64, String> {
    if current_file_count >= MAX_DESKTOP_DROP_FILES {
        return Err(format!("一次最多拖放 {MAX_DESKTOP_DROP_FILES} 个文件"));
    }
    if next_file_bytes > MAX_DESKTOP_DROP_FILE_BYTES {
        return Err("单个拖放文件不能超过 50 MB".to_string());
    }
    let next_total = current_total_bytes
        .checked_add(next_file_bytes)
        .ok_or_else(|| "拖放文件总大小超出限制".to_string())?;
    if next_total > MAX_DESKTOP_DROP_TOTAL_BYTES {
        return Err("拖放文件总大小不能超过 100 MB".to_string());
    }
    Ok(next_total)
}

fn prepare_desktop_drop_paths(paths: Vec<String>) -> Result<Vec<PathBuf>, String> {
    if paths.is_empty() {
        return Err("没有可读取的拖放文件".to_string());
    }
    let mut files = Vec::new();
    let mut seen = HashSet::new();
    let mut total_bytes = 0;
    for raw_path in paths {
        let raw_path = raw_path.trim();
        if raw_path.is_empty() {
            return Err("拖放路径不能为空".to_string());
        }
        let path = std::fs::canonicalize(raw_path)
            .map_err(|error| format!("无法读取拖放路径 {raw_path}：{error}"))?;
        if !seen.insert(path.clone()) {
            continue;
        }
        let metadata = std::fs::metadata(&path)
            .map_err(|error| format!("无法读取拖放文件 {}：{error}", path.display()))?;
        if !metadata.is_file() {
            return Err(format!("仅支持拖放文件：{}", path.display()));
        }
        total_bytes = checked_desktop_drop_total(files.len(), total_bytes, metadata.len())
            .map_err(|error| format!("{error}：{}", path.display()))?;
        files.push(path);
    }
    if files.is_empty() {
        return Err("没有可读取的拖放文件".to_string());
    }
    Ok(files)
}

#[tauri::command]
fn register_desktop_plugin_drop(
    state: tauri::State<'_, BackendState>,
    paths: Vec<String>,
) -> Result<DesktopDropSummary, String> {
    let files = prepare_desktop_drop_paths(paths)?;

    let drop_id = format!(
        "drop-{}",
        NEXT_DESKTOP_DROP_ID.fetch_add(1, Ordering::Relaxed)
    );
    let summary = DesktopDropSummary {
        drop_id: drop_id.clone(),
        files: files
            .iter()
            .map(|path| DesktopDropFileSummary {
                name: path
                    .file_name()
                    .map(|name| name.to_string_lossy().into_owned())
                    .unwrap_or_else(|| "attachment".to_string()),
            })
            .collect(),
    };
    state
        .desktop_drops
        .lock()
        .map_err(|_| "desktop drop state lock failed".to_string())?
        .insert(drop_id, files);
    Ok(summary)
}

#[tauri::command]
fn read_desktop_plugin_drop(
    state: tauri::State<'_, BackendState>,
    drop_id: String,
) -> Result<DesktopDropData, String> {
    let drop_id = drop_id.trim().to_string();
    if drop_id.is_empty() {
        return Err("dropId is required".to_string());
    }
    let paths = state
        .desktop_drops
        .lock()
        .map_err(|_| "desktop drop state lock failed".to_string())?
        .get(&drop_id)
        .cloned()
        .ok_or_else(|| "desktop drop not found or already imported".to_string())?;

    let mut expected_total_bytes = 0;
    for (index, path) in paths.iter().enumerate() {
        let metadata = std::fs::metadata(path)
            .map_err(|error| format!("无法读取拖放文件 {}：{error}", path.display()))?;
        if !metadata.is_file() {
            return Err(format!("拖放文件已不可用：{}", path.display()));
        }
        expected_total_bytes =
            checked_desktop_drop_total(index, expected_total_bytes, metadata.len())
                .map_err(|error| format!("{error}：{}", path.display()))?;
    }

    let mut files = Vec::with_capacity(paths.len());
    let mut actual_total_bytes = 0;
    for (index, path) in paths.into_iter().enumerate() {
        let remaining_total = MAX_DESKTOP_DROP_TOTAL_BYTES.saturating_sub(actual_total_bytes);
        let read_limit = MAX_DESKTOP_DROP_FILE_BYTES
            .min(remaining_total)
            .saturating_add(1);
        let mut bytes = Vec::new();
        std::fs::File::open(&path)
            .map_err(|error| format!("无法打开拖放文件 {}：{error}", path.display()))?
            .take(read_limit)
            .read_to_end(&mut bytes)
            .map_err(|error| format!("无法读取拖放文件 {}：{error}", path.display()))?;
        actual_total_bytes =
            checked_desktop_drop_total(index, actual_total_bytes, bytes.len() as u64)
                .map_err(|error| format!("{error}：{}", path.display()))?;
        let name = path
            .file_name()
            .map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_else(|| "attachment".to_string());
        files.push(DesktopDropFileData {
            name,
            size: bytes.len() as u64,
            data_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
        });
    }

    state
        .desktop_drops
        .lock()
        .map_err(|_| "desktop drop state lock failed".to_string())?
        .remove(&drop_id);
    Ok(DesktopDropData { drop_id, files })
}

#[tauri::command]
fn discard_desktop_plugin_drop(
    state: tauri::State<'_, BackendState>,
    drop_id: String,
) -> Result<(), String> {
    let drop_id = drop_id.trim();
    if drop_id.is_empty() {
        return Ok(());
    }
    state
        .desktop_drops
        .lock()
        .map_err(|_| "desktop drop state lock failed".to_string())?
        .remove(drop_id);
    Ok(())
}

#[tauri::command]
fn get_desktop_plugin_anchor(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, BackendState>,
) -> Result<&'static str, String> {
    let anchor = desktop_window_anchor(&window)?;
    let mut windows = state
        .desktop_windows
        .lock()
        .map_err(|_| "desktop window state lock failed".to_string())?;
    let registration = windows
        .get_mut(window.label())
        .ok_or_else(|| "desktop plugin window is not registered".to_string())?;
    registration.anchor = anchor;
    Ok(anchor.as_str())
}

#[tauri::command]
fn set_desktop_plugin_expanded(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, BackendState>,
    expanded: bool,
    reduced_motion: bool,
    content_width: Option<f64>,
    content_height: Option<f64>,
    viewport_width: Option<f64>,
    viewport_height: Option<f64>,
) -> Result<DesktopWindowTransition, String> {
    let registration = state
        .desktop_windows
        .lock()
        .map_err(|_| "desktop window state lock failed".to_string())?
        .get(window.label())
        .cloned()
        .ok_or_else(|| "desktop plugin window is not registered".to_string())?;
    let (requested_width, requested_height) = if expanded {
        adaptive_expanded_dimensions(
            &window,
            content_width,
            content_height,
            viewport_width,
            viewport_height,
            registration.spec.collapsed_width,
            registration.spec.collapsed_height,
        )?
    } else {
        (None, None)
    };
    let anchor = if expanded && requested_width.is_none() && requested_height.is_none() {
        desktop_window_anchor(&window)?
    } else {
        registration.anchor
    };
    if let Ok(mut windows) = state.desktop_windows.lock() {
        if let Some(current) = windows.get_mut(window.label()) {
            current.anchor = anchor;
        }
    }
    let (width, height) = desktop_window_target_size(
        &window,
        &registration.spec,
        anchor,
        expanded,
        requested_width,
        requested_height,
    )?;
    animate_window_anchored(
        &window,
        width,
        height,
        anchor,
        if reduced_motion {
            Duration::ZERO
        } else {
            Duration::from_millis(220)
        },
    )?;
    Ok(DesktopWindowTransition {
        anchor: anchor.as_str(),
        vertical_anchor: registration.vertical_anchor.as_str(),
    })
}

#[tauri::command]
fn set_desktop_plugin_view_mode(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, BackendState>,
    mode: String,
    reduced_motion: bool,
) -> Result<DesktopWindowTransition, String> {
    let registration = state
        .desktop_windows
        .lock()
        .map_err(|_| "desktop window state lock failed".to_string())?
        .get(window.label())
        .cloned()
        .ok_or_else(|| "desktop plugin window is not registered".to_string())?;
    let mode = mode.trim().to_ascii_lowercase();
    let mode = DesktopPluginViewMode::parse(&mode)
        .ok_or_else(|| format!("unknown desktop plugin view mode: {mode}"))?;
    let (target, work_area) = desktop_plugin_view_mode_target(&window, &registration, mode)?;
    animate_window_to_geometry(
        &window,
        target.geometry,
        work_area,
        if reduced_motion {
            Duration::ZERO
        } else {
            Duration::from_millis(220)
        },
    )?;
    if let Ok(mut windows) = state.desktop_windows.lock() {
        if let Some(current) = windows.get_mut(window.label()) {
            current.anchor = target.anchor;
            current.vertical_anchor = target.vertical_anchor;
        }
    }
    Ok(DesktopWindowTransition {
        anchor: target.anchor.as_str(),
        vertical_anchor: target.vertical_anchor.as_str(),
    })
}

#[tauri::command]
fn get_desktop_plugin_view_mode_transition(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, BackendState>,
    mode: String,
) -> Result<DesktopWindowTransition, String> {
    let registration = state
        .desktop_windows
        .lock()
        .map_err(|_| "desktop window state lock failed".to_string())?
        .get(window.label())
        .cloned()
        .ok_or_else(|| "desktop plugin window is not registered".to_string())?;
    let mode = mode.trim().to_ascii_lowercase();
    let mode = DesktopPluginViewMode::parse(&mode)
        .ok_or_else(|| format!("unknown desktop plugin view mode: {mode}"))?;
    let (target, _) = desktop_plugin_view_mode_target(&window, &registration, mode)?;
    Ok(DesktopWindowTransition {
        anchor: target.anchor.as_str(),
        vertical_anchor: target.vertical_anchor.as_str(),
    })
}

#[tauri::command]
fn get_desktop_plugin_cursor_position(
    window: tauri::WebviewWindow,
) -> Result<DesktopCursorPosition, String> {
    let cursor = window
        .cursor_position()
        .map_err(|error| error.to_string())?;
    let position = window.inner_position().map_err(|error| error.to_string())?;
    let scale = window.scale_factor().map_err(|error| error.to_string())?;
    let (x, y) = logical_cursor_position(
        cursor.x,
        cursor.y,
        f64::from(position.x),
        f64::from(position.y),
        scale,
    );
    Ok(DesktopCursorPosition { x, y })
}

#[tauri::command]
fn set_desktop_plugin_cursor_passthrough(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, BackendState>,
    passthrough: bool,
) -> Result<bool, String> {
    let should_update = state
        .desktop_windows
        .lock()
        .map_err(|_| "desktop window state lock failed".to_string())?
        .get(window.label())
        .map(|registration| registration.ignoring_cursor_events != passthrough)
        .ok_or_else(|| "desktop plugin window is not registered".to_string())?;
    if should_update {
        window
            .set_ignore_cursor_events(passthrough)
            .map_err(|error| error.to_string())?;
        if let Some(registration) = state
            .desktop_windows
            .lock()
            .map_err(|_| "desktop window state lock failed".to_string())?
            .get_mut(window.label())
        {
            registration.ignoring_cursor_events = passthrough;
        }
    }
    Ok(passthrough)
}

#[tauri::command]
fn hide_current_window(window: tauri::WebviewWindow, app: tauri::AppHandle) {
    let _ = window.hide();
    sync_pet_tray_item(&app);
}

#[tauri::command]
fn show_current_window(window: tauri::WebviewWindow, app: tauri::AppHandle) {
    let _ = window.show();
    sync_pet_tray_item(&app);
}

#[tauri::command]
fn configure_desktop_plugin_window(
    window: tauri::WebviewWindow,
    app: tauri::AppHandle,
    state: tauri::State<'_, BackendState>,
    spec: DesktopWindowSpec,
) -> Result<(), String> {
    let spec = spec.sanitized();
    make_desktop_plugin_window_transparent(&window)?;
    state
        .desktop_windows
        .lock()
        .map_err(|_| "desktop window state lock failed".to_string())?
        .insert(
            window.label().to_string(),
            DesktopWindowRegistration {
                spec: spec.clone(),
                anchor: HorizontalAnchor::Right,
                vertical_anchor: VerticalAnchor::Bottom,
                ignoring_cursor_events: false,
            },
        );
    window
        .set_size(tauri::LogicalSize::new(
            spec.collapsed_width,
            spec.collapsed_height,
        ))
        .map_err(|error| error.to_string())?;
    restore_desktop_plugin_position(&window, &app, &spec)?;
    sync_pet_tray_item(&app);
    Ok(())
}

#[tauri::command]
fn show_main_window(app: tauri::AppHandle) {
    reveal_main_window(&app);
}

#[tauri::command]
fn quit_app(app: tauri::AppHandle, state: tauri::State<'_, BackendState>) {
    state.quitting.store(true, Ordering::SeqCst);
    stop_backend(state.inner());
    app.exit(0);
}

#[tauri::command]
fn ping() -> String {
    "pong".to_string()
}

/// Report the packaged app name and version (from tauri.conf.json).
///
/// The frontend injects this into `window.__LAMTOOLS_APP_VERSION__` so the
/// settings UI can show the real version without hardcoding a string — the
/// update check compares it against the backend's `__version__`.
#[tauri::command]
fn get_app_info(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let info = app.package_info();
    Ok(serde_json::json!({
        "name": info.name,
        "version": info.version.to_string(),
    }))
}

#[tauri::command]
fn pick_directory() -> Option<String> {
    rfd::FileDialog::new()
        .set_title("选择目录")
        .pick_folder()
        .map(|p| p.to_string_lossy().into_owned())
}

/// Open an external URL in the OS default browser.
///
/// The Tauri webview has no navigation policy by default, so a plain
/// `<a href="https://...">` click would navigate the app window itself
/// (turning it into a browser). The frontend intercepts link clicks and
/// routes them through this command instead. Only http(s) URLs are
/// accepted — everything else is rejected to prevent scheme/protocol abuse.
#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    let parsed = url::Url::parse(&url).map_err(|_| "invalid URL".to_string())?;
    match parsed.scheme() {
        "http" | "https" => {}
        other => return Err(format!("refused scheme: {other}")),
    }
    open::that(url).map_err(|e| e.to_string())
}

fn sync_pet_tray_item(app: &tauri::AppHandle) {
    let state = app.state::<BackendState>();
    let plugin_enabled = state
        .desktop_windows
        .lock()
        .map(|windows| windows.contains_key(DESKTOP_PLUGIN_WINDOW_LABEL))
        .unwrap_or(false);
    let visible = plugin_enabled
        && app
            .get_webview_window(DESKTOP_PLUGIN_WINDOW_LABEL)
            .and_then(|window| window.is_visible().ok())
            .unwrap_or(false);

    if let Ok(item) = state.tray_pet_item.lock() {
        if let Some(item) = item.as_ref() {
            let _ = item.set_enabled(plugin_enabled);
            let _ = item.set_text(if visible {
                "隐藏桌宠"
            } else {
                "显示桌宠"
            });
        }
    };
}

fn make_desktop_plugin_window_transparent(window: &WebviewWindow) -> Result<(), String> {
    window
        .set_background_color(Some(tauri::utils::config::Color(0, 0, 0, 0)))
        .map_err(|error| error.to_string())?;
    window.set_shadow(false).map_err(|error| error.to_string())
}

fn logical_cursor_position(
    cursor_x: f64,
    cursor_y: f64,
    window_x: f64,
    window_y: f64,
    scale: f64,
) -> (f64, f64) {
    ((cursor_x - window_x) / scale, (cursor_y - window_y) / scale)
}

fn toggle_desktop_plugin_window(app: &tauri::AppHandle) {
    let state = app.state::<BackendState>();
    let plugin_enabled = state
        .desktop_windows
        .lock()
        .map(|windows| windows.contains_key(DESKTOP_PLUGIN_WINDOW_LABEL))
        .unwrap_or(false);
    if !plugin_enabled {
        sync_pet_tray_item(app);
        return;
    }

    if let Some(window) = app.get_webview_window(DESKTOP_PLUGIN_WINDOW_LABEL) {
        if window.is_visible().unwrap_or(false) {
            let _ = window.hide();
        } else {
            let _ = window.show();
        }
    }
    sync_pet_tray_item(app);
}

fn handle_tray_menu(app: &tauri::AppHandle, event: MenuEvent) {
    match event.id().as_ref() {
        TRAY_TOGGLE_PET_ID => toggle_desktop_plugin_window(app),
        TRAY_OPEN_MAIN_ID => reveal_main_window(app),
        TRAY_QUIT_ID => {
            let state = app.state::<BackendState>();
            quit_app(app.clone(), state);
        }
        _ => {}
    }
}

fn setup_tray(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let toggle_pet = MenuItem::with_id(app, TRAY_TOGGLE_PET_ID, "显示桌宠", false, None::<&str>)?;
    let open_main = MenuItem::with_id(app, TRAY_OPEN_MAIN_ID, "打开界面", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, TRAY_QUIT_ID, "退出", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&toggle_pet, &open_main, &quit])?;

    let mut builder = TrayIconBuilder::with_id(TRAY_ID)
        .menu(&menu)
        .tooltip("LamTools")
        .show_menu_on_left_click(true)
        .on_menu_event(handle_tray_menu);
    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder.icon(icon);
    }
    builder.build(app)?;

    let state = app.state::<BackendState>();
    state
        .tray_pet_item
        .lock()
        .map_err(|_| "tray state lock failed")?
        .replace(toggle_pet);
    Ok(())
}

// ---------------------------------------------------------------------------
// App entry point
// ---------------------------------------------------------------------------

fn main() {
    let state = BackendState {
        api_base: Mutex::new(None),
        child: Mutex::new(None),
        desktop_windows: Mutex::new(HashMap::new()),
        desktop_drops: Mutex::new(HashMap::new()),
        tray_pet_item: Mutex::new(None),
        quitting: AtomicBool::new(false),
    };

    tauri::Builder::default()
        // Single-instance guard: two instances would each spawn a backend
        // writing the same .lam/core.db (SQLite lock storms, config
        // clobbering) (audit 20 S3).
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // Focus the existing window instead of starting a second instance.
            reveal_main_window(app);
        }))
        .manage(state)
        .setup(|app| {
            let state = app.state::<BackendState>();
            match start_backend(app, state.inner()) {
                Ok(api_base) => {
                    *state
                        .api_base
                        .lock()
                        .map_err(|_| "backend state lock failed")? = Some(api_base.clone());
                    setup_tray(app)?;
                    // Watch the backend process: if it dies mid-run (panic,
                    // fatal Python exception) the frontend gets an event and
                    // can show a recovery banner instead of silently failing
                    // every request (audit 20 S3).
                    let app_handle = app.handle().clone();
                    spawn_backend_watcher(app_handle);
                    Ok(())
                }
                Err(e) => {
                    let msg = format!("LamCore 后端启动失败：\n\n{}", e);
                    eprintln!("{}", msg);
                    #[cfg(windows)]
                    {
                        let msg_wide: Vec<u16> =
                            msg.encode_utf16().chain(std::iter::once(0)).collect();
                        extern "system" {
                            fn MessageBoxW(
                                hwnd: isize,
                                text: *const u16,
                                caption: *const u16,
                                utype: u32,
                            ) -> i32;
                        }
                        let caption: Vec<u16> = "LamCore 启动错误"
                            .encode_utf16()
                            .chain(std::iter::once(0))
                            .collect();
                        unsafe { MessageBoxW(0, msg_wide.as_ptr(), caption.as_ptr(), 0x00000010) };
                    }
                    Err(e)
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_api_base,
            minimize_window,
            toggle_maximize_window,
            close_window,
            start_window_dragging,
            save_desktop_plugin_position,
            get_desktop_plugin_dock_zone,
            set_desktop_plugin_dock,
            register_desktop_plugin_drop,
            read_desktop_plugin_drop,
            discard_desktop_plugin_drop,
            get_desktop_plugin_anchor,
            set_desktop_plugin_expanded,
            set_desktop_plugin_view_mode,
            get_desktop_plugin_view_mode_transition,
            get_desktop_plugin_cursor_position,
            set_desktop_plugin_cursor_passthrough,
            hide_current_window,
            show_current_window,
            configure_desktop_plugin_window,
            show_main_window,
            quit_app,
            ping,
            get_app_info,
            pick_directory,
            open_external_url
        ])
        .on_window_event(|window, event| {
            let state = window.state::<BackendState>();
            match event {
                tauri::WindowEvent::CloseRequested { api, .. }
                    if window.label() == "main" && !state.quitting.load(Ordering::SeqCst) =>
                {
                    api.prevent_close();
                    let _ = window.hide();
                }
                tauri::WindowEvent::Destroyed if window.label() == "main" => {
                    stop_backend(state.inner());
                }
                tauri::WindowEvent::Destroyed if window.label().starts_with("desktop-plugin-") => {
                    if let Ok(mut windows) = state.desktop_windows.lock() {
                        windows.remove(window.label());
                    }
                }
                _ => {}
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build LamCore")
        .run(|app_handle, event| {
            if matches!(event, tauri::RunEvent::Ready) {
                if let Some(window) = app_handle.get_webview_window(DESKTOP_PLUGIN_WINDOW_LABEL) {
                    if let Err(error) = make_desktop_plugin_window_transparent(&window) {
                        eprintln!("[lamcore] desktop plugin host transparency failed: {error}");
                    }
                    eprintln!("[lamcore] desktop plugin host ready");
                    return;
                }
                let app_handle = app_handle.clone();
                thread::spawn(move || match create_desktop_plugin_host(&app_handle) {
                    Ok(window) => {
                        if let Err(error) = make_desktop_plugin_window_transparent(&window) {
                            eprintln!("[lamcore] desktop plugin host transparency failed: {error}");
                        }
                        eprintln!("[lamcore] desktop plugin host created: {}", window.label())
                    }
                    Err(error) => eprintln!("[lamcore] desktop plugin host failed: {error}"),
                });
            }
        });
}

// ---------------------------------------------------------------------------
// Backend lifecycle
// ---------------------------------------------------------------------------

fn start_backend(
    app: &tauri::App,
    state: &BackendState,
) -> Result<String, Box<dyn std::error::Error>> {
    let port = pick_free_port()?;
    let api_base = format!("http://127.0.0.1:{port}");

    let mut cmd = if cfg!(debug_assertions) {
        dev_backend_command(port)?
    } else {
        prod_backend_command(app, port)?
    };

    let child = cmd.spawn()?;
    *state
        .child
        .lock()
        .map_err(|_| "backend state lock failed")? = Some(child);

    wait_for_health(port)?;
    Ok(api_base)
}

fn dev_backend_command(port: u16) -> Result<Command, Box<dyn std::error::Error>> {
    // Resolve core/ from core/desktop/src-tauri.
    let core_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent() // desktop/
        .and_then(|p| p.parent()) // core/
        .ok_or("cannot locate core/ directory")?
        .to_path_buf();

    let mut cmd = Command::new("py");
    cmd.arg("-3.14")
        .arg("-m")
        .arg("lamtools_core.cli")
        .arg("serve")
        .arg("--port")
        .arg(port.to_string())
        // No --reload: uvicorn's reloader spawns a detached child on Windows
        // that survives stop_backend's kill(), orphaning a backend that keeps
        // core/core.db locked (audit 20 S2). Tauri dev restarts are full
        // teardown anyway (AGENTS.md: exit completely, then tauri dev again).
        .current_dir(&core_dir)
        // A src-layout checkout is not importable from core/ by default.
        // Pin dev mode to this worktree instead of whichever editable
        // lamtools_core installation happens to be active on the machine.
        .env("PYTHONPATH", core_dir.join("src"))
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    hide_console(&mut cmd);
    Ok(cmd)
}

fn prod_backend_command(
    app: &tauri::App,
    port: u16,
) -> Result<Command, Box<dyn std::error::Error>> {
    // The PyInstaller output is bundled as a resource at dist/LamCore/.
    // Tauri copies it to the bundle's resource directory.
    let backend_exe = find_backend_exe(app)?;
    let backend_dir = backend_exe
        .parent()
        .ok_or("cannot locate backend directory")?
        .to_path_buf();

    // Green/portable mode: keep every user data file (core.db, workspace,
    // logs, ~/.lam jsonc configs) beside the app under {app}/.lam so nothing
    // is written outside the install root (no %APPDATA%, no ~).
    let app_dir = env::current_exe()?
        .parent()
        .ok_or("cannot locate app directory")?
        .to_path_buf();
    let lam_home = app_dir.join(".lam");

    let mut cmd = Command::new(&backend_exe);
    cmd.env("LAMCORE_PORT", port.to_string())
        .env("LAMTOOLS_HOME", &lam_home)
        .env("LAMTOOLS_PROJECTS_ROOT", app_dir.join("lam_projects"))
        .current_dir(&backend_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    hide_console(&mut cmd);
    Ok(cmd)
}

fn find_backend_exe(app: &tauri::App) -> Result<PathBuf, Box<dyn std::error::Error>> {
    // 1) Tauri resource directory (bundled flat)
    let resource = app
        .path()
        .resource_dir()?
        .join("lamcore-backend")
        .join("LamCore.exe");
    if resource.exists() {
        return Ok(resource);
    }

    // 2) Adjacent to the current exe (portable layout)
    let adjacent = env::current_exe()?
        .parent()
        .ok_or("cannot locate app directory")?
        .join("LamCore")
        .join("LamCore.exe");
    if adjacent.exists() {
        return Ok(adjacent);
    }

    // 3) Project dist directory (dev convenience)
    let project_dist = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent() // src-tauri/ -> desktop/
        .and_then(|p| p.parent()) // desktop/ -> core/
        .and_then(|p| p.parent()) // core/ -> repo root
        .ok_or("cannot locate project root")?
        .join("dist")
        .join("LamCore")
        .join("LamCore.exe");
    if project_dist.exists() {
        return Ok(project_dist);
    }

    Err(format!(
        "LamCore.exe not found at any of:\n  {}\n  {}\n  {}",
        resource.display(),
        adjacent.display(),
        project_dist.display(),
    )
    .into())
}

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

fn pick_free_port() -> Result<u16, Box<dyn std::error::Error>> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    Ok(listener.local_addr()?.port())
}

fn wait_for_health(port: u16) -> Result<(), Box<dyn std::error::Error>> {
    // Generous timeout: on a loaded dev machine the backend can take a while
    // to start (uvicorn --reload + stale-turn recovery), and failing here
    // blocks the whole app on an error dialog for no reason.
    let deadline = Instant::now() + Duration::from_secs(90);
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let request =
                b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
            if stream.write_all(request).is_ok() {
                let mut response = String::new();
                if stream.read_to_string(&mut response).is_ok() {
                    if response.contains("200") {
                        return Ok(());
                    }
                }
            }
        }
        thread::sleep(Duration::from_millis(250));
    }
    Err("backend health check timed out after 90s".into())
}

fn stop_backend(state: &BackendState) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

/// Poll the backend child process; if it exits outside the normal shutdown
/// path (child was still registered), emit a `backend-crashed` event so the
/// frontend can surface a recovery banner (audit 20 S3).
fn spawn_backend_watcher(app_handle: tauri::AppHandle) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(2));
        let state = app_handle.state::<BackendState>();
        let mut guard = match state.child.lock() {
            Ok(guard) => guard,
            Err(_) => return,
        };
        if guard.is_none() {
            // Normal shutdown: stop_backend already took the child.
            return;
        }
        let exited = match guard.as_mut().map(|child| child.try_wait()) {
            Some(Ok(Some(_status))) => true,
            Some(Ok(None)) => false,
            _ => true, // try_wait error — treat as gone
        };
        if exited {
            *guard = None;
            drop(guard);
            eprintln!("[lamcore] backend process exited unexpectedly");
            let _ = app_handle.emit("backend-crashed", ());
            return;
        }
    });
}

// ---------------------------------------------------------------------------
// Desktop plugin windows
// ---------------------------------------------------------------------------

fn create_desktop_plugin_host(
    app: &tauri::AppHandle,
) -> Result<WebviewWindow, Box<dyn std::error::Error>> {
    let config = app
        .config()
        .app
        .windows
        .iter()
        .find(|config| config.label == DESKTOP_PLUGIN_WINDOW_LABEL)
        .cloned()
        .ok_or("desktop plugin host window config is missing")?;
    Ok(WebviewWindowBuilder::from_config(app, &config)?.build()?)
}

fn desktop_plugin_placement_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|directory| directory.join("desktop-plugin-placement.json"))
        .map_err(|error| error.to_string())
}

fn load_desktop_plugin_placement(app: &tauri::AppHandle) -> Option<DesktopPluginPlacement> {
    let path = match desktop_plugin_placement_path(app) {
        Ok(path) => path,
        Err(error) => {
            eprintln!("[lamcore] desktop plugin placement path unavailable: {error}");
            return None;
        }
    };
    let content = match std::fs::read_to_string(path) {
        Ok(content) => content,
        Err(_) => return None,
    };
    match serde_json::from_str::<DesktopPluginPlacement>(&content) {
        Ok(placement) => Some(placement.sanitized()),
        Err(error) => {
            eprintln!("[lamcore] desktop plugin placement is invalid: {error}");
            None
        }
    }
}

fn write_desktop_plugin_placement(
    app: &tauri::AppHandle,
    placement: &DesktopPluginPlacement,
) -> Result<(), String> {
    let path = desktop_plugin_placement_path(app)?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let content = serde_json::to_string_pretty(placement).map_err(|error| error.to_string())?;
    std::fs::write(path, content).map_err(|error| error.to_string())
}

fn clear_desktop_plugin_dock(app: &tauri::AppHandle) -> Result<(), String> {
    let Some(mut placement) = load_desktop_plugin_placement(app) else {
        return Ok(());
    };
    if placement.dock.is_none() {
        return Ok(());
    }
    placement.dock = None;
    write_desktop_plugin_placement(app, &placement)
}

fn normalized_ratio(value: f64, fallback: f64) -> f64 {
    if value.is_finite() {
        value.clamp(0.0, 1.0)
    } else {
        fallback.clamp(0.0, 1.0)
    }
}

fn normalized_dock(value: Option<&str>) -> Option<String> {
    match value.map(str::trim).map(|dock| dock.to_ascii_lowercase()) {
        Some(dock) if dock == "left" || dock == "right" => Some(dock),
        _ => None,
    }
}

fn desktop_work_area_from_monitor(monitor: &tauri::Monitor) -> DesktopWorkArea {
    let work_area = monitor.work_area();
    DesktopWorkArea {
        x: work_area.position.x,
        y: work_area.position.y,
        width: work_area.size.width,
        height: work_area.size.height,
    }
}

fn physical_window_size(logical_width: f64, logical_height: f64, scale: f64) -> (u32, u32) {
    let scale = if scale.is_finite() && scale > 0.0 {
        scale
    } else {
        1.0
    };
    (
        (logical_width * scale).round().max(1.0) as u32,
        (logical_height * scale).round().max(1.0) as u32,
    )
}

fn saved_monitor_index(
    monitor_names: &[Option<String>],
    saved_name: Option<&str>,
) -> Option<usize> {
    let saved_name = saved_name?.trim();
    if saved_name.is_empty() {
        return None;
    }
    monitor_names.iter().position(|name| {
        name.as_deref()
            .is_some_and(|monitor_name| monitor_name == saved_name)
    })
}

fn clamp_desktop_plugin_position(
    x: i32,
    y: i32,
    width: u32,
    height: u32,
    work_area: DesktopWorkArea,
) -> (i32, i32) {
    (
        clamp_axis(x, work_area.x, work_area.width, width),
        clamp_axis(y, work_area.y, work_area.height, height),
    )
}

fn clamp_axis(position: i32, area_start: i32, area_size: u32, window_size: u32) -> i32 {
    let minimum = i64::from(area_start);
    let maximum = minimum + i64::from(area_size) - i64::from(window_size);
    if maximum <= minimum {
        return area_start;
    }
    i64::from(position)
        .clamp(minimum, maximum)
        .try_into()
        .unwrap_or(area_start)
}

fn normalize_desktop_plugin_position(
    x: i32,
    y: i32,
    width: u32,
    height: u32,
    work_area: DesktopWorkArea,
) -> (f64, f64) {
    (
        normalize_axis(x, work_area.x, work_area.width, width),
        normalize_axis(y, work_area.y, work_area.height, height),
    )
}

fn normalize_axis(position: i32, area_start: i32, area_size: u32, window_size: u32) -> f64 {
    let travel = i64::from(area_size).saturating_sub(i64::from(window_size));
    if travel <= 0 {
        return 0.0;
    }
    let offset = (i64::from(position) - i64::from(area_start)).clamp(0, travel);
    offset as f64 / travel as f64
}

fn desktop_plugin_position_from_placement(
    placement: &DesktopPluginPlacement,
    width: u32,
    height: u32,
    work_area: DesktopWorkArea,
) -> (i32, i32) {
    let x = match placement.dock.as_deref() {
        Some("left") => work_area.x,
        Some("right") => work_area.x + work_area.width.saturating_sub(width) as i32,
        _ => axis_from_ratio(placement.x_ratio, work_area.x, work_area.width, width),
    };
    let y = axis_from_ratio(placement.y_ratio, work_area.y, work_area.height, height);
    clamp_desktop_plugin_position(x, y, width, height, work_area)
}

fn desktop_plugin_dock_zone_for_geometry(
    geometry: DesktopWindowGeometry,
    work_area: DesktopWorkArea,
) -> Option<&'static str> {
    let left_distance = (i64::from(geometry.x) - i64::from(work_area.x)).max(0);
    let right_distance =
        (i64::from(work_area.x) + i64::from(work_area.width) - geometry.right()).max(0);
    let threshold = i64::from(DESKTOP_PLUGIN_DOCK_THRESHOLD);
    let left = left_distance <= threshold;
    let right = right_distance <= threshold;
    match (left, right) {
        (true, true) if left_distance <= right_distance => Some("left"),
        (true, true) => Some("right"),
        (true, false) => Some("left"),
        (false, true) => Some("right"),
        _ => None,
    }
}

fn axis_from_ratio(ratio: f64, area_start: i32, area_size: u32, window_size: u32) -> i32 {
    let travel = i64::from(area_size).saturating_sub(i64::from(window_size));
    let value =
        i64::from(area_start) + (travel as f64 * normalized_ratio(ratio, 1.0)).round() as i64;
    value.try_into().unwrap_or(area_start)
}

fn place_window_bottom_right_on_monitor(
    window: &WebviewWindow,
    spec: &DesktopWindowSpec,
    monitor: &tauri::Monitor,
) -> Result<(), String> {
    let (width, height) = physical_window_size(
        spec.collapsed_width,
        spec.collapsed_height,
        monitor.scale_factor(),
    );
    let margin = (spec.margin * monitor.scale_factor()).round().max(0.0) as i32;
    let work_area = desktop_work_area_from_monitor(monitor);
    let (x, y) = clamp_desktop_plugin_position(
        work_area.x + work_area.width.saturating_sub(width) as i32 - margin,
        work_area.y + work_area.height.saturating_sub(height) as i32 - margin,
        width,
        height,
        work_area,
    );
    window
        .set_size(tauri::PhysicalSize::new(width, height))
        .map_err(|error| error.to_string())?;
    window
        .set_position(tauri::PhysicalPosition::new(x, y))
        .map_err(|error| error.to_string())
}

fn restore_desktop_plugin_position(
    window: &WebviewWindow,
    app: &tauri::AppHandle,
    spec: &DesktopWindowSpec,
) -> Result<(), String> {
    let placement = load_desktop_plugin_placement(app);
    let monitors = window
        .available_monitors()
        .map_err(|error| error.to_string())?;
    let fallback = window
        .primary_monitor()
        .map_err(|error| error.to_string())?
        .or(window
            .current_monitor()
            .map_err(|error| error.to_string())?)
        .ok_or_else(|| "no monitor available".to_string())?;
    let Some(placement) = placement else {
        return place_window_bottom_right_on_monitor(window, spec, &fallback);
    };
    let monitor_names: Vec<Option<String>> = monitors
        .iter()
        .map(|monitor| monitor.name().cloned())
        .collect();
    let monitor = saved_monitor_index(&monitor_names, placement.monitor_name.as_deref())
        .and_then(|index| monitors.get(index))
        .unwrap_or(&fallback);
    let (width, height) = physical_window_size(
        spec.collapsed_width,
        spec.collapsed_height,
        monitor.scale_factor(),
    );
    let position = desktop_plugin_position_from_placement(
        &placement,
        width,
        height,
        desktop_work_area_from_monitor(monitor),
    );
    window
        .set_size(tauri::PhysicalSize::new(width, height))
        .map_err(|error| error.to_string())?;
    window
        .set_position(tauri::PhysicalPosition::new(position.0, position.1))
        .map_err(|error| error.to_string())
}

fn desktop_plugin_placement_for_window(
    window: &WebviewWindow,
    dock: Option<String>,
) -> Result<DesktopPluginPlacement, String> {
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .or(window
            .primary_monitor()
            .map_err(|error| error.to_string())?)
        .ok_or_else(|| "no monitor available".to_string())?;
    let position = window.outer_position().map_err(|error| error.to_string())?;
    let size = window.outer_size().map_err(|error| error.to_string())?;
    let (x_ratio, y_ratio) = normalize_desktop_plugin_position(
        position.x,
        position.y,
        size.width,
        size.height,
        desktop_work_area_from_monitor(&monitor),
    );
    Ok(DesktopPluginPlacement {
        monitor_name: monitor.name().cloned(),
        x_ratio,
        y_ratio,
        dock: normalized_dock(dock.as_deref()),
    })
}

fn desktop_plugin_monitor(window: &WebviewWindow) -> Result<tauri::Monitor, String> {
    window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .or(window
            .primary_monitor()
            .map_err(|error| error.to_string())?)
        .ok_or_else(|| "no monitor available".to_string())
}

fn desktop_window_geometry(window: &WebviewWindow) -> Result<DesktopWindowGeometry, String> {
    let position = window.outer_position().map_err(|error| error.to_string())?;
    let size = window.outer_size().map_err(|error| error.to_string())?;
    Ok(DesktopWindowGeometry {
        x: position.x,
        y: position.y,
        width: size.width.max(1),
        height: size.height.max(1),
    })
}

fn desktop_window_anchor(window: &WebviewWindow) -> Result<HorizontalAnchor, String> {
    let monitor = desktop_plugin_monitor(window)?;
    let work_area = monitor.work_area();
    let geometry = desktop_window_geometry(window)?;
    Ok(horizontal_anchor_for_geometry(
        geometry.x,
        geometry.width,
        work_area.position.x,
        work_area.size.width,
    ))
}

fn horizontal_anchor_for_geometry(
    window_x: i32,
    window_width: u32,
    work_x: i32,
    work_width: u32,
) -> HorizontalAnchor {
    let window_center = i64::from(window_x) * 2 + i64::from(window_width);
    let work_center = i64::from(work_x) * 2 + i64::from(work_width);
    if window_center < work_center {
        HorizontalAnchor::Left
    } else {
        HorizontalAnchor::Right
    }
}

fn desktop_plugin_view_mode_target(
    window: &WebviewWindow,
    registration: &DesktopWindowRegistration,
    target_mode: DesktopPluginViewMode,
) -> Result<(DesktopWindowTargetGeometry, DesktopWorkArea), String> {
    let monitor = desktop_plugin_monitor(window)?;
    let work_area = desktop_work_area_from_monitor(&monitor);
    let target = desktop_window_target_geometry(
        desktop_window_geometry(window)?,
        target_mode,
        work_area,
        &registration.spec,
        monitor.scale_factor(),
    );
    Ok((target, work_area))
}

fn desktop_window_target_geometry(
    current_geometry: DesktopWindowGeometry,
    target_mode: DesktopPluginViewMode,
    monitor_work_area: DesktopWorkArea,
    spec: &DesktopWindowSpec,
    scale: f64,
) -> DesktopWindowTargetGeometry {
    let (logical_width, logical_height) = target_mode.logical_size(spec);
    let (requested_width, requested_height) =
        physical_window_size(logical_width, logical_height, scale);
    let target_width = requested_width.min(monitor_work_area.width.max(1));
    let target_height = requested_height.min(monitor_work_area.height.max(1));
    let work_right = i64::from(monitor_work_area.x) + i64::from(monitor_work_area.width);
    let work_bottom = i64::from(monitor_work_area.y) + i64::from(monitor_work_area.height);
    let space_right = (work_right - current_geometry.right()).max(0);
    let space_bottom = (work_bottom - current_geometry.bottom()).max(0);

    // The anchor names describe where the pet remains inside the expanded
    // window. Left means the window grows to the right; right means it grows
    // to the left. The same convention is used by the plugin CSS.
    let anchor = if space_right >= i64::from(target_width) {
        HorizontalAnchor::Left
    } else {
        HorizontalAnchor::Right
    };
    let vertical_anchor = if space_bottom >= i64::from(target_height) {
        VerticalAnchor::Top
    } else {
        VerticalAnchor::Bottom
    };
    let requested_x = match anchor {
        HorizontalAnchor::Left => i64::from(current_geometry.x),
        HorizontalAnchor::Right => current_geometry.right() - i64::from(target_width),
    };
    let requested_y = match vertical_anchor {
        VerticalAnchor::Top => i64::from(current_geometry.y),
        VerticalAnchor::Bottom => current_geometry.bottom() - i64::from(target_height),
    };
    let (x, y) = clamp_desktop_plugin_position(
        requested_x.try_into().unwrap_or(current_geometry.x),
        requested_y.try_into().unwrap_or(current_geometry.y),
        target_width,
        target_height,
        monitor_work_area,
    );

    DesktopWindowTargetGeometry {
        geometry: DesktopWindowGeometry {
            x,
            y,
            width: target_width,
            height: target_height,
        },
        anchor,
        vertical_anchor,
    }
}

fn desktop_window_target_size(
    window: &WebviewWindow,
    spec: &DesktopWindowSpec,
    anchor: HorizontalAnchor,
    expanded: bool,
    requested_width: Option<f64>,
    requested_height: Option<f64>,
) -> Result<(f64, f64), String> {
    if !expanded {
        return Ok((spec.collapsed_width, spec.collapsed_height));
    }
    let monitor = window
        .current_monitor()
        .map_err(|error| error.to_string())?
        .or(window
            .primary_monitor()
            .map_err(|error| error.to_string())?)
        .ok_or_else(|| "no monitor available".to_string())?;
    let work_area = monitor.work_area();
    let position = window.outer_position().map_err(|error| error.to_string())?;
    let size = window.outer_size().map_err(|error| error.to_string())?;
    let scale = window.scale_factor().map_err(|error| error.to_string())?;
    let margin = (spec.margin * scale).round() as i32;
    let work_left = work_area.position.x + margin;
    let work_right = work_area.position.x + work_area.size.width as i32 - margin;
    let work_top = work_area.position.y + margin;
    let old_right = position.x + size.width as i32;
    let old_bottom = position.y + size.height as i32;
    let available_width = match anchor {
        HorizontalAnchor::Left => work_right - position.x,
        HorizontalAnchor::Right => old_right - work_left,
    };
    let available_height = old_bottom - work_top;
    let max_width = (f64::from(available_width.max(1)) / scale).max(spec.collapsed_width);
    let max_height = (f64::from(available_height.max(1)) / scale).max(spec.collapsed_height);
    Ok((
        requested_width
            .unwrap_or(spec.expanded_width)
            .clamp(spec.collapsed_width, max_width),
        requested_height
            .unwrap_or(spec.expanded_height)
            .clamp(spec.collapsed_height, max_height),
    ))
}

fn adaptive_expanded_dimensions(
    window: &WebviewWindow,
    content_width: Option<f64>,
    content_height: Option<f64>,
    viewport_width: Option<f64>,
    viewport_height: Option<f64>,
    minimum_width: f64,
    minimum_height: f64,
) -> Result<(Option<f64>, Option<f64>), String> {
    let size = window.outer_size().map_err(|error| error.to_string())?;
    let scale = window.scale_factor().map_err(|error| error.to_string())?;
    let current_width = f64::from(size.width) / scale;
    let current_height = f64::from(size.height) / scale;
    Ok((
        content_width
            .zip(viewport_width)
            .and_then(|(content, viewport)| {
                scaled_viewport_dimension(current_width, content, viewport, minimum_width)
            }),
        content_height
            .zip(viewport_height)
            .and_then(|(content, viewport)| {
                scaled_viewport_dimension(current_height, content, viewport, minimum_height)
            }),
    ))
}

fn scaled_viewport_dimension(
    current_dimension: f64,
    requested_viewport_dimension: f64,
    current_viewport_dimension: f64,
    minimum_dimension: f64,
) -> Option<f64> {
    if !current_dimension.is_finite()
        || !requested_viewport_dimension.is_finite()
        || !current_viewport_dimension.is_finite()
        || current_dimension <= 0.0
        || requested_viewport_dimension <= 0.0
        || current_viewport_dimension <= 0.0
    {
        return None;
    }
    Some(
        (current_dimension * requested_viewport_dimension / current_viewport_dimension)
            .max(minimum_dimension),
    )
}

fn animate_window_to_geometry(
    window: &WebviewWindow,
    target_geometry: DesktopWindowGeometry,
    monitor_work_area: DesktopWorkArea,
    duration: Duration,
) -> Result<(), String> {
    let start_geometry = desktop_window_geometry(window)?;
    let apply = |progress: f64| -> Result<(), String> {
        let current_width = lerp_u32(start_geometry.width, target_geometry.width, progress);
        let current_height = lerp_u32(start_geometry.height, target_geometry.height, progress);
        let requested_x = lerp_i32(start_geometry.x, target_geometry.x, progress);
        let requested_y = lerp_i32(start_geometry.y, target_geometry.y, progress);
        let (x, y) = clamp_desktop_plugin_position(
            requested_x,
            requested_y,
            current_width,
            current_height,
            monitor_work_area,
        );
        window
            .set_size(tauri::PhysicalSize::new(current_width, current_height))
            .map_err(|error| error.to_string())?;
        window
            .set_position(tauri::PhysicalPosition::new(x, y))
            .map_err(|error| error.to_string())
    };

    if duration.is_zero() {
        return apply(1.0);
    }
    let steps = 14u32;
    let step_duration = duration / steps;
    for step in 1..=steps {
        let linear = f64::from(step) / f64::from(steps);
        let eased = 1.0 - (1.0 - linear).powi(4);
        apply(eased)?;
        if step < steps {
            thread::sleep(step_duration);
        }
    }
    Ok(())
}

fn animate_window_anchored(
    window: &WebviewWindow,
    width: f64,
    height: f64,
    anchor: HorizontalAnchor,
    duration: Duration,
) -> Result<(), String> {
    let start_position = window.outer_position().map_err(|error| error.to_string())?;
    let start_size = window.outer_size().map_err(|error| error.to_string())?;
    let scale = window.scale_factor().map_err(|error| error.to_string())?;
    let target_width = (width * scale).round().max(1.0) as u32;
    let target_height = (height * scale).round().max(1.0) as u32;
    let fixed_x = match anchor {
        HorizontalAnchor::Left => start_position.x,
        HorizontalAnchor::Right => start_position.x + start_size.width as i32,
    };
    let fixed_bottom = start_position.y + start_size.height as i32;

    let apply = |progress: f64| -> Result<(), String> {
        let current_width = lerp_u32(start_size.width, target_width, progress);
        let current_height = lerp_u32(start_size.height, target_height, progress);
        let (x, y) =
            anchored_position(fixed_x, fixed_bottom, current_width, current_height, anchor);
        window
            .set_size(tauri::PhysicalSize::new(current_width, current_height))
            .map_err(|error| error.to_string())?;
        window
            .set_position(tauri::PhysicalPosition::new(x, y))
            .map_err(|error| error.to_string())
    };

    if duration.is_zero() {
        return apply(1.0);
    }
    let steps = 14u32;
    let step_duration = duration / steps;
    for step in 1..=steps {
        let linear = f64::from(step) / f64::from(steps);
        let eased = 1.0 - (1.0 - linear).powi(4);
        apply(eased)?;
        if step < steps {
            thread::sleep(step_duration);
        }
    }
    Ok(())
}

fn lerp_u32(start: u32, end: u32, progress: f64) -> u32 {
    (f64::from(start) + (f64::from(end) - f64::from(start)) * progress)
        .round()
        .max(1.0) as u32
}

fn lerp_i32(start: i32, end: i32, progress: f64) -> i32 {
    (f64::from(start) + (f64::from(end) - f64::from(start)) * progress).round() as i32
}

fn anchored_position(
    fixed_x: i32,
    fixed_bottom: i32,
    width: u32,
    height: u32,
    anchor: HorizontalAnchor,
) -> (i32, i32) {
    let x = match anchor {
        HorizontalAnchor::Left => fixed_x,
        HorizontalAnchor::Right => fixed_x - width as i32,
    };
    (x, fixed_bottom - height as i32)
}

#[cfg(test)]
mod desktop_window_tests {
    use super::{
        anchored_position, checked_desktop_drop_total, clamp_desktop_plugin_position,
        desktop_plugin_dock_zone_for_geometry, desktop_plugin_position_from_placement,
        desktop_window_target_geometry, horizontal_anchor_for_geometry, logical_cursor_position,
        normalize_desktop_plugin_position, normalized_dock, physical_window_size,
        prepare_desktop_drop_paths, saved_monitor_index, scaled_viewport_dimension,
        DesktopPluginPlacement, DesktopPluginViewMode, DesktopWindowGeometry, DesktopWindowSpec,
        DesktopWorkArea, HorizontalAnchor, VerticalAnchor, MAX_DESKTOP_DROP_FILES,
        MAX_DESKTOP_DROP_FILE_BYTES, MAX_DESKTOP_DROP_TOTAL_BYTES,
    };

    #[test]
    fn enforces_desktop_drop_count_and_byte_limits() {
        assert_eq!(
            checked_desktop_drop_total(
                MAX_DESKTOP_DROP_FILES - 1,
                MAX_DESKTOP_DROP_TOTAL_BYTES - 1,
                1,
            ),
            Ok(MAX_DESKTOP_DROP_TOTAL_BYTES)
        );
        assert!(checked_desktop_drop_total(MAX_DESKTOP_DROP_FILES, 0, 0)
            .unwrap_err()
            .contains("最多拖放"));
        assert!(
            checked_desktop_drop_total(0, 0, MAX_DESKTOP_DROP_FILE_BYTES + 1)
                .unwrap_err()
                .contains("单个拖放文件")
        );
        assert!(
            checked_desktop_drop_total(1, MAX_DESKTOP_DROP_TOTAL_BYTES, 1)
                .unwrap_err()
                .contains("总大小")
        );
    }

    #[test]
    fn canonicalizes_and_deduplicates_desktop_drop_paths() {
        let path = std::env::temp_dir().join(format!(
            "lamtools-pet-drop-test-{}-{}.txt",
            std::process::id(),
            super::NEXT_DESKTOP_DROP_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        std::fs::write(&path, b"pet").expect("create desktop drop test file");
        let raw = path.to_string_lossy().into_owned();
        let prepared =
            prepare_desktop_drop_paths(vec![raw.clone(), raw]).expect("prepare desktop drop paths");
        assert_eq!(prepared.len(), 1);
        assert_eq!(prepared[0], std::fs::canonicalize(&path).unwrap());
        std::fs::remove_file(path).expect("remove desktop drop test file");
    }

    #[test]
    fn rejects_directories_in_desktop_file_drops() {
        let error =
            prepare_desktop_drop_paths(vec![std::env::temp_dir().to_string_lossy().into_owned()])
                .unwrap_err();
        assert!(error.contains("仅支持拖放文件"));
    }

    #[test]
    fn maps_physical_desktop_cursor_to_logical_webview_coordinates() {
        assert_eq!(
            logical_cursor_position(1810.0, 910.0, 1600.0, 700.0, 1.5),
            (140.0, 140.0)
        );
        assert_eq!(
            logical_cursor_position(140.0, 230.0, -160.0, -70.0, 2.0),
            (150.0, 150.0)
        );
    }

    #[test]
    fn chooses_inward_expansion_from_each_monitor_half() {
        assert_eq!(
            horizontal_anchor_for_geometry(40, 256, 0, 1920),
            HorizontalAnchor::Left
        );
        assert_eq!(
            horizontal_anchor_for_geometry(1600, 256, 0, 1920),
            HorizontalAnchor::Right
        );
    }

    fn geometry_test_spec() -> DesktopWindowSpec {
        DesktopWindowSpec {
            collapsed_width: 256.0,
            collapsed_height: 288.0,
            expanded_width: 376.0,
            expanded_height: 680.0,
            card_width: 376.0,
            card_height: 360.0,
            margin: 24.0,
        }
    }

    fn geometry_test_work_area() -> DesktopWorkArea {
        DesktopWorkArea {
            x: 0,
            y: 0,
            width: 1920,
            height: 1080,
        }
    }

    #[test]
    fn target_geometry_expands_panel_inward_from_all_four_corners() {
        let spec = geometry_test_spec();
        let work_area = geometry_test_work_area();
        let cases = [
            (
                DesktopWindowGeometry {
                    x: 0,
                    y: 0,
                    width: 256,
                    height: 288,
                },
                DesktopWindowGeometry {
                    x: 0,
                    y: 0,
                    width: 376,
                    height: 680,
                },
                HorizontalAnchor::Left,
                VerticalAnchor::Top,
            ),
            (
                DesktopWindowGeometry {
                    x: 1664,
                    y: 0,
                    width: 256,
                    height: 288,
                },
                DesktopWindowGeometry {
                    x: 1544,
                    y: 0,
                    width: 376,
                    height: 680,
                },
                HorizontalAnchor::Right,
                VerticalAnchor::Top,
            ),
            (
                DesktopWindowGeometry {
                    x: 0,
                    y: 792,
                    width: 256,
                    height: 288,
                },
                DesktopWindowGeometry {
                    x: 0,
                    y: 400,
                    width: 376,
                    height: 680,
                },
                HorizontalAnchor::Left,
                VerticalAnchor::Bottom,
            ),
            (
                DesktopWindowGeometry {
                    x: 1664,
                    y: 792,
                    width: 256,
                    height: 288,
                },
                DesktopWindowGeometry {
                    x: 1544,
                    y: 400,
                    width: 376,
                    height: 680,
                },
                HorizontalAnchor::Right,
                VerticalAnchor::Bottom,
            ),
        ];

        for (current, expected_geometry, expected_anchor, expected_vertical_anchor) in cases {
            let target = desktop_window_target_geometry(
                current,
                DesktopPluginViewMode::Panel,
                work_area,
                &spec,
                1.0,
            );
            assert_eq!(target.geometry, expected_geometry);
            assert_eq!(target.anchor, expected_anchor);
            assert_eq!(target.vertical_anchor, expected_vertical_anchor);
        }
    }

    #[test]
    fn bundled_pet_bottom_left_expansion_keeps_the_full_surface_width() {
        let mut spec = geometry_test_spec();
        spec.card_width = 506.0;
        spec.expanded_width = 506.0;
        let work_area = geometry_test_work_area();
        let bottom_left_pet = DesktopWindowGeometry {
            x: 0,
            y: 792,
            width: 256,
            height: 288,
        };

        let card = desktop_window_target_geometry(
            bottom_left_pet,
            DesktopPluginViewMode::Card,
            work_area,
            &spec,
            1.0,
        );
        assert_eq!(
            card.geometry,
            DesktopWindowGeometry {
                x: 0,
                y: 720,
                width: 506,
                height: 360,
            }
        );
        assert_eq!(card.anchor, HorizontalAnchor::Left);
        assert_eq!(card.vertical_anchor, VerticalAnchor::Bottom);
        assert_eq!(card.geometry.width - 130 - 16, 360);

        let panel = desktop_window_target_geometry(
            bottom_left_pet,
            DesktopPluginViewMode::Panel,
            work_area,
            &spec,
            1.0,
        );
        assert_eq!(
            panel.geometry,
            DesktopWindowGeometry {
                x: 0,
                y: 400,
                width: 506,
                height: 680,
            }
        );
        assert_eq!(panel.anchor, HorizontalAnchor::Left);
        assert_eq!(panel.vertical_anchor, VerticalAnchor::Bottom);
        assert_eq!(panel.geometry.width - 130 - 16, 360);
    }

    #[test]
    fn target_geometry_handles_card_and_panel_transitions_at_center() {
        let spec = geometry_test_spec();
        let work_area = geometry_test_work_area();
        let center_pet = DesktopWindowGeometry {
            x: 832,
            y: 360,
            width: 256,
            height: 288,
        };
        let card = desktop_window_target_geometry(
            center_pet,
            DesktopPluginViewMode::Card,
            work_area,
            &spec,
            1.0,
        );
        assert_eq!(
            card.geometry,
            DesktopWindowGeometry {
                x: 832,
                y: 360,
                width: 376,
                height: 360,
            }
        );
        assert_eq!(card.anchor, HorizontalAnchor::Left);
        assert_eq!(card.vertical_anchor, VerticalAnchor::Top);

        let panel = desktop_window_target_geometry(
            card.geometry,
            DesktopPluginViewMode::Panel,
            work_area,
            &spec,
            1.0,
        );
        assert_eq!(
            panel.geometry,
            DesktopWindowGeometry {
                x: 832,
                y: 40,
                width: 376,
                height: 680,
            }
        );
        assert_eq!(panel.anchor, HorizontalAnchor::Left);
        assert_eq!(panel.vertical_anchor, VerticalAnchor::Bottom);

        let pet = desktop_window_target_geometry(
            panel.geometry,
            DesktopPluginViewMode::Pet,
            work_area,
            &spec,
            1.0,
        );
        assert_eq!(
            pet.geometry,
            DesktopWindowGeometry {
                x: 832,
                y: 40,
                width: 256,
                height: 288,
            }
        );
        assert_eq!(pet.anchor, HorizontalAnchor::Left);
        assert_eq!(pet.vertical_anchor, VerticalAnchor::Top);
    }

    #[test]
    fn parses_all_view_modes_and_uses_their_dimensions() {
        let spec = geometry_test_spec();
        assert_eq!(
            DesktopPluginViewMode::parse("pet"),
            Some(DesktopPluginViewMode::Pet)
        );
        assert_eq!(
            DesktopPluginViewMode::parse("card"),
            Some(DesktopPluginViewMode::Card)
        );
        assert_eq!(
            DesktopPluginViewMode::parse("panel"),
            Some(DesktopPluginViewMode::Panel)
        );
        assert_eq!(DesktopPluginViewMode::parse("unknown"), None);
        assert_eq!(
            DesktopPluginViewMode::Pet.logical_size(&spec),
            (256.0, 288.0)
        );
        assert_eq!(
            DesktopPluginViewMode::Card.logical_size(&spec),
            (376.0, 360.0)
        );
        assert_eq!(
            DesktopPluginViewMode::Panel.logical_size(&spec),
            (376.0, 680.0)
        );
    }

    #[test]
    fn target_geometry_clamps_card_and_panel_to_a_small_work_area() {
        let current = DesktopWindowGeometry {
            x: 0,
            y: 0,
            width: 96,
            height: 96,
        };
        let work_area = DesktopWorkArea {
            x: -100,
            y: -50,
            width: 300,
            height: 200,
        };
        let target = desktop_window_target_geometry(
            current,
            DesktopPluginViewMode::Panel,
            work_area,
            &geometry_test_spec(),
            1.0,
        );
        assert_eq!(
            target.geometry,
            DesktopWindowGeometry {
                x: -100,
                y: -50,
                width: 300,
                height: 200,
            }
        );
        assert_eq!(target.anchor, HorizontalAnchor::Right);
        assert_eq!(target.vertical_anchor, VerticalAnchor::Bottom);
    }

    #[test]
    fn expansion_preserves_bottom_left_anchor() {
        assert_eq!(
            anchored_position(24, 1040, 440, 680, HorizontalAnchor::Left),
            (24, 360)
        );
    }

    #[test]
    fn expansion_preserves_bottom_right_anchor() {
        assert_eq!(
            anchored_position(1896, 1040, 440, 680, HorizontalAnchor::Right),
            (1456, 360)
        );
    }

    #[test]
    fn adaptive_dimension_scales_from_the_rendered_viewport() {
        assert_eq!(
            scaled_viewport_dimension(680.0, 320.0, 460.0, 288.0),
            Some(473.04347826086956)
        );
        assert_eq!(
            scaled_viewport_dimension(680.0, 120.0, 460.0, 288.0),
            Some(288.0)
        );
        assert_eq!(scaled_viewport_dimension(680.0, 320.0, 0.0, 288.0), None);
    }

    #[test]
    fn normalizes_window_position_against_work_area_travel() {
        let work_area = DesktopWorkArea {
            x: -1920,
            y: 40,
            width: 1920,
            height: 1040,
        };
        assert_eq!(
            normalize_desktop_plugin_position(-1920, 40, 256, 288, work_area),
            (0.0, 0.0)
        );
        assert_eq!(
            normalize_desktop_plugin_position(-256, 792, 256, 288, work_area),
            (1.0, 1.0)
        );
        assert_eq!(
            normalize_desktop_plugin_position(-1088, 416, 256, 288, work_area),
            (0.5, 0.5)
        );
    }

    #[test]
    fn restores_and_clamps_normalized_position() {
        let work_area = DesktopWorkArea {
            x: 100,
            y: -200,
            width: 1600,
            height: 1200,
        };
        let placement = DesktopPluginPlacement {
            monitor_name: Some("Display 1".to_string()),
            x_ratio: 1.5,
            y_ratio: -0.5,
            dock: None,
        };
        assert_eq!(
            desktop_plugin_position_from_placement(&placement, 400, 300, work_area),
            (1300, -200)
        );
        assert_eq!(
            clamp_desktop_plugin_position(9999, -9999, 400, 300, work_area),
            (1300, -200)
        );
    }

    #[test]
    fn detects_only_left_and_right_dock_zones_within_threshold() {
        let work_area = DesktopWorkArea {
            x: 100,
            y: 50,
            width: 1600,
            height: 900,
        };
        assert_eq!(
            desktop_plugin_dock_zone_for_geometry(
                DesktopWindowGeometry {
                    x: 100,
                    y: 200,
                    width: 256,
                    height: 288,
                },
                work_area,
            ),
            Some("left")
        );
        assert_eq!(
            desktop_plugin_dock_zone_for_geometry(
                DesktopWindowGeometry {
                    x: 1460,
                    y: 200,
                    width: 240,
                    height: 288,
                },
                work_area,
            ),
            Some("right")
        );
        assert_eq!(
            desktop_plugin_dock_zone_for_geometry(
                DesktopWindowGeometry {
                    x: 500,
                    y: 200,
                    width: 256,
                    height: 288,
                },
                work_area,
            ),
            None
        );
    }

    #[test]
    fn dock_zone_uses_the_threshold_boundary() {
        let work_area = DesktopWorkArea {
            x: 100,
            y: 50,
            width: 1600,
            height: 900,
        };
        let left_at_boundary = DesktopWindowGeometry {
            x: 140,
            y: 200,
            width: 256,
            height: 288,
        };
        let left_outside_boundary = DesktopWindowGeometry {
            x: 141,
            ..left_at_boundary
        };
        assert_eq!(
            desktop_plugin_dock_zone_for_geometry(left_at_boundary, work_area),
            Some("left")
        );
        assert_eq!(
            desktop_plugin_dock_zone_for_geometry(left_outside_boundary, work_area),
            None
        );

        let right_at_boundary = DesktopWindowGeometry {
            x: 1404,
            y: 200,
            width: 256,
            height: 288,
        };
        let right_outside_boundary = DesktopWindowGeometry {
            x: 1403,
            ..right_at_boundary
        };
        assert_eq!(
            desktop_plugin_dock_zone_for_geometry(right_at_boundary, work_area),
            Some("right")
        );
        assert_eq!(
            desktop_plugin_dock_zone_for_geometry(right_outside_boundary, work_area),
            None
        );
    }

    #[test]
    fn docked_placement_restores_to_the_selected_edge_and_keeps_y_ratio() {
        let work_area = DesktopWorkArea {
            x: 100,
            y: -200,
            width: 1600,
            height: 1200,
        };
        let left = DesktopPluginPlacement {
            monitor_name: Some("Display 1".to_string()),
            x_ratio: 0.75,
            y_ratio: 0.5,
            dock: Some("left".to_string()),
        };
        let right = DesktopPluginPlacement {
            dock: Some("right".to_string()),
            ..left.clone()
        };
        assert_eq!(
            desktop_plugin_position_from_placement(&left, 400, 300, work_area),
            (100, 250)
        );
        assert_eq!(
            desktop_plugin_position_from_placement(&right, 400, 300, work_area),
            (1300, 250)
        );
    }

    #[test]
    fn invalid_dock_values_are_discarded_while_legacy_placement_stays_valid() {
        assert_eq!(normalized_dock(Some(" LEFT ")), Some("left".to_string()));
        assert_eq!(normalized_dock(Some("center")), None);
        let legacy = DesktopPluginPlacement {
            monitor_name: None,
            x_ratio: 0.25,
            y_ratio: 0.75,
            dock: None,
        };
        assert_eq!(legacy.sanitized().dock, None);
    }

    #[test]
    fn sanitizes_monitor_name_ratios_and_dock_together() {
        let placement = DesktopPluginPlacement {
            monitor_name: Some(" Display 2 ".to_string()),
            x_ratio: f64::NAN,
            y_ratio: -0.5,
            dock: Some(" RIGHT ".to_string()),
        };
        let sanitized = placement.sanitized();
        assert_eq!(sanitized.monitor_name.as_deref(), Some("Display 2"));
        assert_eq!(sanitized.x_ratio, 1.0);
        assert_eq!(sanitized.y_ratio, 0.0);
        assert_eq!(sanitized.dock.as_deref(), Some("right"));
    }

    #[test]
    fn oversized_window_position_is_clamped_to_work_area_origin() {
        let placement = DesktopPluginPlacement {
            monitor_name: None,
            x_ratio: 0.5,
            y_ratio: 0.5,
            dock: None,
        };
        let work_area = DesktopWorkArea {
            x: -100,
            y: -50,
            width: 300,
            height: 200,
        };
        assert_eq!(
            desktop_plugin_position_from_placement(&placement, 400, 300, work_area),
            (-100, -50)
        );
    }

    #[test]
    fn missing_saved_monitor_name_uses_fallback_index() {
        let monitors = vec![Some("Primary".to_string()), Some("External".to_string())];
        assert_eq!(saved_monitor_index(&monitors, Some("External")), Some(1));
        assert_eq!(saved_monitor_index(&monitors, Some("Disconnected")), None);
        assert_eq!(saved_monitor_index(&monitors, None), None);
    }

    #[test]
    fn physical_size_respects_monitor_scale_factor() {
        assert_eq!(physical_window_size(256.0, 288.0, 1.25), (320, 360));
        assert_eq!(physical_window_size(256.0, 288.0, 1.5), (384, 432));
    }
}

fn reveal_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg(windows)]
fn hide_console(cmd: &mut Command) {
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn hide_console(_cmd: &mut Command) {}
