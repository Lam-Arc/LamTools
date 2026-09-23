//! Scoped, file-backed persistence for editable Workflow V2 documents.
//! Execution and scheduling deliberately live outside this boundary.

use crate::workflow_document::{
    canonicalize_document, document_from_workflow_def, is_v2_document, workflow_def_from_document,
    WorkflowDocumentError,
};
use serde_json::{json, Value};
use std::collections::HashSet;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use thiserror::Error;
use uuid::Uuid;

#[derive(Debug, Error)]
pub enum WorkflowStoreError {
    #[error("workflow revision conflict: expected {expected}, current {current}")]
    Conflict { expected: u64, current: u64 },
    #[error("workflow path escapes its scope: {0}")]
    Confinement(PathBuf),
    #[error("workflow name is required")]
    EmptyName,
    #[error("workflow name or id collides with another workflow")]
    Collision,
    #[error(transparent)]
    Document(#[from] WorkflowDocumentError),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}

pub type StoreResult<T> = Result<T, WorkflowStoreError>;

/// `global_root` is the host's `.lam` directory. Additional global roots
/// participate in scoped reads and deletes; writes use `global_root`.
#[derive(Debug, Clone)]
pub struct WorkflowStore {
    global_root: PathBuf,
    explicit_roots: Vec<PathBuf>,
}

impl WorkflowStore {
    pub fn new(global_root: impl Into<PathBuf>) -> Self {
        Self {
            global_root: global_root.into(),
            explicit_roots: Vec::new(),
        }
    }

    pub fn with_explicit_roots(mut self, roots: impl IntoIterator<Item = PathBuf>) -> Self {
        self.explicit_roots = roots.into_iter().collect();
        self
    }

    /// Discover global and optional project workflows, with each entry read
    /// from its canonical document when one exists.
    pub fn list(&self, work_root: Option<&Path>) -> StoreResult<Vec<Value>> {
        let mut items = self.list_scoped(None)?;
        if let Some(root) = work_root {
            items.extend(self.list_scoped(Some(root))?);
        }
        items.sort_by(|a, b| name(a).cmp(name(b)));
        Ok(items)
    }

    /// A project scope does not see global entries, including same-name ones.
    pub fn list_scoped(&self, work_root: Option<&Path>) -> StoreResult<Vec<Value>> {
        let mut items = Vec::new();
        for entry in self.scoped_entries(work_root)? {
            if let Some(doc) = read_entry(&entry)? {
                items.push(doc);
            }
        }
        items.sort_by(|a, b| name(a).cmp(name(b)));
        Ok(items)
    }

    pub fn get(&self, workflow_name: &str, work_root: Option<&Path>) -> StoreResult<Option<Value>> {
        let target = workflow_name.trim();
        if target.is_empty() {
            return Ok(None);
        }
        let items = self.list_scoped(work_root)?;
        if let Some(exact) = items.iter().find(|doc| name(doc) == target) {
            return Ok(Some(exact.clone()));
        }
        // Slug lookup is only for ASCII session-derived names. A missing
        // Unicode name must not alias a different, still-readable workflow.
        if !target.is_ascii() {
            return Ok(None);
        }
        let slug = ascii_slug(target);
        let mut matches = items
            .into_iter()
            .filter(|doc| ascii_slug(name(doc)) == slug);
        let first = matches.next();
        Ok(if matches.next().is_none() {
            first
        } else {
            None
        })
    }

    pub fn get_by_id(&self, id: &str, work_root: Option<&Path>) -> StoreResult<Option<Value>> {
        if id.trim().is_empty() {
            return Ok(None);
        }
        Ok(self
            .list_scoped(work_root)?
            .into_iter()
            .find(|doc| doc["resource"]["id"] == id))
    }

    /// Compare-and-swap the named workflow. The process-wide lock protects
    /// independent store instances in this process; the final document is
    /// written by synced temporary file and atomic replacement.
    pub fn save_document(
        &self,
        document: &Value,
        work_root: Option<&Path>,
        expected_revision: Option<u64>,
    ) -> StoreResult<Value> {
        let _guard = mutation_lock()
            .lock()
            .expect("workflow mutation lock poisoned");
        let mut doc = canonicalize_document(document)?;
        // The document is caller-supplied data. Only the explicit argument
        // selects the repository; None always means the global scope.
        let scope = work_root;
        let entries = self.scoped_entries(scope)?;
        let mut by_name = None;
        let mut by_id = None;
        for entry in entries {
            if let Some(existing) = read_entry(&entry)? {
                if name(&existing) == name(&doc) {
                    by_name = Some((entry.clone(), existing.clone()));
                }
                if existing["resource"]["id"] == doc["resource"]["id"] {
                    by_id = Some((entry, existing));
                }
            }
        }
        if by_name.as_ref().is_some_and(|(_, named)| {
            by_id.as_ref().is_some_and(|(_, identified)| {
                named["resource"]["id"] != identified["resource"]["id"]
            })
        }) {
            return Err(WorkflowStoreError::Collision);
        }
        let current_entry = by_name.or(by_id);
        let current = current_entry.as_ref().map(|(_, value)| value);
        let current_revision = current.map(|doc| revision(doc)).unwrap_or(0);
        if expected_revision.is_some_and(|expected| expected != current_revision) {
            return Err(WorkflowStoreError::Conflict {
                expected: expected_revision.unwrap(),
                current: current_revision,
            });
        }
        if let Some(current) = &current {
            doc["resource"]["id"] = current["resource"]["id"].clone();
            doc["resource"]["created_at"] = current["resource"]["created_at"].clone();
            doc["resource"]["revision"] = json!(current_revision.saturating_add(1).max(1));
        } else {
            doc["resource"]["revision"] = json!(revision(&doc).max(1));
        }
        doc["resource"]["work_root"] = json!(scope
            .map(|p| p.to_string_lossy().into_owned())
            .unwrap_or_default());
        doc["resource"]["updated_at"] = json!(now_string());
        doc = canonicalize_document(&doc)?;

        let writable = self.writable_dir(scope)?;
        ensure_directory(&writable)?;
        let previous = current_entry.map(|(path, _)| path);
        let target = match previous.as_ref() {
            Some(path)
                if path.is_dir()
                    && path.parent() == Some(writable.as_path())
                    && read_entry(path)?.is_some_and(|existing| name(&existing) == name(&doc)) =>
            {
                path.clone()
            }
            _ => unique_folder(&writable, name(&doc))?,
        };
        confined_child(&writable, &target)?;
        ensure_directory(&target)?;
        let canonical = target.join("workflow.json");
        reject_symlink(&canonical)?;
        // Canonical V2 is committed last; legacy siblings are for older readers.
        write_legacy_projection(&target, &doc)?;
        write_atomic(&canonical, &serde_json::to_vec_pretty(&doc)?)?;
        if let Some(previous) = previous {
            if previous != target
                && previous.is_dir()
                && previous.parent() == Some(writable.as_path())
            {
                confined_child(&writable, &previous)?;
                fs::remove_dir_all(previous)?;
            }
        }
        Ok(doc)
    }

    pub fn delete(&self, workflow_name: &str, work_root: Option<&Path>) -> StoreResult<bool> {
        let _guard = mutation_lock()
            .lock()
            .expect("workflow mutation lock poisoned");
        let target = workflow_name.trim();
        if target.is_empty() {
            return Ok(false);
        }
        let candidates = self.scoped_entries(work_root)?;
        let mut found = None;
        let mut slug_matches = Vec::new();
        for entry in candidates {
            if let Some(doc) = read_entry(&entry)? {
                if name(&doc) == target {
                    found = Some(entry);
                    break;
                }
                if target.is_ascii() && ascii_slug(name(&doc)) == ascii_slug(target) {
                    slug_matches.push(entry);
                }
            }
        }
        let selected = found.or_else(|| {
            if slug_matches.len() == 1 {
                slug_matches.pop()
            } else {
                None
            }
        });
        let Some(entry) = selected else {
            return Ok(false);
        };
        let parent = entry
            .parent()
            .ok_or_else(|| WorkflowStoreError::Confinement(entry.clone()))?;
        confined_child(parent, &entry)?;
        if entry.is_dir() {
            fs::remove_dir_all(&entry)?;
        } else {
            fs::remove_file(&entry)?;
        }
        Ok(true)
    }

    fn writable_dir(&self, work_root: Option<&Path>) -> StoreResult<PathBuf> {
        let root = match work_root {
            Some(root) => root.join(".lam"),
            None => self.global_root.clone(),
        };
        reject_symlink_components(&root)?;
        Ok(root.join("workflows"))
    }

    fn scoped_entries(&self, work_root: Option<&Path>) -> StoreResult<Vec<PathBuf>> {
        let mut roots = Vec::new();
        if let Some(root) = work_root {
            let lam = root.join(".lam");
            reject_symlink_components(&lam)?;
            if lam.is_dir() {
                roots.push(lam.join("workflows"));
                // Python discovers nested `.lam/**/workflows` trees too.
                find_nested_workflows(&lam, &mut roots)?;
            }
        } else {
            roots.push(self.global_root.join("workflows"));
            roots.extend(
                self.explicit_roots
                    .iter()
                    .map(|root| root.join("workflows")),
            );
        }
        let mut seen = HashSet::new();
        let mut entries = Vec::new();
        for root in roots {
            reject_symlink_components(&root)?;
            for entry in scan_dir(&root)? {
                if seen.insert(entry.clone()) {
                    entries.push(entry);
                }
            }
        }
        Ok(entries)
    }
}

fn mutation_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}
fn name(doc: &Value) -> &str {
    doc["resource"]["name"].as_str().unwrap_or("")
}
fn revision(doc: &Value) -> u64 {
    doc["resource"]["revision"].as_u64().unwrap_or(0)
}
fn now_string() -> String {
    chrono::Utc::now().to_rfc3339()
}
fn safe_filename(name: &str) -> String {
    let value = name
        .chars()
        .map(|c| {
            if c.is_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect::<String>();
    let value = value.trim_matches('_');
    if value.is_empty() {
        "workflow".into()
    } else {
        value.into()
    }
}
fn ascii_slug(name: &str) -> String {
    let value = name
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect::<String>();
    let value = value.trim_matches('_');
    if value.is_empty() {
        "workflow".into()
    } else {
        value.into()
    }
}

fn reject_symlink(path: &Path) -> StoreResult<()> {
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.file_type().is_symlink() => {
            Err(WorkflowStoreError::Confinement(path.to_path_buf()))
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}
fn reject_symlink_components(path: &Path) -> StoreResult<()> {
    for ancestor in path.ancestors() {
        reject_symlink(ancestor)?;
    }
    Ok(())
}
fn confined_child(parent: &Path, child: &Path) -> StoreResult<()> {
    if child.parent() != Some(parent) || child.file_name().is_none() {
        return Err(WorkflowStoreError::Confinement(child.to_path_buf()));
    }
    reject_symlink_components(child)
}
fn ensure_directory(path: &Path) -> StoreResult<()> {
    reject_symlink_components(path)?;
    fs::create_dir_all(path)?;
    reject_symlink_components(path)
}
fn scan_dir(root: &Path) -> StoreResult<Vec<PathBuf>> {
    if !root.exists() {
        return Ok(Vec::new());
    }
    reject_symlink_components(root)?;
    let mut entries = Vec::new();
    for item in fs::read_dir(root)? {
        let item = item?;
        let path = item.path();
        if item.file_type()?.is_symlink() {
            continue;
        }
        if path.is_dir() {
            if path.join("workflow.json").is_file() || path.join("config.json").is_file() {
                entries.push(path);
            }
        } else if path.extension().is_some_and(|ext| ext == "json")
            && path.file_name().is_some_and(|n| n != "config.json")
        {
            if !root
                .join(path.file_stem().unwrap())
                .join("workflow.json")
                .is_file()
            {
                entries.push(path);
            }
        }
    }
    entries.sort();
    Ok(entries)
}
fn find_nested_workflows(root: &Path, found: &mut Vec<PathBuf>) -> StoreResult<()> {
    for item in fs::read_dir(root)? {
        let item = item?;
        if !item.file_type()?.is_dir() {
            continue;
        }
        let path = item.path();
        if path.file_name().is_some_and(|n| n == "workflows") {
            found.push(path);
        } else {
            find_nested_workflows(&path, found)?;
        }
    }
    Ok(())
}
fn read_json(path: &Path) -> StoreResult<Value> {
    reject_symlink(path)?;
    let mut bytes = Vec::new();
    File::open(path)?.read_to_end(&mut bytes)?;
    Ok(serde_json::from_slice(&bytes)?)
}
fn read_entry(path: &Path) -> StoreResult<Option<Value>> {
    reject_symlink_components(path)?;
    if path.is_dir() {
        let canonical = path.join("workflow.json");
        if canonical.exists() {
            // Corrupt canonical content must never fall back to stale legacy files.
            return Ok(read_json(&canonical)
                .ok()
                .filter(is_v2_document)
                .and_then(|value| canonicalize_document(&value).ok()));
        }
        let config = path.join("config.json");
        if !config.is_file() {
            return Ok(None);
        }
        let Ok(mut legacy) = read_json(&config) else {
            return Ok(None);
        };
        let mut nodes = Vec::new();
        for item in fs::read_dir(path)? {
            let item = item?;
            if !item.file_type()?.is_file() || item.file_name() == "config.json" {
                continue;
            }
            if item.path().extension().is_some_and(|ext| ext == "json") {
                if let Ok(node) = read_json(&item.path()) {
                    if node.is_object() {
                        nodes.push(node);
                    }
                }
            }
        }
        if let Some(obj) = legacy.as_object_mut() {
            ensure_legacy_id(obj, path)?;
            obj.insert("nodes".into(), Value::Array(nodes));
            if !obj
                .get("edges")
                .is_some_and(|edges| edges.as_array().is_some_and(|array| !array.is_empty()))
            {
                obj.insert(
                    "edges".into(),
                    parse_map(obj.get("map").and_then(Value::as_str).unwrap_or("")),
                );
            }
        }
        return Ok(document_from_workflow_def(&legacy).ok());
    }
    let Ok(mut legacy) = read_json(path) else {
        return Ok(None);
    };
    if let Some(obj) = legacy.as_object_mut() {
        ensure_legacy_id(obj, path)?;
    }
    Ok(document_from_workflow_def(&legacy).ok())
}
fn ensure_legacy_id(obj: &mut serde_json::Map<String, Value>, path: &Path) -> StoreResult<()> {
    if obj
        .get("id")
        .and_then(Value::as_str)
        .is_some_and(|id| !id.is_empty())
    {
        return Ok(());
    }
    let seed = legacy_id_seed(&fs::canonicalize(path)?);
    obj.insert(
        "id".into(),
        json!(Uuid::new_v5(&Uuid::NAMESPACE_URL, seed.as_bytes())
            .simple()
            .to_string()),
    );
    Ok(())
}
fn legacy_id_seed(path: &Path) -> String {
    let text = path.to_string_lossy().into_owned();
    #[cfg(windows)]
    {
        // std::fs::canonicalize adds the Windows extended-path prefix;
        // Python Path.resolve() (the legacy ID seed) does not retain it.
        if let Some(unc) = text.strip_prefix(r"\\?\UNC\") {
            return format!(r"\\{unc}");
        }
        if let Some(drive_path) = text.strip_prefix(r"\\?\") {
            return drive_path.to_owned();
        }
    }
    text
}
fn parse_map(text: &str) -> Value {
    Value::Array(
        text.lines()
            .filter_map(|line| {
                let line = line.trim();
                if line.is_empty() || line.starts_with('#') {
                    return None;
                }
                let (left, right) = line.split_once("->")?;
                if right.contains("->") {
                    return None;
                }
                let (source, source_port) = parse_map_endpoint(left)?;
                let (target, target_port) = parse_map_endpoint(right)?;
                Some(json!({"id": format!("e-{source}-{source_port}-{target}-{target_port}"), "source": source, "source_port": source_port, "target": target, "target_port": target_port}))
            })
            .collect(),
    )
}
fn parse_map_endpoint(text: &str) -> Option<(&str, &str)> {
    let pieces = text.trim().split('.').collect::<Vec<_>>();
    if !(2..=3).contains(&pieces.len())
        || pieces
            .iter()
            .any(|part| part.is_empty() || part.chars().any(char::is_whitespace))
    {
        return None;
    }
    Some((pieces[0], pieces[1]))
}
fn unique_folder(root: &Path, name: &str) -> StoreResult<PathBuf> {
    let base = safe_filename(name);
    for index in 1..=10_000 {
        let filename = if index == 1 {
            base.clone()
        } else {
            format!("{base}-{index}")
        };
        let path = root.join(filename);
        reject_symlink(&path)?;
        if !path.exists() {
            return Ok(path);
        }
    }
    Err(WorkflowStoreError::Collision)
}
fn write_legacy_projection(folder: &Path, doc: &Value) -> StoreResult<()> {
    let legacy = workflow_def_from_document(doc)?;
    let mut config = legacy.clone();
    let nodes = config
        .as_object_mut()
        .and_then(|obj| obj.remove("nodes"))
        .unwrap_or(json!([]));
    write_atomic(
        &folder.join("config.json"),
        &serde_json::to_vec_pretty(&config)?,
    )?;
    let mut written_names = HashSet::new();
    written_names.insert("config.json".to_string());
    written_names.insert("workflow.json".to_string());
    if let Some(nodes) = nodes.as_array() {
        for node in nodes {
            let id = node["id"].as_str().unwrap_or("");
            if id.is_empty() {
                continue;
            }
            let base = safe_filename(id);
            let mut candidate = format!("{base}.json");
            let mut index = 2;
            while written_names.contains(&candidate) {
                candidate = format!("{base}-{index}.json");
                index += 1;
            }
            written_names.insert(candidate.clone());
            let path = folder.join(candidate);
            confined_child(folder, &path)?;
            write_atomic(&path, &serde_json::to_vec_pretty(node)?)?;
        }
    }
    Ok(())
}
fn write_atomic(path: &Path, bytes: &[u8]) -> StoreResult<()> {
    reject_symlink(path)?;
    let parent = path
        .parent()
        .ok_or_else(|| WorkflowStoreError::Confinement(path.to_path_buf()))?;
    let temp = parent.join(format!(
        ".{}.{}.tmp",
        path.file_name().unwrap().to_string_lossy(),
        Uuid::new_v4()
    ));
    let result = (|| -> StoreResult<()> {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        atomic_replace(&temp, path)?;
        sync_directory(parent)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}
#[cfg(not(windows))]
fn atomic_replace(from: &Path, to: &Path) -> std::io::Result<()> {
    fs::rename(from, to)
}
#[cfg(windows)]
fn atomic_replace(from: &Path, to: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "Kernel32")]
    extern "system" {
        fn MoveFileExW(from: *const u16, to: *const u16, flags: u32) -> i32;
    }
    let from = from
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    let to = to
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    // MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
    if unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), 0x1 | 0x8) } == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}
#[cfg(unix)]
fn sync_directory(path: &Path) -> std::io::Result<()> {
    File::open(path)?.sync_all()
}
#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> std::io::Result<()> {
    Ok(())
}
