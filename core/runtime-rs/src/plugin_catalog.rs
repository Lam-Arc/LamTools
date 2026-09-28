//! Bundled plugin catalogue for hosts without a plugin loader.
//!
//! The desktop host discovers plugins by scanning plugin roots and parsing each
//! manifest. The mobile host has no plugin loader: it runs a fixed set of Rust
//! tool runtimes. Two hand-written lists used to stand in for the manifests here
//! — one naming the plugins, one naming their tools — and both drifted (an
//! earlier mobile panel advertised plugin tools that did not exist, and a plugin
//! the phone can never run stayed on the list). This module therefore reads the
//! embedded manifests instead:
//!
//! * the manifest's `platforms` class decides whether this host offers the
//!   plugin at all (`desktop` / `mobile` / `universal`, absent = universal);
//! * the parent manifest supplies the name, version, description, skill roots,
//!   modes and dependencies the panel shows;
//! * the tools file it declares is compared against the tools this host
//!   actually assembles, and the difference is reported rather than hidden.
use serde::Serialize;

use crate::study::{self, STUDY_TOOLS_RESOURCE};
use crate::{HostPlatform, PLATFORM_UNIVERSAL};

/// Every bundled plugin manifest, embedded so the host reads the same
/// declarations the desktop loader does.
///
/// Desktop-only plugins are embedded too: their manifest is where the `desktop`
/// class comes from, so the phone skips them by reading it rather than by a
/// second list saying so.
const BUNDLED_MANIFESTS: &[(&str, &str)] = &[
    (
        "emotion-ball-pet",
        include_str!("../../src/lamtools_core/plugins/bundled/emotion-ball-pet/plugin.json"),
    ),
    (
        "git",
        include_str!("../../src/lamtools_core/plugins/bundled/git/plugin.json"),
    ),
    (
        "imagegen",
        include_str!("../../src/lamtools_core/plugins/bundled/imagegen/plugin.json"),
    ),
    (
        "study",
        include_str!("../../src/lamtools_core/plugins/bundled/study/plugin.json"),
    ),
    (
        "websearch",
        include_str!("../../src/lamtools_core/plugins/bundled/websearch/plugin.json"),
    ),
    (
        "workflow",
        include_str!("../../src/lamtools_core/plugins/bundled/workflow/plugin.json"),
    ),
];

/// Tools files of the plugins this host can offer, keyed by plugin and by the
/// path its manifest declares, so a declaration resolves to the exact file the
/// desktop would read.
const BUNDLED_TOOL_FILES: &[(&str, &str, &str)] = &[
    (
        "imagegen",
        "./tools/tools.jsonc",
        include_str!("../../src/lamtools_core/plugins/bundled/imagegen/tools/tools.jsonc"),
    ),
    ("study", "./tools.jsonc", STUDY_TOOLS_RESOURCE),
    (
        "websearch",
        "./tools/tools.jsonc",
        include_str!("../../src/lamtools_core/plugins/bundled/websearch/tools/tools.jsonc"),
    ),
];

/// One tool the mobile agent can actually call.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PluginToolSummary {
    pub name: String,
    pub permission: String,
}

/// One mode a plugin contributes, as the panel needs it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PluginMode {
    pub id: String,
    pub title: String,
    pub icon: String,
    pub tools: Vec<String>,
    /// `None` when the manifest makes no claim, an empty list when it claims the
    /// host supports none of the mode's surfaces — the same contract the desktop
    /// payload carries.
    pub capabilities: Option<Vec<String>>,
}

