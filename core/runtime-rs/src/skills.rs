//! Generic, read-only skill tools. Core skills are embedded so Android builds
//! expose the same instructions even without a source-tree filesystem.
use crate::{
    study_skills::{self, BundledStudySkillTools},
    DeviceCapabilities, RuntimeError, ToolCall, ToolDefinition, ToolPermission, ToolRuntime,
};
use async_trait::async_trait;
use serde::Serialize;
use serde_json::{json, Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Component, Path, PathBuf},
};

const CORE: &[(&str, &str)] = &[
    (
        "create-plugin",
        include_str!("../../skills/create-plugin/SKILL.md"),
    ),
    (
        "observe-events",
        include_str!("../../skills/observe-events/SKILL.md"),
    ),
    (
        "office-charts",
        include_str!("../../skills/office-charts/SKILL.md"),
    ),
    (
        "office-documents",
        include_str!("../../skills/office-documents/SKILL.md"),
    ),
    (
        "office-email",
        include_str!("../../skills/office-email/SKILL.md"),
    ),
    (
        "office-files",
        include_str!("../../skills/office-files/SKILL.md"),
    ),
    (
        "office-infographics",
        include_str!("../../skills/office-infographics/SKILL.md"),
    ),
    (
        "office-meetings",
        include_str!("../../skills/office-meetings/SKILL.md"),
    ),
    (
        "office-pdf",
        include_str!("../../skills/office-pdf/SKILL.md"),
    ),
    (
        "office-renderer",
        include_str!("../../skills/office-renderer/SKILL.md"),
    ),
    (
        "office-research",
        include_str!("../../skills/office-research/SKILL.md"),
    ),
    (
        "office-slides",
        include_str!("../../skills/office-slides/SKILL.md"),
    ),
    (
        "office-spreadsheets",
        include_str!("../../skills/office-spreadsheets/SKILL.md"),
    ),
    (
        "plugin-manager",
        include_str!("../../skills/plugin-manager/SKILL.md"),
    ),
];

// Only documented Markdown references are bundled. Other referenced assets
// are still represented by their source paths in the skill instructions.
const CORE_REFERENCES: &[(&str, &str)] = &[
    (
        "references/acceptance-tests.md",
        include_str!("../../skills/references/acceptance-tests.md"),
    ),
    (
        "references/office-design-system.md",
        include_str!("../../skills/references/office-design-system.md"),
    ),
    (
        "references/office-renderer-contract.md",
        include_str!("../../skills/references/office-renderer-contract.md"),
    ),
    (
        "references/sources.md",
        include_str!("../../skills/references/sources.md"),
    ),
    (
        "references/tooling-contract.md",
        include_str!("../../skills/references/tooling-contract.md"),
    ),
    (
        "observe-events/references/signal-protocol.md",
        include_str!("../../skills/observe-events/references/signal-protocol.md"),
    ),
];

#[derive(Clone, Debug, Serialize)]
pub struct SkillRecord {
    pub name: String,
    pub description: String,
    pub location: String,
}

