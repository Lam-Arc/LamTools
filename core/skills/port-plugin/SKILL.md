---
name: port-plugin
description: Rebuild an external plugin (Claude Code, Codex, or any repository or package the user names) as a LamTools v2 plugin. Use when the user asks to port, migrate, convert, copy, or reproduce a plugin from another agent or another plugin ecosystem. Checks the licence first, inventories the source, maps each capability onto the six declarative kinds, and returns a rebuilt plugin plus a difference table.
metadata:
  platforms: desktop
---

# Port Plugin

Goal: deliver a working LamTools v2 plugin, not a runtime compatibility layer. We take the capability, not the code.

## 1. Licence first

Read the source licence before anything else.

- Permissive or no licence file: you may reimplement the behaviour.
- Copyleft: reimplementation is fine, copying code is not. Do not copy source text.
- No licence, or a licence that forbids derivative work: stop. Produce only the difference report and say plainly that the plugin cannot be ported, with the licence line that says so.

Never copy code from a repository whose licence you have not read. Reimplementing a described behaviour in our own terms is always allowed.

## 2. Inventory the source

Fetch and read: the manifest, README, entry point, tool definitions, command definitions, skills, hooks, MCP config, and settings schema.

Build one table before writing any file:

| source item | kind | what it does | host dependencies | port decision |
| --- | --- | --- | --- | --- |
| `search_agent` tool | tool | searches the web | none | native tool |
| `/report` command | command | builds a report | internal API | command + operation |
| `postinstall` script | hook/script | downloads data | Node runtime | skill + run_command |
| settings page | UI | form with 4 fields | React component | config schema |
| sidebar panel | UI | live counter | React, websocket | window or region |
| `fs.watch` daemon | runtime | watches files | Node | refuse, explain |

Rules for the decision column:

- Pure computation or a single API call that is called rarely: a skill plus a script run through `run_command`.
- Frequent calls, a strict return shape, or permissions `run_command` cannot express: a native tool.
- A form: `config.schema`. A page that does not fit a panel: `ui.windows`. A small readout: a declarative region.
- Anything that needs a second runtime (Node daemon, background watcher, browser automation service): refuse and say what would be required. Do not install a runtime inside a plugin.
- Anything depending on a proprietary service or a local app the user must already own: port the call, list the credential or service as a prerequisite, and do not fake a key.

## 3. One plugin folder

```
<name>/
├── plugin.json
├── skills/<name>/SKILL.md
├── tools/tools.jsonc
├── tools.py
├── commands.jsonc        # only if commands are numerous; otherwise inline in plugin.json
├── config/schema.jsonc
├── ui/panel.js
└── data/
```

Set `"assembly": "v2"`. Keep every tool handler dependency-free unless `engine.dependencies` declares the package.

## 4. Port per capability

- Tool: rewrite the handler against our `ToolResult` contract. Keep the source tool's argument names when they are natural; do not preserve accidental quirks.
- Skill: rewrite the instructions for our environment. Keep the trigger description. Update every path, command and tool name to ours.
- Command: one entry in `commands`, pointing at a registered operation. If the source command only injected a prompt, make it a skill and a command that inserts the token.
- Hook: map the event; if the source hook depended on the other host's lifecycle, drop it and note the gap.
- MCP: copy the server declaration; keep secrets out of the file, use placeholders and tell the user what to fill in.
- Config: convert the source settings into a JSON schema. Use `title` and `description` so the default panel is readable. A source control that has no equivalent (for example a file picker) becomes a string with a description, not a fake widget.
- UI: prefer declarative blocks. If the source page is genuinely interactive, write `ui/window.html` + `ui/panel.js` and call our operations. If the source UI edits things we do not expose, list the missing operation in the difference table instead of inventing one.
- Overrides: only when the user explicitly asks to change host behaviour. Warn that a broken override can stop the app from starting.

## 5. Verification

1. Install locally with `plugin.system.install`.
2. `plugin.system.list` and `plugin.system.ui`: every declaration parsed, no errors.
3. Exercise each ported capability once with a realistic input.
4. Open every window and save the config once; restart and confirm `data/` survived.
5. Confirm the unported items are listed, not silently missing.

## 6. Difference report

Always end with this table, in the user's language:

| source capability | our equivalent | status | notes |
| --- | --- | --- | --- |
| web search tool | native tool | ported | same arguments |
| settings page | config schema | ported, simplified | file picker became a path string |
| background watcher | none | not ported | needs a process; run `run_command` manually instead |
| OAuth login | none | blocked | requires the vendor's client secret |

Also state the licence conclusion and whether any code was copied (answer should be no).

## Rules

- Never claim a port is complete while a capability is missing; the difference table is the deliverable.
- Do not add a second runtime, a compatibility shim, or the source host's SDK.
- Do not copy code across a licence boundary. Reimplement.
- Do not invent operations or manifest fields. If the feature needs a host capability we lack, report it.
- If three similar source tools exist, consider one tool with a mode argument, or a skill that runs three scripts. Fewer tools is better.
