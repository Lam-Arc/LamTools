// user:“内置浏览器、内置文本编辑器、内置文件树”+(桌面原生宿主独立实现，网页不依赖 iframe，文件写入检查外部修改)。
use serde::{Deserialize, Serialize};
use std::{fs, io::Write, path::{Path, PathBuf}};
use tauri::{Emitter, Manager};

const MAX_TEXT_BYTES: u64 = 4 * 1024 * 1024;
fn scoped_root(root: &str) -> Result<PathBuf, String> {
    #[cfg(windows)]
    let root = root.replace('/', "\\");
    #[cfg(windows)]
    let root = root.as_str();
    fs::canonicalize(root).map_err(|e| format!("项目目录无法访问：{e}"))
}
fn scoped_path_in(root: &Path, path: &str) -> Result<PathBuf, String> {
    #[cfg(windows)]
    let path = path.replace('/', "\\");
    #[cfg(windows)]
    let path = path.as_str();
    let candidate = if Path::new(path).is_absolute() { PathBuf::from(path) } else { root.join(path) };
    let resolved = if candidate.exists() { fs::canonicalize(&candidate) } else {
        let parent = candidate.parent().ok_or("文件路径无效")?;
        fs::canonicalize(parent).map(|p| p.join(candidate.file_name().unwrap_or_default()))
    }.map_err(|e| format!("路径无法访问：{e}"))?;
    if !resolved.starts_with(root) { return Err("只能访问当前项目目录内的文件".into()); }
    Ok(resolved)
}
fn scoped_path(root: &str, path: &str) -> Result<PathBuf, String> {
    // user:“路径无法访问：文件名、目录名或卷标语法不正确”+(Windows 长路径前缀要求反斜杠；在权限校验前还原前端统一的分隔符)。
    scoped_path_in(&scoped_root(root)?, path)
}
fn read_text(path: &Path) -> Result<String, String> {
    let meta = fs::metadata(path).map_err(|e| e.to_string())?;
    if !meta.is_file() || meta.len() > MAX_TEXT_BYTES { return Err("只能编辑 4 MB 以内的文本文件".into()); }
    let bytes = fs::read(path).map_err(|e| e.to_string())?;
    if bytes.contains(&0) { return Err("这个文件不是文本文件".into()); }
    String::from_utf8(bytes).map_err(|_| "文件不是 UTF-8 文本，请用默认应用打开".into())
}
fn write_text(path: &Path, content: &str, original: Option<&str>) -> Result<(), String> {
    if content.len() as u64 > MAX_TEXT_BYTES { return Err("文本超过 4 MB，未保存".into()); }
    if path.exists() {
        if original != Some(read_text(path)?.as_str()) { return Err("文件已被其他程序修改，请重新打开后合并内容；当前草稿已保留".into()); }
    } else if original.is_some() { return Err("原文件已被删除；当前草稿已保留".into()); }
    let suffix = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map_err(|e| e.to_string())?.as_nanos();
    let tmp = path.with_file_name(format!(".split-{}-{suffix}.tmp", std::process::id()));
    let result = (|| {
        let mut file = fs::OpenOptions::new().write(true).create_new(true).open(&tmp).map_err(|e| e.to_string())?;
        file.write_all(content.as_bytes()).and_then(|_| file.sync_all()).map_err(|e| e.to_string())?;
        // Check again before replacement, so changes during the write are not silently overwritten.
        if path.exists() && original != Some(read_text(path)?.as_str()) { return Err("文件在保存期间发生变化；当前草稿已保留".into()); }
        fs::rename(&tmp, path).map_err(|e| e.to_string())
    })();
    if result.is_err() { let _ = fs::remove_file(&tmp); }
    result
}
fn require_main(view: &tauri::Webview) -> Result<(), String> { if view.label() == "main" { Ok(()) } else { Err("此操作仅供主工作区使用".into()) } }
#[derive(Serialize)]
pub struct FileEntry { name: String, path: String, directory: bool }
#[tauri::command]
pub async fn split_file_read(webview: tauri::Webview, root: String, path: String) -> Result<String, String> {
    require_main(&webview)?;
    tauri::async_runtime::spawn_blocking(move || read_text(&scoped_path(&root, &path)?)).await.map_err(|e| e.to_string())?
}
#[tauri::command]
pub async fn split_file_write(webview: tauri::Webview, root: String, path: String, content: String, original: Option<String>) -> Result<(), String> {
    require_main(&webview)?;
    tauri::async_runtime::spawn_blocking(move || write_text(&scoped_path(&root, &path)?, &content, original.as_deref())).await.map_err(|e| e.to_string())?
}
#[tauri::command]
pub async fn split_file_list(webview: tauri::Webview, root: String, path: String) -> Result<Vec<FileEntry>, String> {
    require_main(&webview)?;
    tauri::async_runtime::spawn_blocking(move || {
        // user:“审查分屏代码，并优化”+(列出大目录时项目根只规范化一次，避免每个条目都重复解析同一个路径)。
        let root = scoped_root(&root)?;
        let path = scoped_path_in(&root, &path)?;
        let mut entries = Vec::new();
        for entry in fs::read_dir(path).map_err(|e| e.to_string())?.take(5000) {
            let entry = entry.map_err(|e| e.to_string())?;
            // Do not follow directory links outside the workspace.
            let Ok(resolved) = scoped_path_in(&root, &entry.path().to_string_lossy()) else { continue };
            entries.push(FileEntry { name: entry.file_name().to_string_lossy().to_string(), path: resolved.to_string_lossy().to_string(), directory: resolved.is_dir() });
        }
        entries.sort_by(|a, b| b.directory.cmp(&a.directory).then(a.name.to_lowercase().cmp(&b.name.to_lowercase())));
        Ok(entries)
    }).await.map_err(|e| e.to_string())?
}

