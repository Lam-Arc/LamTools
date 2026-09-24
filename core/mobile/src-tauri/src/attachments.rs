//! Durable, app-private attachment bytes for the standalone mobile host.
//! Each attachment is published by one directory rename after both files are
//! synced; uncommitted directories are never visible to list/read.
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, OpenOptions},
    io::{self, Write},
    path::{Path, PathBuf},
};
use uuid::Uuid;

pub const MAX_ATTACHMENT_BYTES: usize = 50 * 1024 * 1024;
const MAX_METADATA_BYTES: u64 = 16 * 1024;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub struct AttachmentMetadata {
    pub id: String,
    pub session_id: String,
    pub filename: String,
    pub mime_type: String,
    pub size: u64,
    pub preview_type: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AttachmentData {
    pub metadata: AttachmentMetadata,
    pub bytes: Vec<u8>,
}

#[derive(Clone, Debug)]
pub struct AttachmentStore {
    root: PathBuf,
}

impl AttachmentStore {
    pub fn new(root: impl AsRef<Path>) -> io::Result<Self> {
        fs::create_dir_all(root.as_ref())?;
        Ok(Self {
            root: fs::canonicalize(root)?,
        })
    }

    pub fn save(
        &self,
        session_id: &str,
        filename: &str,
        mime: &str,
        bytes: &[u8],
    ) -> io::Result<AttachmentMetadata> {
        self.save_inner(session_id, filename, mime, bytes, || Ok(()))
    }

    fn save_inner<F>(
        &self,
        session_id: &str,
        filename: &str,
        mime: &str,
        bytes: &[u8],
        after_content: F,
    ) -> io::Result<AttachmentMetadata>
    where
        F: FnOnce() -> io::Result<()>,
    {
        validate_session_id(session_id)?;
        validate_filename(filename)?;
        if bytes.len() > MAX_ATTACHMENT_BYTES {
            return Err(invalid_input("Attachment exceeds the 50 MiB limit"));
        }
        let mime_type = resolve_mime(filename, mime, bytes)?;
        let id = Uuid::new_v4().simple().to_string();
        let record = AttachmentMetadata {
            id: id.clone(),
            session_id: session_id.to_owned(),
            filename: filename.to_owned(),
            mime_type: mime_type.clone(),
            size: bytes.len() as u64,
            preview_type: preview_type(filename, &mime_type).into(),
        };
        let temporary = self.root.join(format!(".pending-{id}"));
        let destination = self.root.join(&id);
        fs::create_dir(&temporary)?;
        let result = (|| {
            write_synced(&temporary.join("content.bin"), bytes)?;
            after_content()?;
            let metadata = serde_json::to_vec(&record)
                .map_err(|err| io::Error::new(io::ErrorKind::InvalidData, err))?;
            write_synced(&temporary.join("metadata.json"), &metadata)?;
            fs::rename(&temporary, &destination)?;
            Ok(record)
        })();
        if result.is_err() {
            let _ = fs::remove_dir_all(&temporary);
        }
        result
    }

    pub fn read(&self, id: &str) -> io::Result<AttachmentData> {
        let directory = self.directory(id)?;
        let metadata = self.read_metadata(id, &directory)?;
        let content = checked_file(&directory, "content.bin")?;
        let size = fs::metadata(&content)?.len();
        if size > MAX_ATTACHMENT_BYTES as u64 || size != metadata.size {
            return Err(invalid_data(
                "Attachment content size does not match metadata",
            ));
        }
        let bytes = fs::read(content)?;
        if bytes.len() as u64 != metadata.size {
            return Err(invalid_data("Attachment changed during read"));
        }
        Ok(AttachmentData { metadata, bytes })
    }

    /// Materialize a verified attachment in Android's private cache for a
    /// temporary FileProvider grant. The public filename contains only the
    /// validated id and a short ASCII extension, never the uploaded name.
    pub fn write_open_cache(&self, id: &str, cache_dir: &Path) -> io::Result<(String, String)> {
        let data = self.read(id)?;
        let directory = fs::canonicalize(cache_dir)?;
        if !directory.is_dir() {
            return Err(invalid_input("Attachment cache is not a directory"));
        }
        let extension = Path::new(&data.metadata.filename)
            .extension()
            .and_then(|value| value.to_str())
            .filter(|value| {
                !value.is_empty()
                    && value.len() <= 10
                    && value.bytes().all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
            })
            .unwrap_or("bin");
        let file_name = format!("{id}.{extension}");
        let temporary = directory.join(format!(".pending-{}", Uuid::new_v4().simple()));
        let result = (|| {
            write_synced(&temporary, &data.bytes)?;
            fs::rename(&temporary, directory.join(&file_name))?;
            Ok((file_name, data.metadata.mime_type))
        })();
        if result.is_err() {
            let _ = fs::remove_file(temporary);
        }
        result
    }

    pub fn list(&self, session_id: &str) -> io::Result<Vec<AttachmentMetadata>> {
        validate_session_id(session_id)?;
        let mut records = Vec::new();
        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            let name = entry.file_name();
            let Some(id) = name.to_str() else { continue };
            if !valid_id(id) {
                continue;
            }
            let directory = self.directory(id)?;
            let metadata = self.read_metadata(id, &directory)?;
            if metadata.session_id != session_id {
                continue;
            }
            // A committed metadata record without bytes is corrupt, not an
            // empty listing. Surface the failure to the caller.
            let content = checked_file(&directory, "content.bin")?;
            if fs::metadata(content)?.len() != metadata.size {
                return Err(invalid_data(
                    "Attachment content size does not match metadata",
                ));
            }
            records.push(metadata);
        }
        records.sort_by(|a, b| a.id.cmp(&b.id));
        Ok(records)
    }

    pub fn delete(&self, id: &str) -> io::Result<bool> {
        let directory = match self.directory(id) {
            Ok(directory) => directory,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
            Err(error) => return Err(error),
        };
        self.read_metadata(id, &directory)?;
        let tombstone = self
            .root
            .join(format!(".deleted-{}", Uuid::new_v4().simple()));
        fs::rename(&directory, &tombstone)?;
        // Logical deletion is the rename. A cleanup failure leaves only an
        // unaddressable tombstone and cannot make the attachment visible again.
        let _ = fs::remove_dir_all(tombstone);
        Ok(true)
    }

    fn directory(&self, id: &str) -> io::Result<PathBuf> {
        if !valid_id(id) {
            return Err(invalid_input("Invalid attachment id"));
        }
        let path = self.root.join(id);
        let kind = fs::symlink_metadata(&path)?;
        if kind.file_type().is_symlink() || !kind.is_dir() {
            return Err(invalid_data("Attachment directory is unsafe"));
        }
        let resolved = fs::canonicalize(path)?;
        if resolved.parent() != Some(self.root.as_path()) {
            return Err(invalid_data("Attachment directory escapes store"));
        }
        Ok(resolved)
    }

    fn read_metadata(&self, id: &str, directory: &Path) -> io::Result<AttachmentMetadata> {
        let path = checked_file(directory, "metadata.json")?;
        if fs::metadata(&path)?.len() > MAX_METADATA_BYTES {
            return Err(invalid_data("Attachment metadata is too large"));
        }
        let raw = fs::read(path)?;
        let record: AttachmentMetadata = serde_json::from_slice(&raw)
            .map_err(|_| invalid_data("Attachment metadata is invalid"))?;
        if record.id != id
            || !valid_id(&record.id)
            || validate_session_id(&record.session_id).is_err()
            || validate_filename(&record.filename).is_err()
            || record.size > MAX_ATTACHMENT_BYTES as u64
            || !valid_mime(&record.mime_type)
            || record.preview_type != preview_type(&record.filename, &record.mime_type)
        {
            return Err(invalid_data("Attachment metadata failed validation"));
        }
        Ok(record)
    }
}