#[derive(Clone)]
enum Source {
    Embedded(&'static str),
    Filesystem {
        root: PathBuf,
        skill_dir: PathBuf,
        skill_file: PathBuf,
    },
}

#[derive(Clone)]
struct Entry {
    record: SkillRecord,
    source: Source,
    implicit: bool,
}

pub struct SkillTools {
    entries: BTreeMap<String, Entry>,
    disabled: BTreeSet<String>,
}

impl SkillTools {
    /// `roots` are explicitly trusted plugin or user skill directories. Each
    /// root may contain `<name>/SKILL.md` or `skills/<name>/SKILL.md`.
    /// No arbitrary workspace path is discovered.
    pub fn new(
        disabled: impl IntoIterator<Item = String>,
        roots: impl IntoIterator<Item = PathBuf>,
    ) -> Self {
        let mut entries = BTreeMap::new();
        for (name, body) in CORE {
            entries.insert(
                (*name).into(),
                Entry {
                    record: SkillRecord {
                        name: (*name).into(),
                        description: description(body),
                        location: format!("bundled://core/{name}/SKILL.md"),
                    },
                    source: Source::Embedded(body),
                    implicit: true,
                },
            );
        }
        for root in roots {
            let Ok(root) = fs::canonicalize(&root) else {
                continue;
            };
            for parent in [root.clone(), root.join("skills")] {
                let Ok(dirs) = fs::read_dir(&parent) else {
                    continue;
                };
                for item in dirs.flatten() {
                    let name = item.file_name().to_string_lossy().into_owned();
                    if !valid_name(&name) {
                        continue;
                    }
                    let skill_dir = item.path();
                    let skill_file = skill_dir.join("SKILL.md");
                    let (Ok(dir), Ok(file)) =
                        (fs::canonicalize(&skill_dir), fs::canonicalize(&skill_file))
                    else {
                        continue;
                    };
                    if !dir.starts_with(&root) || !file.starts_with(&dir) || !file.is_file() {
                        continue;
                    }
                    let Ok(body) = fs::read_to_string(&file) else {
                        continue;
                    };
                    // Built-in names retain their canonical bundled source.
                    entries.entry(name.clone()).or_insert_with(|| Entry {
                        record: SkillRecord {
                            name: name.clone(),
                            description: description(&body),
                            location: file.display().to_string(),
                        },
                        source: Source::Filesystem {
                            root: root.clone(),
                            skill_dir: dir.clone(),
                            skill_file: file.clone(),
                        },
                        implicit: implicit_allowed(&dir),
                    });
                }
            }
        }
        Self {
            entries,
            disabled: disabled.into_iter().collect(),
        }
    }

    pub fn catalog(&self) -> Vec<SkillRecord> {
        self.entries
            .values()
            .map(|entry| entry.record.clone())
            .collect()
    }

    pub fn is_enabled(&self, name: &str) -> bool {
        self.entries.contains_key(name) && !self.disabled.contains(name)
    }

    pub fn catalog_prompt(&self) -> String {
        self.catalog_prompt_for(&DeviceCapabilities::default())
    }

    /// The skill list, told whether this host can run the commands a skill
    /// documents.
    ///
    /// Several office skills describe a validation and rendering step through
    /// `py -3.14 -m lamtools_core.cli office …`. A host without a shell cannot
    /// run it, and saying so beats letting the model announce a step it will then
    /// fail; the capability line the system prompt already carries stays the
    /// single source of truth for what this device can do.
    pub fn catalog_prompt_for(&self, capabilities: &DeviceCapabilities) -> String {
        let rows = self
            .entries
            .values()
            .filter(|entry| entry.implicit && !self.disabled.contains(&entry.record.name))
            .map(|entry| format!("- {}: {}", entry.record.name, entry.record.description))
            .collect::<Vec<_>>();
        if rows.is_empty() {
            return String::new();
        }
        let mut prompt = format!(
            "Available skills:\nUse load_skill only when the task matches a trigger below; full instructions load on demand.\n{}",
            rows.join("\n")
        );
        if !capabilities.shell {
            prompt.push_str(
                "\nSkills that describe a `py -3.14 -m lamtools_core.cli office …` step need a desktop host: \
                 this device has no shell, so produce the source files directly and say in your reply that \
                 validation and rendering have to run on the desktop.",
            );
        }
        prompt
    }

    fn lookup(&self, name: &str) -> Result<&Entry, RuntimeError> {
        if self.disabled.contains(name) {
            return Err(RuntimeError::Tool(format!("Skill '{name}' is disabled")));
        }
        self.entries
            .get(name)
            .ok_or_else(|| RuntimeError::Tool(format!("Unknown skill: {name}")))
    }

    pub fn load(&self, name: &str) -> Result<Value, RuntimeError> {
        let entry = self.lookup(name)?;
        let body = match &entry.source {
            Source::Embedded(body) => (*body).to_owned(),
            Source::Filesystem { skill_file, .. } => {
                fs::read_to_string(skill_file).map_err(|err| RuntimeError::Tool(err.to_string()))?
            }
        };
        let base = match &entry.source {
            Source::Embedded(_) => format!("bundled://core/{name}"),
            Source::Filesystem { skill_dir, .. } => skill_dir.display().to_string(),
        };
        let content = format!("<skill_content name=\"{name}\">\n# Skill: {name}\n\n{}\n\nBase directory for this skill: {base}\nRelative paths in this skill are relative to this base directory.\n</skill_content>", body.trim());
        Ok(json!({"name":name,"location":entry.record.location,"content":content}))
    }

