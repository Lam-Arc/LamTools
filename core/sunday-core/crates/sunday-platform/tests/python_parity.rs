//! Parity tests against behaviours that already existed in the Python core.
//!
//! Each test names the Python evidence it mirrors. These are not differential
//! tests that run Python; they encode the observed behaviour so a future change
//! here that breaks it fails loudly.

use std::sync::Arc;
use sunday_platform::{FileAccess, FileHandle, LocalFiles};

fn workspace() -> (tempfile::TempDir, Arc<LocalFiles>) {
    let dir = tempfile::tempdir().unwrap();
    let files = Arc::new(LocalFiles::new(dir.path()).unwrap());
    (dir, files)
}

/// Python: `tool/workspace_files.py:699 resolve_read_resource_path` raises
/// `Path '{path}' is outside work_root` and the caller turns it into the failure
/// code `path_outside_root`.
#[tokio::test]
async fn path_outside_the_workspace_is_refused() {
    let (_dir, files) = workspace();
    for escape in ["../x", "a/../../x", "..", "./../x"] {
        let err = files
            .read(&FileHandle::Workspace { rel: escape.into() })
            .await
            .unwrap_err();
        assert!(
            matches!(err, sunday_protocol::CoreError::PermissionDenied { .. }),
            "{escape} should be refused, got {err:?}"
        );
    }
}

/// Python: `tool/workspace_files.py:197 atomic_write_bytes` writes a sibling temp
/// file and `os.replace`s it, so a crash never leaves half a file behind.
#[tokio::test]
async fn a_write_never_leaves_a_partial_file() {
    let (dir, files) = workspace();
    let handle = FileHandle::Workspace {
        rel: "sub/deep/a.txt".into(),
    };
    files.write(&handle, b"0123456789", None).await.unwrap();

    assert_eq!(
        std::fs::read(dir.path().join("sub/deep/a.txt")).unwrap(),
        b"0123456789"
    );
    // The temporary artefact must be gone once the write reports success.
    let leftovers: Vec<String> = std::fs::read_dir(dir.path().join("sub/deep"))
        .unwrap()
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|name| name.contains("sunday-tmp"))
        .collect();
    assert!(
        leftovers.is_empty(),
        "temp files left behind: {leftovers:?}"
    );
}

/// Python: `edit_file` returns `content_version_changed` instead of overwriting a
/// file that changed underneath the agent (`tool/workspace_files.py` version
/// hashes). The new core expresses the same rule as a compare-and-swap.
#[tokio::test]
async fn a_changed_file_is_not_silently_overwritten() {
    let (_dir, files) = workspace();
    let handle = FileHandle::Workspace {
        rel: "a.txt".into(),
    };
    let etag = files.write(&handle, b"v1", None).await.unwrap();
    files.write(&handle, b"v2", None).await.unwrap();

    let err = files.write(&handle, b"v3", Some(&etag)).await.unwrap_err();
    assert!(
        matches!(err, sunday_protocol::CoreError::RevisionConflict { .. }),
        "got {err:?}"
    );
    assert_eq!(files.read(&handle).await.unwrap(), b"v2");
}

/// Python blocks a fixed list of sensitive paths in
/// `tool/approval.py:44 DEFAULT_BLOCKED_FILE_PATTERNS` (`.env`, `.ssh/`,
/// `id_rsa`, `credentials`, `.aws/`).
///
/// This used to be a recorded gap. It is now a parity assertion, and the test
/// names the Python evidence so it cannot drift back into a gap unnoticed.
#[tokio::test]
async fn sensitive_paths_are_blocked_like_the_python_core() {
    let (_dir, files) = workspace();
    for rel in [
        ".env",
        ".env.production",
        ".ssh/id_rsa",
        "id_ed25519",
        "server.pem",
        ".aws/credentials",
        ".git/config",
    ] {
        let err = files
            .write(&FileHandle::Workspace { rel: rel.into() }, b"x", None)
            .await
            .expect_err(&format!("{rel} must be refused"));
        assert!(
            matches!(err, sunday_protocol::CoreError::PermissionDenied { .. }),
            "{rel}: {err:?}"
        );
    }
}

/// The blocklist must not turn into "nothing is writable".
#[tokio::test]
async fn ordinary_workspace_files_still_work() {
    let (_dir, files) = workspace();
    let handle = FileHandle::Workspace {
        rel: "notes/todo.md".into(),
    };
    files.write(&handle, b"# todo", None).await.unwrap();
    assert_eq!(files.read(&handle).await.unwrap(), b"# todo");
}