fn write_synced(path: &Path, bytes: &[u8]) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()
}

fn checked_file(directory: &Path, name: &str) -> io::Result<PathBuf> {
    let path = directory.join(name);
    let kind = fs::symlink_metadata(&path)?;
    if kind.file_type().is_symlink() || !kind.is_file() {
        return Err(invalid_data("Attachment file is unsafe"));
    }
    let resolved = fs::canonicalize(path)?;
    if resolved.parent() != Some(directory) {
        return Err(invalid_data("Attachment file escapes store"));
    }
    Ok(resolved)
}

fn valid_id(id: &str) -> bool {
    id.len() == 32
        && id
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn validate_session_id(id: &str) -> io::Result<()> {
    if id.is_empty()
        || id.len() > 256
        || id == ".."
        || !id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(invalid_input("Invalid attachment session id"));
    }
    Ok(())
}

fn validate_filename(filename: &str) -> io::Result<()> {
    if filename.is_empty()
        || filename.len() > 255
        || filename == "."
        || filename == ".."
        || filename
            .chars()
            .any(|ch| ch.is_control() || "<>:\"/\\|?*".contains(ch))
    {
        return Err(invalid_input("Invalid attachment filename"));
    }
    Ok(())
}

fn valid_mime(mime: &str) -> bool {
    let Some((top, subtype)) = mime.split_once('/') else {
        return false;
    };
    !top.is_empty()
        && !subtype.is_empty()
        && !mime.contains(';')
        && mime.len() <= 128
        && mime.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || b"/!#$&^_.+-".contains(&byte)
        })
}

