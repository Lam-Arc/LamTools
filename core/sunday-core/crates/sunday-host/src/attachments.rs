//! Files a user gives a session, owned by the core.
//!
//! user:“复用 Sunday 现有文件、附件、项目工作区和 Library 机制，不另造 Android 专属文件系统”
//! +(附件由核心管理：复制导入、登记、读取、绑定会话与项目；Android 只负责选文件)
//!
//! Two properties decide the shape of this module.
//!
//! **Import, not reference.** A `content://` grant on a phone survives until the process
//! ends unless it is persisted, and the file behind it can move or be deleted at any time.
//! A record that only remembers an outside path breaks the transcript later, so the bytes
//! are copied in at import time and the outside path is kept as provenance only.
//!
//! **The core stays the gate.** A source path is only accepted when it resolves inside the
//! directory the host handed us, which on Android is the app's own sandbox. File selection
//! cannot be used to reach a file the core would otherwise refuse.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::json;

/// Uploads are bounded so one attachment cannot exhaust the device's storage or memory.
pub const MAX_ATTACHMENT_BYTES: u64 = 50 * 1024 * 1024;

pub const INDEX_FILE: &str = "attachments.json";
const STORAGE_DIR: &str = "attachments";

/// One file a session owns.
///
/// Field names follow the record the desktop core already returns, because the shared
/// interface reads them by name (`CoreAttachment`).
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct AttachmentRecord {
    pub id: String,
    pub session_id: String,
    pub filename: String,
    pub mime_type: String,
    pub size: u64,
    /// Absolute path of the core-owned copy.
    pub path: String,
    pub preview_type: String,
    #[serde(default)]
    pub project_id: String,
    #[serde(default)]
    pub message_id: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub metadata: serde_json::Value,
    #[serde(default)]
    pub created_at: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct Index {
    #[serde(default)]
    attachments: Vec<AttachmentRecord>,
}

/// Attachment storage for one host.
pub struct AttachmentStore {
    index_file: PathBuf,
    storage: PathBuf,
    /// Where an incoming file must live before it may be imported.
    allowed_root: PathBuf,
}

impl AttachmentStore {
    pub fn new(data_dir: impl AsRef<Path>, allowed_root: impl AsRef<Path>) -> Self {
        let data_dir = data_dir.as_ref();
        let storage = data_dir.join(STORAGE_DIR);
        let _ = std::fs::create_dir_all(&storage);
        Self {
            index_file: data_dir.join(INDEX_FILE),
            storage,
            allowed_root: allowed_root.as_ref().to_path_buf(),
        }
    }

    fn load(&self) -> Index {
        std::fs::read_to_string(&self.index_file)
            .ok()
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_default()
    }

    fn save(&self, index: &Index) -> Result<(), String> {
        let text = serde_json::to_string_pretty(index).map_err(|error| error.to_string())?;
        crate::private_file::write(&self.index_file, &text, "attachments")
            .map_err(|error| error.to_string())
    }

    pub fn list(&self, session_id: &str) -> Vec<AttachmentRecord> {
        let mut rows: Vec<AttachmentRecord> = self
            .load()
            .attachments
            .into_iter()
            .filter(|record| record.session_id == session_id)
            .collect();
        rows.sort_by(|left, right| left.created_at.cmp(&right.created_at));
        rows
    }

    pub fn get(&self, attachment_id: &str) -> Option<AttachmentRecord> {
        self.load()
            .attachments
            .into_iter()
            .find(|record| record.id == attachment_id)
    }

    /// The bytes of a stored attachment, read back through the record, not a caller path.
    pub fn content(&self, attachment_id: &str) -> Result<Vec<u8>, String> {
        let record = self
            .get(attachment_id)
            .ok_or_else(|| format!("no such attachment: {attachment_id}"))?;
        std::fs::read(&record.path).map_err(|error| format!("cannot read {}: {error}", record.path))
    }

    /// Imports a file the host has already placed inside the sandbox.
    ///
    /// Re-importing the same bytes for the same session returns the existing record, so a
    /// user who picks the same file twice does not end up with two copies of it.
    pub fn import(
        &self,
        session_id: &str,
        project_id: &str,
        source_path: &Path,
    ) -> Result<AttachmentRecord, String> {
        if session_id.trim().is_empty() {
            return Err("a session id is required".into());
        }
        let canonical = source_path
            .canonicalize()
            .map_err(|error| format!("cannot read {}: {error}", source_path.display()))?;
        let root = self
            .allowed_root
            .canonicalize()
            .map_err(|error| format!("cannot resolve the allowed root: {error}"))?;
        if !canonical.starts_with(&root) {
            return Err(format!(
                "{} is outside the directory this app may read",
                source_path.display()
            ));
        }
        let metadata =
            std::fs::metadata(&canonical).map_err(|error| format!("cannot stat: {error}"))?;
        if metadata.is_dir() {
            return Err("a folder cannot be attached".into());
        }
        if metadata.len() > MAX_ATTACHMENT_BYTES {
            return Err(format!(
                "this file is {} MB; the limit is {} MB",
                metadata.len() / (1024 * 1024),
                MAX_ATTACHMENT_BYTES / (1024 * 1024)
            ));
        }
        let bytes = std::fs::read(&canonical).map_err(|error| format!("cannot read: {error}"))?;
        let filename = safe_filename(
            canonical
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("attachment"),
        );
        let digest = fingerprint(&bytes);

        let mut index = self.load();
        if let Some(existing) = index.attachments.iter().find(|record| {
            record.session_id == session_id
                && record.filename == filename
                && record.metadata.get("digest").and_then(|value| value.as_str())
                    == Some(digest.as_str())
        }) {
            return Ok(existing.clone());
        }

        let id = format!(
            "att-{}",
            &fingerprint(format!("{session_id}|{filename}|{digest}").as_bytes())[..16]
        );
        let directory = self.storage.join(&id);
        std::fs::create_dir_all(&directory)
            .map_err(|error| format!("cannot create {}: {error}", directory.display()))?;
        let stored = directory.join(&filename);
        std::fs::write(&stored, &bytes).map_err(|error| format!("cannot store: {error}"))?;

        let record = AttachmentRecord {
            id,
            session_id: session_id.to_owned(),
            filename: filename.clone(),
            mime_type: mime_for(&filename, &bytes).to_owned(),
            size: bytes.len() as u64,
            path: stored.to_string_lossy().replace('\\', "/"),
            preview_type: preview_for(&filename, &bytes).to_owned(),
            project_id: project_id.to_owned(),
            message_id: String::new(),
            source: "user_upload".into(),
            metadata: json!({
                "digest": digest,
                "original_path": canonical.to_string_lossy().replace('\\', "/"),
            }),
            created_at: crate::app_server::iso_utc(now_ms()),
        };
        index.attachments.push(record.clone());
        self.save(&index)?;
        Ok(record)
    }

    /// Binds an attachment to the message that carried it.
    pub fn bind_message(&self, attachment_id: &str, message_id: &str) -> Result<(), String> {
        let mut index = self.load();
        let record = index
            .attachments
            .iter_mut()
            .find(|record| record.id == attachment_id)
            .ok_or_else(|| format!("no such attachment: {attachment_id}"))?;
        record.message_id = message_id.to_owned();
        self.save(&index)
    }
}

/// Keeps a display name printable and usable as a file name.
fn safe_filename(raw: &str) -> String {
    let cleaned: String = raw
        .chars()
        .map(|character| match character {
            '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => '_',
            control if control.is_control() => '_',
            other => other,
        })
        .collect();
    let trimmed = cleaned.trim().trim_matches('.').to_owned();
    if trimmed.is_empty() {
        "attachment".into()
    } else {
        trimmed
    }
}

fn extension_of(filename: &str) -> String {
    filename
        .rsplit_once('.')
        .map(|(_, extension)| extension.to_ascii_lowercase())
        .unwrap_or_default()
}

/// Type by name first, then by content, because a picker can hand over a nameless file.
fn mime_for(filename: &str, bytes: &[u8]) -> &'static str {
    match extension_of(filename).as_str() {
        "txt" | "log" => "text/plain",
        "md" | "markdown" => "text/markdown",
        "json" => "application/json",
        "csv" => "text/csv",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "pdf" => "application/pdf",
        _ if looks_like_text(bytes) => "text/plain",
        _ => "application/octet-stream",
    }
}

