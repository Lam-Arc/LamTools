---
name: plugin-manager
description: Guide plugin installation, update, uninstall, and dependency management inside a session. Use when the user asks to install, update, remove, enable, disable, or check dependencies of a LamTools plugin, or asks about available plugins and how to install them. Loads the plugin model (tools/skills/hooks/mcp assets), install sources (local directory / zip / GitHub Release URL), and the plugin_install / plugin_deps / plugin_list tools.
---

# Plugin Manager

Install and manage LamTools plugins from natural language.

## What a plugin is

A plugin is a directory with a `plugin.json` manifest. A plugin may contain any combination of assets — the manifest is the single install unit:

- `skills` — SKILL.md directories (agent capabilities)
- `hooks` — hook definitions (event handlers)
- `mcpServers` — MCP server configs (external tools)
- `tools` — native tools declared in `tools/tools.jsonc` (in-process Python handlers)
- `dependencies` — pip packages installed into the Core runtime
- `configSchema` — JSONC schema driving the plugin configuration form

A plugin can be *only* a skill, *only* hooks, *only* MCP config, or all of them. Install is always per-plugin; there is no separate skill.install / hook.install.

## Workflow: install

1. Identify what the user wants and which plugin provides it. If they name a plugin, use it. If they only describe the need, check `plugin_list` for installed plugins first, then propose the plugin that fits (e.g. a git plugin for version-control needs, a websearch plugin for search, an imagegen plugin for image generation).
2. Ask the user for the install source if unknown:
   - **local**: a directory containing `plugin.json` on this machine
   - **zip**: a local `.zip` of the plugin
   - **url**: a GitHub Release `.zip` asset URL (`https://github.com/{owner}/{repo}/releases/...`)
3. Call `plugin_install` with `source` and the corresponding `path`/`url`. The tool requires user confirmation (approval) — the user must approve the install, especially because pip may run for dependencies.
4. On success, report the plugin name, version, and dependency status. If dependencies were declared and install failed on a conflict, report the conflicting packages and the rejected installation.

## Workflow: update

Reinstalling an existing plugin name overwrites the old directory (reinstall = update). Run `plugin_install` with the new source again; the user approves the update.

## Workflow: check dependencies

Call `plugin_deps` with the plugin name. It reports installed / missing / version mismatch and an install command hint. Do not claim a plugin works when its dependencies are missing.

## Workflow: uninstall / enable / disable

- Uninstall and dependency cleanup are management actions: direct the user to the plugin page (UI) or the CLI (`lamtools plugin uninstall <name>`). Uninstall removes the plugin directory and may uninstall its recorded dependencies (shared dependencies are kept).
- Enable/disable are available in the plugin page; disabling a plugin makes its tools invisible to the model immediately (next turn) and its hooks stop loading.

## Rules

- A plugin is executable code once installed. Installing is an explicit trust action: warn the user before installing plugins from untrusted sources.
- Never fabricate a plugin that does not exist. If the user asks for a capability with no plugin, suggest the `create-plugin` skill to scaffold one.
- `plugin_install` requires user confirmation — never claim it ran without approval.
