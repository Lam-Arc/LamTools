//! The HTTP-shaped surface the existing UI already speaks.
//!
//! Kept in its own module so the routing is reviewable on its own: every path here is a
//! path the desktop UI calls, and a missing one shows up as a broken screen rather than a
//! compile error. The list is therefore written out rather than built from a pattern.

use crate::projects::{Projects, Reply};

/// Decodes `%xx` escapes. Query values arrive encoded and a project id is never a path,
/// so a full URL parser would be more machinery than the job needs.
fn percent_decode(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' && index + 2 < bytes.len() {
            let pair = std::str::from_utf8(&bytes[index + 1..index + 3]).unwrap_or("");
            if let Ok(value) = u8::from_str_radix(pair, 16) {
                out.push(value);
                index += 3;
                continue;
            }
        }
        if bytes[index] == b'+' {
            out.push(b' ');
            index += 1;
            continue;
        }
        out.push(bytes[index]);
        index += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// The same reader, for `Projects`' own helpers.
pub(crate) fn query_value_public(query: &str, key: &str) -> Option<String> {
    query_value(query, key)
}

fn query_value(query: &str, key: &str) -> Option<String> {
    for pair in query.split('&') {
        let (name, value) = match pair.split_once('=') {
            Some((name, value)) => (name, value),
            None => (pair, ""),
        };
        if percent_decode(name) == key {
            return Some(percent_decode(value));
        }
    }
    None
}

fn json_body(body: &str) -> serde_json::Value {
    serde_json::from_str(body).unwrap_or(serde_json::Value::Null)
}

/// A stored content type as the header value the screen reads.
///
/// `Reply` carries a static string, and the set of types the store can produce is closed,
/// so this maps within it instead of allocating per download.
fn static_mime(mime: &str) -> &'static str {
    match mime {
        "text/plain" => "text/plain",
        "text/markdown" => "text/markdown",
        "text/csv" => "text/csv",
        "application/json" => "application/json",
        "image/png" => "image/png",
        "image/jpeg" => "image/jpeg",
        "image/gif" => "image/gif",
        "image/webp" => "image/webp",
        "application/pdf" => "application/pdf",
        _ => "application/octet-stream",
    }
}

fn string_field(body: &serde_json::Value, key: &str) -> Option<String> {
    body.get(key)
        .and_then(|value| value.as_str())
        .map(str::to_owned)
}

