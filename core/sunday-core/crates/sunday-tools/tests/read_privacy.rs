//! The privacy boundary of a read-only tool.
//!
//! `SideEffect::Pure` says a tool does not change state. It says nothing about what
//! the tool may *look at*, and a read that returns a private key is a worse outcome
//! than a write, because the result goes straight into the model context and from
//! there to a provider.
//!
//! So the three boundaries are checked separately:
//!
//! * **file read**: the policy refuses the path before any bytes are read;
//! * **model context**: a refused read produces no tool output at all, so there is
//!   nothing to put in the prompt;
//! * **network send**: `web_fetch` refuses this machine, which is the way a local
//!   file would otherwise leave through a second step.

use serde_json::json;
use std::sync::Arc;
use sunday_platform::LocalFiles;
use sunday_protocol::{CoreError, Tool, ToolCtx};
use sunday_tools::file_read::ReadFile;

const SECRET: &str = "sk-live-should-never-be-readable-4a7f";

fn tool(root: &std::path::Path) -> ReadFile {
    ReadFile::new(Arc::new(LocalFiles::new(root).unwrap()))
}

/// Every one of these is a credential, and every one of them must be refused.
#[tokio::test]
async fn credentials_are_never_readable_through_a_pure_tool() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();

    // Each entry is created first, so the refusal cannot be "the file is missing".
    let planted = [
        ".env",
        ".env.local",
        ".env.production",
        ".ssh/id_rsa",
        ".ssh/id_ed25519",
        ".ssh/config",
        "id_rsa",
        "id_ed25519",
        "id_dsa",
        "server.pem",
        "tls.key",
        "cert.p12",
        "store.pfx",
        "keystore.jks",
        "putty.ppk",
        ".git/config",
        ".git-credentials",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".htpasswd",
        ".aws/credentials",
        ".kube/config",
        ".docker/config.json",
        ".gnupg/secring.gpg",
        "credentials",
    ];
    for rel in planted {
        let path = root.join(rel);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(&path, SECRET).unwrap();
    }

    let tool = tool(root);
    for rel in planted {
        let error = tool
            .execute(json!({"path": rel}), &ToolCtx::default())
            .await
            .unwrap_err();
        assert!(
            matches!(error, CoreError::PermissionDenied { .. }),
            "{rel} was not refused: {error:?}"
        );
        // The refusal must not carry the thing it refused to read. An error message
        // is rendered in the UI and pasted into bug reports.
        assert!(
            !format!("{error:?}").contains(SECRET),
            "{rel}: the refusal leaked the content"
        );
    }
}

/// Ordinary files must still be readable, or the policy is just a broken tool.
#[tokio::test]
async fn ordinary_files_are_still_readable() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    std::fs::write(root.join("notes.md"), "# hello").unwrap();
    std::fs::create_dir_all(root.join("src")).unwrap();
    std::fs::write(root.join("src/main.rs"), "fn main() {}").unwrap();
    // A name that merely resembles a protected one must not be caught.
    std::fs::write(root.join("environment.md"), "docs").unwrap();

    let tool = tool(root);
    for rel in ["notes.md", "src/main.rs", "environment.md"] {
        let out = tool
            .execute(json!({"path": rel}), &ToolCtx::default())
            .await
            .unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&out.content).unwrap();
        assert_eq!(parsed["ok"], true, "{rel} was refused");
    }
}

/// Creates a symbolic link, or reports that this platform will not.
///
/// Windows needs either an elevated process or Developer Mode. When it refuses, the
/// test says so rather than passing quietly: the Linux job is what caught the symlink
/// bypass in the first place, and a silent skip on the other platform is how a green
/// board hides an open hole.
fn try_symlink(original: &std::path::Path, link: &std::path::Path) -> bool {
    #[cfg(unix)]
    {
        std::os::unix::fs::symlink(original, link).is_ok()
    }
    #[cfg(windows)]
    {
        std::os::windows::fs::symlink_file(original, link).is_ok()
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = (original, link);
        false
    }
}

/// A symlink is the obvious way around a rule that inspects the name. A link inside
/// the workspace pointing at a protected name must be refused on what it resolves to,
/// and a link pointing outside must be refused on the boundary.
#[tokio::test]
async fn a_symlink_cannot_smuggle_a_credential_past_the_policy() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    std::fs::create_dir_all(root.join(".ssh")).unwrap();
    std::fs::write(root.join(".ssh/id_rsa"), SECRET).unwrap();

    if !try_symlink(&root.join(".ssh/id_rsa"), &root.join("innocent.txt")) {
        eprintln!(
            "skipping the symlink cases: this platform refused to create a link \
             (Windows needs an elevated process or Developer Mode). The Linux CI job \
             runs them unconditionally."
        );
        return;
    }

    let tool = tool(root);
    let error = tool
        .execute(json!({"path": "innocent.txt"}), &ToolCtx::default())
        .await
        .unwrap_err();
    assert!(
        !format!("{error:?}").contains(SECRET),
        "a symlink handed out the key: {error:?}"
    );

    // A link pointing outside the workspace, which the boundary check has to catch.
    let outside = tempfile::tempdir().unwrap();
    std::fs::write(outside.path().join("secret.txt"), SECRET).unwrap();
    if try_symlink(&outside.path().join("secret.txt"), &root.join("escape.txt")) {
        let error = tool
            .execute(json!({"path": "escape.txt"}), &ToolCtx::default())
            .await
            .unwrap_err();
        assert!(
            matches!(error, CoreError::PermissionDenied { .. }),
            "a link out of the workspace was not refused: {error:?}"
        );
    }
}

/// A refused read must produce no `ToolOutput`, because that output is what would be
/// placed in the model context and sent to a provider. An error is not content.
#[tokio::test]
async fn a_refused_read_puts_nothing_into_the_model_context() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path();
    std::fs::write(root.join(".env"), format!("OPENAI_API_KEY={SECRET}")).unwrap();

    let tool = tool(root);
    let result = tool
        .execute(json!({"path": ".env"}), &ToolCtx::default())
        .await;

    let error = result.expect_err("a protected file was read");
    let rendered = format!("{error:?}");
    assert!(!rendered.contains(SECRET), "the error carries the secret");
    assert!(
        !rendered.contains("OPENAI_API_KEY"),
        "the error carries the variable name, which is itself a hint worth not leaking"
    );
}

/// The network step, checked from this side of the boundary: the tool that could
/// send a read result onward is not reachable to this machine.
#[tokio::test]
async fn the_network_tool_cannot_be_pointed_at_this_machine() {
    use sunday_tools::web_fetch::WebFetch;
    let tool = WebFetch::default();
    for url in [
        "http://127.0.0.1:8080/",
        "http://localhost:11434/v1/models",
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    ] {
        let error = tool
            .execute(json!({"url": url}), &ToolCtx::default())
            .await
            .unwrap_err();
        assert!(
            matches!(error, CoreError::PermissionDenied { .. }),
            "{url} was reachable: {error:?}"
        );
    }
}
