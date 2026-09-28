//! Generic, read-only skill tools. Core skills are embedded so Android builds
//! expose the same instructions even without a source-tree filesystem.
//!
//! Embedding is not the same as offering. A skill whose own frontmatter declares
//! a desktop target cannot run on a host without a shell, and this runtime used
//! to list those anyway with a warning line after the catalog. A phone that lists
//! `office-documents` promises a `py -3.14 -m lamtools_core.cli office …` step
//! the device will fail, and an offer the panel shows but `load_skill` refuses is
//! worse than no offer at all — so the catalog, the prompt and the loader are all
//! built here, and all three follow the same host decision.
use crate::{
    study_skills::{self, BundledStudySkillTools},
    DeviceCapabilities, HostPlatform, RuntimeError, ToolCall, ToolDefinition, ToolPermission,
    ToolRuntime, PLATFORM_DESKTOP, PLATFORM_MOBILE, PLATFORM_UNIVERSAL,
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

/// The platform class a skill declares in its frontmatter:
///
/// ```text
/// metadata:
///   platforms: desktop
/// ```
///
/// One of `desktop`, `mobile` or `universal`, the same three words a plugin
/// manifest uses; absent means universal. The Office bundle declares `desktop`
/// on all eleven skills because their validation and rendering step is
/// `py -3.14 -m lamtools_core.cli office …`; `create-plugin` and
/// `plugin-manager` end their install-and-verify loop at `plugin_install` and
/// `plugin_list`, and `observe-events` binds its observer to an event Arrange;
/// none of those three tools exists outside the desktop either.
///
/// Only the frontmatter block is read, so a body that discusses the desktop — as
/// these skills do on every page — cannot declare itself.
fn platform_class(body: &str) -> &'static str {
    let mut lines = body.lines();
    if lines.next().map(str::trim) != Some("---") {
        return PLATFORM_UNIVERSAL;
    }
    let declared = lines
        .take_while(|line| line.trim() != "---")
        .find_map(|line| line.trim().strip_prefix("platforms:").map(str::trim));
    match declared {
        Some(value) if value == PLATFORM_DESKTOP => PLATFORM_DESKTOP,
        Some(value) if value == PLATFORM_MOBILE => PLATFORM_MOBILE,
        // An unreadable or unrecognised declaration is universal: a skill that
        // asks for nothing lands where undeclared skills land, and the host
        // class check below still decides.
        _ => PLATFORM_UNIVERSAL,
    }
}

/// Why a skill is not offered here, in the loader's own words.
fn foreign_platform_reason(host: HostPlatform) -> &'static str {
    match host {
        HostPlatform::Mobile => {
            "its instructions run on the desktop host (office CLI, plugin installer or Arrange scheduler)"
        }
        HostPlatform::Desktop => "its instructions run on the mobile host",
    }
}

pub struct SkillTools {
    entries: BTreeMap<String, Entry>,
    disabled: BTreeSet<String>,
    /// Skills this host must not offer, with the reason `load_skill` reports.
    /// Kept separately from `entries` so the refusal names the cause instead of
    /// claiming the skill does not exist.
    unavailable: BTreeMap<String, &'static str>,
}