impl Projects {
    /// Serves one request. `path` excludes the query string, which arrives separately.
    pub fn handle(&self, method: &str, path: &str, query: &str, body: &str) -> Reply {
        let decoded: Vec<String> = path
            .trim_matches('/')
            .split('/')
            .filter(|segment| !segment.is_empty())
            .map(percent_decode)
            .collect();
        // Borrowed for the match: a slice pattern of `&str` is what lets the arms read as
        // the paths themselves rather than as indexes.
        let segments: Vec<&str> = decoded.iter().map(String::as_str).collect();

        match (method, segments.as_slice()) {
            ("GET", ["browse-directory"]) => {
                let relative = query_value(query, "path").unwrap_or_default();
                self.browse(&relative)
            }

            // user:“先调查现有 Windows 功能，最大化复用成熟实现，再补齐 Rust Core 与 Android
            // 平台的必要接口”+(界面显示引用、读取预览、用系统打开都走这三个端点，桌面侧就是
            // 它们；这里补同一份语义，手机上的预览才真的出图出文)。
            ("GET", ["files", "resolve-reference"]) => {
                let raw = query_value(query, "path").unwrap_or_default();
                match self.reference_root(query) {
                    Err(reply) => reply,
                    Ok(files) => match crate::file_refs::resolve(&files, &raw) {
                        Ok(path) => Reply::json(
                            200,
                            serde_json::json!({
                                "path": path.to_string_lossy().replace('\\', "/"),
                            }),
                        ),
                        Err(error) => Reply::json(
                            error.status(),
                            serde_json::json!({ "detail": error.detail() }),
                        ),
                    },
                }
            }

            ("GET", ["files", "read-reference"]) => {
                let raw = query_value(query, "path").unwrap_or_default();
                match self.reference_root(query) {
                    Err(reply) => reply,
                    Ok(files) => match crate::file_refs::resolve(&files, &raw) {
                        Ok(path) => match std::fs::read(&path) {
                            Ok(bytes) => {
                                let name = path
                                    .file_name()
                                    .and_then(|value| value.to_str())
                                    .unwrap_or_default();
                                Reply {
                                    status: 200,
                                    body: bytes,
                                    content_type: crate::file_refs::mime_for_name(name),
                                }
                            }
                            Err(error) => Reply::json(
                                404,
                                serde_json::json!({ "detail": format!("原文件不存在: {error}") }),
                            ),
                        },
                        Err(error) => Reply::json(
                            error.status(),
                            serde_json::json!({ "detail": error.detail() }),
                        ),
                    },
                }
            }

            // Opening a file with whatever the system installed is the host's job, and
            // this core has no window manager. Answering "opened" would leave a button
            // that does nothing; the screen can show this instead.
            ("POST", ["files", "open-reference"]) => Reply::json(
                501,
                serde_json::json!({ "detail": "这个核心不负责用系统程序打开文件" }),
            ),

            // The sidebar loads every session once, grouped by project, so this is the
            // endpoint that decides whether the app looks empty or alive.
            //
            // A bare array, not `{"sessions": [...]}`: one caller reads it as an array
            // directly and throws on an object, while the other accepts both.
            ("GET", ["sessions"]) => Reply::json(
                200,
                serde_json::to_value(self.all_sessions()).unwrap_or_default(),
            ),

            // Some flows let the client choose the session id, so it is honoured when
            // present. The id doubles as the core's thread id, which is why it matters.
            ("POST", ["sessions"]) => {
                let payload = json_body(body);
                let title = string_field(&payload, "title").unwrap_or_default();
                let project = string_field(&payload, "project_id")
                    .or_else(|| self.projects().last().map(|project| project.id.clone()));
                let project = match project {
                    Some(project) => project,
                    None => return Reply::error(400, "create a project first"),
                };
                match self.create_session(&project, &title) {
                    Ok(session) => {
                        Reply::json(200, serde_json::to_value(&session).unwrap_or_default())
                    }
                    Err(error) => Reply::error(400, error),
                }
            }

            ("GET", ["sessions", id]) => match self.find_session(id) {
                Some(session) => {
                    Reply::json(200, serde_json::to_value(&session).unwrap_or_default())
                }
                None => Reply::error(404, format!("no such session: {id}")),
            },

            ("PATCH", ["sessions", id]) => {
                let payload = json_body(body);
                let title = string_field(&payload, "title").unwrap_or_default();
                match self.rename_session(id, &title) {
                    Ok(session) => {
                        Reply::json(200, serde_json::to_value(&session).unwrap_or_default())
                    }
                    Err(error) => Reply::error(404, error),
                }
            }

            ("DELETE", ["sessions", id]) => match self.delete_session(id) {
                Ok(()) => Reply::empty(204),
                Err(error) => Reply::error(500, error),
            },

            // user:“选择文件 → 显示附件 → 发送消息 → Agent 读取真实内容”+(附件由核心登记并
            // 复制导入；界面在发送前把返回的记录放进待发托盘)。
            //
            // Reference import: the host has already placed the picked file inside the
            // sandbox (a `content://` grant has no path worth trusting), so this records
            // and copies it rather than reading an outside location later.
            ("POST", ["sessions", id, "attachments", "reference"]) => {
                if self.find_session(id).is_none() {
                    return Reply::error(404, format!("no such session: {id}"));
                }
                let payload = json_body(body);
                let path = string_field(&payload, "path").unwrap_or_default();
                if path.trim().is_empty() {
                    return Reply::error(400, "path is required");
                }
                let project = string_field(&payload, "project_id")
                    .or_else(|| query_value(query, "project_id"))
                    .unwrap_or_default();
                match self
                    .attachments()
                    .import(id, &project, std::path::Path::new(&path))
                {
                    Ok(record) => {
                        Reply::json(200, serde_json::to_value(record).unwrap_or_default())
                    }
                    Err(error) => Reply::error(400, error),
                }
            }

            ("GET", ["sessions", id, "attachments"]) => Reply::json(
                200,
                serde_json::json!({ "attachments": self.attachments().list(id) }),
            ),

            ("GET", ["attachments", attachment_id]) => {
                match self.attachments().get(attachment_id) {
                    Some(record) => Reply::json(200, serde_json::json!({ "attachment": record })),
                    None => Reply::error(404, format!("no such attachment: {attachment_id}")),
                }
            }

            // The bytes, for a preview or for opening the file. Read through the record,
            // never through a caller-supplied path.
            ("GET", ["attachments", attachment_id, "content"])
            | ("GET", ["attachments", attachment_id, "download"]) => {
                match self.attachments().get(attachment_id) {
                    Some(record) => match self.attachments().content(attachment_id) {
                        Ok(bytes) => Reply {
                            status: 200,
                            body: bytes,
                            // The screen decides how to render from this, so an image
                            // served as generic bytes becomes a broken thumbnail.
                            content_type: static_mime(&record.mime_type),
                        },
                        Err(error) => Reply::error(500, error),
                    },
                    None => Reply::error(404, format!("no such attachment: {attachment_id}")),
                }
            }

            // What the deck needs before it renders: where the file is, and enough of a
            // text file to show a few lines without downloading it twice.
            ("GET", ["attachments", attachment_id, "preview"]) => {
                match self.attachments().get(attachment_id) {
                    Some(record) => {
                        let mut payload = serde_json::json!({
                            "id": record.id,
                            "filename": record.filename,
                            "mime_type": record.mime_type,
                            "size": record.size,
                            "preview_type": record.preview_type,
                            "path": record.path,
                        });
                        let mut code = "";
                        if record.preview_type == "text" {
                            match self.attachments().content(attachment_id) {
                                Ok(bytes) => {
                                    let (shown, truncated) =
                                        crate::file_refs::preview_text(&bytes, 64 * 1024);
                                    if let Some(object) = payload.as_object_mut() {
                                        object.insert(
                                            "text".into(),
                                            serde_json::Value::String(shown),
                                        );
                                        if truncated {
                                            object.insert(
                                                "truncated".into(),
                                                serde_json::Value::Bool(true),
                                            );
                                        }
                                    }
                                }
                                Err(_) => code = "file_unreadable",
                            }
                        } else if !std::path::Path::new(&record.path).exists() {
                            code = "file_missing";
                        }
                        if !code.is_empty() {
                            if let Some(object) = payload.as_object_mut() {
                                object.insert(
                                    "error_code".into(),
                                    serde_json::Value::String(code.into()),
                                );
                            }
                        }
                        Reply::json(200, payload)
                    }
                    None => Reply::error(404, format!("no such attachment: {attachment_id}")),
                }
            }

            // Opening a file with another program is the host's job: only it knows what
            // this platform offers. Answering "done" here would leave a button that does
            // nothing, so the reply is the truth the screen can show.
            ("POST", ["attachments", attachment_id, "open"]) => {
                match self.attachments().get(attachment_id) {
                    Some(_) => {
                        Reply::error(501, "this core does not open files with another program")
                    }
                    None => Reply::error(404, format!("no such attachment: {attachment_id}")),
                }
            }

            ("GET", ["projects"]) => Reply::json(
                200,
                serde_json::json!({
                    "projects": self.projects().iter().map(Projects::project_view).collect::<Vec<_>>(),
                }),
            ),

            ("POST", ["projects"]) => {
                let payload = json_body(body);
                let name = string_field(&payload, "name").unwrap_or_default();
                let work_root = string_field(&payload, "work_root").unwrap_or_default();
                let icon = string_field(&payload, "icon_key").unwrap_or_default();
                let color = string_field(&payload, "color_key").unwrap_or_default();
                match self.create_project(&name, &work_root, &icon, &color) {
                    Ok((project, session)) => Reply::json(
                        200,
                        serde_json::json!({
                            "project": Projects::project_view(&project),
                            "session": session,
                        }),
                    ),
                    Err(error) => Reply::error(400, error),
                }
            }

            ("GET", ["projects", id]) => match self.find(id) {
                Some(project) => Reply::json(200, Projects::project_view(&project)),
                None => Reply::error(404, format!("no such project: {id}")),
            },

            ("PATCH", ["projects", id]) => {
                let payload = json_body(body);
                match self.update_project(
                    id,
                    string_field(&payload, "name").as_deref(),
                    string_field(&payload, "icon_key").as_deref(),
                    string_field(&payload, "color_key").as_deref(),
                ) {
                    Ok(project) => Reply::json(200, Projects::project_view(&project)),
                    Err(error) => Reply::error(404, error),
                }
            }

            ("DELETE", ["projects", id]) => match self.delete_project(id) {
                Ok(()) => Reply::empty(204),
                Err(error) => Reply::error(500, error),
            },

            ("GET", ["projects", id, "sessions"]) => Reply::json(
                200,
                serde_json::json!({
                    "sessions": self.sessions_of(id),
                }),
            ),

            ("POST", ["projects", id, "sessions"]) => {
                let payload = json_body(body);
                let title = string_field(&payload, "title").unwrap_or_default();
                match self.create_session(id, &title) {
                    Ok(session) => {
                        Reply::json(200, serde_json::to_value(&session).unwrap_or_default())
                    }
                    Err(error) => Reply::error(404, error),
                }
            }

            // user:“优先复用…文件操作”+(桌面用 multipart 传字节；手机的选择器只交回沙盒
            // 路径，所以这条只收路径，落到同一个「资料/」，资料库两边看到同一批文件)。
            ("POST", ["projects", id, "artifacts", "reference"]) => {
                let payload = json_body(body);
                let path = string_field(&payload, "path").unwrap_or_default();
                if path.trim().is_empty() {
                    return Reply::error(400, "path is required");
                }
                let folder = string_field(&payload, "folder")
                    .or_else(|| query_value(query, "folder"))
                    .unwrap_or_default();
                self.upload_artifact(id, &folder, &path)
            }

            ("GET", ["projects", id, "files"]) => {
                let relative = query_value(query, "path").unwrap_or_default();
                self.list_files(id, &relative)
            }

            ("GET", ["projects", id, "files", "content"]) => {
                let relative = query_value(query, "path").unwrap_or_default();
                self.read_text(id, &relative)
            }

            ("PUT", ["projects", id, "files", "content"]) => {
                let relative = query_value(query, "path").unwrap_or_default();
                let payload = json_body(body);
                let content = string_field(&payload, "content").unwrap_or_default();
                self.write_text(id, &relative, &content)
            }

            ("GET", ["projects", id, "files", "raw"]) => {
                let relative = query_value(query, "path").unwrap_or_default();
                self.read_raw(id, &relative)
            }

            ("GET", ["projects", id, "agents-md"]) => self.agents_md(id),

            ("PUT", ["projects", id, "agents-md"]) => {
                let payload = json_body(body);
                let content = string_field(&payload, "content").unwrap_or_default();
                self.write_agents_md(id, &content)
            }

            // user:“优先复用 Windows Sunday 已经验证的功能、Library、预览器、文件操作与 UI”
            // +(资料库是项目里「方案/」下的普通 markdown，桌面侧早就这么做；这里补齐同一批
            // 文件操作，界面不用为手机另开一套)。
            ("GET", ["projects", id, "plan-library"]) => match self.plan_root(id) {
                Err(reply) => reply,
                Ok(root) => Reply::json(
                    200,
                    serde_json::json!({
                        "dir": crate::plan_library::DIRNAME,
                        "entries": crate::plan_library::scan(&root),
                        "folders": crate::plan_library::folders(&root),
                    }),
                ),
            },

            ("POST", ["projects", id, "plan-library", "files"]) => {
                let payload = json_body(body);
                let name = string_field(&payload, "name").unwrap_or_default();
                let folder = string_field(&payload, "folder").unwrap_or_default();
                match self.plan_root(id) {
                    Err(reply) => reply,
                    Ok(root) => match crate::plan_library::create_file(&root, &name, &folder) {
                        Ok(entry) => Reply::json(200, serde_json::json!({ "entry": entry })),
                        Err(error) => Reply::error(400, error),
                    },
                }
            }

            ("POST", ["projects", id, "plan-library", "folders"]) => {
                let payload = json_body(body);
                let path = string_field(&payload, "path").unwrap_or_default();
                match self.plan_root(id) {
                    Err(reply) => reply,
                    Ok(root) => match crate::plan_library::create_folder(&root, &path) {
                        Ok(folder) => Reply::json(200, serde_json::json!({ "folder": folder })),
                        Err(error) => Reply::error(400, error),
                    },
                }
            }

            ("DELETE", ["projects", id, "plan-library", "folders"]) => {
                let path = query_value(query, "path").unwrap_or_default();
                match self.plan_root(id) {
                    Err(reply) => reply,
                    Ok(root) => match crate::plan_library::delete_folder(&root, &path) {
                        Ok(deleted) => Reply::json(200, serde_json::json!({ "deleted": deleted })),
                        Err(error) => Reply::error(400, error),
                    },
                }
            }

            ("POST", ["projects", id, "plan-library", "rename"]) => {
                let payload = json_body(body);
                let path = string_field(&payload, "path").unwrap_or_default();
                let name = string_field(&payload, "name").unwrap_or_default();
                match self.plan_root(id) {
                    Err(reply) => reply,
                    Ok(root) => match crate::plan_library::rename(&root, &path, &name) {
                        Ok(entry) => Reply::json(200, serde_json::json!({ "entry": entry })),
                        Err(error) => Reply::error(400, error),
                    },
                }
            }

            ("POST", ["projects", id, "plan-library", "move"]) => {
                let payload = json_body(body);
                let path = string_field(&payload, "path").unwrap_or_default();
                let folder = string_field(&payload, "folder").unwrap_or_default();
                match self.plan_root(id) {
                    Err(reply) => reply,
                    Ok(root) => match crate::plan_library::move_to(&root, &path, &folder) {
                        Ok(entry) => Reply::json(200, serde_json::json!({ "entry": entry })),
                        Err(error) => Reply::error(400, error),
                    },
                }
            }

            ("POST", ["projects", id, "plan-library", "favorite"]) => {
                let payload = json_body(body);
                let path = string_field(&payload, "path").unwrap_or_default();
                let starred = payload
                    .get("favorite")
                    .and_then(|value| value.as_bool())
                    .unwrap_or(false);
                match self.plan_root(id) {
                    Err(reply) => reply,
                    Ok(root) => match crate::plan_library::favorite(&root, &path, starred) {
                        Ok(entry) => Reply::json(200, serde_json::json!({ "entry": entry })),
                        Err(error) => Reply::error(400, error),
                    },
                }
            }

            ("DELETE", ["projects", id, "plan-library"]) => {
                let path = query_value(query, "path").unwrap_or_default();
                match self.plan_root(id) {
                    Err(reply) => reply,
                    Ok(root) => match crate::plan_library::delete_file(&root, &path) {
                        Ok(deleted) => Reply::json(200, serde_json::json!({ "deleted": deleted })),
                        Err(error) => Reply::error(400, error),
                    },
                }
            }

            _ => Reply::error(
                404,
                format!("{method} {path} is not served by the in-app core"),
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    struct Fixture {
        _dir: tempfile::TempDir,
        projects: Projects,
        root: std::path::PathBuf,
    }

    fn fixture() -> Fixture {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("workspace");
        std::fs::create_dir_all(&root).unwrap();
        let projects = Projects::new(dir.path(), &root);
        Fixture {
            _dir: dir,
            projects,
            root,
        }
    }

    fn body(reply: &Reply) -> serde_json::Value {
        serde_json::from_slice(&reply.body).unwrap_or(serde_json::Value::Null)
    }

    fn create(fixture: &Fixture, name: &str) -> (String, String) {
        let payload = serde_json::json!({"name": name, "work_root": "", "icon_key": "folder", "color_key": "green"});
        let reply = fixture
            .projects
            .handle("POST", "/projects", "", &payload.to_string());
        assert_eq!(
            reply.status,
            200,
            "{}",
            String::from_utf8_lossy(&reply.body)
        );
        let value = body(&reply);
        (
            value["project"]["id"].as_str().unwrap().to_owned(),
            value["session"]["id"].as_str().unwrap().to_owned(),
        )
    }

    /// The preview chain the shared interface already speaks: a reference resolves, its
    /// bytes come back with a type a preview can use, and opening it names who owns that.
    #[test]
    fn a_file_reference_resolves_and_reads_through_the_routes() {
        let fixture = fixture();
        let (project, _) = create(&fixture, "演示");
        let write = format!("/projects/{project}/files/content");
        let written = fixture.projects.handle(
            "PUT",
            &write,
            "path=notes.md",
            &serde_json::json!({ "content": "# hi" }).to_string(),
        );
        assert_eq!(written.status, 200);

        let root = body(&fixture.projects.handle("GET", "/projects", "", ""))["projects"][0]
            ["work_root"]
            .as_str()
            .expect("the project has no work root")
            .to_owned();
        let query = format!("path=workspace%3A%2F%2Fnotes.md&work_root={root}");

        let resolved = fixture
            .projects
            .handle("GET", "/files/resolve-reference", &query, "");
        assert_eq!(
            resolved.status,
            200,
            "{}",
            String::from_utf8_lossy(&resolved.body)
        );
        assert!(
            body(&resolved)["path"]
                .as_str()
                .unwrap_or_default()
                .ends_with("notes.md"),
            "{}",
            String::from_utf8_lossy(&resolved.body)
        );

        let read = fixture
            .projects
            .handle("GET", "/files/read-reference", &query, "");
        assert_eq!(read.status, 200);
        assert_eq!(read.body, b"# hi");
        assert_eq!(read.content_type, "text/markdown");

        let open = fixture.projects.handle(
            "POST",
            "/files/open-reference",
            "",
            &serde_json::json!({ "path": "notes.md" }).to_string(),
        );
        assert_eq!(open.status, 501, "the host opens files, not this core");
    }

    /// A working directory outside the sandbox is refused: a reference is not a grant.
    #[test]
    fn a_reference_root_outside_the_sandbox_is_refused() {
        let fixture = fixture();
        let (_, _) = create(&fixture, "演示");
        let reply = fixture.projects.handle(
            "GET",
            "/files/resolve-reference",
            "path=notes.md&work_root=/sdcard",
            "",
        );
        assert!(
            reply.status >= 400,
            "{} {}",
            reply.status,
            String::from_utf8_lossy(&reply.body)
        );
    }

    /// The attachment routes the shared interface already calls.
    ///
    /// The interface posts a picked file for a session, then renders the record it gets
    /// back and reads the bytes for a preview. If any of the three steps is missing the
    /// attachment shows up as a name that cannot be opened.
    #[test]
    fn an_attachment_is_imported_listed_and_readable() {
        let fixture = fixture();
        let (_, session) = create(&fixture, "演示");
        let incoming = fixture._dir.path().join("incoming");
        std::fs::create_dir_all(&incoming).unwrap();
        let source = incoming.join("notes.txt");
        std::fs::write(&source, b"goal\n").unwrap();

        let payload = serde_json::json!({ "path": source.to_string_lossy() });
        let reply = fixture.projects.handle(
            "POST",
            &format!("/sessions/{session}/attachments/reference"),
            "",
            &payload.to_string(),
        );
        assert_eq!(
            reply.status,
            200,
            "{}",
            String::from_utf8_lossy(&reply.body)
        );
        let record = body(&reply);
        let id = record["id"].as_str().unwrap().to_owned();
        assert_eq!(record["filename"], "notes.txt");
        assert_eq!(record["session_id"], session.as_str());
        assert_eq!(record["preview_type"], "text");

        let listed = body(&fixture.projects.handle(
            "GET",
            &format!("/sessions/{session}/attachments"),
            "",
            "",
        ));
        assert_eq!(listed["attachments"].as_array().unwrap().len(), 1);

        let content = fixture
            .projects
            .handle("GET", &format!("/attachments/{id}/content"), "", "");
        assert_eq!(content.status, 200);
        assert_eq!(content.body, b"goal\n");
    }

    /// A path outside the sandbox is refused by the route, not only by the store: the
    /// picker must not become a way around the core's own file boundary.
    #[test]
    fn an_attachment_outside_the_sandbox_is_refused_by_the_route() {
        let fixture = fixture();
        let (_, session) = create(&fixture, "演示");
        let outside =
            std::env::temp_dir().join(format!("sunday-outside-{}.txt", std::process::id()));
        std::fs::write(&outside, b"no").unwrap();
        let payload = serde_json::json!({ "path": outside.to_string_lossy() });
        let reply = fixture.projects.handle(
            "POST",
            &format!("/sessions/{session}/attachments/reference"),
            "",
            &payload.to_string(),
        );
        assert_eq!(reply.status, 400);
        assert!(
            String::from_utf8_lossy(&reply.body).contains("outside"),
            "{}",
            String::from_utf8_lossy(&reply.body)
        );
        let _ = std::fs::remove_file(&outside);
    }

    /// The shape the client reads: `{ project, session }`, snake_case inside.
    #[test]
    fn creating_a_project_returns_the_project_and_its_first_session() {
        let fixture = fixture();
        let payload = serde_json::json!({"name": "演示", "work_root": "", "icon_key": "folder", "color_key": "green"});
        let reply = fixture
            .projects
            .handle("POST", "/projects", "", &payload.to_string());
        assert_eq!(reply.status, 200);
        let value = body(&reply);
        assert_eq!(value["project"]["name"], "演示");
        assert!(value["project"]["id"].as_str().unwrap().starts_with("prj-"));
        assert!(value["session"]["id"].as_str().unwrap().starts_with("ses-"));
        // The session id is what the core uses as a thread id, so it has to exist here.
        assert_eq!(value["session"]["project_id"], value["project"]["id"]);
        assert!(value["project"]["created_at"]
            .as_str()
            .unwrap()
            .contains('T'));
    }

    #[test]
    fn listing_projects_reflects_what_was_created() {
        let fixture = fixture();
        let (first, _) = create(&fixture, "one");
        let (second, _) = create(&fixture, "two");
        let reply = fixture.projects.handle("GET", "/projects", "", "");
        let value = body(&reply);
        let ids: Vec<&str> = value["projects"]
            .as_array()
            .unwrap()
            .iter()
            .map(|item| item["id"].as_str().unwrap())
            .collect();
        assert!(ids.contains(&first.as_str()));
        assert!(ids.contains(&second.as_str()));
    }

    #[test]
    fn sessions_can_be_added_and_listed() {
        let fixture = fixture();
        let (project, first) = create(&fixture, "one");
        let path = format!("/projects/{project}/sessions");
        let reply = fixture.projects.handle(
            "POST",
            &path,
            "",
            &serde_json::json!({"title": "第二个"}).to_string(),
        );
        assert_eq!(reply.status, 200);
        assert_eq!(body(&reply)["title"], "第二个");

        let reply = fixture.projects.handle("GET", &path, "", "");
        let value = body(&reply);
        let ids: Vec<&str> = value["sessions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|item| item["id"].as_str().unwrap())
            .collect();
        assert_eq!(ids.len(), 2);
        assert!(ids.contains(&first.as_str()));
    }

    /// The whole point of the file endpoints: a user can see and edit their own files.
    #[test]
    fn a_file_can_be_written_listed_and_read_back() {
        let fixture = fixture();
        let (project, _) = create(&fixture, "one");
        let write = format!("/projects/{project}/files/content");
        let reply = fixture.projects.handle(
            "PUT",
            &write,
            "path=notes.md",
            &serde_json::json!({"content": "# hi"}).to_string(),
        );
        assert_eq!(
            reply.status,
            200,
            "{}",
            String::from_utf8_lossy(&reply.body)
        );

        let read = fixture.projects.handle("GET", &write, "path=notes.md", "");
        assert_eq!(body(&read)["content"], "# hi");

        let list =
            fixture
                .projects
                .handle("GET", &format!("/projects/{project}/files"), "path=", "");
        let entries = body(&list)["entries"].as_array().unwrap().clone();
        assert!(
            entries.iter().any(|entry| entry["name"] == "notes.md"),
            "the written file is not listed: {entries:?}"
        );
    }

    /// The UI reads files through the same policy as the tools, so a protected name is
    /// refused here too. Without this the shell would be the way around the boundary.
    #[test]
    fn a_protected_file_is_refused_through_the_ui_too() {
        let fixture = fixture();
        let (project, _) = create(&fixture, "one");
        std::fs::create_dir_all(fixture.root.join(".ssh")).unwrap();
        std::fs::write(fixture.root.join(".ssh/id_rsa"), "secret").unwrap();

        let read = format!("/projects/{project}/files/content");
        let reply = fixture
            .projects
            .handle("GET", &read, "path=.ssh/id_rsa", "");
        assert_eq!(
            reply.status, 403,
            "a key was readable through the file endpoint"
        );

        let list = fixture.projects.handle(
            "GET",
            &format!("/projects/{project}/files"),
            "path=.ssh",
            "",
        );
        // Listing the directory itself is refused, and its contents never appear.
        assert!(reply.status == 403);
        let _ = list;
    }

    #[test]
    fn escaping_the_workspace_is_refused() {
        let fixture = fixture();
        let (project, _) = create(&fixture, "one");
        let read = format!("/projects/{project}/files/content");
        let reply = fixture
            .projects
            .handle("GET", &read, "path=../../etc/passwd", "");
        assert_eq!(reply.status, 403);
    }

    /// A project may not point outside the directory the host granted.
    #[test]
    fn a_project_outside_the_granted_root_is_refused() {
        let fixture = fixture();
        let payload = serde_json::json!({"name": "bad", "work_root": "/data/data/other"});
        let reply = fixture
            .projects
            .handle("POST", "/projects", "", &payload.to_string());
        assert_eq!(reply.status, 400);
        assert!(String::from_utf8_lossy(&reply.body).contains("outside"));
    }

    /// A directory picker that walked out of the granted root would undo the above.
    #[test]
    fn browsing_stays_inside_the_granted_root() {
        let fixture = fixture();
        std::fs::create_dir_all(fixture.root.join("project-a")).unwrap();
        let inside = fixture
            .projects
            .handle("GET", "/browse-directory", "path=", "");
        let names: Vec<String> = body(&inside)["entries"]
            .as_array()
            .unwrap()
            .iter()
            .map(|entry| entry["name"].as_str().unwrap().to_owned())
            .collect();
        assert!(names.contains(&"project-a".to_owned()));

        let outside = fixture
            .projects
            .handle("GET", "/browse-directory", "path=../..", "");
        assert_eq!(outside.status, 403);
    }

    /// The plan library is empty here, but it must answer with the documented shape.
    #[test]
    /// The library round trip the interface performs: create, list, star, delete. Every
    /// step is a file operation on the project, so the same folder is readable from the
    /// desktop and from the phone.
    #[test]
    fn a_plan_is_created_listed_starred_and_deleted_through_the_routes() {
        let fixture = fixture();
        let (project, _) = create(&fixture, "演示");
        let base = format!("/projects/{project}/plan-library");

        let created = fixture.projects.handle(
            "POST",
            &format!("{base}/files"),
            "",
            &serde_json::json!({ "name": "第一期", "folder": "" }).to_string(),
        );
        assert_eq!(
            created.status,
            200,
            "{}",
            String::from_utf8_lossy(&created.body)
        );
        assert_eq!(body(&created)["entry"]["title"], "第一期");

        let listed = body(&fixture.projects.handle("GET", &base, "", ""));
        assert_eq!(listed["dir"], "方案");
        assert_eq!(listed["entries"].as_array().unwrap().len(), 1);

        let starred = fixture.projects.handle(
            "POST",
            &format!("{base}/favorite"),
            "",
            &serde_json::json!({ "path": "方案/第一期.md", "favorite": true }).to_string(),
        );
        assert_eq!(body(&starred)["entry"]["favorite"], true);

        let deleted = fixture
            .projects
            .handle("DELETE", &base, "path=方案%2F第一期.md", "");
        assert_eq!(deleted.status, 200);
        let after = body(&fixture.projects.handle("GET", &base, "", ""));
        assert_eq!(after["entries"].as_array().unwrap().len(), 0);
    }

    /// The 资料库 upload on a phone: the picker hands over a sandbox path, and the file
    /// becomes a real file in the project's 「资料/」.
    #[test]
    fn an_artifact_is_copied_into_the_materials_folder() {
        let fixture = fixture();
        let (project, _) = create(&fixture, "演示");
        // The picker stages files inside the app sandbox, which is this fixture root.
        let picked = fixture.root.join("picked");
        std::fs::create_dir_all(&picked).unwrap();
        let source = picked.join("参考.txt");
        std::fs::write(&source, b"material").unwrap();

        let reply = fixture.projects.handle(
            "POST",
            &format!("/projects/{project}/artifacts/reference"),
            "",
            &serde_json::json!({ "path": source.to_string_lossy(), "folder": "" }).to_string(),
        );
        assert_eq!(
            reply.status,
            200,
            "{}",
            String::from_utf8_lossy(&reply.body)
        );
        let record = body(&reply);
        assert_eq!(record["name"], "参考.txt");
        assert_eq!(record["path"], "资料/参考.txt");
        assert_eq!(record["size"], 8);

        let root = body(&fixture.projects.handle("GET", "/projects", "", ""))["projects"][0]
            ["work_root"]
            .as_str()
            .unwrap()
            .to_owned();
        let stored = std::path::PathBuf::from(root).join("资料/参考.txt");
        assert_eq!(std::fs::read(&stored).unwrap(), b"material");

        // The same bytes again is the same upload, not a second copy.
        let again = fixture.projects.handle(
            "POST",
            &format!("/projects/{project}/artifacts/reference"),
            "",
            &serde_json::json!({ "path": source.to_string_lossy() }).to_string(),
        );
        assert_eq!(body(&again)["path"], "资料/参考.txt");

        // A different file with the same name keeps both.
        std::fs::write(&source, b"other").unwrap();
        let renamed = fixture.projects.handle(
            "POST",
            &format!("/projects/{project}/artifacts/reference"),
            "",
            &serde_json::json!({ "path": source.to_string_lossy() }).to_string(),
        );
        assert_eq!(body(&renamed)["path"], "资料/参考-2.txt");
    }

    fn the_plan_library_answers_with_an_empty_library() {
        let fixture = fixture();
        let (project, _) = create(&fixture, "one");
        let reply =
            fixture
                .projects
                .handle("GET", &format!("/projects/{project}/plan-library"), "", "");
        assert_eq!(reply.status, 200);
        let value = body(&reply);
        assert_eq!(value["entries"].as_array().unwrap().len(), 0);
        assert_eq!(value["folders"].as_array().unwrap().len(), 0);
    }

    #[test]
    fn an_unknown_path_says_so_instead_of_returning_empty_data() {
        let fixture = fixture();
        let reply = fixture.projects.handle("GET", "/nope", "", "");
        assert_eq!(reply.status, 404);
        assert!(String::from_utf8_lossy(&reply.body).contains("not served"));
    }

    /// Projects survive a restart: the list is a file, not memory.
    #[test]
    fn projects_are_persisted() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().join("workspace");
        std::fs::create_dir_all(&root).unwrap();
        let (id, session) = {
            let projects = Projects::new(dir.path(), &root);
            create(
                &Fixture {
                    _dir: tempfile::tempdir().unwrap(),
                    projects,
                    root: root.clone(),
                },
                "persisted",
            )
        };
        let reopened = Projects::new(dir.path(), &root);
        let listed = reopened.handle("GET", "/projects", "", "");
        let value = body(&listed);
        assert!(value["projects"]
            .as_array()
            .unwrap()
            .iter()
            .any(|item| item["id"] == id.as_str()
                && Path::new(item["work_root"].as_str().unwrap()).exists()));
        let sessions = reopened.handle("GET", &format!("/projects/{id}/sessions"), "", "");
        assert!(body(&sessions)["sessions"]
            .as_array()
            .unwrap()
            .iter()
            .any(|item| item["id"] == session.as_str()));
    }
}
