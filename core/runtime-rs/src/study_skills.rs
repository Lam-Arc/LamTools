//! Bundled Study skills for the embedded Android agent. Source text is shared
//! with the desktop/Python plugin, so an APK cannot advertise absent files.
use crate::{
    DeviceCapabilities, RuntimeError, ToolCall, ToolDefinition, ToolPermission, ToolRuntime,
};
use async_trait::async_trait;
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::BTreeSet;

const ANSWER: &str =
    include_str!("../../src/lamtools_core/plugins/bundled/study/skills/answer/SKILL.md");
const BUILD_MAP: &str =
    include_str!("../../src/lamtools_core/plugins/bundled/study/skills/build-map/SKILL.md");
const TAKE_EXAM: &str =
    include_str!("../../src/lamtools_core/plugins/bundled/study/skills/take-exam/SKILL.md");
const TEACH: &str =
    include_str!("../../src/lamtools_core/plugins/bundled/study/skills/teach/SKILL.md");
const CURATE_NOTES: &str =
    include_str!("../../src/lamtools_core/plugins/bundled/study/future/curate-notes/SKILL.md");

const REFERENCES: &[(&str, &str, &str)] = &[
    ("answer", "references/diagnosis.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/answer/references/diagnosis.md")),
    ("answer", "references/resources.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/answer/references/resources.md")),
    ("build-map", "references/curriculum.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/build-map/references/curriculum.md")),
    ("build-map", "references/resources.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/build-map/references/resources.md")),
    ("take-exam", "references/assessment.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/take-exam/references/assessment.md")),
    ("take-exam", "references/grading.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/take-exam/references/grading.md")),
    ("take-exam", "references/resources.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/take-exam/references/resources.md")),
    ("teach", "references/density.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/teach/references/density.md")),
    ("teach", "references/examples.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/teach/references/examples.md")),
    ("teach", "references/pedagogy.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/teach/references/pedagogy.md")),
    ("teach", "references/resources.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/teach/references/resources.md")),
    ("teach", "references/visuals.md", include_str!("../../src/lamtools_core/plugins/bundled/study/skills/teach/references/visuals.md")),
    ("curate-notes", "references/notes.md", include_str!("../../src/lamtools_core/plugins/bundled/study/future/curate-notes/references/notes.md")),
    ("curate-notes", "references/resources.md", include_str!("../../src/lamtools_core/plugins/bundled/study/future/curate-notes/references/resources.md")),
];

const SKILLS: &[(&str, &str, &str)] = &[
    ("answer", "skills/answer", ANSWER),
    ("build-map", "skills/build-map", BUILD_MAP),
    ("take-exam", "skills/take-exam", TAKE_EXAM),
    ("teach", "skills/teach", TEACH),
    ("curate-notes", "future/curate-notes", CURATE_NOTES),
];

#[derive(Clone, Debug, Serialize)]
pub struct StudySkillRecord {
    pub name: String,
    pub description: String,
    pub location: String,
}

fn frontmatter_field<'a>(content: &'a str, field: &str) -> Option<&'a str> {
    content
        .lines()
        .skip(1)
        .take_while(|line| *line != "---")
        .find_map(|line| {
            line.strip_prefix(field)
                .and_then(|rest| rest.strip_prefix(": "))
        })
}

pub fn catalog() -> Vec<StudySkillRecord> {
    SKILLS
        .iter()
        .map(|(name, folder, body)| StudySkillRecord {
            name: (*name).into(),
            description: frontmatter_field(body, "description")
                .unwrap_or_default()
                .into(),
            location: format!("bundled://study/{folder}/SKILL.md"),
        })
        .collect()
}

pub fn catalog_prompt(disabled: &[String]) -> String {
    let names = disabled.iter().map(String::as_str).collect::<BTreeSet<_>>();
    let available = catalog()
        .into_iter()
        .filter(|skill| !names.contains(skill.name.as_str()))
        .map(|skill| format!("- {}: {}", skill.name, skill.description))
        .collect::<Vec<_>>();
    format!("Available Study skills (use load_skill only when relevant; use read_skill_reference for linked reference files):\n{}", available.join("\n"))
}