fn resolve_mime(filename: &str, supplied: &str, bytes: &[u8]) -> io::Result<String> {
    if supplied.len() > 128 || supplied.chars().any(char::is_control) {
        return Err(invalid_input("Invalid attachment MIME type"));
    }
    let supplied = supplied
        .split(';')
        .next()
        .unwrap_or_default()
        .trim()
        .to_ascii_lowercase();
    if supplied.starts_with("multipart/") {
        return Err(invalid_input(
            "Multipart envelope MIME is not a file MIME type",
        ));
    }
    if valid_mime(&supplied) && supplied != "application/octet-stream" {
        return Ok(supplied);
    }
    let detected = infer::get(bytes).map(|kind| kind.mime_type());
    if let Some(magic) = detected {
        return Ok(magic.to_owned());
    }
    let extension = Path::new(filename)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    let guessed = match extension.as_str() {
        "txt" | "log" | "md" | "markdown" | "csv" | "tsv" | "py" | "rs" | "js" | "ts" | "tsx"
        | "jsx" | "css" | "sql" | "sh" | "ps1" => "text/plain",
        "json" => "application/json",
        "yaml" | "yml" => "application/yaml",
        "xml" => "application/xml",
        "html" | "htm" => "text/html",
        "pdf" => "application/pdf",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "svg" => "image/svg+xml",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "mp4" => "video/mp4",
        _ => "application/octet-stream",
    };
    Ok(guessed.into())
}

fn preview_type(filename: &str, mime: &str) -> &'static str {
    let extension = Path::new(filename)
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if matches!(
        extension.as_str(),
        "txt"
            | "md"
            | "markdown"
            | "json"
            | "yaml"
            | "yml"
            | "csv"
            | "tsv"
            | "log"
            | "xml"
            | "html"
            | "htm"
            | "css"
            | "js"
            | "ts"
            | "tsx"
            | "jsx"
            | "py"
            | "ps1"
            | "bat"
            | "sh"
            | "toml"
            | "ini"
            | "cfg"
            | "sql"
    ) || mime.starts_with("text/")
        || matches!(
            mime,
            "application/json" | "application/xml" | "application/x-yaml" | "application/yaml"
        )
    {
        return "text";
    }
    if mime.starts_with("image/") {
        return "image";
    }
    if mime.starts_with("audio/") {
        return "audio";
    }
    if mime.starts_with("video/") {
        return "video";
    }
    if mime == "application/pdf" {
        return "pdf";
    }
    "external"
}

