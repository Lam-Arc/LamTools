//! Bundled plugin tool inventory for hosts without a plugin loader.
//!
//! The desktop host discovers plugin tools by scanning plugin roots and parsing
//! each manifest. The mobile host has no plugin loader: it runs a fixed set of
//! Rust tool runtimes. A hand-written list of plugin tools cannot be trusted in
//! that situation, because it keeps advertising tools the runtime would refuse
//! to run (an earlier mobile plugin panel reported a hard-coded empty list for
//! every plugin, which is why this module derives the inventory instead).
//!
//! Each entry reports the tools that are actually assembled on this host, the
//! number the manifest declares, and a short reason when the two disagree. The
//! manifests are embedded so the comparison cannot silently drift from the
//! Python-side declarations.
use serde::Serialize;

use crate::study::{self, STUDY_TOOLS_RESOURCE};

const GIT_TOOLS: &str =
    include_str!("../../src/lamtools_core/plugins/bundled/git/tools/tools.jsonc");
const WEBSEARCH_TOOLS: &str =
    include_str!("../../src/lamtools_core/plugins/bundled/websearch/tools/tools.jsonc");
const IMAGEGEN_TOOLS: &str =
    include_str!("../../src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc");
const WORKFLOW_TOOLS: &str =
    include_str!("../../src/lamtools_core/plugins/bundled/workflow/tools.jsonc");

/// One tool the mobile agent can actually call.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PluginToolSummary {
    pub name: String,
    pub permission: String,
}

/// Tool inventory for one bundled plugin on this host.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PluginInventory {
    pub plugin: String,
    /// Tools assembled into the agent. The UI count must come from this list.
    pub assembled: Vec<PluginToolSummary>,
    /// How many tools the plugin manifest declares, for an honest comparison.
    pub declared_count: usize,
    /// Human-readable status; empty when every declared tool is assembled.
    pub note: String,
}

/// Declared `(name, permission)` pairs from a plugin tools manifest.
fn declared_tools(manifest: &str) -> Vec<PluginToolSummary> {
    let Ok(parsed) = serde_json::from_str::<serde_json::Value>(manifest) else {
        return Vec::new();
    };
    parsed
        .get("tools")
        .and_then(serde_json::Value::as_array)
        .map(|tools| {
            tools
                .iter()
                .filter_map(|tool| {
                    let name = tool.get("name").and_then(serde_json::Value::as_str)?;
                    Some(PluginToolSummary {
                        name: name.to_owned(),
                        permission: tool
                            .get("permission")
                            .and_then(serde_json::Value::as_str)
                            .unwrap_or("auto_allow")
                            .to_owned(),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Build one entry, keeping only declared tools the host actually implements.
fn entry(
    plugin: &str,
    manifest: &str,
    implemented: &[&str],
    unavailable_note: &str,
) -> PluginInventory {
    let declared = declared_tools(manifest);
    let assembled = declared
        .iter()
        .filter(|tool| implemented.contains(&tool.name.as_str()))
        .cloned()
        .collect::<Vec<_>>();
    let note = if assembled.len() == declared.len() {
        String::new()
    } else if assembled.is_empty() {
        unavailable_note.to_owned()
    } else {
        format!(
            "清单声明 {} 项，移动端已装配 {} 项",
            declared.len(),
            assembled.len()
        )
    };
    PluginInventory {
        plugin: plugin.to_owned(),
        assembled,
        declared_count: declared.len(),
        note,
    }
}

/// Tool inventory for every bundled plugin, in a stable order.
///
/// Plugin availability on this host is a property of this function: adding a
/// mobile implementation means adding its name to [`study::IMPLEMENTED_TOOL_NAMES`]
/// equivalent list here, and the UI follows automatically.
pub fn bundled_plugin_inventory() -> Vec<PluginInventory> {
    vec![
        entry(
            "git",
            GIT_TOOLS,
            &[],
            "移动端未装配：Android 没有 git 可执行文件，且项目目录不是仓库",
        ),
        entry(
            "imagegen",
            IMAGEGEN_TOOLS,
            &[],
            "移动端未装配：需要先完成生图配置与图片落地",
        ),
        entry(
            "study",
            STUDY_TOOLS_RESOURCE,
            study::IMPLEMENTED_STUDY_TOOLS.as_slice(),
            "移动端未装配",
        ),
        entry(
            "websearch",
            WEBSEARCH_TOOLS,
            &[],
            "移动端未装配：搜索内核尚未移植到 Rust",
        ),
        entry(
            "workflow",
            WORKFLOW_TOOLS,
            &[],
            "移动端仅提供界面 RPC，未向 Agent 装配工具",
        ),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_assembled_tools_are_reported_for_study() {
        let inventory = bundled_plugin_inventory();
        let study_entry = inventory
            .iter()
            .find(|item| item.plugin == "study")
            .expect("study entry");
        // The count the panel shows must equal what the runtime can actually run.
        let runtime: Vec<String> = study::study_tool_definitions()
            .into_iter()
            .map(|tool| tool.name)
            .collect();
        let reported: Vec<String> = study_entry
            .assembled
            .iter()
            .map(|tool| tool.name.clone())
            .collect();
        assert_eq!(reported, runtime);
        assert_eq!(study_entry.declared_count, 5);
        assert!(study_entry.note.is_empty());
    }

    #[test]
    fn unavailable_plugins_report_no_tools_and_a_reason() {
        let inventory = bundled_plugin_inventory();
        for name in ["git", "imagegen", "websearch", "workflow"] {
            let item = inventory
                .iter()
                .find(|entry| entry.plugin == name)
                .unwrap_or_else(|| panic!("missing entry {name}"));
            assert!(
                item.assembled.is_empty(),
                "{name} must not claim unassembled tools"
            );
            assert!(!item.note.is_empty(), "{name} needs a reason");
            assert!(
                item.declared_count > 0,
                "{name} declares tools in its manifest"
            );
        }
    }

    #[test]
    fn declared_permissions_come_from_the_manifest() {
        let inventory = bundled_plugin_inventory();
        let study_entry = inventory
            .iter()
            .find(|item| item.plugin == "study")
            .expect("study entry");
        assert!(
            study_entry
                .assembled
                .iter()
                .all(|tool| tool.permission == "auto_allow"),
            "study manifest declares auto_allow"
        );
    }
}
