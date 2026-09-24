//! Tool catalog for the mode tool-set editor (`config.loadtools.get`).
//!
//! The editor renders a grouped checklist of every tool the agent can be given,
//! so it needs names and categories. Desktop builds that list from tool specs and
//! plugin runtimes; this host has no plugin loader, so the list is derived from
//! the definitions the Rust runtimes actually return — a tool the runtime would
//! refuse to run must not appear in the checklist (an earlier mobile panel
//! advertised plugin tools that did not exist, which is why this is derived).
//!
//! Categories use the desktop vocabulary (`file_read`, `web`, `skill`, ...) so a
//! mode configured on one host means the same thing on the other.
use serde::Serialize;

use crate::fetch_tools::WebFetchTools;
use crate::image_gen::{GenerateImageTools, ImageGenConfig, ImageSink};
use crate::project_tools::ProjectFileTools;
use crate::study::IMPLEMENTED_STUDY_TOOLS;
use crate::sub_agent::{SUB_AGENT_MESSAGE_TOOL, SUB_AGENT_TOOL};
use crate::skills::CombinedSkillTools;
use crate::web_search::WebSearchTools;
use crate::{DeviceCapabilities, ToolRuntime};

/// One selectable tool in the editor.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct CatalogTool {
    pub name: String,
    pub category: String,
}

/// Desktop's `DEFAULT_TOOL_CATEGORIES`, restricted to the names this host
/// assembles. Study tools keep the `other` bucket desktop leaves them in.
fn category_of(name: &str) -> &'static str {
    match name {
        "read_file" | "list_dir" | "search_files" | "search_content" => "file_read",
        "write_file" | "edit_file" => "file_write",
        "web_search" | "web_fetch" => "web",
        "generate_image" => "image",
        "load_skill" | "read_skill_reference" => "skill",
        "mcp_activate" | "mcp_tool" => "mcp",
        SUB_AGENT_TOOL | SUB_AGENT_MESSAGE_TOOL | "message" => "agent",
        _ => "other",
    }
}

struct NullSink;

#[async_trait::async_trait]
impl ImageSink for NullSink {
    async fn save_image(
        &self,
        _filename: &str,
        _mime: &str,
        _bytes: &[u8],
    ) -> Result<String, crate::RuntimeError> {
        Ok("attachment://catalog".into())
    }
}

/// Every tool this host can advertise, in a stable order.
///
/// The names come from the runtimes themselves rather than from a list kept
/// here: `definitions` is what the model is offered, so the editor cannot drift
/// from it. Runtimes that need live state (Study's store, the sub-agent hub) are
/// represented by their published name constants, which the tests pin.
pub fn catalog_tools() -> Vec<CatalogTool> {
    let capabilities = DeviceCapabilities {
        git: false,
        network: true,
        notifications: false,
        project_files: true,
        shell: false,
        platform: "catalog".into(),
    };
    let mut names: Vec<String> = Vec::new();
    let push = |runtime_names: Vec<String>, names: &mut Vec<String>| {
        for name in runtime_names {
            if !names.contains(&name) {
                names.push(name);
            }
        }
    };
    push(
        definitions(ProjectFileTools::new(std::env::temp_dir()), &capabilities),
        &mut names,
    );
    push(definitions(WebFetchTools::new(), &capabilities), &mut names);
    push(definitions(WebSearchTools::new(), &capabilities), &mut names);
    push(
        definitions(
            GenerateImageTools::new(
                // Image generation hides itself until it is configured, so the
                // catalog asks with a configured stand-in; the editor must be
                // able to grant the tool before the user has filled the form.
                ImageGenConfig {
                    enabled: true,
                    api_url: "https://catalog.invalid/v1".into(),
                    api_key: String::new(),
                    model: String::new(),
                },
                std::sync::Arc::new(NullSink),
            ),
            &capabilities,
        ),
        &mut names,
    );
    // Skills are embedded in the runtime, so the catalog can ask the real
    // runtime rather than naming `load_skill` itself.
    push(
        definitions(
            CombinedSkillTools::new(Vec::new(), Vec::new()),
            &capabilities,
        ),
        &mut names,
    );
    // Study tools are assembled only inside the Study workspace; the mode editor
    // still has to be able to grant them.
    for name in IMPLEMENTED_STUDY_TOOLS {
        push(vec![name.to_owned()], &mut names);
    }
    for name in [
        SUB_AGENT_TOOL,
        SUB_AGENT_MESSAGE_TOOL,
        // The MCP gateway is config-dependent (servers come from user config),
        // so the gateway itself is listed instead of individual server tools.
        "mcp_activate",
    ] {
        push(vec![name.to_owned()], &mut names);
    }
    let mut catalog: Vec<CatalogTool> = names
        .into_iter()
        .map(|name| CatalogTool {
            category: category_of(&name).to_owned(),
            name,
        })
        .collect();
    catalog.sort_by(|left, right| left.name.cmp(&right.name));
    catalog
}

fn definitions(runtime: impl ToolRuntime, capabilities: &DeviceCapabilities) -> Vec<String> {
    runtime
        .definitions(capabilities)
        .into_iter()
        .map(|definition| definition.name)
        .collect()
}

