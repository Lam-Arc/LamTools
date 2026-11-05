//! Turning a reference the transcript shows into the file it means.
//!
//! user:“先调查现有 Windows 功能，最大化复用成熟实现”+(同一套语义从
//! `core/src/lamtools_core/app/file_references.py` 移植，界面在两处不该有两种答案)。
//!
//! A reply can name a path the user never typed: `workspace://notes.md`, `/artifacts/x.png`,
//! or a file name whose real location is one of the artifact folders. The desktop resolves
//! those rules; this is the same resolution, bounded the same way, so a preview on a phone
//! shows the file a preview on the desktop shows.
//!
//! What differs is the ceiling: here every result must land inside the root the host handed
//! over. On a phone that root is the app sandbox, and a reference is not a grant.

use std::path::{Path, PathBuf};

use sunday_platform::LocalFiles;

/// Where a turn's outputs land, and therefore where a bare file name may be found.
const ARTIFACT_FOLDERS: [&str; 4] = [".lam/artifacts", ".lam/artifact", "artifacts", "artifact"];

/// A search this large means the reference is too vague to resolve by name.
const MAX_ENTRIES: usize = 5000;

#[derive(Debug, PartialEq, Eq)]
pub enum ReferenceError {
    /// Nothing by that name, or a path this root may not read.
    Missing,
    /// More than one file answers to the name, so guessing would show the wrong one.
    Ambiguous(String),
    /// The search itself is too expensive to answer honestly.
    TooMany,
}

impl ReferenceError {
    /// The two statuses and texts the interface already knows how to show.
    pub fn status(&self) -> u16 {
        match self {
            Self::Missing => 404,
            Self::Ambiguous(_) | Self::TooMany => 409,
        }
    }

    pub fn detail(&self) -> String {
        match self {
            Self::Missing => "原文件不存在".into(),
            Self::Ambiguous(text) => text.clone(),
            Self::TooMany => "成果目录过大，请使用工具返回的完整路径".into(),
        }
    }
}

/// Resolves a reference to a real file inside `files`' root.
pub fn resolve(files: &LocalFiles, raw: &str) -> Result<PathBuf, ReferenceError> {
    let root = files.root();
    let value = strip_scheme(raw);
    if value.is_empty() || value.contains('\0') {
        return Err(ReferenceError::Missing);
    }
    if has_foreign_scheme(&value) {
        return Err(ReferenceError::Missing);
    }
    // `/artifacts/x.png` is how a report names an output; it is relative to the root.
    let alias = value.starts_with("/artifacts/") || value.starts_with("/artifact/");
    let candidate = Path::new(&value);
    let target = if candidate.is_absolute() && !alias {
        // `resolve_read` takes a relative path, so an absolute one is checked here
        // instead, against the same root.
        let path = candidate
            .canonicalize()
            .map_err(|_| ReferenceError::Missing)?;
        if !path.starts_with(root) {
            return Err(ReferenceError::Missing);
        }
        path
    } else {
        let relative = value.trim_start_matches('/');
        if relative
            .split('/')
            .any(|segment| segment == ".." || segment == ".")
        {
            return Err(ReferenceError::Missing);
        }
        match files.resolve_read(relative) {
            Ok(path) => path,
            // Missing, protected, or outside the grant. Only a name can be searched for;
            // a path that tried to leave stays refused.
            Err(_) => return search_by_name(files, Path::new(&value)),
        }
    };
    if target.is_file() {
        return Ok(target);
    }
    search_by_name(files, &target)
}

/// The file name, looked for in the folders a turn writes into.
fn search_by_name(files: &LocalFiles, wanted: &Path) -> Result<PathBuf, ReferenceError> {
    let root = files.root();
    let name = wanted
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(ReferenceError::Missing)?
        .to_owned();
    if !files.policy().allows(&name) {
        return Err(ReferenceError::Missing);
    }
    // The candidate's own directory is searched too, because a report can name a file
    // relative to a subfolder that still lives inside the project.
    let mut bases: Vec<PathBuf> = vec![root.to_path_buf()];
    if let Some(parent) = wanted.parent() {
        let joined = root.join(parent);
        if joined != root && joined.is_dir() && joined.starts_with(root) {
            bases.push(joined);
        }
    }
    let mut found: Vec<PathBuf> = Vec::new();
    let mut visited = 0usize;
    for base in bases {
        for folder in ARTIFACT_FOLDERS {
            let artifacts = base.join(folder);
            let Ok(artifacts) = artifacts.canonicalize() else {
                continue;
            };
            if !artifacts.starts_with(root) || !artifacts.is_dir() {
                continue;
            }
            for entry in walk(&artifacts, &mut visited)? {
                if entry.file_name().and_then(|value| value.to_str()) == Some(name.as_str())
                    && !found.contains(&entry)
                {
                    found.push(entry);
                }
            }
        }
    }
    match found.len() {
        0 => Err(ReferenceError::Missing),
        1 => Ok(found.remove(0)),
        _ => Err(ReferenceError::Ambiguous(
            "存在多个同名成果，请使用完整路径".into(),
        )),
    }
}