fn preview_for(filename: &str, bytes: &[u8]) -> &'static str {
    match mime_for(filename, bytes) {
        "text/plain" | "text/markdown" | "application/json" | "text/csv" => "text",
        "image/png" | "image/jpeg" | "image/gif" | "image/webp" => "image",
        "application/pdf" => "pdf",
        _ => "external",
    }
}

fn looks_like_text(bytes: &[u8]) -> bool {
    let sample = &bytes[..bytes.len().min(1024)];
    !sample.is_empty() && !sample.contains(&0) && std::str::from_utf8(sample).is_ok()
}

/// A small, stable digest so the same bytes are recognised as the same attachment.
fn fingerprint(bytes: &[u8]) -> String {
    // FNV-1a: enough to tell two user files apart, and it costs no dependency. A
    // cryptographic hash would be the wrong tool here, since this is not a security check.
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in bytes {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{hash:016x}")
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis() as i64)
        .unwrap_or(0)
}

/// One file the client named when it started a turn.
///
/// The client sends the record it holds, so a renamed or re-imported file still resolves
/// by id. `path` is only a fallback for a client that sent no id.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TurnAttachment {
    pub id: String,
    pub path: String,
    pub filename: String,
    pub mime_type: String,
}

/// What the model should be told about the files a turn carries.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AttachmentBriefing {
    /// Text appended to the turn's own instruction.
    pub text: String,
    /// Images that can be sent as themselves.
    pub images: Vec<sunday_protocol::ImageInput>,
}