/// One bundled plugin as this host offers it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct BundledPlugin {
    pub name: String,
    pub version: String,
    pub description: String,
    /// The class the manifest declares (`desktop` / `mobile` / `universal`).
    pub platforms: String,
    /// Skill roots the manifest declares, as `bundled://<plugin>/<path>`.
    pub skills: Vec<String>,
    /// Skills under those roots this host has embedded.
    pub skill_names: Vec<String>,
    pub modes: Vec<PluginMode>,
    pub dependencies: Vec<String>,
    /// Tools assembled into the agent. The UI count must come from this list.
    pub tools: Vec<PluginToolSummary>,
    /// How many tools the plugin manifest declares, for an honest comparison.
    pub declared_tool_count: usize,
    /// Human-readable status; empty when every declared tool is assembled.
    pub tools_note: String,
}

/// What this host can run for one plugin, and what to say when it cannot.
struct HostImplementation {
    tools: &'static [&'static str],
    unavailable_note: &'static str,
    ready_note: &'static str,
}

/// The tools the phone implements per plugin.
///
/// This is host knowledge, not a declaration: the manifests say what each plugin
/// offers, this table says what the Rust runtimes assemble. A bundled plugin
/// absent from the table is reported as declared-but-unassembled, never as a
/// plugin with no tools.
fn host_implementation(plugin: &str) -> HostImplementation {
    match plugin {
        "imagegen" => HostImplementation {
            tools: &["generate_image"],
            unavailable_note: "移动端未装配：需要先完成生图配置与图片落地",
            ready_note: "需在设置 → 生图中启用并填写 API 地址，模型才会看到该工具",
        },
        "study" => HostImplementation {
            tools: &study::IMPLEMENTED_STUDY_TOOLS,
            unavailable_note: "移动端未装配",
            ready_note: "",
        },
        "websearch" => HostImplementation {
            tools: &["web_search"],
            unavailable_note: "移动端未装配：搜索内核尚未移植到 Rust",
            ready_note: "",
        },
        _ => HostImplementation {
            tools: &[],
            unavailable_note: "本机未装配该插件的工具",
            ready_note: "",
        },
    }
}

fn manifest_value(manifest: &str) -> serde_json::Value {
    serde_json::from_str(manifest).unwrap_or(serde_json::Value::Null)
}