/// Every regular file under `dir`, refusing a directory large enough that the answer would
/// be a guess. Symlinks are skipped rather than followed: the grant is this directory.
fn walk(dir: &Path, visited: &mut usize) -> Result<Vec<PathBuf>, ReferenceError> {
    let mut out = Vec::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(current) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&current) else {
            continue;
        };
        for entry in entries.flatten() {
            *visited += 1;
            if *visited > MAX_ENTRIES {
                return Err(ReferenceError::TooMany);
            }
            let path = entry.path();
            let Ok(kind) = entry.file_type() else {
                continue;
            };
            if kind.is_symlink() {
                continue;
            }
            if kind.is_dir() {
                stack.push(path);
            } else if kind.is_file() {
                out.push(path);
            }
        }
    }
    Ok(out)
}

/// Drops the two prefixes a stored reference may carry.
fn strip_scheme(raw: &str) -> String {
    let mut value = raw.trim().replace('\\', "/");
    if let Some(rest) = value.strip_prefix("workspace://") {
        value = rest.to_owned();
    }
    if let Some(rest) = value.strip_prefix("file://") {
        value = percent_decode(rest);
        // `file:///C:/x` keeps a leading slash that is not part of the drive.
        if value.len() > 2 && value.starts_with('/') && value.as_bytes()[2] == b':' {
            value = value[1..].to_owned();
        }
    }
    value
}

/// A scheme that is not a drive letter means this is not a path on this machine.
fn has_foreign_scheme(value: &str) -> bool {
    let Some(colon) = value.find(':') else {
        return false;
    };
    if colon == 0 {
        return false;
    }
    let scheme = &value[..colon];
    if !scheme
        .chars()
        .next()
        .map(|first| first.is_ascii_alphabetic())
        .unwrap_or(false)
    {
        return false;
    }
    if !scheme
        .chars()
        .all(|character| character.is_ascii_alphanumeric() || "+.-".contains(character))
    {
        return false;
    }
    // `C:/x` and `c:x` are drive paths, not schemes.
    !(scheme.len() == 1 && scheme.chars().next().unwrap().is_ascii_alphabetic())
}

fn percent_decode(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' && index + 2 < bytes.len() {
            let hex = std::str::from_utf8(&bytes[index + 1..index + 3]).unwrap_or("");
            if let Ok(value) = u8::from_str_radix(hex, 16) {
                out.push(value);
                index += 3;
                continue;
            }
        }
        out.push(bytes[index]);
        index += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// The content type a preview needs, from the name alone.
pub fn mime_for_name(name: &str) -> &'static str {
    let extension = name
        .rsplit_once('.')
        .map(|(_, rest)| rest.to_ascii_lowercase())
        .unwrap_or_default();
    match extension.as_str() {
        "txt" | "log" => "text/plain",
        "md" | "markdown" => "text/markdown",
        "csv" => "text/csv",
        "json" => "application/json",
        "html" | "htm" => "text/html",
        "css" => "text/css",
        "js" | "mjs" => "text/javascript",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "svg" => "image/svg+xml",
        "avif" => "image/avif",
        "bmp" => "image/bmp",
        "ico" => "image/x-icon",
        "pdf" => "application/pdf",
        "mp4" => "video/mp4",
        "webm" => "video/webm",
        "mov" => "video/quicktime",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "ogg" => "audio/ogg",
        "m4a" => "audio/mp4",
        "flac" => "audio/flac",
        _ => "application/octet-stream",
    }
}