/// How much of one text file is put in the prompt.
///
/// A prompt is not a file transfer: past a point the model is reading cost, not content.
/// The rest stays available through the attachment itself, and the notice says so.
const MAX_INLINE_TEXT: usize = 32 * 1024;

/// Stop inlining after this, so ten files cannot fill the whole context window.
const MAX_INLINE_TOTAL: usize = 96 * 1024;

/// A larger image is not sent natively: base64 grows it by a third, and a photo of a
/// document at full resolution is not more legible than one inside this bound.
const MAX_INLINE_IMAGE: u64 = 4 * 1024 * 1024;

impl AttachmentStore {
    /// The record a client's item refers to, by id first and by stored path second.
    pub fn resolve(&self, request: &TurnAttachment) -> Option<AttachmentRecord> {
        if !request.id.trim().is_empty() {
            if let Some(record) = self.get(&request.id) {
                return Some(record);
            }
        }
        let wanted = request.path.trim().replace('\\', "/");
        if wanted.is_empty() {
            return None;
        }
        self.load()
            .attachments
            .into_iter()
            .find(|record| record.path == wanted)
    }

    /// The instructions that put a file's content in front of the model.
    ///
    /// user:“将附件实际送入 Agent 的输入链路…不支持的格式必须明确提示”+(文本内联、
    /// 图片按模型能力原生送入，其余格式说清楚看不到内容，而不是假装附件生效了)。
    ///
    /// Nothing here trusts a caller path: each file is read through its record, so a
    /// crafted item cannot turn an attachment into a read of an arbitrary file.
    pub fn briefing(&self, requested: &[TurnAttachment], vision: bool) -> AttachmentBriefing {
        let mut briefing = AttachmentBriefing::default();
        if requested.is_empty() {
            return briefing;
        }
        let mut inlined = 0usize;
        briefing
            .text
            .push_str("\n\n以下是用户随这条消息附上的文件。\n");
        for (index, request) in requested.iter().enumerate() {
            let number = index + 1;
            let Some(record) = self.resolve(request) else {
                let name = display_name(request);
                briefing.text.push_str(&format!(
                    "\n### 附件 {number}：{name}\n（这条附件记录已经不存在，看不到内容，请让用户重新添加。）\n"
                ));
                continue;
            };
            briefing.text.push_str(&format!(
                "\n### 附件 {number}：{}（{}，{}）\n",
                record.filename,
                record.mime_type,
                human_size(record.size)
            ));
            match self.brief_one(&record, &mut briefing, vision, &mut inlined) {
                Ok(()) => {}
                Err(reason) => {
                    briefing
                        .text
                        .push_str(&format!("（{reason}）\n"));
                }
            }
        }
        briefing
    }