#[derive(Deserialize)]
pub struct BrowserRequest { id: String, action: String, url: Option<String>, x: Option<f64>, y: Option<f64>, width: Option<f64>, height: Option<f64>, visible: Option<bool> }
#[derive(Clone, Serialize)]
struct BrowserEvent { id: String, url: String, loading: bool }
fn web_url(raw: &str) -> Result<url::Url, String> {
    let url = url::Url::parse(raw).map_err(|_| "请输入完整网页地址")?;
    if !matches!(url.scheme(), "http" | "https") || url.host_str().is_none() { return Err("仅支持 HTTP 或 HTTPS 网页".into()); }
    Ok(url)
}
#[tauri::command]
pub async fn split_browser(app: tauri::AppHandle, webview: tauri::Webview, request: BrowserRequest) -> Result<(), String> {
    require_main(&webview)?;
    if request.id.len() > 100 || !request.id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-') { return Err("无效的浏览器标签".into()); }
    let label = format!("split-browser-{}", request.id);
    let existing = app.get_webview(&label);
    if request.action == "close" { if let Some(view) = existing { view.close().map_err(|e| e.to_string())?; } return Ok(()); }
    if request.action == "create" && existing.is_none() {
        let url = web_url(request.url.as_deref().unwrap_or("https://example.com"))?;
        let id = request.id.clone(); let events = app.clone();
        let builder = tauri::webview::WebviewBuilder::new(label, tauri::WebviewUrl::External(url))
            .on_navigation(|url| matches!(url.scheme(), "http" | "https"))
            .on_page_load(move |view, payload| {
                let _ = events.emit_to("main", "lamtools://split-browser", BrowserEvent { id: id.clone(), url: view.url().map(|u| u.to_string()).unwrap_or_default(), loading: matches!(payload.event(), tauri::webview::PageLoadEvent::Started) });
            });
        webview.window().add_child(builder, tauri::LogicalPosition::new(request.x.unwrap_or(0.), request.y.unwrap_or(0.)), tauri::LogicalSize::new(request.width.unwrap_or(320.).max(1.), request.height.unwrap_or(240.).max(1.))).map_err(|e| e.to_string())?;
    }
    let view = app.get_webview(&format!("split-browser-{}", request.id)).ok_or("网页尚未打开")?;
    match request.action.as_str() {
        "create" | "bounds" => {
            let values = [request.x.unwrap_or(0.), request.y.unwrap_or(0.), request.width.unwrap_or(1.), request.height.unwrap_or(1.)];
            if !values.iter().all(|v| v.is_finite() && *v >= 0.) { return Err("无效的网页区域".into()); }
            view.set_position(tauri::LogicalPosition::new(values[0], values[1])).map_err(|e| e.to_string())?;
            view.set_size(tauri::LogicalSize::new(values[2].max(1.), values[3].max(1.))).map_err(|e| e.to_string())?;
            if request.visible.unwrap_or(true) { view.show() } else { view.hide() }.map_err(|e| e.to_string())?;
        }
        "navigate" => view.navigate(web_url(request.url.as_deref().unwrap_or_default())?).map_err(|e| e.to_string())?,
        "back" => view.eval("history.back()").map_err(|e| e.to_string())?,
        "forward" => view.eval("history.forward()").map_err(|e| e.to_string())?,
        "reload" => view.reload().map_err(|e| e.to_string())?,
        _ => return Err("未知的浏览器操作".into()),
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    // user:“路径无法访问：文件名、目录名或卷标语法不正确”+(验证文件树路径经前端斜杠规范化后仍能访问，且不能逃离项目)。
    #[cfg(windows)]
    #[test]
    fn split_pane_windows_namespace_paths_round_trip() {
        let base = std::env::temp_dir().join(format!("lam-split-path-{}", std::process::id()));
        fs::create_dir_all(&base).unwrap();
        let file = base.join("中文 note.txt");
        fs::write(&file, "before").unwrap();
        let root = fs::canonicalize(&base).unwrap().to_string_lossy().replace('\\', "/");
        let path = fs::canonicalize(&file).unwrap().to_string_lossy().replace('\\', "/");
        let resolved = scoped_path(&root, &path).unwrap();
        assert_eq!(read_text(&resolved).unwrap(), "before");
        write_text(&resolved, "after", Some("before")).unwrap();
        assert_eq!(read_text(&resolved).unwrap(), "after");
        assert!(scoped_path(&root, "../outside.txt").is_err());
        fs::remove_file(file).unwrap();
        fs::remove_dir(base).unwrap();
    }
    #[test]
    fn split_pane_scope_and_optimistic_save() {
        let base = std::env::temp_dir().join(format!("lam-split-test-{}", std::process::id()));
        fs::create_dir_all(&base).unwrap();
        let root = base.to_string_lossy();
        assert!(scoped_path(&root, "../escape.txt").is_err());
        let path = base.join("draft.txt");
        write_text(&path, "first", None).unwrap();
        assert!(write_text(&path, "overwrite", None).is_err());
        assert!(write_text(&path, "overwrite", Some("stale")).is_err());
        assert_eq!(read_text(&path).unwrap(), "first");
        write_text(&path, "second", Some("first")).unwrap();
        assert_eq!(read_text(&path).unwrap(), "second");
        fs::remove_file(path).unwrap(); fs::remove_dir(base).unwrap();
    }
    #[test]
    fn split_pane_browser_rejects_non_web_navigation() {
        for raw in ["file:///C:/Windows", "javascript:alert(1)", "data:text/html,x", "https://"] { assert!(web_url(raw).is_err()); }
        assert!(web_url("https://example.com/docs").is_ok());
    }
}