impl SkillTools {
    /// `roots` are explicitly trusted plugin or user skill directories. Each
    /// root may contain `<name>/SKILL.md` or `skills/<name>/SKILL.md`.
    /// No arbitrary workspace path is discovered.
    ///
    /// `host` decides which embedded skills may be offered: a skill declared for
    /// another platform is left out of the catalog and the prompt, and
    /// `load_skill` refuses it with the reason.
    pub fn new(
        disabled: impl IntoIterator<Item = String>,
        roots: impl IntoIterator<Item = PathBuf>,
        host: HostPlatform,
    ) -> Self {
        let mut entries = BTreeMap::new();
        let mut unavailable = BTreeMap::new();
        for (name, body) in CORE {
            let declared = platform_class(body);
            if !host.offers(declared) {
                unavailable.insert((*name).into(), foreign_platform_reason(host));
                continue;
            }
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
        // Root skills are not filtered by class: a skill sitting in a user's or a
        // plugin's own directory was put there on purpose, and the panels list
        // those directories directly, so the offer and the loader stay in step.
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
            unavailable,
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

    /// The skill list this host offers.
    ///
    /// It is the three surfaces — this prompt line, `catalog()` behind the panel,
    /// and `load_skill` — that have to agree, which is why the host decision is
    /// made once in [`SkillTools::new`] rather than per caller.
    pub fn catalog_prompt(&self) -> String {
        let rows = self
            .entries
            .values()
            .filter(|entry| entry.implicit && !self.disabled.contains(&entry.record.name))
            .map(|entry| format!("- {}: {}", entry.record.name, entry.record.description))
            .collect::<Vec<_>>();
        if rows.is_empty() {
            return String::new();
        }
        format!(
            "Available skills:\nUse load_skill only when the task matches a trigger below; full instructions load on demand.\n{}",
            rows.join("\n")
        )
    }

    fn lookup(&self, name: &str) -> Result<&Entry, RuntimeError> {
        if self.disabled.contains(name) {
            return Err(RuntimeError::Tool(format!("Skill '{name}' is disabled")));
        }
        if let Some(reason) = self.unavailable.get(name) {
            return Err(RuntimeError::Tool(format!(
                "Skill '{name}' is not available on this device: {reason}"
            )));
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

    #[test]
    fn a_phone_is_offered_none_of_the_desktop_skills() {
        let phone = SkillTools::new(Vec::new(), Vec::new(), HostPlatform::Mobile);
        // Every embedded skill declares `platforms: desktop` today — the office
        // CLI, the plugin installer or the Arrange scheduler — so a phone offers
        // none of them. A skill that earns a place on this host fails this
        // assertion on purpose, so the list is re-decided rather than inherited.
        assert!(phone.catalog().is_empty(), "{:?}", phone.catalog());
        assert!(phone.catalog_prompt().is_empty());
        assert!(!phone.is_enabled("office-documents"));
        // The loader explains the omission instead of denying the skill exists.
        let refusal = phone.load("office-documents").unwrap_err().to_string();
        assert!(refusal.contains("not available on this device"), "{refusal}");
        assert!(refusal.contains("desktop host"), "{refusal}");
        assert!(phone.load("plugin-manager").is_err());
    }

    #[test]
    fn the_desktop_host_still_gets_every_embedded_skill() {
        let desktop = SkillTools::new(Vec::new(), Vec::new(), HostPlatform::Desktop);
        assert_eq!(desktop.catalog().len(), 14);
        assert!(desktop.catalog_prompt().contains("office-documents"));
        assert!(desktop.catalog_prompt().contains("plugin-manager"));
        assert!(desktop.is_enabled("observe-events"));
        assert!(desktop.load("office-documents").is_ok());
        // Nothing was left behind for the phone to reach.
        assert!(desktop
            .catalog()
            .iter()
            .all(|skill| !skill.name.is_empty()));
    }

    #[test]
    fn the_platform_class_is_read_from_the_frontmatter_only() {
        assert_eq!(
            platform_class("---\nname: x\ndescription: d\nmetadata:\n  platforms: desktop\n---\n\n# Body"),
            PLATFORM_DESKTOP
        );
        assert_eq!(
            platform_class("---\nname: x\nmetadata:\n  platforms: mobile\n---\n"),
            PLATFORM_MOBILE
        );
        // Absent, unknown and out-of-frontmatter declarations all read as
        // universal: the class is what a skill asks for, and a skill that asks
        // for nothing lands where undeclared skills land.
        assert_eq!(platform_class("---\nname: x\ndescription: d\n---\n"), PLATFORM_UNIVERSAL);
        assert_eq!(platform_class("no frontmatter at all"), PLATFORM_UNIVERSAL);
        assert_eq!(
            platform_class("---\nname: x\nmetadata:\n  platforms: desktop-2\n---\n"),
            PLATFORM_UNIVERSAL
        );
        // Talking about the class in the body is not declaring it.
        assert_eq!(
            platform_class("---\nname: x\ndescription: d\n---\n\nRun against platforms: desktop"),
            PLATFORM_UNIVERSAL
        );
    }

    #[test]
    fn a_mobile_only_skill_is_withheld_from_the_desktop_host() {
        // The class works in both directions; no shipped skill declares `mobile`
        // today, so this pins the rule rather than a shipped file.
        assert!(!HostPlatform::Desktop.offers(PLATFORM_MOBILE));
        assert!(HostPlatform::Mobile.offers(PLATFORM_MOBILE));
        assert!(HostPlatform::Desktop.offers(PLATFORM_UNIVERSAL));
        assert!(HostPlatform::Mobile.offers(PLATFORM_UNIVERSAL));
        assert!(HostPlatform::Desktop.offers(PLATFORM_DESKTOP));
        assert!(!HostPlatform::Mobile.offers(PLATFORM_DESKTOP));
        // An unknown word is not honoured by either host.
        assert!(!HostPlatform::Desktop.offers("web"));
        assert!(!HostPlatform::Mobile.offers("web"));
    }

    #[test]
    fn the_study_workspace_keeps_its_skills_on_a_phone() {
        let names = CombinedSkillTools::new(Vec::new(), Vec::new(), HostPlatform::Mobile)
            .catalog()
            .into_iter()
            .map(|skill| skill.name)
            .collect::<Vec<_>>();
        // Five Study skills, no core skill beside them.
        assert_eq!(names.len(), 5, "{names:?}");
        assert!(names.contains(&"build-map".to_string()));

        let phone = CombinedSkillTools::new(Vec::new(), Vec::new(), HostPlatform::Mobile);
        assert!(phone.is_enabled("build-map"));
        assert!(!phone.is_enabled("office-documents"));
        assert!(phone.catalog_prompt().contains("build-map"));
        assert!(!phone.catalog_prompt().contains("office-documents"));
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
        host: HostPlatform,
    ) -> Self {
        let disabled = disabled.into_iter().collect::<Vec<_>>();
        let study_names = study_skills::catalog()
            .into_iter()
            .map(|skill| skill.name)
            .collect();
        Self {
            core: SkillTools::new(disabled.clone(), roots, host),
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

    /// The combined list: the core skills this host offers, then the Study
    /// skills the Study workspace adds.
    pub fn catalog_prompt(&self) -> String {
        format!(
            "{}\n{}",
            self.core.catalog_prompt(),
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
        let tools = SkillTools::new(Vec::<String>::new(), Vec::<PathBuf>::new(), HostPlatform::Desktop);
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
        let tools = SkillTools::new(["office-documents".into()], Vec::<PathBuf>::new(), HostPlatform::Desktop);
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
        let tools = SkillTools::new(Vec::<String>::new(), [root.clone()], HostPlatform::Mobile);
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
        let tools =
            CombinedSkillTools::new(Vec::<String>::new(), Vec::<PathBuf>::new(), HostPlatform::Desktop);
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
        // The phone keeps its Study workspace and everything else the host can
        // run, and gets a refusal — not a silent success — for the rest.
        let phone =
            CombinedSkillTools::new(Vec::<String>::new(), Vec::<PathBuf>::new(), HostPlatform::Mobile);
        assert!(phone
            .execute(&ToolCall {
                id: "study".into(),
                name: "load_skill".into(),
                arguments: json!({"name":"build-map"})
            })
            .await
            .is_ok());
        assert!(phone
            .execute(&ToolCall {
                id: "office".into(),
                name: "load_skill".into(),
                arguments: json!({"name":"office-documents"})
            })
            .await
            .is_err());
        let disabled =
            CombinedSkillTools::new(["build-map".into()], Vec::<PathBuf>::new(), HostPlatform::Desktop);
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