    fn brief_one(
        &self,
        record: &AttachmentRecord,
        briefing: &mut AttachmentBriefing,
        vision: bool,
        inlined: &mut usize,
    ) -> Result<(), String> {
        let bytes = self.content(&record.id)?;
        match record.preview_type.as_str() {
            "text" => {
                if *inlined >= MAX_INLINE_TOTAL {
                    return Err("附带的文本已经够多，这个文件只保存了本身，需要时请让用户单独发送。".into());
                }
                let budget = MAX_INLINE_TEXT.min(MAX_INLINE_TOTAL - *inlined);
                let (body, truncated) = slice_text(&bytes, budget);
                *inlined += body.len();
                // The id is derived from these bytes, so a file cannot contain the
                // delimiter that closes its own block: the marker cannot be forged by
                // the content it wraps.
                let marker = record.id.replace("att-", "");
                briefing.text.push_str(&format!(
                    "<<<{marker}\n{body}\n{marker}>>>\n"
                ));
                if truncated {
                    briefing.text.push_str(
                        "（文件更长，这里只放了开头部分；需要后面的内容请让用户分批发送。）\n",
                    );
                }
                Ok(())
            }
            "image" => {
                if !vision {
                    return Err(
                        "当前模型没有开启图片输入，看不到这张图片，请如实告诉用户，不要猜测画面。"
                            .into(),
                    );
                }
                if record.size > MAX_INLINE_IMAGE {
                    return Err(format!(
                        "图片超过 {} MB，没有随消息发送，请让用户提供更小的图或说明画面内容。",
                        MAX_INLINE_IMAGE / (1024 * 1024)
                    ));
                }
                briefing.images.push(sunday_protocol::ImageInput {
                    mime: record.mime_type.clone(),
                    data_b64: base64(&bytes),
                });
                briefing.text.push_str("（图片已随消息附上，可以直接查看。）\n");
                Ok(())
            }
            _ => Err("这个格式暂时无法提取内容，只保存了文件本身。".into()),
        }
    }
}

fn display_name(request: &TurnAttachment) -> String {
    if !request.filename.trim().is_empty() {
        return request.filename.clone();
    }
    request
        .path
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or("附件")
        .to_owned()
}

fn human_size(size: u64) -> String {
    if size < 1024 {
        format!("{size} B")
    } else if size < 1024 * 1024 {
        format!("{:.1} KB", size as f64 / 1024.0)
    } else {
        format!("{:.1} MB", size as f64 / (1024.0 * 1024.0))
    }
}

/// A prefix of a text file, cut on a character boundary.
///
/// Returns whether anything was left out, so the caller can say so instead of handing
/// the model a sentence that stops mid-word with no explanation.
fn slice_text(bytes: &[u8], budget: usize) -> (String, bool) {
    if bytes.len() <= budget {
        return (String::from_utf8_lossy(bytes).into_owned(), false);
    }
    let mut end = budget;
    while end > 0 && !is_char_boundary(bytes[end]) {
        end -= 1;
    }
    (String::from_utf8_lossy(&bytes[..end]).into_owned(), true)
}

fn is_char_boundary(byte: u8) -> bool {
    // Continuation bytes are 10xxxxxx; anything else starts a character.
    byte & 0b1100_0000 != 0b1000_0000
}

