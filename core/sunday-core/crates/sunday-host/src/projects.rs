//! Projects, sessions and their files, served to the existing UI.
//!
//! The desktop UI talks to the Python core over HTTP. The Android host runs the Rust
//! core in-process, which speaks `core.app_server.v1` and has no HTTP surface, so every
//! project and file call died at the transport with "cannot be served". That is the wall
//! between a user and their first task, and this module is what removes it.
//!
//! Three decisions worth stating.
//!
//! **A session is a thread.** The id handed to the UI as a session id is the id the core
//! uses as a thread id, so opening a session and asking for its history are the same
//! thing the agent already does. No second identity to keep in sync.
//!
//! **Everything lives under one root.** A project's `work_root` must resolve inside the
//! directory the host grants. Android's URI permission model is not a path model, and
//! letting a typed path point anywhere would be exactly the bypass that model exists to
//! prevent. SAF, when it arrives, hands out a root; this rule stays the same underneath.
//!
//! **Files go through the same policy as the tools.** A read from the UI and a read from
//! `read_file` use the same `LocalFiles` and the same `PathPolicy`, so the UI cannot show
//! a file the agent is forbidden to read.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use sunday_platform::{LocalFiles, PathPolicy};

pub const PROJECTS_FILE: &str = "projects.json";

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct Project {
    pub id: String,
    pub name: String,
    pub work_root: String,
    #[serde(default)]
    pub icon_key: String,
    #[serde(default)]
    pub color_key: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProjectSession {
    pub id: String,
    /// The project this session belongs to. Also exposed as `groupId`, which is the
    /// name the shared sidebar groups by.
    pub project_id: String,
    #[serde(rename = "groupId", default)]
    pub group_id: String,
    pub title: String,
    #[serde(rename = "createdAt")]
    pub created_at: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct ProjectsFile {
    #[serde(default)]
    projects: Vec<Project>,
    #[serde(default)]
    sessions: Vec<ProjectSession>,
}

/// One HTTP-shaped answer.
pub struct Reply {
    pub status: u16,
    pub body: Vec<u8>,
    pub content_type: &'static str,
}

impl Reply {
    pub(crate) fn json(status: u16, value: serde_json::Value) -> Self {
        Self {
            status,
            body: value.to_string().into_bytes(),
            content_type: "application/json",
        }
    }

    pub(crate) fn error(status: u16, message: impl Into<String>) -> Self {
        Self::json(status, serde_json::json!({ "error": message.into() }))
    }

    pub(crate) fn empty(status: u16) -> Self {
        Self {
            status,
            body: Vec::new(),
            content_type: "application/json",
        }
    }
}

/// The project layer for one host.
pub struct Projects {
    file: PathBuf,
    /// The only directory a project may live under.
    root: PathBuf,
    policy: PathPolicy,
}

impl Projects {
    pub fn new(data_dir: impl AsRef<Path>, root: impl AsRef<Path>) -> Self {
        let data_dir = data_dir.as_ref();
        let root = root.as_ref();
        // The root is created here rather than assumed: `browse-directory` starts from it
        // and an empty listing is indistinguishable from a missing directory.
        let _ = std::fs::create_dir_all(root);
        Self {
            file: data_dir.join(PROJECTS_FILE),
            root: root.to_path_buf(),
            policy: PathPolicy::default(),
        }
    }

    fn load(&self) -> ProjectsFile {
        std::fs::read_to_string(&self.file)
            .ok()
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_default()
    }

    fn save(&self, data: &ProjectsFile) -> Result<(), String> {
        let text = serde_json::to_string_pretty(data).map_err(|error| error.to_string())?;
        crate::private_file::write(&self.file, &text, "projects").map_err(|error| error.to_string())
    }

    pub fn projects(&self) -> Vec<Project> {
        self.load().projects
    }

    pub fn sessions_of(&self, project_id: &str) -> Vec<ProjectSession> {
        self.load()
            .sessions
            .into_iter()
            .filter(|session| session.project_id == project_id)
            .collect()
    }

    pub fn find(&self, id: &str) -> Option<Project> {
        self.load().projects.into_iter().find(|item| item.id == id)
    }

    /// Where a session's files belong: the work root of the project it was opened in.
    ///
    /// The runner needs this so a turn's tools write where the user is looking. Without
    /// it every session shares one process-wide directory, a project becomes decorative,
    /// and the file a reply mentions cannot be opened from the transcript.
    pub fn work_root_for_session(&self, session_id: &str) -> Option<String> {
        let data = self.load();
        let project_id = data
            .sessions
            .into_iter()
            .find(|session| session.id == session_id)?
            .project_id;
        data.projects
            .into_iter()
            .find(|project| project.id == project_id)
            .map(|project| project.work_root)
    }

    /// Creates a project and its first session.
    pub fn create_project(
        &self,
        name: &str,
        work_root: &str,
        icon_key: &str,
        color_key: &str,
    ) -> Result<(Project, ProjectSession), String> {
        let resolved = self.resolve_root(work_root)?;
        std::fs::create_dir_all(&resolved)
            .map_err(|error| format!("cannot create {work_root}: {error}"))?;

        let mut data = self.load();
        let now = now_iso();
        let project = Project {
            id: new_id("prj"),
            name: if name.trim().is_empty() {
                resolved
                    .file_name()
                    .map(|name| name.to_string_lossy().into_owned())
                    .unwrap_or_else(|| "项目".to_owned())
            } else {
                name.trim().to_owned()
            },
            work_root: resolved.to_string_lossy().replace('\\', "/"),
            icon_key: icon_key.to_owned(),
            color_key: color_key.to_owned(),
            created_at: now.clone(),
            updated_at: now,
        };
        let session = ProjectSession {
            id: new_id("ses"),
            project_id: project.id.clone(),
            group_id: project.id.clone(),
            title: "新会话".to_owned(),
            created_at: project.created_at.clone(),
            updated_at: project.created_at.clone(),
        };
        data.projects.push(project.clone());
        data.sessions.push(session.clone());
        self.save(&data)?;
        Ok((project, session))
    }

    pub fn update_project(
        &self,
        id: &str,
        name: Option<&str>,
        icon_key: Option<&str>,
        color_key: Option<&str>,
    ) -> Result<Project, String> {
        let mut data = self.load();
        let project = data
            .projects
            .iter_mut()
            .find(|item| item.id == id)
            .ok_or_else(|| format!("no such project: {id}"))?;
        if let Some(name) = name {
            if !name.trim().is_empty() {
                project.name = name.trim().to_owned();
            }
        }
        if let Some(key) = icon_key {
            project.icon_key = key.to_owned();
        }
        if let Some(key) = color_key {
            project.color_key = key.to_owned();
        }
        project.updated_at = now_iso();
        let updated = project.clone();
        self.save(&data)?;
        Ok(updated)
    }

    /// Removes the project from the list. The files on disk are left alone.
    pub fn delete_project(&self, id: &str) -> Result<(), String> {
        let mut data = self.load();
        data.projects.retain(|item| item.id != id);
        data.sessions.retain(|item| item.project_id != id);
        self.save(&data)
    }

    /// Every session, across projects. The shared sidebar asks for this once on load
    /// rather than a request per project.
    pub fn all_sessions(&self) -> Vec<ProjectSession> {
        self.load().sessions
    }

    pub fn find_session(&self, id: &str) -> Option<ProjectSession> {
        self.load().sessions.into_iter().find(|item| item.id == id)
    }

    pub fn rename_session(&self, id: &str, title: &str) -> Result<ProjectSession, String> {
        let mut data = self.load();
        let session = data
            .sessions
            .iter_mut()
            .find(|item| item.id == id)
            .ok_or_else(|| format!("no such session: {id}"))?;
        if !title.trim().is_empty() {
            session.title = title.trim().to_owned();
        }
        session.updated_at = now_iso();
        let updated = session.clone();
        self.save(&data)?;
        Ok(updated)
    }

    pub fn delete_session(&self, id: &str) -> Result<(), String> {
        let mut data = self.load();
        data.sessions.retain(|item| item.id != id);
        self.save(&data)
    }

    pub fn create_session(&self, project_id: &str, title: &str) -> Result<ProjectSession, String> {
        let mut data = self.load();
        if !data.projects.iter().any(|item| item.id == project_id) {
            return Err(format!("no such project: {project_id}"));
        }
        let now = now_iso();
        let session = ProjectSession {
            id: new_id("ses"),
            project_id: project_id.to_owned(),
            group_id: project_id.to_owned(),
            title: if title.trim().is_empty() {
                "新会话".to_owned()
            } else {
                title.trim().to_owned()
            },
            created_at: now.clone(),
            updated_at: now,
        };
        data.sessions.push(session.clone());
        self.save(&data)?;
        Ok(session)
    }

    /// The only paths a project may point at.
    ///
    /// A typed path outside the granted root is rejected by name rather than silently
    /// clamped, so the user learns that the boundary exists.
    fn resolve_root(&self, work_root: &str) -> Result<PathBuf, String> {
        let candidate = if work_root.trim().is_empty() {
            self.root.clone()
        } else {
            PathBuf::from(work_root.trim())
        };
        let root = self
            .root
            .canonicalize()
            .map_err(|error| format!("cannot resolve {}: {error}", self.root.display()))?;
        // The path may not exist yet, so compare the deepest existing ancestor.
        let mut probe = candidate.clone();
        while !probe.exists() {
            match probe.parent() {
                Some(parent) => probe = parent.to_path_buf(),
                None => break,
            }
        }
        let existing = probe
            .canonicalize()
            .map_err(|error| format!("cannot resolve {}: {error}", candidate.display()))?;
        if !existing.starts_with(&root) {
            return Err(format!(
                "{} is outside the directory this app may use",
                candidate.display()
            ));
        }
        // `existing` is canonical; the part that does not exist yet is appended as
        // typed, so a project directory is created at the path the user chose.
        let rest = candidate.strip_prefix(&probe).unwrap_or(Path::new(""));
        Ok(existing.join(rest))
    }

    fn files_of(&self, project_id: &str) -> Result<LocalFiles, Reply> {
        let project = self
            .find(project_id)
            .ok_or_else(|| Reply::error(404, format!("no such project: {project_id}")))?;
        LocalFiles::with_policy(PathBuf::from(&project.work_root), self.policy.clone())
            .map_err(|error| Reply::error(500, error.to_string()))
    }

    /// Lists a directory inside a project.
    pub fn list_files(&self, project_id: &str, relative: &str) -> Reply {
        let project = match self.find(project_id) {
            Some(project) => project,
            None => return Reply::error(404, format!("no such project: {project_id}")),
        };
        let files = match self.files_of(project_id) {
            Ok(files) => files,
            Err(reply) => return reply,
        };
        let base = PathBuf::from(&project.work_root);
        let target = if relative.trim().is_empty() {
            base.clone()
        } else {
            match files.resolve_read(relative) {
                Ok(path) => path,
                Err(error) => return Reply::error(403, error.to_string()),
            }
        };
        let entries = match read_dir_entries(&base, &target, &self.policy) {
            Ok(entries) => entries,
            Err(error) => return Reply::error(500, error),
        };
        Reply::json(
            200,
            serde_json::json!({
                "entries": entries,
                "path": relative,
            }),
        )
    }

    pub fn read_text(&self, project_id: &str, relative: &str) -> Reply {
        let files = match self.files_of(project_id) {
            Ok(files) => files,
            Err(reply) => return reply,
        };
        let path = match files.resolve_read(relative) {
            Ok(path) => path,
            Err(error) => return Reply::error(403, error.to_string()),
        };
        match std::fs::read_to_string(&path) {
            Ok(content) => Reply::json(
                200,
                serde_json::json!({ "content": content, "path": relative }),
            ),
            // A binary file is not a failure of the request; it is a file the text
            // preview cannot show, and the client has a raw endpoint for it.
            Err(_) => Reply::json(
                200,
                serde_json::json!({ "content": "", "path": relative, "binary": true }),
            ),
        }
    }

    pub fn write_text(&self, project_id: &str, relative: &str, content: &str) -> Reply {
        let files = match self.files_of(project_id) {
            Ok(files) => files,
            Err(reply) => return reply,
        };
        let path = match files.resolve_write(relative) {
            Ok(path) => path,
            Err(error) => return Reply::error(403, error.to_string()),
        };
        if let Some(parent) = path.parent() {
            if let Err(error) = std::fs::create_dir_all(parent) {
                return Reply::error(500, format!("cannot create {}: {error}", parent.display()));
            }
        }
        match std::fs::write(&path, content) {
            Ok(()) => Reply::json(
                200,
                serde_json::json!({ "content": content, "path": relative }),
            ),
            Err(error) => Reply::error(500, error.to_string()),
        }
    }

    pub fn read_raw(&self, project_id: &str, relative: &str) -> Reply {
        let files = match self.files_of(project_id) {
            Ok(files) => files,
            Err(reply) => return reply,
        };
        let path = match files.resolve_read(relative) {
            Ok(path) => path,
            Err(error) => return Reply::error(403, error.to_string()),
        };
        match std::fs::read(&path) {
            Ok(bytes) => Reply {
                status: 200,
                body: bytes,
                content_type: "application/octet-stream",
            },
            Err(error) => Reply::error(500, error.to_string()),
        }
    }

    /// The agent's instruction file for a project.
    pub fn agents_md(&self, project_id: &str) -> Reply {
        let files = match self.files_of(project_id) {
            Ok(files) => files,
            Err(reply) => return reply,
        };
        let path = match files.resolve_read("AGENTS.md") {
            Ok(path) => path,
            Err(error) => return Reply::error(403, error.to_string()),
        };
        let content = std::fs::read_to_string(&path).unwrap_or_default();
        Reply::json(
            200,
            serde_json::json!({ "content": content, "path": "AGENTS.md" }),
        )
    }

    pub fn write_agents_md(&self, project_id: &str, content: &str) -> Reply {
        let files = match self.files_of(project_id) {
            Ok(files) => files,
            Err(reply) => return reply,
        };
        let path = match files.resolve_write("AGENTS.md") {
            Ok(path) => path,
            Err(error) => return Reply::error(403, error.to_string()),
        };
        match std::fs::write(&path, content) {
            Ok(()) => Reply::json(
                200,
                serde_json::json!({ "content": content, "path": "AGENTS.md" }),
            ),
            Err(error) => Reply::error(500, error.to_string()),
        }
    }

    /// What the directory picker may show, starting from the granted root.
    pub fn browse(&self, relative: &str) -> Reply {
        let root = match self.root.canonicalize() {
            Ok(root) => root,
            Err(error) => return Reply::error(500, error.to_string()),
        };
        let target = if relative.trim().is_empty() {
            root.clone()
        } else {
            let candidate = root.join(relative.trim_start_matches('/'));
            match candidate.canonicalize() {
                Ok(path) if path.starts_with(&root) => path,
                Ok(_) => return Reply::error(403, "outside the directory this app may use"),
                Err(error) => return Reply::error(404, error.to_string()),
            }
        };
        let entries = match read_dir_entries(&root, &target, &self.policy) {
            Ok(entries) => entries,
            Err(error) => return Reply::error(500, error),
        };
        Reply::json(
            200,
            serde_json::json!({ "entries": entries, "path": relative }),
        )
    }

    /// The plan library: a folder of markdown documents inside the project.
    ///
    /// The Android host has no plan workflow yet, so an empty library is the truth. It is
    /// served rather than 404'd because the UI asks for it on every project open and a
    /// missing endpoint reads as a broken project.
    pub fn plan_library(&self, _project_id: &str) -> Reply {
        Reply::json(
            200,
            serde_json::json!({ "dir": "", "entries": [], "folders": [] }),
        )
    }

    pub(crate) fn project_view(project: &Project) -> serde_json::Value {
        serde_json::json!({
            "id": project.id,
            "name": project.name,
            "work_root": project.work_root,
            "icon_key": project.icon_key,
            "color_key": project.color_key,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        })
    }
}

fn read_dir_entries(
    base: &Path,
    target: &Path,
    policy: &PathPolicy,
) -> Result<Vec<serde_json::Value>, String> {
    let listing = std::fs::read_dir(target).map_err(|error| error.to_string())?;
    let mut entries = Vec::new();
    for item in listing.flatten() {
        let name = item.file_name().to_string_lossy().into_owned();
        let relative = item
            .path()
            .strip_prefix(base)
            .map(|path| path.to_string_lossy().replace('\\', "/"))
            .unwrap_or_else(|_| name.clone());
        // A protected name is hidden from the listing too, not only from reads: showing
        // it invites a click that must then be refused.
        if !policy.allows(&relative) {
            continue;
        }
        let metadata = match item.metadata() {
            Ok(metadata) => metadata,
            Err(_) => continue,
        };
        let is_dir = metadata.is_dir();
        entries.push(serde_json::json!({
            "name": name,
            "type": if is_dir { "directory" } else { "file" },
            "size": metadata.len(),
            "ext": if is_dir {
                String::new()
            } else {
                Path::new(&name)
                    .extension()
                    .map(|ext| ext.to_string_lossy().into_owned())
                    .unwrap_or_default()
            },
        }));
    }
    entries.sort_by(|a, b| {
        let a_dir = a["type"] == "directory";
        let b_dir = b["type"] == "directory";
        b_dir.cmp(&a_dir).then_with(|| {
            a["name"]
                .as_str()
                .unwrap_or("")
                .cmp(b["name"].as_str().unwrap_or(""))
        })
    });
    Ok(entries)
}

fn new_id(prefix: &str) -> String {
    let mut bytes = [0u8; 8];
    if getrandom::fill(&mut bytes).is_err() {
        // Without randomness, the timestamp still keeps ids distinct enough for one
        // device. A collision would overwrite a project, so this is only a fallback.
        return format!("{prefix}-{}", now_millis());
    }
    let mut out = String::with_capacity(prefix.len() + 17);
    out.push_str(prefix);
    out.push('-');
    for byte in bytes {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

fn now_millis() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0)
}

/// ISO-8601 in UTC, which is what the UI parses.
fn now_iso() -> String {
    let millis = now_millis();
    let seconds = (millis / 1000) as i64;
    let days = seconds.div_euclid(86_400);
    let time_of_day = seconds.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        time_of_day / 3600,
        (time_of_day % 3600) / 60,
        time_of_day % 60
    )
}

/// Howard Hinnant's days-to-civil, so no date crate is needed for one format.
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}