/// A prefix of a text file, cut on a character boundary, for a preview card.
///
/// A preview is a glance, not a download: a 40 MB log would otherwise be parsed as JSON on
/// the screen's thread to fill a card that shows ten lines.
pub fn preview_text(bytes: &[u8], limit: usize) -> (String, bool) {
    if bytes.len() <= limit {
        return (String::from_utf8_lossy(bytes).into_owned(), false);
    }
    let mut end = limit;
    while end > 0 && bytes[end] & 0b1100_0000 == 0b1000_0000 {
        end -= 1;
    }
    (String::from_utf8_lossy(&bytes[..end]).into_owned(), true)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture() -> (tempfile::TempDir, LocalFiles) {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("workspace");
        std::fs::create_dir_all(root.join("artifacts")).unwrap();
        std::fs::write(root.join("notes.md"), "hello").unwrap();
        std::fs::write(root.join("artifacts/chart.png"), [0x89, b'P', b'N', b'G']).unwrap();
        let files = LocalFiles::new(&root).unwrap();
        (dir, files)
    }

    #[test]
    fn a_plain_relative_name_is_a_file_in_the_root() {
        let (_dir, files) = fixture();
        let path = resolve(&files, "notes.md").unwrap();
        assert_eq!(path, files.root().join("notes.md").canonicalize().unwrap());
    }

    #[test]
    fn a_workspace_reference_is_the_same_file() {
        let (_dir, files) = fixture();
        assert_eq!(
            resolve(&files, "workspace://notes.md").unwrap(),
            resolve(&files, "notes.md").unwrap()
        );
    }

    #[test]
    fn an_artifact_alias_is_relative_to_the_root() {
        let (_dir, files) = fixture();
        let path = resolve(&files, "/artifacts/chart.png").unwrap();
        assert_eq!(
            path,
            files
                .root()
                .join("artifacts/chart.png")
                .canonicalize()
                .unwrap()
        );
        assert_eq!(mime_for_name("chart.png"), "image/png");
    }

    /// A report can name a file that only exists inside an output folder.
    #[test]
    fn a_bare_name_is_found_in_the_output_folder() {
        let (_dir, files) = fixture();
        let path = resolve(&files, "chart.png").unwrap();
        assert!(path.ends_with("artifacts/chart.png"), "{path:?}");
    }

    /// Two files with one name is a question, not a guess.
    #[test]
    fn two_files_with_one_name_are_ambiguous() {
        let (_dir, files) = fixture();
        std::fs::create_dir_all(files.root().join(".lam/artifacts")).unwrap();
        std::fs::write(files.root().join(".lam/artifacts/chart.png"), b"x").unwrap();
        match resolve(&files, "chart.png") {
            Err(ReferenceError::Ambiguous(_)) => {}
            other => panic!("expected ambiguity, got {other:?}"),
        }
    }

    #[test]
    fn leaving_the_root_is_refused() {
        let (_dir, files) = fixture();
        assert_eq!(
            resolve(&files, "../../etc/passwd"),
            Err(ReferenceError::Missing)
        );
        assert_eq!(
            resolve(&files, "notes.md/../secret.txt"),
            Err(ReferenceError::Missing)
        );
    }

    /// An absolute path outside the granted root is not a reference, it is another file.
    #[test]
    fn an_absolute_path_outside_the_root_is_refused() {
        let (dir, files) = fixture();
        let outside = dir.path().join("outside.txt");
        std::fs::write(&outside, "no").unwrap();
        assert_eq!(
            resolve(&files, &outside.to_string_lossy()),
            Err(ReferenceError::Missing)
        );
    }

    /// and inside the root it is the same file as the relative spelling.
    #[test]
    fn an_absolute_path_inside_the_root_is_the_file() {
        let (_dir, files) = fixture();
        let inside = files.root().join("notes.md");
        assert_eq!(
            resolve(&files, &inside.to_string_lossy()).unwrap(),
            resolve(&files, "notes.md").unwrap()
        );
    }

    #[test]
    fn a_network_reference_is_not_a_local_file() {
        let (_dir, files) = fixture();
        assert_eq!(
            resolve(&files, "https://example.com/a.png"),
            Err(ReferenceError::Missing)
        );
    }

    /// A long file is cut, the cut is announced, and the cut never splits a character.
    #[test]
    fn a_preview_is_a_prefix_that_says_it_was_cut() {
        let text = "字".repeat(100);
        let (shown, truncated) = preview_text(text.as_bytes(), 100);
        assert!(truncated);
        assert!(shown.len() <= 100);
        assert!(shown.chars().all(|character| character == '字'));
        let (whole, cut) = preview_text(b"short", 100);
        assert_eq!(whole, "short");
        assert!(!cut);
    }

    #[test]
    fn percent_escapes_in_a_file_url_are_decoded() {
        let (_dir, files) = fixture();
        std::fs::write(files.root().join("a b.txt"), "x").unwrap();
        let path = resolve(&files, "file://a%20b.txt").unwrap();
        assert!(path.ends_with("a b.txt"), "{path:?}");
    }
}