    pub fn read_reference(&self, name: &str, path: &str) -> Result<Value, RuntimeError> {
        let entry = self.lookup(name)?;
        let parts = safe_reference_parts(path)?;
        let (location, content) = match &entry.source {
            Source::Embedded(_) => {
                // Common references are a sibling of core skill directories.
                let key = if parts[0] == ".." {
                    if parts.len() != 3 || parts[1] != "references" {
                        return Err(invalid_reference());
                    }
                    format!("references/{}", parts[2])
                } else {
                    if parts.len() != 2 || parts[0] != "references" {
                        return Err(invalid_reference());
                    }
                    format!("{name}/{}", parts.join("/"))
                };
                let content = CORE_REFERENCES
                    .iter()
                    .find(|(candidate, _)| *candidate == key)
                    .map(|(_, text)| *text)
                    .ok_or_else(invalid_reference)?;
                (format!("bundled://core/{key}"), content.to_owned())
            }
            Source::Filesystem {
                root, skill_dir, ..
            } => {
                let candidate = skill_dir.join(path);
                let resolved = fs::canonicalize(&candidate).map_err(|_| invalid_reference())?;
                if !resolved.starts_with(root) || !resolved.is_file() {
                    return Err(invalid_reference());
                }
                let inside_skill =
                    resolved.starts_with(skill_dir) && parts.len() == 2 && parts[0] == "references";
                let common_reference = parts.len() == 3
                    && parts[0] == ".."
                    && parts[1] == "references"
                    && resolved.parent()
                        == skill_dir
                            .parent()
                            .map(|parent| parent.join("references"))
                            .as_deref();
                if !inside_skill && !common_reference {
                    return Err(invalid_reference());
                }
                let content = fs::read_to_string(&resolved)
                    .map_err(|err| RuntimeError::Tool(err.to_string()))?;
                (resolved.display().to_string(), content)
            }
        };
        Ok(json!({"name":name,"path":path,"location":location,"content":content}))
    }
}

fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
}

fn invalid_reference() -> RuntimeError {
    RuntimeError::Tool("Reference path is outside the skill's allowed Markdown references".into())
}

fn safe_reference_parts(path: &str) -> Result<Vec<&str>, RuntimeError> {
    if path.contains('\\') || !path.ends_with(".md") || path.contains('\0') {
        return Err(invalid_reference());
    }
    let components = Path::new(path).components().collect::<Vec<_>>();
    if components
        .iter()
        .any(|component| !matches!(component, Component::Normal(_) | Component::ParentDir))
    {
        return Err(invalid_reference());
    }
    let parts = path.split('/').collect::<Vec<_>>();
    if parts
        .iter()
        .enumerate()
        .any(|(index, part)| part.is_empty() || *part == "." || (*part == ".." && index != 0))
    {
        return Err(invalid_reference());
    }
    Ok(parts)
}

fn description(body: &str) -> String {
    body.lines()
        .skip(1)
        .take_while(|line| *line != "---")
        .find_map(|line| {
            line.strip_prefix("description:")
                .map(|value| value.trim().trim_matches(['\'', '"']).to_owned())
        })
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "Specialized capability.".into())
}

fn implicit_allowed(dir: &Path) -> bool {
    let Ok(raw) = fs::read_to_string(dir.join("agents/openai.yaml")) else {
        return true;
    };
    !raw.lines().any(|line| {
        line.trim()
            .eq_ignore_ascii_case("allow_implicit_invocation: false")
    })
}

#[cfg(test)]
mod capability_tests {
    use super::*;

    fn tools() -> SkillTools {
        SkillTools::new(Vec::new(), Vec::new())
    }

    #[test]
    fn a_host_without_a_shell_is_told_which_steps_it_cannot_run() {
        let with_shell = DeviceCapabilities {
            shell: true,
            ..Default::default()
        };
        let without_shell = DeviceCapabilities {
            shell: false,
            ..Default::default()
        };
        let desktop = tools().catalog_prompt_for(&with_shell);
        let phone = tools().catalog_prompt_for(&without_shell);
        // The skill list is the same on both: the instructions are shared.
        assert!(desktop.contains("office-documents"));
        assert!(phone.contains("office-documents"));
        // Only the host that cannot run the CLI says so.
        assert!(!desktop.contains("need a desktop host"));
        assert!(phone.contains("need a desktop host"));
        assert!(phone.contains("lamtools_core.cli office"));
        assert!(phone.contains("has no shell"));
    }

