use crate::{
    DeviceCapabilities, RuntimeError, ToolCall, ToolDefinition, ToolPermission, ToolRuntime,
};
use async_trait::async_trait;
use serde_json::{json, Value};
use std::path::{Component, Path, PathBuf};
use tokio::io::AsyncWriteExt;

pub struct ProjectFileTools {
    root: PathBuf,
}

impl ProjectFileTools {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    fn resolve(&self, value: &Value) -> Result<PathBuf, RuntimeError> {
        let relative = value.as_str().unwrap_or_default();
        let path = Path::new(relative);
        // `C:notes.md` 既不是绝对路径也没有 `..`，但 `PathBuf::push` 遇到带盘符
        // 前缀的值会替换整个基路径，于是目标落在项目根之外（2026-09-25 审计 P3）。
        // 只接受普通组件：绝对路径、盘符前缀、根目录一律拒绝。
        let mut components = path.components();
        // `.`（项目根）与普通名字可以，盘符/根目录前缀不行。
        let normal_first = matches!(
            components.next(),
            Some(Component::Normal(_)) | Some(Component::CurDir)
        );
        if relative.is_empty()
            || path.is_absolute()
            || !normal_first
            || path
                .components()
                .any(|part| matches!(part, Component::ParentDir))
        {
            return Err(RuntimeError::Tool(
                "path must stay inside the current project".into(),
            ));
        }
        let mut resolved = self.root.clone();
        for component in path.components() {
            resolved.push(component);
            match std::fs::symlink_metadata(&resolved) {
                Ok(metadata) if metadata.file_type().is_symlink() => {
                    return Err(RuntimeError::Tool(
                        "project path cannot follow a symbolic link".into(),
                    ))
                }
                Ok(_) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => break,
                Err(error) => return Err(RuntimeError::Tool(error.to_string())),
            }
        }
        Ok(self.root.join(path))
    }
}