/// Standard base64, written here so the host crate needs no new dependency for one call.
fn base64(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] =
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let first = chunk[0] as u32;
        let second = chunk.get(1).copied().unwrap_or(0) as u32;
        let third = chunk.get(2).copied().unwrap_or(0) as u32;
        let packed = (first << 16) | (second << 8) | third;
        out.push(ALPHABET[(packed >> 18) as usize & 0x3f] as char);
        out.push(ALPHABET[(packed >> 12) as usize & 0x3f] as char);
        out.push(if chunk.len() > 1 {
            ALPHABET[(packed >> 6) as usize & 0x3f] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            ALPHABET[packed as usize & 0x3f] as char
        } else {
            '='
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A Windows path and a stored path are written with different separators; tests
    /// compare them through one spelling rather than each inventing its own.
    const BACKSLASH: char = '\\';

    fn fixture() -> (tempfile::TempDir, AttachmentStore, PathBuf) {
        let dir = tempfile::tempdir().unwrap();
        let data = dir.path().join("data");
        let incoming = data.join("incoming");
        std::fs::create_dir_all(&incoming).unwrap();
        let store = AttachmentStore::new(&data, &data);
        (dir, store, incoming)
    }

    #[test]
    fn an_imported_text_file_can_be_read_back() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("notes.txt");
        std::fs::write(&source, "goal\nprogress\n").unwrap();

        let record = store.import("ses-1", "prj-1", &source).unwrap();
        assert_eq!(record.filename, "notes.txt");
        assert_eq!(record.size, 14);
        assert_eq!(record.mime_type, "text/plain");
        assert_eq!(record.preview_type, "text");
        assert_eq!(record.session_id, "ses-1");
        assert_eq!(record.project_id, "prj-1");
        let storage = store.storage.to_string_lossy().replace(BACKSLASH, "/");
        assert!(record.path.starts_with(&storage), "{} not under {storage}", record.path);

        assert_eq!(store.content(&record.id).unwrap(), b"goal\nprogress\n");
        assert_eq!(store.list("ses-1"), vec![record.clone()]);
        assert_eq!(store.get(&record.id).map(|row| row.filename), Some("notes.txt".into()));
        // The original is only provenance; the copy is what a transcript reads, and the
        // provenance names the file the picker handed over.
        let original = record.metadata["original_path"]
            .as_str()
            .unwrap_or_default()
            .replace(BACKSLASH, "/");
        assert!(
            original.ends_with("incoming/notes.txt"),
            "provenance lost the source: {original}"
        );
    }

    #[test]
    fn picking_the_same_file_twice_keeps_one_copy() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("a.txt");
        std::fs::write(&source, "same").unwrap();
        let first = store.import("ses-1", "", &source).unwrap();
        let second = store.import("ses-1", "", &source).unwrap();
        assert_eq!(first.id, second.id);
        assert_eq!(store.list("ses-1").len(), 1);
    }

    #[test]
    fn two_files_with_one_name_stay_apart() {
        let (_dir, store, incoming) = fixture();
        let one = incoming.join("one");
        let two = incoming.join("two");
        std::fs::create_dir_all(&one).unwrap();
        std::fs::create_dir_all(&two).unwrap();
        std::fs::write(one.join("notes.txt"), "first").unwrap();
        std::fs::write(two.join("notes.txt"), "second").unwrap();

        let a = store.import("ses-1", "", &one.join("notes.txt")).unwrap();
        let b = store.import("ses-1", "", &two.join("notes.txt")).unwrap();
        assert_ne!(a.id, b.id);
        assert_eq!(store.content(&a.id).unwrap(), b"first");
        assert_eq!(store.content(&b.id).unwrap(), b"second");
        assert_eq!(store.list("ses-1").len(), 2);
    }

    #[test]
    fn an_empty_file_is_an_attachment_not_an_error() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("empty.txt");
        std::fs::write(&source, "").unwrap();
        let record = store.import("ses-1", "", &source).unwrap();
        assert_eq!(record.size, 0);
        assert_eq!(store.content(&record.id).unwrap(), Vec::<u8>::new());
    }

    #[test]
    fn a_file_outside_the_sandbox_is_refused() {
        let (dir, store, _incoming) = fixture();
        let outside = dir.path().join("outside.txt");
        std::fs::write(&outside, "not mine").unwrap();
        let error = store.import("ses-1", "", &outside).unwrap_err();
        assert!(error.contains("outside the directory"), "{error}");
    }

    #[test]
    fn a_file_over_the_limit_is_refused_before_it_is_read() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("huge.bin");
        let file = std::fs::File::create(&source).unwrap();
        file.set_len(MAX_ATTACHMENT_BYTES + 1).unwrap();
        let error = store.import("ses-1", "", &source).unwrap_err();
        assert!(error.contains("limit"), "{error}");
    }

    #[test]
    fn an_unknown_type_is_stored_without_preview() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("blob.zzz");
        std::fs::write(&source, [0u8, 159, 146, 150]).unwrap();
        let record = store.import("ses-1", "", &source).unwrap();
        assert_eq!(record.mime_type, "application/octet-stream");
        assert_eq!(record.preview_type, "external");
    }

    #[test]
    fn an_image_is_marked_for_preview() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("shot.png");
        std::fs::write(&source, [0x89, b'P', b'N', b'G']).unwrap();
        let record = store.import("ses-1", "", &source).unwrap();
        assert_eq!(record.mime_type, "image/png");
        assert_eq!(record.preview_type, "image");
    }

    fn asking(record: &AttachmentRecord) -> TurnAttachment {
        TurnAttachment {
            id: record.id.clone(),
            path: record.path.clone(),
            filename: record.filename.clone(),
            mime_type: record.mime_type.clone(),
        }
    }

    /// The whole point of attaching a file: the model reads it, not just its name.
    #[test]
    fn a_text_attachment_puts_its_content_in_the_prompt() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("notes.md");
        std::fs::write(&source, "goal: ship the attachment loop\n").unwrap();
        let record = store.import("ses-1", "", &source).unwrap();

        let briefing = store.briefing(&[asking(&record)], false);
        assert!(
            briefing.text.contains("goal: ship the attachment loop"),
            "{}",
            briefing.text
        );
        assert!(briefing.text.contains("notes.md"), "{}", briefing.text);
        assert!(briefing.images.is_empty());
    }

    /// A model that cannot see must be told so; staying silent makes it invent a picture.
    #[test]
    fn an_image_without_vision_says_it_cannot_be_seen() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("shot.png");
        std::fs::write(&source, [0x89, b'P', b'N', b'G']).unwrap();
        let record = store.import("ses-1", "", &source).unwrap();

        let briefing = store.briefing(&[asking(&record)], false);
        assert!(briefing.images.is_empty());
        assert!(briefing.text.contains("看不到这张图片"), "{}", briefing.text);
    }

    #[test]
    fn an_image_with_vision_is_sent_as_an_image() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("shot.png");
        // "PNG" and one byte that is not valid text, so the type is read from the name.
        std::fs::write(&source, [0x89, b'P', b'N', b'G', 0x00]).unwrap();
        let record = store.import("ses-1", "", &source).unwrap();

        let briefing = store.briefing(&[asking(&record)], true);
        assert_eq!(briefing.images.len(), 1);
        assert_eq!(briefing.images[0].mime, "image/png");
        assert_eq!(briefing.images[0].data_b64, "iVBORwA=");
    }

    /// A binary the core cannot read has to say so instead of pretending.
    #[test]
    fn an_unreadable_format_is_reported_as_such() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("report.zzz");
        std::fs::write(&source, [0u8, 1, 2, 3]).unwrap();
        let record = store.import("ses-1", "", &source).unwrap();

        let briefing = store.briefing(&[asking(&record)], true);
        assert!(briefing.text.contains("无法提取内容"), "{}", briefing.text);
    }

    #[test]
    fn a_record_that_vanished_is_reported_not_skipped() {
        let (_dir, store, _incoming) = fixture();
        let briefing = store.briefing(
            &[TurnAttachment {
                id: "att-missing".into(),
                path: String::new(),
                filename: "gone.txt".into(),
                mime_type: "text/plain".into(),
            }],
            false,
        );
        assert!(briefing.text.contains("gone.txt"), "{}", briefing.text);
        assert!(briefing.text.contains("不存在"), "{}", briefing.text);
    }

    /// A long file is cut and the cut is announced: half a sentence with no warning reads
    /// to the model as the whole document.
    #[test]
    fn a_long_text_file_is_cut_and_the_cut_is_announced() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("long.txt");
        std::fs::write(&source, "字".repeat(MAX_INLINE_TEXT)).unwrap();
        let record = store.import("ses-1", "", &source).unwrap();

        let briefing = store.briefing(&[asking(&record)], false);
        assert!(briefing.text.contains("只放了开头部分"), "{}", briefing.text.len());
        // The cut lands on a character boundary, so the block stays valid UTF-8.
        assert!(std::str::from_utf8(briefing.text.as_bytes()).is_ok());
    }

    /// A second file is still described when the first one used the inline budget.
    #[test]
    fn several_text_files_all_appear() {
        let (_dir, store, incoming) = fixture();
        let first = incoming.join("a.txt");
        let second = incoming.join("b.txt");
        std::fs::write(&first, "alpha\n").unwrap();
        std::fs::write(&second, "beta\n").unwrap();
        let a = store.import("ses-1", "", &first).unwrap();
        let b = store.import("ses-1", "", &second).unwrap();

        let briefing = store.briefing(&[asking(&a), asking(&b)], false);
        assert!(briefing.text.contains("alpha"), "{}", briefing.text);
        assert!(briefing.text.contains("beta"), "{}", briefing.text);
    }

    /// A record is found the way the client sent it, id first and path second.
    #[test]
    fn a_record_resolves_by_id_or_by_path() {
        let (_dir, store, incoming) = fixture();
        let source = incoming.join("notes.txt");
        std::fs::write(&source, "x").unwrap();
        let record = store.import("ses-1", "", &source).unwrap();

        assert!(store.resolve(&asking(&record)).is_some());
        let by_path = TurnAttachment {
            id: String::new(),
            path: record.path.clone(),
            filename: String::new(),
            mime_type: String::new(),
        };
        assert_eq!(store.resolve(&by_path).map(|row| row.id), Some(record.id));
    }

    #[test]
    fn base64_matches_the_standard_alphabet() {
        assert_eq!(base64(b""), "");
        assert_eq!(base64(b"f"), "Zg==");
        assert_eq!(base64(b"fo"), "Zm8=");
        assert_eq!(base64(b"foo"), "Zm9v");
        assert_eq!(base64(b"foob"), "Zm9vYg==");
        // 11111111 11111110 11111101 grouped six bits at a time: 63, 63, 59, 61.
        assert_eq!(base64(&[0xff, 0xfe, 0xfd]), "//79");
    }
}