/// Tool names the bundled Study plugin grants its own mode.
///
/// Declared in the plugin manifest for the desktop loader; the mobile host has no
/// loader, so the same declaration is embedded here and intersected with
/// [`catalog_tools`] before use. A name the host cannot run is dropped rather
/// than promised.
pub fn study_mode_tools() -> Vec<String> {
    const STUDY_MODE_TOOLS: &str = "study:study";
    let manifest: serde_json::Value = serde_json::from_str(include_str!(
        "../../src/lamtools_core/plugins/bundled/study/plugin.json"
    ))
    .unwrap_or(serde_json::Value::Null);
    let declared = manifest
        .get("ui")
        .and_then(|ui| ui.get("modes"))
        .and_then(serde_json::Value::as_array)
        .and_then(|modes| {
            modes.iter().find(|mode| {
                mode.get("id").and_then(serde_json::Value::as_str) == Some("study")
            })
        })
        .and_then(|mode| mode.get("tools"))
        .and_then(serde_json::Value::as_array)
        .map(|tools| {
            tools
                .iter()
                .filter_map(serde_json::Value::as_str)
                .map(str::to_owned)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let known: Vec<String> = catalog_tools()
        .into_iter()
        .map(|tool| tool.name)
        .collect();
    let mut resolved: Vec<String> = declared
        .iter()
        .map(String::as_str)
        .chain(
            // The mobile Study skill prompt tells the model to use this tool for
            // linked reference files; the desktop prompt does not, so it is not
            // in the declaration and has to be added here.
            ["read_skill_reference"],
        )
        .filter(|name| known.iter().any(|known| known == name))
        .map(str::to_owned)
        .collect();
    debug_assert!(
        !resolved.is_empty() || declared.is_empty(),
        "{STUDY_MODE_TOOLS} declares tools none of which this host assembles"
    );
    resolved.dedup();
    resolved
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_catalog_is_the_definitions_the_runtimes_publish() {
        let names: Vec<String> = catalog_tools().into_iter().map(|tool| tool.name).collect();
        for expected in [
            "list_dir",
            "read_file",
            "write_file",
            "edit_file",
            "search_files",
            "search_content",
            "web_fetch",
            "web_search",
            "generate_image",
            "sub_agent",
            "sub_agent_message",
        ] {
            assert!(
                names.iter().any(|name| name == expected),
                "catalog is missing {expected}"
            );
        }
        // Sorted and unique, so the editor's checklist is stable.
        let mut sorted = names.clone();
        sorted.sort();
        sorted.dedup();
        assert_eq!(names, sorted);
    }

    #[test]
    fn categories_follow_the_desktop_vocabulary() {
        let catalog = catalog_tools();
        let category = |name: &str| {
            catalog
                .iter()
                .find(|tool| tool.name == name)
                .unwrap_or_else(|| panic!("missing {name}"))
                .category
                .clone()
        };
        assert_eq!(category("read_file"), "file_read");
        assert_eq!(category("write_file"), "file_write");
        assert_eq!(category("web_fetch"), "web");
        assert_eq!(category("generate_image"), "image");
        assert_eq!(category("sub_agent"), "agent");
        assert_eq!(category("load_skill"), "skill");
    }

    #[test]
    fn study_mode_tools_are_declared_and_assembled() {
        let tools = study_mode_tools();
        // The manifest grants the five Study tools plus read-only core work; a
        // mismatch means the embedded manifest and this host disagree.
        for expected in ["notes", "read_file", "list_dir", "search_files", "web_search"] {
            assert!(
                tools.iter().any(|name| name == expected),
                "study mode is missing {expected}"
            );
        }
        for name in &tools {
            assert!(
                !name.is_empty(),
                "study mode must not carry an empty tool name"
            );
        }
    }

    #[test]
    fn a_restricted_mode_hides_exactly_what_it_blocks() {
        let options = crate::TurnOptions {
            active_mode: "consider".into(),
            mode_tools: Some(vec!["read_file".into(), "search_content".into()]),
            ..Default::default()
        };
        let definitions = crate::mode_filtered_definitions(
            vec![
                crate::ToolDefinition {
                    name: "read_file".into(),
                    description: String::new(),
                    input_schema: serde_json::json!({}),
                },
                crate::ToolDefinition {
                    name: "write_file".into(),
                    description: String::new(),
                    input_schema: serde_json::json!({}),
                },
            ],
            &options,
        );
        assert_eq!(definitions.len(), 1);
        assert_eq!(definitions[0].name, "read_file");
        assert!(options.mode_block_reason("read_file").is_none());
        let reason = options.mode_block_reason("write_file").expect("blocked");
        assert_eq!(
            reason,
            "You are in the consider mode, you can't use write_file. Please make the plan prepared and ask user to switch mode."
        );
    }

    #[test]
    fn full_access_and_unknown_modes_never_restrict() {
        let unrestricted = crate::TurnOptions {
            active_mode: "execute".into(),
            mode_tools: Some(Vec::new()),
            ..Default::default()
        };
        assert!(unrestricted.mode_whitelist().is_none());
        assert!(unrestricted.mode_block_reason("write_file").is_none());

        let unknown = crate::TurnOptions::default();
        assert!(unknown.mode_whitelist().is_none());
        assert!(unknown.mode_block_reason("write_file").is_none());
        assert_eq!(
            crate::mode_filtered_definitions(
                vec![crate::ToolDefinition {
                    name: "write_file".into(),
                    description: String::new(),
                    input_schema: serde_json::json!({}),
                }],
                &unknown,
            )
            .len(),
            1
        );
    }
}