#[async_trait]
impl ToolRuntime for ProjectFileTools {
    fn definitions(&self, capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        if !capabilities.project_files {
            return Vec::new();
        }
        vec![
            ToolDefinition {
                name: "list_dir".into(),
                description: "List files in the current project. The result includes the absolute project_root path; on Android this directory is app-private and cannot be browsed in the Android Files app. Omit path, pass an empty path, or use '.' to list the project root; pass a relative path to list a subdirectory.".into(),
                input_schema: json!({"type":"object","properties":{"path":{"type":"string","description":"Optional directory path relative to the current project. Omit it, use an empty string, or use '.' for the project root."}}}),
            },
            ToolDefinition {
                name: "search_files".into(),
                description: "Find files by glob pattern within the current project. Supports *, ** and ? in a relative pattern such as 'src/**/*.rs'.".into(),
                input_schema: json!({"type":"object","additionalProperties":false,"properties":{"pattern":{"type":"string","description":"Glob pattern"},"path":{"type":"string","description":"Optional directory to search from"}},"required":["pattern"]}),
            },
            ToolDefinition {
                name: "search_content".into(),
                description: "Search file contents for a literal text pattern within the current project. Returns matching lines with their file and line number.".into(),
                input_schema: json!({"type":"object","additionalProperties":false,"properties":{"pattern":{"type":"string","description":"Literal text pattern"},"path":{"type":"string","description":"Optional file or directory to search"}},"required":["pattern"]}),
            },
            ToolDefinition {
                name: "edit_file".into(),
                description: "Replace one exact UTF-8 text segment in an existing file. Matching is case-sensitive and preserves surrounding whitespace and line endings. The match must be unique unless occurrence or before_context/after_context selects one.".into(),
                input_schema: json!({"type":"object","additionalProperties":false,"properties":{
                    "path":{"type":"string","description":"File path relative to the current project"},
                    "old_string":{"type":"string","description":"Exact text to replace"},
                    "new_string":{"type":"string","description":"Replacement text"},
                    "expected_file_hash":{"type":["string","null"],"description":"Expected full-file sha256:... hash, or null for no check"},
                    "occurrence":{"type":["integer","null"],"description":"Optional 1-based occurrence after context filtering"},
                    "before_context":{"type":["string","null"],"description":"Exact text immediately before old_string, or null"},
                    "after_context":{"type":["string","null"],"description":"Exact text immediately after old_string, or null"}
                },"required":["path","old_string","new_string"]}),
            },
            ToolDefinition {
                name: "read_file".into(),
                description: "Read a UTF-8 project file".into(),
                input_schema: json!({"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}),
            },
            ToolDefinition {
                name: "write_file".into(),
                description: "Create or overwrite a UTF-8 project file".into(),
                input_schema: json!({"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}),
            },
        ]
    }

    fn permission(&self, call: &ToolCall) -> ToolPermission {
        match call.name.as_str() {
            "list_dir" | "read_file" => ToolPermission::AutoAllow,
            "write_file" | "edit_file" => ToolPermission::AskUser,
            // Reading the project the user already opened needs no approval,
            // matching the desktop host.
            "search_files" | "search_content" => ToolPermission::AutoAllow,
            _ => ToolPermission::HardBlock,
        }
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        match call.name.as_str() {
            "write_file" => {
                let path = self.resolve(&call.arguments["path"])?;
                if let Some(parent) = path.parent() {
                    tokio::fs::create_dir_all(parent)
                        .await
                        .map_err(tool_error)?;
                }
                let content = call.arguments["content"].as_str().unwrap_or_default();
                write_atomic(&path, content.as_bytes())
                    .await
                    .map_err(tool_error)?;
                Ok(json!({"ok":true,"path":call.arguments["path"],"bytes":content.len()}))
            }
            "read_file" => {
                let path = self.resolve(&call.arguments["path"])?;
                let content = tokio::fs::read_to_string(path).await.map_err(tool_error)?;
                // 一个日志/压缩文件不该把整份内容送进模型与历史：与桌面同为
                // 50,000 字符 + 同一截断标记（2026-09-25 审计 P2）。
                let truncated = content.chars().count() > MAX_READ_CHARS;
                let content = if truncated {
                    let cut: String = content.chars().take(MAX_READ_CHARS).collect();
                    format!("{cut}{TRUNCATED_MARKER}")
                } else {
                    content
                };
                Ok(json!({"ok":true,"path":call.arguments["path"],"content":content,"truncated":truncated}))
            }
            "list_dir" => {
                let relative = call
                    .arguments
                    .get("path")
                    .and_then(Value::as_str)
                    .filter(|path| !path.is_empty())
                    .unwrap_or(".");
                let relative = json!(relative);
                let path = self.resolve(&relative)?;
                let mut entries = tokio::fs::read_dir(path).await.map_err(tool_error)?;
                let mut names = Vec::new();
                while let Some(entry) = entries.next_entry().await.map_err(tool_error)? {
                    names.push(entry.file_name().to_string_lossy().to_string());
                }
                names.sort();
                // 与桌面同为 100 条上限，并回报总数（2026-09-25 审计 P2）。
                let total = names.len();
                let truncated = total > MAX_DIR_ENTRIES;
                names.truncate(MAX_DIR_ENTRIES);
                let project_root =
                    std::fs::canonicalize(&self.root).unwrap_or_else(|_| self.root.clone());
                Ok(
                    json!({"ok":true,"path":relative,"project_root":project_root.to_string_lossy().to_string(),"entries":names,"total":total,"truncated":truncated}),
                )
            }
            "search_files" => {
                let pattern = call.arguments["pattern"]
                    .as_str()
                    .unwrap_or_default()
                    .trim()
                    .to_owned();
                if pattern.is_empty() {
                    return Err(RuntimeError::Tool("Missing 'pattern' argument".into()));
                }
                let from = call
                    .arguments
                    .get("path")
                    .and_then(Value::as_str)
                    .unwrap_or(".");
                let root = self.resolve(&json!(from))?;
                let matches = search_files(&root, &self.root, &pattern);
                Ok(json!({"ok":true,"pattern":pattern,"count":matches.len(),"matches":matches}))
            }
            "search_content" => {
                let pattern = call.arguments["pattern"]
                    .as_str()
                    .unwrap_or_default()
                    .to_owned();
                if pattern.is_empty() {
                    return Err(RuntimeError::Tool("Missing 'pattern' argument".into()));
                }
                let from = call
                    .arguments
                    .get("path")
                    .and_then(Value::as_str)
                    .unwrap_or(".");
                let root = self.resolve(&json!(from))?;
                let matches = search_content(&root, &self.root, &pattern);
                Ok(json!({"ok":true,"pattern":pattern,"count":matches.len(),"matches":matches}))
            }
            "edit_file" => edit_file(&self.root, &self.resolve(&call.arguments["path"])?, &call.arguments),
            _ => Err(RuntimeError::Tool(format!("unknown tool: {}", call.name))),
        }
    }
}

/// Bound the work a single search may do, so a large project cannot turn a
/// tool call into an unbounded scan.
///
/// Aligned with the desktop's `DEFAULT_MAX_SEARCH_RESULTS` (2026-09-25 审计 P2:
/// 200 here vs 50 there meant the same question returned different answers).
const MAX_SEARCH_MATCHES: usize = 50;
/// Aligned with the desktop's `DEFAULT_MAX_LIST_ITEMS`.
const MAX_DIR_ENTRIES: usize = 100;
/// Aligned with the desktop's `DEFAULT_MAX_TEXT_LENGTH`.
const MAX_READ_CHARS: usize = 50_000;
/// Same marker the desktop appends when it cuts a file short.
const TRUNCATED_MARKER: &str = "
[... truncated]";
const MAX_SEARCH_FILE_BYTES: u64 = 2 * 1024 * 1024;
const MAX_FILE_HASH_BYTES: u64 = 8 * 1024 * 1024;

/// Match one path segment against a glob segment (`*` and `?`).
fn glob_segment_matches(pattern: &str, name: &str) -> bool {
    let pattern = pattern.as_bytes();
    let name = name.as_bytes();
    let (mut p, mut n, mut star, mut backtrack) = (0usize, 0usize, None::<usize>, 0usize);
    while n < name.len() {
        if p < pattern.len() && (pattern[p] == b'?' || pattern[p] == name[n]) {
            p += 1;
            n += 1;
        } else if p < pattern.len() && pattern[p] == b'*' {
            star = Some(p);
            backtrack = n;
            p += 1;
        } else if let Some(star_at) = star {
            p = star_at + 1;
            backtrack += 1;
            n = backtrack;
        } else {
            return false;
        }
    }
    while p < pattern.len() && pattern[p] == b'*' {
        p += 1;
    }
    p == pattern.len()
}

/// Match a relative path against a glob pattern, where `**` spans directories.
fn glob_matches(pattern: &str, relative: &str) -> bool {
    fn walk(pattern: &[&str], path: &[&str]) -> bool {
        match pattern.split_first() {
            None => path.is_empty(),
            Some((segment, rest)) if *segment == "**" => {
                walk(rest, path) || (!path.is_empty() && walk(pattern, &path[1..]))
            }
            Some((segment, rest)) => match path.split_first() {
                Some((name, path_rest)) => glob_segment_matches(segment, name) && walk(rest, path_rest),
                None => false,
            },
        }
    }
    let pattern_parts: Vec<&str> = pattern.split('/').filter(|part| !part.is_empty()).collect();
    let path_parts: Vec<&str> = relative.split('/').filter(|part| !part.is_empty()).collect();
    walk(&pattern_parts, &path_parts)
}

fn project_relative(path: &Path, root: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}

/// Depth-first walk that never follows symlinks and skips build/VCS noise.
fn walk_files(dir: &Path, out: &mut Vec<std::path::PathBuf>) {
    if out.len() >= MAX_SEARCH_MATCHES * 4 {
        return;
    }
    let Ok(entries) = std::fs::read_dir(dir) else {
        return;
    };
    let mut paths: Vec<std::path::PathBuf> = entries.flatten().map(|entry| entry.path()).collect();
    paths.sort();
    for path in paths {
        let Ok(metadata) = std::fs::symlink_metadata(&path) else {
            continue;
        };
        if metadata.file_type().is_symlink() {
            continue;
        }
        if metadata.is_dir() {
            let name = path.file_name().and_then(|name| name.to_str()).unwrap_or_default();
            if matches!(name, "node_modules" | ".git" | "target" | "__pycache__" | ".lam") {
                continue;
            }
            walk_files(&path, out);
        } else if metadata.is_file() {
            out.push(path);
        }
    }
}

fn collect_candidates(from: &Path) -> Vec<std::path::PathBuf> {
    let mut files = Vec::new();
    if from.is_file() {
        files.push(from.to_path_buf());
    } else {
        walk_files(from, &mut files);
    }
    files
}

fn search_files(from: &Path, root: &Path, pattern: &str) -> Vec<Value> {
    collect_candidates(from)
        .into_iter()
        .map(|path| project_relative(&path, root))
        // 与桌面同语义：整条相对路径匹配，或者文件名本身匹配（Python 的
        // `Path(rel).match(p) or Path(name).match(p)` 是右对齐的，所以
        // `*.rs` 必须能命中 `src/main.rs`）——2026-09-25 审计 P2。
        .filter(|relative| {
            glob_matches(pattern, relative)
                || relative
                    .rsplit('/')
                    .next()
                    .is_some_and(|name| glob_matches(pattern, name))
        })
        .take(MAX_SEARCH_MATCHES)
        .map(Value::String)
        .collect()
}

fn search_content(from: &Path, root: &Path, pattern: &str) -> Vec<Value> {
    let mut matches = Vec::new();
    for path in collect_candidates(from) {
        if matches.len() >= MAX_SEARCH_MATCHES {
            break;
        }
        let Ok(metadata) = std::fs::metadata(&path) else {
            continue;
        };
        if metadata.len() > MAX_SEARCH_FILE_BYTES {
            continue;
        }
        // A non-UTF-8 file is data, not a searchable text source.
        let Ok(text) = std::fs::read_to_string(&path) else {
            continue;
        };
        let relative = project_relative(&path, root);
        for (index, line) in text.lines().enumerate() {
            if matches.len() >= MAX_SEARCH_MATCHES {
                break;
            }
            if line.contains(pattern) {
                matches.push(json!({
                    "path": relative,
                    "line": index + 1,
                    "text": line.chars().take(400).collect::<String>(),
                }));
            }
        }
    }
    matches
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

/// Replace one exact segment, refusing an ambiguous or unexpected edit.
///
/// The desktop contract: matching is case-sensitive and byte-exact, the match
/// must be unique unless `occurrence` or the surrounding context selects one,
/// and the optional hashes guard against editing a file that changed since the
/// caller read it.
fn edit_file(root: &Path, path: &Path, arguments: &Value) -> Result<Value, RuntimeError> {
    let old_string = arguments["old_string"].as_str().unwrap_or_default();
    if old_string.is_empty() {
        return Err(RuntimeError::Tool(
            "old_string must not be empty; use write_file to create a file".into(),
        ));
    }
    let new_string = arguments["new_string"].as_str().unwrap_or_default();
    let metadata = std::fs::metadata(path).map_err(|_| {
        RuntimeError::Tool("file does not exist; use write_file to create it".into())
    })?;
    if metadata.len() > MAX_FILE_HASH_BYTES {
        return Err(RuntimeError::Tool(format!(
            "file is larger than the {MAX_FILE_HASH_BYTES}-byte edit limit"
        )));
    }
    let text =
        std::fs::read_to_string(path).map_err(|error| RuntimeError::Tool(error.to_string()))?;

    if let Some(expected) = arguments
        .get("expected_file_hash")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
    {
        let actual = format!("sha256:{}", sha256_hex(text.as_bytes()));
        if !expected.eq_ignore_ascii_case(&actual) {
            return Err(RuntimeError::Tool(format!(
                "file hash mismatch: expected {expected}, found {actual}"
            )));
        }
    }

    let before = arguments
        .get("before_context")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let after = arguments
        .get("after_context")
        .and_then(Value::as_str)
        .unwrap_or_default();

    let mut candidates: Vec<usize> = Vec::new();
    let mut total_matches = 0usize;
    let mut search_from = 0usize;
    while let Some(offset) = text[search_from..].find(old_string) {
        let start = search_from + offset;
        let end = start + old_string.len();
        total_matches += 1;
        let context_ok = (before.is_empty() || text[..start].ends_with(before))
            && (after.is_empty() || text[end..].starts_with(after));
        if context_ok {
            candidates.push(start);
        }
        search_from = start + old_string.len().max(1);
    }
    if candidates.is_empty() {
        return Err(RuntimeError::Tool("old_string was not found in the file".into()));
    }
    let chosen = match arguments.get("occurrence").and_then(Value::as_u64) {
        Some(occurrence) => {
            let index = occurrence.max(1) as usize - 1;
            *candidates.get(index).ok_or_else(|| {
                RuntimeError::Tool(format!(
                    "occurrence {occurrence} is out of range for {} match(es)",
                    candidates.len()
                ))
            })?
        }
        None if candidates.len() == 1 => candidates[0],
        None => {
            return Err(RuntimeError::Tool(format!(
                "old_string matches {} times; pass occurrence or before_context/after_context to select one",
                candidates.len()
            )))
        }
    };

    let mut updated = String::with_capacity(text.len() + new_string.len());
    updated.push_str(&text[..chosen]);
    updated.push_str(new_string);
    updated.push_str(&text[chosen + old_string.len()..]);
    std::fs::write(path, updated.as_bytes())
        .map_err(|error| RuntimeError::Tool(error.to_string()))?;
    Ok(json!({
        "ok": true,
        "path": project_relative(path, root),
        "occurrences": total_matches,
        "candidates": candidates.len(),
        "file_hash": format!("sha256:{}", sha256_hex(updated.as_bytes())),
        "bytes": updated.len(),
    }))
}

fn tool_error(error: std::io::Error) -> RuntimeError {
    RuntimeError::Tool(error.to_string())
}

async fn write_atomic(path: &Path, content: &[u8]) -> std::io::Result<()> {
    let temporary = path.with_file_name(format!(
        ".{}.{}.tmp",
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("project"),
        uuid::Uuid::new_v4()
    ));
    let mut file = tokio::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)
        .await?;
    let written = async {
        file.write_all(content).await?;
        file.sync_all().await
    }
    .await;
    drop(file);
    if let Err(error) = written {
        let _ = tokio::fs::remove_file(&temporary).await;
        return Err(error);
    }
    if let Err(error) = tokio::fs::rename(&temporary, path).await {
        let _ = tokio::fs::remove_file(&temporary).await;
        return Err(error);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn file_tools_cap_their_output_like_the_desktop() {
        // 桌面：read_file 50,000 字符、list_dir 100 条、search 50 条。
        // 移动端此前没有上限（一个日志文件会把整份内容送进模型与历史），
        // 搜索上限还是 200（2026-09-25 审计 P2）。
        let root = std::env::temp_dir().join(format!(
            "lamtools-tool-caps-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(root.join("src")).unwrap();
        std::fs::create_dir_all(root.join("many")).unwrap();
        std::fs::write(root.join("big.log"), "x".repeat(super::MAX_READ_CHARS + 500)).unwrap();
        std::fs::write(root.join("src/main.rs"), "fn main() {}
").unwrap();
        for index in 0..(super::MAX_DIR_ENTRIES + 20) {
            std::fs::write(root.join("many").join(format!("f{index:03}.txt")), "x").unwrap();
        }
        let tools = ProjectFileTools::new(root.clone());
        let call = |name: &str, arguments: Value| ToolCall {
            id: "call".into(),
            name: name.into(),
            arguments,
        };

        let big = tools
            .execute(&call("read_file", json!({"path": "big.log"})))
            .await
            .unwrap();
        assert_eq!(big["truncated"], json!(true));
        let content = big["content"].as_str().unwrap();
        assert!(content.ends_with(super::TRUNCATED_MARKER));
        assert_eq!(content.chars().count(), super::MAX_READ_CHARS + super::TRUNCATED_MARKER.chars().count());

        let listed = tools
            .execute(&call("list_dir", json!({"path": "many"})))
            .await
            .unwrap();
        assert_eq!(listed["entries"].as_array().unwrap().len(), super::MAX_DIR_ENTRIES);
        assert_eq!(listed["total"], json!(super::MAX_DIR_ENTRIES + 20));
        assert_eq!(listed["truncated"], json!(true));

        // 右对齐 glob：`*.rs` 必须命中 `src/main.rs`（桌面用 Path.match 的语义）。
        let found = tools
            .execute(&call("search_files", json!({"pattern": "*.rs"})))
            .await
            .unwrap();
        let names: Vec<&str> = found["matches"]
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_str().unwrap())
            .collect();
        assert_eq!(names, ["src/main.rs"]);

        let capped = tools
            .execute(&call("search_files", json!({"pattern": "many/*.txt"})))
            .await
            .unwrap();
        assert_eq!(capped["matches"].as_array().unwrap().len(), super::MAX_SEARCH_MATCHES);
    }

    #[cfg(windows)]
    #[tokio::test]
    async fn drive_relative_paths_are_refused() {
        // `C:notes.md` 既非绝对路径也无 `..`，但 PathBuf::push 会用盘符前缀替换
        // 整个基路径（2026-09-25 审计 P3）。
        let root = std::env::temp_dir().join(format!("lamtools-drive-path-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        let tools = ProjectFileTools::new(root);
        let error = tools
            .execute(&ToolCall {
                id: "call".into(),
                name: "read_file".into(),
                arguments: json!({"path": "C:notes.md"}),
            })
            .await
            .expect_err("drive-relative paths must be refused");
        assert!(error.to_string().contains("inside the current project"));
    }

    #[tokio::test]
    async fn search_and_edit_tools_stay_inside_the_project_and_report_ambiguity() {
        let root = std::env::temp_dir().join(format!(
            "lamtools-edit-tools-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(root.join("src")).unwrap();
        std::fs::write(root.join("src/main.rs"), "fn main() {}\n").unwrap();
        std::fs::write(root.join("src/lib.rs"), "pub fn dup() {}\npub fn dup() {}\n").unwrap();
        std::fs::write(root.join("notes.md"), "alpha\nbeta\nalpha\n").unwrap();
        let tools = ProjectFileTools::new(root.clone());
        let call = |name: &str, arguments: Value| ToolCall {
            id: "call".into(),
            name: name.into(),
            arguments,
        };

        // Glob search covers nested directories and skips nothing by accident.
        let found = tools
            .execute(&call("search_files", json!({"pattern": "src/**/*.rs"})))
            .await
            .unwrap();
        let mut names: Vec<String> = found["matches"]
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_str().unwrap().to_owned())
            .collect();
        names.sort();
        assert_eq!(names, ["src/lib.rs", "src/main.rs"]);

        let content = tools
            .execute(&call("search_content", json!({"pattern": "alpha", "path": "notes.md"})))
            .await
            .unwrap();
        assert_eq!(content["count"], json!(2));
        assert_eq!(content["matches"][0]["line"], json!(1));
        assert_eq!(content["matches"][1]["line"], json!(3));

        // An ambiguous edit is refused rather than guessed.
        let ambiguous = tools
            .execute(&call(
                "edit_file",
                json!({"path": "src/lib.rs", "old_string": "pub fn dup() {}", "new_string": "pub fn dup2() {}"}),
            ))
            .await
            .expect_err("two matches must be refused");
        assert!(ambiguous.to_string().contains("matches 2 times"), "{ambiguous}");

        // Context selects exactly one of them.
        let edited = tools
            .execute(&call(
                "edit_file",
                json!({
                    "path": "src/lib.rs",
                    "old_string": "pub fn dup() {}",
                    "new_string": "pub fn first() {}",
                    "after_context": "\npub fn dup() {}",
                }),
            ))
            .await
            .expect("context selects the first occurrence");
        // Both counts are reported: how many matched, and how many survived
        // the context filter that selected the edit.
        assert_eq!(edited["occurrences"], json!(2));
        assert_eq!(edited["candidates"], json!(1));
        let after = std::fs::read_to_string(root.join("src/lib.rs")).unwrap();
        assert_eq!(after, "pub fn first() {}\npub fn dup() {}\n");

        // `occurrence` selects the second one, and the reported hash matches.
        let edited = tools
            .execute(&call(
                "edit_file",
                json!({
                    "path": "src/lib.rs",
                    "old_string": "pub fn dup() {}",
                    "new_string": "pub fn second() {}",
                    "occurrence": 1,
                    "expected_file_hash": edited["file_hash"],
                }),
            ))
            .await
            .expect("the reported hash is accepted");
        assert_eq!(std::fs::read_to_string(root.join("src/lib.rs")).unwrap(), "pub fn first() {}\npub fn second() {}\n");
        assert!(edited["file_hash"].as_str().unwrap().starts_with("sha256:"));

        // A stale hash is refused instead of editing the wrong revision.
        let stale = tools
            .execute(&call(
                "edit_file",
                json!({
                    "path": "src/lib.rs",
                    "old_string": "pub fn second() {}",
                    "new_string": "pub fn third() {}",
                    "expected_file_hash": "sha256:0000",
                }),
            ))
            .await
            .expect_err("a stale hash must be refused");
        assert!(stale.to_string().contains("file hash mismatch"));

        // Escaping the project is refused for every tool, including search.
        assert!(tools
            .execute(&call("search_files", json!({"pattern": "*", "path": "../"})))
            .await
            .is_err());
        assert!(tools
            .execute(&call("edit_file", json!({"path": "../outside.txt", "old_string": "a", "new_string": "b"})))
            .await
            .is_err());

        // Permissions match the desktop host: writes need approval, reads do not.
        assert_eq!(
            tools.permission(&call("edit_file", json!({}))),
            ToolPermission::AskUser
        );
        assert_eq!(
            tools.permission(&call("search_content", json!({}))),
            ToolPermission::AutoAllow
        );

        std::fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn project_file_tools_write_read_list_and_reject_escape() {
        let root = std::env::temp_dir().join(format!(
            "lamtools-project-tools-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let tools = ProjectFileTools::new(&root);

        let written = tools
            .execute(&ToolCall {
                id: "write-1".into(),
                name: "write_file".into(),
                arguments: json!({"path":"notes/你好.txt","content":"你好，这是测试文档"}),
            })
            .await
            .unwrap();
        assert_eq!(written["ok"], true);

        let read = tools
            .execute(&ToolCall {
                id: "read-1".into(),
                name: "read_file".into(),
                arguments: json!({"path":"notes/你好.txt"}),
            })
            .await
            .unwrap();
        assert_eq!(read["content"], "你好，这是测试文档");

        let listed = tools
            .execute(&ToolCall {
                id: "list-1".into(),
                name: "list_dir".into(),
                arguments: json!({"path":"notes"}),
            })
            .await
            .unwrap();
        assert_eq!(listed["entries"], json!(["你好.txt"]));
        assert_eq!(listed["path"], "notes");

        let root_listed = tools
            .execute(&ToolCall {
                id: "list-root-empty".into(),
                name: "list_dir".into(),
                arguments: json!({"path":""}),
            })
            .await
            .unwrap();
        assert_eq!(root_listed["path"], ".");
        assert_eq!(root_listed["entries"], json!(["notes"]));
        assert_eq!(
            root_listed["project_root"],
            std::fs::canonicalize(&root)
                .unwrap()
                .to_string_lossy()
                .to_string()
        );

        let omitted_root = tools
            .execute(&ToolCall {
                id: "list-root-omitted".into(),
                name: "list_dir".into(),
                arguments: json!({}),
            })
            .await
            .unwrap();
        assert_eq!(omitted_root["entries"], json!(["notes"]));

        let escaped = tools
            .execute(&ToolCall {
                id: "escape-1".into(),
                name: "write_file".into(),
                arguments: json!({"path":"../outside.txt","content":"no"}),
            })
            .await;
        assert!(matches!(escaped, Err(RuntimeError::Tool(_))));

        let empty_read_path = tools
            .execute(&ToolCall {
                id: "read-empty".into(),
                name: "read_file".into(),
                arguments: json!({"path":""}),
            })
            .await;
        assert!(matches!(empty_read_path, Err(RuntimeError::Tool(_))));

        let rewritten = tools
            .execute(&ToolCall {
                id: "write-2".into(),
                name: "write_file".into(),
                arguments: json!({"path":"notes/你好.txt","content":"第二版"}),
            })
            .await
            .unwrap();
        assert_eq!(rewritten["bytes"], "第二版".len());
        assert_eq!(
            tokio::fs::read_to_string(root.join("notes/你好.txt"))
                .await
                .unwrap(),
            "第二版"
        );

        #[cfg(unix)]
        {
            let outside = root.with_extension("outside");
            tokio::fs::create_dir(&outside).await.unwrap();
            std::os::unix::fs::symlink(&outside, root.join("linked")).unwrap();
            let escaped_link = tools
                .execute(&ToolCall {
                    id: "linked-read".into(),
                    name: "read_file".into(),
                    arguments: json!({"path":"linked/secret.txt"}),
                })
                .await;
            assert!(matches!(escaped_link, Err(RuntimeError::Tool(_))));
            tokio::fs::remove_dir_all(&outside).await.unwrap();
        }

        tokio::fs::remove_dir_all(root).await.unwrap();
    }
}