/// The class a manifest declares; absent or unreadable means universal, which is
/// what an undeclared plugin is.
fn manifest_platforms(manifest: &str) -> String {
    manifest_value(manifest)
        .get("platforms")
        .and_then(serde_json::Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(PLATFORM_UNIVERSAL)
        .to_owned()
}

fn string_list(value: Option<&serde_json::Value>) -> Vec<String> {
    value
        .and_then(serde_json::Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(serde_json::Value::as_str)
                .map(str::trim)
                .filter(|item| !item.is_empty())
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

/// Declared `(name, permission)` pairs from a plugin tools manifest.
fn declared_tools(manifest: &str) -> Vec<PluginToolSummary> {
    manifest_value(manifest)
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

/// The declared tools file of one plugin, as embedded content.
fn declared_tools_file(plugin: &str, manifest: &str) -> Option<&'static str> {
    let declared = string_list(manifest_value(manifest).get("tools"));
    BUNDLED_TOOL_FILES
        .iter()
        .find(|(name, path, _)| *name == plugin && declared.iter().any(|item| item == path))
        .map(|(_, _, content)| *content)
}

fn manifest_modes(manifest: &str) -> Vec<PluginMode> {
    manifest_value(manifest)
        .get("ui")
        .and_then(|ui| ui.get("modes"))
        .and_then(serde_json::Value::as_array)
        .map(|modes| {
            modes
                .iter()
                .filter_map(|mode| {
                    let id = mode.get("id").and_then(serde_json::Value::as_str)?;
                    Some(PluginMode {
                        id: id.to_owned(),
                        title: mode
                            .get("title")
                            .and_then(serde_json::Value::as_str)
                            .unwrap_or(id)
                            .to_owned(),
                        icon: mode
                            .get("icon")
                            .and_then(serde_json::Value::as_str)
                            .unwrap_or_default()
                            .to_owned(),
                        tools: string_list(mode.get("tools")),
                        capabilities: mode
                            .get("capabilities")
                            .and_then(serde_json::Value::as_array)
                            .map(|_| string_list(mode.get("capabilities"))),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Skill roots the manifest declares, as the `bundled://` locations the panel
/// reports rather than the `./` paths the manifest writes.
fn manifest_skill_dirs(plugin: &str, manifest: &str) -> Vec<String> {
    string_list(manifest_value(manifest).get("skills"))
        .into_iter()
        .map(|path| {
            format!(
                "bundled://{plugin}/{}",
                path.trim_start_matches("./").trim_end_matches('/')
            )
        })
        .collect()
}

/// Skill names this host has embedded under the plugin's declared roots.
fn embedded_skill_names(plugin: &str) -> Vec<String> {
    let prefix = format!("bundled://{plugin}/");
    crate::study_skills::catalog()
        .into_iter()
        .filter(|skill| skill.location.starts_with(&prefix))
        .map(|skill| skill.name)
        .collect()
}

/// One plugin's entry, with its declared tools compared against the assembled
/// ones.
fn bundled_plugin(plugin: &str, manifest: &str) -> BundledPlugin {
    let implementation = host_implementation(plugin);
    let declares_tools = !string_list(manifest_value(manifest).get("tools")).is_empty();
    let declared_file = declared_tools_file(plugin, manifest);
    let declared = declared_file.map(declared_tools).unwrap_or_default();
    let tools = declared
        .iter()
        .filter(|tool| implementation.tools.contains(&tool.name.as_str()))
        .cloned()
        .collect::<Vec<_>>();
    let tools_note = if !declares_tools {
        // Nothing declared, nothing to compare: no note rather than a claim.
        String::new()
    } else if declared_file.is_none() {
        // The manifest names a tools file this build does not embed; saying so
        // beats reporting a plugin with no tools.
        "清单声明的工具文件本机未内嵌".to_owned()
    } else if tools.len() == declared.len() {
        implementation.ready_note.to_owned()
    } else if tools.is_empty() {
        implementation.unavailable_note.to_owned()
    } else {
        format!(
            "清单声明 {} 项，移动端已装配 {} 项",
            declared.len(),
            tools.len()
        )
    };
    let value = manifest_value(manifest);
    BundledPlugin {
        name: plugin.to_owned(),
        version: value
            .get("version")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("0.0.0")
            .to_owned(),
        description: value
            .get("description")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        platforms: manifest_platforms(manifest),
        skills: manifest_skill_dirs(plugin, manifest),
        skill_names: embedded_skill_names(plugin),
        modes: manifest_modes(manifest),
        dependencies: string_list(value.get("dependencies")),
        tools,
        declared_tool_count: declared.len(),
        tools_note,
    }
}

/// Every bundled plugin this host offers, in a stable order.
///
/// Availability is a property of this function: a plugin appears here when its
/// own manifest declares a class this host is (`universal` or its own), and stops
/// appearing the moment that declaration changes.
pub fn bundled_plugins(host: HostPlatform) -> Vec<BundledPlugin> {
    let mut plugins = BUNDLED_MANIFESTS
        .iter()
        .filter(|(_, manifest)| host.offers(&manifest_platforms(manifest)))
        .map(|(plugin, manifest)| bundled_plugin(plugin, manifest))
        .collect::<Vec<_>>();
    plugins.sort_by(|left, right| left.name.cmp(&right.name));
    plugins
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_phone_offers_universal_plugins_and_not_desktop_ones() {
        let names: Vec<String> = bundled_plugins(HostPlatform::Mobile)
            .into_iter()
            .map(|plugin| plugin.name)
            .collect();
        // imagegen / study / websearch declare `universal`; git, workflow and the
        // desktop pet declare `desktop`, so the phone does not offer them at all.
        assert_eq!(names, ["imagegen", "study", "websearch"], "{names:?}");
    }

    #[test]
    fn the_desktop_host_would_offer_every_bundled_plugin() {
        // Nothing bundled declares `mobile` yet, so the desktop side of the rule
        // is the universal set plus its own.
        let names: Vec<String> = bundled_plugins(HostPlatform::Desktop)
            .into_iter()
            .map(|plugin| plugin.name)
            .collect();
        assert_eq!(
            names,
            [
                "emotion-ball-pet",
                "git",
                "imagegen",
                "study",
                "websearch",
                "workflow"
            ],
            "{names:?}"
        );
    }

    #[test]
    fn the_catalogue_carries_what_the_manifest_declares() {
        let plugins = bundled_plugins(HostPlatform::Mobile);
        let study = plugins
            .iter()
            .find(|plugin| plugin.name == "study")
            .expect("study entry");
        assert_eq!(study.version, "1.0.0");
        assert_eq!(study.platforms, "universal");
        // The declared skill roots, as the panel reports them.
        assert_eq!(
            study.skills,
            ["bundled://study/skills", "bundled://study/future"]
        );
        // The skill names under those roots this host has embedded.
        assert!(study.skill_names.contains(&"build-map".to_string()), "{:?}", study.skill_names);
        // Its mode comes from the same manifest, capabilities included.
        let mode = study.modes.first().expect("study mode");
        assert_eq!(mode.id, "study");
        assert_eq!(mode.title, "Study");
        assert_eq!(mode.capabilities, Some(vec!["notes".to_string()]));
        assert!(mode.tools.contains(&"build_knowledge_net".to_string()));
    }

    #[test]
    fn the_assembled_tools_match_the_runtime_definitions() {
        use crate::study::study_tool_definitions;
        use crate::ToolRuntime;
        use crate::web_search::WebSearchTools;

        let plugins = bundled_plugins(HostPlatform::Mobile);
        let study = plugins
            .iter()
            .find(|plugin| plugin.name == "study")
            .expect("study entry");
        let runtime: Vec<String> = study_tool_definitions()
            .into_iter()
            .map(|tool| tool.name)
            .collect();
        let reported: Vec<String> = study.tools.iter().map(|tool| tool.name.clone()).collect();
        assert_eq!(reported, runtime);
        assert_eq!(study.declared_tool_count, 5);
        assert!(study.tools_note.is_empty());

        let websearch = plugins
            .iter()
            .find(|plugin| plugin.name == "websearch")
            .expect("websearch entry");
        let runtime: Vec<String> = WebSearchTools::new()
            .definitions(&crate::DeviceCapabilities {
                network: true,
                ..Default::default()
            })
            .into_iter()
            .map(|tool| tool.name)
            .collect();
        let reported: Vec<String> = websearch.tools.iter().map(|tool| tool.name.clone()).collect();
        assert_eq!(reported, runtime);
        assert_eq!(websearch.declared_tool_count, 1);
        assert!(websearch.tools_note.is_empty());
    }

    #[test]
    fn imagegen_reports_its_setup_instead_of_looking_offline() {
        let plugins = bundled_plugins(HostPlatform::Mobile);
        let imagegen = plugins
            .iter()
            .find(|plugin| plugin.name == "imagegen")
            .expect("imagegen entry");
        assert_eq!(
            imagegen
                .tools
                .iter()
                .map(|tool| tool.name.as_str())
                .collect::<Vec<_>>(),
            ["generate_image"]
        );
        // Assembled but not usable until the user configures it, which the panel
        // has to say because the tool hides itself while unconfigured.
        assert!(imagegen.tools_note.contains("生图"), "{}", imagegen.tools_note);
    }

    #[test]
    fn documented_permissions_come_from_the_manifest() {
        let plugins = bundled_plugins(HostPlatform::Mobile);
        let study = plugins
            .iter()
            .find(|plugin| plugin.name == "study")
            .expect("study entry");
        assert!(
            study.tools.iter().all(|tool| tool.permission == "auto_allow"),
            "study manifest declares auto_allow"
        );
    }
}