pub struct BundledStudySkillTools {
    disabled: BTreeSet<String>,
}

impl BundledStudySkillTools {
    pub fn new(disabled: impl IntoIterator<Item = String>) -> Self {
        Self {
            disabled: disabled.into_iter().collect(),
        }
    }

    fn lookup(&self, name: &str) -> Result<(&'static str, &'static str), RuntimeError> {
        if self.disabled.contains(name) {
            return Err(RuntimeError::Tool(format!(
                "Study skill '{name}' is disabled"
            )));
        }
        SKILLS
            .iter()
            .find(|(skill, _, _)| *skill == name)
            .map(|(_, folder, body)| (*folder, *body))
            .ok_or_else(|| RuntimeError::Tool(format!("Unknown Study skill: {name}")))
    }
}

#[async_trait]
impl ToolRuntime for BundledStudySkillTools {
    fn definitions(&self, _capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        if SKILLS
            .iter()
            .all(|(name, _, _)| self.disabled.contains(*name))
        {
            return Vec::new();
        }
        vec![
            ToolDefinition { name: "load_skill".into(), description: "Load the complete instructions for an available Study skill by name.".into(), input_schema: json!({"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}) },
            ToolDefinition { name: "read_skill_reference".into(), description: "Read one reference linked by a Study skill. Provide the skill name and its relative references/*.md path.".into(), input_schema: json!({"type":"object","properties":{"name":{"type":"string"},"path":{"type":"string"}},"required":["name","path"]}) },
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
        let (folder, body) = self.lookup(name)?;
        match call.name.as_str() {
            "load_skill" => Ok(
                json!({"name":name,"location":format!("bundled://study/{folder}/SKILL.md"),"content":format!("<skill_content name=\"{name}\">\n{body}\n</skill_content>")}),
            ),
            "read_skill_reference" => {
                let path = call
                    .arguments
                    .get("path")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let content = REFERENCES
                    .iter()
                    .find(|(skill, reference, _)| *skill == name && *reference == path)
                    .map(|(_, _, content)| *content)
                    .ok_or_else(|| {
                        RuntimeError::Tool(format!(
                            "Unknown reference for Study skill '{name}': {path}"
                        ))
                    })?;
                Ok(
                    json!({"name":name,"path":path,"location":format!("bundled://study/{folder}/{path}"),"content":content}),
                )
            }
            other => Err(RuntimeError::Tool(format!(
                "Unknown Study skill tool: {other}"
            ))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn canonical_skill_and_future_reference_are_readable_and_disable_is_enforced() {
        let tools = BundledStudySkillTools::new(Vec::new());
        let loaded = tools
            .execute(&ToolCall {
                id: "1".into(),
                name: "load_skill".into(),
                arguments: json!({"name":"curate-notes"}),
            })
            .await
            .unwrap();
        assert!(loaded["content"]
            .as_str()
            .unwrap()
            .contains("<skill_content name=\"curate-notes\">"));
        assert_eq!(
            loaded["location"],
            "bundled://study/future/curate-notes/SKILL.md"
        );
        let reference = tools
            .execute(&ToolCall {
                id: "2".into(),
                name: "read_skill_reference".into(),
                arguments: json!({"name":"curate-notes","path":"references/notes.md"}),
            })
            .await
            .unwrap();
        assert!(reference["content"]
            .as_str()
            .unwrap()
            .contains("A Note is an actual user-visible Markdown file"));
        assert!(tools
            .execute(&ToolCall {
                id: "3".into(),
                name: "read_skill_reference".into(),
                arguments: json!({"name":"curate-notes","path":"../SKILL.md"})
            })
            .await
            .is_err());
        let disabled = BundledStudySkillTools::new(["build-map".into()]);
        assert!(disabled
            .execute(&ToolCall {
                id: "4".into(),
                name: "load_skill".into(),
                arguments: json!({"name":"build-map"})
            })
            .await
            .is_err());
        assert!(!catalog_prompt(&["build-map".into()]).contains("- build-map:"));
        assert!(catalog()
            .iter()
            .any(|skill| skill.name == "build-map" && skill.description.contains("knowledge")));
    }
}