    #[test]
    fn the_combined_catalog_carries_the_same_note() {
        let without_shell = DeviceCapabilities {
            shell: false,
            ..Default::default()
        };
        let combined = CombinedSkillTools::new(Vec::new(), Vec::new()).catalog_prompt_for(&without_shell);
        assert!(combined.contains("need a desktop host"));
        // Study skills are appended after the core list, as before.
        let with_shell = CombinedSkillTools::new(Vec::new(), Vec::new())
            .catalog_prompt_for(&DeviceCapabilities {
                shell: true,
                ..Default::default()
            });
        assert!(!with_shell.contains("need a desktop host"));
    }
}

#[async_trait]
impl ToolRuntime for SkillTools {
    fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        vec![
            ToolDefinition {
                name: "load_skill".into(),
                description: "Load an available skill's instructions by name.".into(),
                input_schema: json!({"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}),
            },
            ToolDefinition {
                name: "read_skill_reference".into(),
                description: "Read a Markdown reference linked by a loaded skill.".into(),
                input_schema: json!({"type":"object","properties":{"name":{"type":"string"},"path":{"type":"string"}},"required":["name","path"]}),
            },
        ]
    }
    fn permission(&self, _call: &ToolCall) -> ToolPermission {
        ToolPermission::AutoAllow
    }
    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        let name = call
            .arguments
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default();
        match call.name.as_str() {
            "load_skill" => self.load(name),
            "read_skill_reference" => self.read_reference(
                name,
                call.arguments
                    .get("path")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
            ),
            other => Err(RuntimeError::Tool(format!("Unknown skill tool: {other}"))),
        }
    }
}

/// One tool owner for both ordinary Core skills and the separately bundled
/// Study skills. Use this in Study mode to avoid duplicate tool names in a
/// CompositeToolRuntime, which routes all calls to the first owner.
pub struct CombinedSkillTools {
    core: SkillTools,
    study: BundledStudySkillTools,
    study_names: BTreeSet<String>,
    disabled: Vec<String>,
}

impl CombinedSkillTools {
    pub fn new(
        disabled: impl IntoIterator<Item = String>,
        roots: impl IntoIterator<Item = PathBuf>,
    ) -> Self {
        let disabled = disabled.into_iter().collect::<Vec<_>>();
        let study_names = study_skills::catalog()
            .into_iter()
            .map(|skill| skill.name)
            .collect();
        Self {
            core: SkillTools::new(disabled.clone(), roots),
            study: BundledStudySkillTools::new(disabled.clone()),
            study_names,
            disabled,
        }
    }

    pub fn catalog(&self) -> Vec<SkillRecord> {
        let mut entries = self
            .core
            .catalog()
            .into_iter()
            .filter(|skill| !self.study_names.contains(&skill.name))
            .collect::<Vec<_>>();
        entries.extend(
            study_skills::catalog()
                .into_iter()
                .map(|skill| SkillRecord {
                    name: skill.name,
                    description: skill.description,
                    location: skill.location,
                }),
        );
        entries.sort_by(|left, right| left.name.cmp(&right.name));
        entries
    }

    pub fn catalog_prompt(&self) -> String {
        self.catalog_prompt_for(&DeviceCapabilities::default())
    }

    /// The combined list, told whether this host can run documented commands.
    pub fn catalog_prompt_for(&self, capabilities: &DeviceCapabilities) -> String {
        format!(
            "{}\n{}",
            self.core.catalog_prompt_for(capabilities),
            study_skills::catalog_prompt(&self.disabled)
        )
        .trim()
        .to_owned()
    }

    pub fn is_enabled(&self, name: &str) -> bool {
        if self.study_names.contains(name) {
            !self.disabled.iter().any(|disabled| disabled == name)
        } else {
            self.core.is_enabled(name)
        }
    }
}

