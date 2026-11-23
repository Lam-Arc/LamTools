// user:“内置浏览器、内置文本编辑器、内置文件树”+(这一层只剩文件能力：文件树与文本读写；浏览器宿主已迁到 browser/ 模块，不做两套)。
use serde::Serialize;
use std::{fs, io::Write, path::{Path, PathBuf}};

const MAX_TEXT_BYTES: u64 = 4 * 1024 * 1024;

// user:“require_main 提升为公共函数”+(浏览器与文件能力共用同一条主窗口校验，不在两个文件里各写一份)。
fn require_main(view: &tauri::Webview) -> Result<(), String> {
    crate::browser::url_policy::require_main(view).map_err(|error| error.message)
}

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
}
