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
        if relative.is_empty()
            || path.is_absolute()
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
                name: "list_files".into(),
                description: "List files in the current project. The result includes the absolute project_root path; on Android this directory is app-private and cannot be browsed in the Android Files app. Omit path, pass an empty path, or use '.' to list the project root; pass a relative path to list a subdirectory.".into(),
                input_schema: json!({"type":"object","properties":{"path":{"type":"string","description":"Optional directory path relative to the current project. Omit it, use an empty string, or use '.' for the project root."}}}),
            },
            ToolDefinition {
                name: "read_text_file".into(),
                description: "Read a UTF-8 project file".into(),
                input_schema: json!({"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}),
            },
            ToolDefinition {
                name: "write_text_file".into(),
                description: "Create or overwrite a UTF-8 project file".into(),
                input_schema: json!({"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}),
            },
        ]
    }

    fn permission(&self, call: &ToolCall) -> ToolPermission {
        match call.name.as_str() {
            "list_files" | "read_text_file" => ToolPermission::AutoAllow,
            "write_text_file" => ToolPermission::AskUser,
            _ => ToolPermission::HardBlock,
        }
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        match call.name.as_str() {
            "write_text_file" => {
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
            "read_text_file" => {
                let path = self.resolve(&call.arguments["path"])?;
                let content = tokio::fs::read_to_string(path).await.map_err(tool_error)?;
                Ok(json!({"ok":true,"path":call.arguments["path"],"content":content}))
            }
            "list_files" => {
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
                let project_root =
                    std::fs::canonicalize(&self.root).unwrap_or_else(|_| self.root.clone());
                Ok(
                    json!({"ok":true,"path":relative,"project_root":project_root.to_string_lossy().to_string(),"entries":names}),
                )
            }
            _ => Err(RuntimeError::Tool(format!("unknown tool: {}", call.name))),
        }
    }
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
                name: "write_text_file".into(),
                arguments: json!({"path":"notes/你好.txt","content":"你好，这是测试文档"}),
            })
            .await
            .unwrap();
        assert_eq!(written["ok"], true);

        let read = tools
            .execute(&ToolCall {
                id: "read-1".into(),
                name: "read_text_file".into(),
                arguments: json!({"path":"notes/你好.txt"}),
            })
            .await
            .unwrap();
        assert_eq!(read["content"], "你好，这是测试文档");

        let listed = tools
            .execute(&ToolCall {
                id: "list-1".into(),
                name: "list_files".into(),
                arguments: json!({"path":"notes"}),
            })
            .await
            .unwrap();
        assert_eq!(listed["entries"], json!(["你好.txt"]));
        assert_eq!(listed["path"], "notes");

        let root_listed = tools
            .execute(&ToolCall {
                id: "list-root-empty".into(),
                name: "list_files".into(),
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
                name: "list_files".into(),
                arguments: json!({}),
            })
            .await
            .unwrap();
        assert_eq!(omitted_root["entries"], json!(["notes"]));

        let escaped = tools
            .execute(&ToolCall {
                id: "escape-1".into(),
                name: "write_text_file".into(),
                arguments: json!({"path":"../outside.txt","content":"no"}),
            })
            .await;
        assert!(matches!(escaped, Err(RuntimeError::Tool(_))));

        let empty_read_path = tools
            .execute(&ToolCall {
                id: "read-empty".into(),
                name: "read_text_file".into(),
                arguments: json!({"path":""}),
            })
            .await;
        assert!(matches!(empty_read_path, Err(RuntimeError::Tool(_))));

        let rewritten = tools
            .execute(&ToolCall {
                id: "write-2".into(),
                name: "write_text_file".into(),
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
                    name: "read_text_file".into(),
                    arguments: json!({"path":"linked/secret.txt"}),
                })
                .await;
            assert!(matches!(escaped_link, Err(RuntimeError::Tool(_))));
            tokio::fs::remove_dir_all(&outside).await.unwrap();
        }

        tokio::fs::remove_dir_all(root).await.unwrap();
    }
}
