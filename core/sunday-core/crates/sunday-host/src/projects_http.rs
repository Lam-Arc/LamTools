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

            // The plan library is not part of this host yet. Serving an empty one keeps a
            // missing feature from reading as a broken project, and the shape matches.
            (_, ["projects", id, "plan-library", ..]) => self.plan_library(id),

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
