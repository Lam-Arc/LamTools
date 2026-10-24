---
name: port-plugin
description: Rebuild an external plugin (Claude Code, Codex, or any repository or package the user names) as a LamTools v2 plugin. Use when the user asks to port, migrate, convert, copy, or reproduce a plugin from another agent or another plugin ecosystem. Checks the licence first, inventories the source, maps each capability onto the six declarative kinds, and returns a rebuilt plugin plus a difference table.
metadata:
  platforms: desktop
---

# Port Plugin

Goal: deliver a working LamTools plugin, not a runtime compatibility layer. We take the capability, not the code.

## 1. The replication contract

Replication means **capability restoration**: the deliverable is the source's capability list, restored. Three rules keep it honest:

- The source's decisions are the spec. Defaults, switches, gates, interaction shapes — the original already made the product decisions; port them. Do not make the port more conservative than the source, and do not defer a capability by claiming a product decision is needed when the source already made it.
- Every capability in the source ends up in exactly one of three states: **ported**, **missing** (with the reason and what it would take), or **changed** (different shape, with the user's decision recorded). Nothing silently disappears and nothing is quietly re-architected.
- A deviation is reported **as a deviation**. Never package one as an improvement or an "architecture simplification" — the user decides whether a deviation is acceptable, not the porter.

Real examples from the bili-scroll port: local transcription was declared impossible because the host Python is frozen — wrong, the script pattern (own venv + run_command) makes it portable; the source's MCP server was silently swapped for native tools — a shape deviation that should have been the user's decision; DM delivery was deferred for "product semantics" the source had already decided (its default delivery mode is DM).

## 2. Licence first

Read the source licence before anything else.

- Permissive or no licence file: you may reimplement the behaviour.
- Copyleft: reimplementation is fine, copying code is not. Do not copy source text.
- No licence, or a licence that forbids derivative work: stop. Produce only the difference report and say plainly that the plugin cannot be ported, with the licence line that says so.

Never copy code from a repository whose licence you have not read. Reimplementing a described behaviour in our own terms is always allowed.

## 3. Inventory the source

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

## 4. One plugin folder

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

There is one plugin system; no marker field is needed. Keep every tool handler dependency-free unless `engine.dependencies` declares the package.

## 5. Port per capability

- Tool: rewrite the handler against our `ToolResult` contract. Keep the source tool's argument names when they are natural; do not preserve accidental quirks.
- Skill: rewrite the instructions for our environment. Keep the trigger description. Update every path, command and tool name to ours.
- Command: one entry in `commands`, pointing at a registered operation. If the source command only injected a prompt, make it a skill and a command that inserts the token.
- Hook: map the event; if the source hook depended on the other host's lifecycle, drop it and note the gap.
- MCP: copy the server declaration; keep secrets out of the file, use placeholders and tell the user what to fill in.
- Config: convert the source settings into a JSON schema. Use `title` and `description` so the default panel is readable. A source control that has no equivalent (for example a file picker) becomes a string with a description, not a fake widget.
- UI: prefer declarative blocks. If the source page is genuinely interactive, write `ui/window.html` + `ui/panel.js` and call our operations. If the source UI edits things we do not expose, list the missing operation in the difference table instead of inventing one.
- Overrides: only when the user explicitly asks to change host behaviour. Warn that a broken override can stop the app from starting.

## 6. Verification

1. Install locally with `plugin.system.install`.
2. `plugin.system.list` and `plugin.system.ui`: every declaration parsed, no errors.
3. Exercise each ported capability once with a realistic input.
4. Open every window and save the config once; restart and confirm `data/` survived.
5. Confirm the unported items are listed, not silently missing.

## 7. Difference report

Always end with this table, in the user's language. The status column uses exactly three values — **ported / missing / changed** — and any "changed" or "missing" row is a deviation the user must be able to decide on:

| source capability | our equivalent | status | notes |
| --- | --- | --- | --- |
| web search tool | native tool | ported | same arguments |
| settings page | config schema | changed | source's four tabs became one schema form — confirm acceptable |
| background watcher | none | missing | needs a process; run `run_command` manually instead |
| OAuth login | none | missing | requires the vendor's client secret |

A port where every source capability maps to a "ported" row is a complete replication. Every "missing" or "changed" row is a deliverable, not a footnote — never balance them against "improvements" the port added.

Also state the licence conclusion and whether any code was copied (answer should be no).

## Rules

- Never claim a port is complete while a capability is missing; the difference table is the deliverable.
- Never present a deviation as an improvement. "The source did X, we did Y" is always a deviation row for the user to decide.
- Capabilities that cannot run inside the host process are ported via a script in the plugin folder plus its own environment bootstrap (uv + venv) and `run_command` — "the host Python is frozen" is never a reason to drop one.
- Do not add a second runtime for the source host, a compatibility shim, or the source host's SDK. (A plugin-owned venv for its own capability is not a second runtime.)
- Do not copy code across a licence boundary. Reimplement.
- Do not invent operations or manifest fields. If the feature needs a host capability we lack, report it.
- If three similar source tools exist, consider one tool with a mode argument, or a skill that runs three scripts. Fewer tools is better.
