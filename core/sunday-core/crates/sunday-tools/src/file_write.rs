//! `write_file`. Non-idempotent on purpose: its side effect is a user file, so
//! an unknown outcome must stop the machine rather than be retried.

use serde_json::{json, Value};
use std::sync::Arc;
use sunday_platform::{FileAccess, FileHandle};
use sunday_protocol::{
    CoreError, HostKind, Permission, SideEffect, Tool, ToolCtx, ToolOutput, ToolSpec,
};

pub struct WriteFile {
    files: Arc<dyn FileAccess>,
    spec: ToolSpec,
}

impl WriteFile {
    pub fn new(files: Arc<dyn FileAccess>) -> Self {
        Self {
            files,
            spec: ToolSpec {
                id: "write_file".into(),
                description: "Write a text file in the workspace. Fails instead of overwriting \
                              when an expected version is supplied and does not match."
                    .into(),
                input_schema: json!({
                    "type": "object",
                    "additionalProperties": false,
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "expect": {"type": "string", "description": "version from a previous read"}
                    },
                    "required": ["path", "content"]
                }),
                side_effect: SideEffect::NonIdempotent,
                hosts: vec![HostKind::Windows, HostKind::Android, HostKind::Server],
                permission: Permission::AskUser,
            },
        }
    }
}

#[async_trait::async_trait]
impl Tool for WriteFile {
    fn spec(&self) -> &ToolSpec {
        &self.spec
    }

    async fn execute(&self, args: Value, _ctx: &ToolCtx) -> Result<ToolOutput, CoreError> {
        let path = args
            .get("path")
            .and_then(Value::as_str)
            .ok_or_else(|| CoreError::invalid("'path' is required"))?
            .to_owned();
        let content = args
            .get("content")
            .and_then(Value::as_str)
            .ok_or_else(|| CoreError::invalid("'content' is required"))?;
        let expect = args.get("expect").and_then(Value::as_str);
        let etag = self
            .files
            .write(
                &FileHandle::Workspace { rel: path.clone() },
                content.as_bytes(),
                expect,
            )
            .await?;
        Ok(ToolOutput {
            content: json!({"ok": true, "path": path, "etag": etag, "bytes": content.len()})
                .to_string(),
            is_error: false,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sunday_platform::LocalFiles;

    fn tool() -> (tempfile::TempDir, WriteFile) {
        let dir = tempfile::tempdir().unwrap();
        let files = Arc::new(LocalFiles::new(dir.path()).unwrap());
        let tool = WriteFile::new(files);
        (dir, tool)
    }

    #[tokio::test]
    async fn writes_and_returns_an_etag() {
        let (dir, tool) = tool();
        let out = tool
            .execute(
                json!({"path": "notes/a.txt", "content": "hello"}),
                &ToolCtx::default(),
            )
            .await
            .unwrap();
        let parsed: Value = serde_json::from_str(&out.content).unwrap();
        assert_eq!(parsed["bytes"], 5);
        assert_eq!(
            std::fs::read_to_string(dir.path().join("notes/a.txt")).unwrap(),
            "hello"
        );
    }

    #[tokio::test]
    async fn refuses_to_overwrite_a_changed_file() {
        let (dir, tool) = tool();
        std::fs::write(dir.path().join("a.txt"), "first").unwrap();
        let err = tool
            .execute(
                json!({"path": "a.txt", "content": "second", "expect": "wrong"}),
                &ToolCtx::default(),
            )
            .await
            .unwrap_err();
        assert!(matches!(err, CoreError::RevisionConflict { .. }));
        assert_eq!(
            std::fs::read_to_string(dir.path().join("a.txt")).unwrap(),
            "first"
        );
    }

    #[tokio::test]
    async fn the_spec_is_non_idempotent_and_needs_approval() {
        let (_dir, tool) = tool();
        assert_eq!(tool.spec().side_effect, SideEffect::NonIdempotent);
        assert_eq!(tool.spec().permission, Permission::AskUser);
    }
}