fn invalid_input(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message.to_owned())
}
fn invalid_data(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_store() -> (PathBuf, AttachmentStore) {
        let root =
            std::env::temp_dir().join(format!("lamtools-attachment-{}", Uuid::new_v4().simple()));
        let store = AttachmentStore::new(&root).unwrap();
        (root, store)
    }

    #[test]
    fn binary_persists_across_restart_with_correct_metadata_and_delete() {
        let (root, store) = temp_store();
        let png = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR";
        let record = store
            .save("study:main", "image.png", "application/octet-stream", png)
            .unwrap();
        assert_eq!(record.mime_type, "image/png");
        assert_eq!(record.preview_type, "image");
        assert_eq!(record.size, png.len() as u64);
        assert_eq!(
            serde_json::to_value(&record).unwrap()["mime_type"],
            "image/png"
        );
        drop(store);
        let reopened = AttachmentStore::new(&root).unwrap();
        assert_eq!(reopened.list("study:main").unwrap(), vec![record.clone()]);
        assert_eq!(reopened.read(&record.id).unwrap().bytes, png);
        assert!(reopened.delete(&record.id).unwrap());
        assert!(!reopened.delete(&record.id).unwrap());
        assert!(reopened.list("study:main").unwrap().is_empty());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rejects_traversal_bad_mime_and_oversize_without_publishing() {
        let (root, store) = temp_store();
        for (session, filename, mime) in [
            ("../outside", "a.txt", "text/plain"),
            ("session", "../secret.txt", "text/plain"),
            ("session", "sub\\secret.txt", "text/plain"),
            ("session", "a.txt", "multipart/form-data; boundary=oops"),
        ] {
            assert!(store.save(session, filename, mime, b"hello").is_err());
        }
        assert!(store
            .save(
                "session",
                "large.bin",
                "application/octet-stream",
                &vec![0; MAX_ATTACHMENT_BYTES + 1]
            )
            .is_err());
        assert!(store.list("session").unwrap().is_empty());
        assert!(store.read("../outside").is_err());
        assert!(store.delete("../outside").is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn missing_content_is_reported_and_save_failure_is_atomic() {
        let (root, store) = temp_store();
        let record = store
            .save("session", "notes.txt", "text/plain", b"content")
            .unwrap();
        fs::remove_file(root.join(&record.id).join("content.bin")).unwrap();
        assert_eq!(
            store.read(&record.id).unwrap_err().kind(),
            io::ErrorKind::NotFound
        );
        assert_eq!(
            store.list("session").unwrap_err().kind(),
            io::ErrorKind::NotFound
        );
        let failed = store.save_inner("session", "other.txt", "text/plain", b"other", || {
            Err(io::Error::other("simulated publish failure"))
        });
        assert!(failed.is_err());
        assert_eq!(
            fs::read_dir(&root).unwrap().count(),
            1,
            "uncommitted directory survived failure"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn open_cache_uses_safe_name_and_exact_verified_bytes() {
        let (root, store) = temp_store();
        let cache = root.join("cache");
        fs::create_dir(&cache).unwrap();
        let record = store
            .save("session", "private-notes.txt", "text/plain", b"private text")
            .unwrap();
        let (file_name, mime_type) = store.write_open_cache(&record.id, &cache).unwrap();
        assert_eq!(file_name, format!("{}.txt", record.id));
        assert_eq!(mime_type, "text/plain");
        assert_eq!(fs::read(cache.join(file_name)).unwrap(), b"private text");
        fs::remove_dir_all(root).unwrap();
    }
}
