//! `read_file`. Reads through the platform port, so the same tool works on a
//! private directory and on a granted system folder without a branch here.

use serde_json::{json, Value};
use std::sync::Arc;
use sunday_platform::{FileAccess, FileHandle};
use sunday_protocol::{
    CoreError, HostKind, Permission, SideEffect, Tool, ToolCtx, ToolOutput, ToolSpec,
};

const MAX_BYTES: usize = 256 * 1024;

pub struct ReadFile {
    files: Arc<dyn FileAccess>,
    spec: ToolSpec,
}

impl ReadFile {
    pub fn new(files: Arc<dyn FileAccess>) -> Self {
        Self {
            files,
            spec: ToolSpec {
                id: "read_file".into(),
                description: "Read a text file from the workspace. Paths are relative and may \
                              not escape the workspace."
                    .into(),
                input_schema: json!({
                    "type": "object",
                    "additionalProperties": false,
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]
                }),
                side_effect: SideEffect::Pure,
                hosts: vec![HostKind::Windows, HostKind::Android, HostKind::Server],
                permission: Permission::AutoAllow,
            },
        }
    }
}

#[async_trait::async_trait]
impl Tool for ReadFile {
    fn spec(&self) -> &ToolSpec {
        &self.spec
    }

    async fn execute(&self, args: Value, _ctx: &ToolCtx) -> Result<ToolOutput, CoreError> {
        let path = args
            .get("path")
            .and_then(Value::as_str)
            .ok_or_else(|| CoreError::invalid("'path' is required"))?
            .to_owned();
        let bytes = self
            .files
            .read(&FileHandle::Workspace { rel: path.clone() })
            .await?;
        let clipped = bytes.len() > MAX_BYTES;
        let slice = if clipped {
            &bytes[..MAX_BYTES]
        } else {
            &bytes[..]
        };
        let text = String::from_utf8_lossy(slice).into_owned();
        Ok(ToolOutput {
            content: json!({
                "ok": true,
                "path": path,
                "bytes": bytes.len(),
                "truncated": clipped,
                "content": text,
            })
            .to_string(),
            is_error: false,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sunday_platform::LocalFiles;

    fn tool() -> (tempfile::TempDir, ReadFile) {
        let dir = tempfile::tempdir().unwrap();
        let files = Arc::new(LocalFiles::new(dir.path()).unwrap());
        let tool = ReadFile::new(files);
        (dir, tool)
    }

    #[tokio::test]
    async fn reads_a_file_inside_the_workspace() {
        let (dir, tool) = tool();
        std::fs::write(dir.path().join("a.txt"), "hello").unwrap();
        let out = tool
            .execute(json!({"path": "a.txt"}), &ToolCtx::default())
            .await
            .unwrap();
        let parsed: Value = serde_json::from_str(&out.content).unwrap();
        assert_eq!(parsed["content"], "hello");
        assert_eq!(parsed["truncated"], false);
    }

    #[tokio::test]
    async fn refuses_to_escape_the_workspace() {
        let (_dir, tool) = tool();
        let err = tool
            .execute(json!({"path": "../outside.txt"}), &ToolCtx::default())
            .await
            .unwrap_err();
        assert!(matches!(err, CoreError::PermissionDenied { .. }));
    }

    #[tokio::test]
    async fn a_missing_file_is_an_invalid_request() {
        let (_dir, tool) = tool();
        let err = tool
            .execute(json!({"path": "nope.txt"}), &ToolCtx::default())
            .await
            .unwrap_err();
        assert!(matches!(err, CoreError::InvalidRequest { .. }));
    }
}