#[async_trait]
impl ToolRuntime for CombinedSkillTools {
    fn definitions(&self, capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        self.core.definitions(capabilities)
    }
    fn permission(&self, call: &ToolCall) -> ToolPermission {
        self.core.permission(call)
    }
    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        let name = call
            .arguments
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if self.study_names.contains(name) {
            self.study.execute(call).await
        } else {
            self.core.execute(call).await
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn bundled_core_catalog_load_and_shared_reference_are_real_content() {
        let tools = SkillTools::new(Vec::<String>::new(), Vec::<PathBuf>::new());
        assert_eq!(tools.catalog().len(), 14);
        assert!(tools.catalog_prompt().contains("office-documents"));
        let loaded = tools
            .execute(&ToolCall {
                id: "1".into(),
                name: "load_skill".into(),
                arguments: json!({"name":"office-documents"}),
            })
            .await
            .unwrap();
        assert!(loaded["content"]
            .as_str()
            .unwrap()
            .contains("<skill_content name=\"office-documents\">"));
        assert!(loaded["content"]
            .as_str()
            .unwrap()
            .contains("../references/office-design-system.md"));
        let reference = tools.execute(&ToolCall { id: "2".into(), name: "read_skill_reference".into(), arguments: json!({"name":"office-documents","path":"../references/office-design-system.md"}) }).await.unwrap();
        assert!(reference["content"].as_str().unwrap().len() > 100);
        for path in [
            "../../secret.md",
            "../office-email/SKILL.md",
            "C:/secret.md",
            "references/../../secret.md",
            "../references/../secret.md",
        ] {
            assert!(
                tools.read_reference("office-documents", path).is_err(),
                "accepted {path}"
            );
        }
    }

    #[tokio::test]
    async fn disabled_skill_cannot_be_loaded_or_referenced() {
        let tools = SkillTools::new(["office-documents".into()], Vec::<PathBuf>::new());
        assert!(!tools
            .catalog_prompt()
            .lines()
            .any(|line| line.starts_with("- office-documents:")));
        assert!(tools
            .catalog()
            .iter()
            .any(|skill| skill.name == "office-documents"));
        assert!(!tools.is_enabled("office-documents"));
        assert!(tools.load("office-documents").is_err());
        assert!(tools
            .read_reference("office-documents", "../references/office-design-system.md")
            .is_err());
    }

    #[tokio::test]
    async fn plugin_root_reference_cannot_escape() {
        let root =
            std::env::temp_dir().join(format!("lamtools-skill-test-{}", uuid::Uuid::new_v4()));
        let dir = root.join("skills/example");
        fs::create_dir_all(dir.join("references")).unwrap();
        fs::write(dir.join("SKILL.md"), "---\nname: example\ndescription: Plugin fixture\n---\nUse [guide](references/guide.md).").unwrap();
        fs::write(dir.join("references/guide.md"), "approved guide").unwrap();
        fs::write(root.join("secret.md"), "secret").unwrap();
        let tools = SkillTools::new(Vec::<String>::new(), [root.clone()]);
        assert!(tools.catalog().iter().any(|skill| skill.name == "example"));
        assert_eq!(
            tools
                .read_reference("example", "references/guide.md")
                .unwrap()["content"],
            "approved guide"
        );
        assert!(tools.read_reference("example", "../../secret.md").is_err());
        assert!(tools
            .read_reference("example", "../references/guide.md")
            .is_err());
        fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn combined_loader_serves_core_and_study_without_duplicate_tool_definitions() {
        let tools = CombinedSkillTools::new(Vec::<String>::new(), Vec::<PathBuf>::new());
        assert_eq!(tools.definitions(&DeviceCapabilities::default()).len(), 2);
        assert_eq!(tools.catalog().len(), 19);
        for name in ["office-documents", "build-map"] {
            let result = tools
                .execute(&ToolCall {
                    id: name.into(),
                    name: "load_skill".into(),
                    arguments: json!({"name":name}),
                })
                .await
                .unwrap();
            assert!(result["content"]
                .as_str()
                .unwrap()
                .contains("<skill_content"));
        }
        let disabled = CombinedSkillTools::new(["build-map".into()], Vec::<PathBuf>::new());
        assert!(!disabled.is_enabled("build-map"));
        assert!(disabled
            .execute(&ToolCall {
                id: "x".into(),
                name: "load_skill".into(),
                arguments: json!({"name":"build-map"})
            })
            .await
            .is_err());
    }
}
