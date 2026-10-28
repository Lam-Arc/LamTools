---
name: port-plugin
description: Port an external plugin (Claude Code, Codex, or any repository or package the user names) as a LamTools v2 plugin. Use when the user asks to port, migrate, convert, copy, or reproduce a plugin from another agent or another plugin ecosystem. Checks the licence first, inventories the source, maps each capability onto the six declarative kinds, and preserves reusable source and UI behind minimal host adapters, and returns a port plus a difference table.
metadata:
  platforms: desktop
---

# Port Plugin

Goal: deliver a working LamTools plugin by reusing the original implementation wherever its licence and compatibility allow. Preserve source behaviour and appearance; change host boundaries only as needed.

<!-- user:“在复刻或者说移植的状态下，尽可能使用原本的源码”+(源码复用为默认，不能因宿主不同而先重写)。 -->

For a port or replica, first test whether the original source, assets, styles and components can run with a small adapter. Prefer copying permitted source intact, bundling its existing framework, and adapting loading, API/RPC, paths, theme aliases and lifecycle. A different host or frontend framework alone is not evidence that rewriting is necessary. For every part that must be rewritten, identify the concrete incompatibility and why a smaller adaptation cannot resolve it. Do not redesign an original page or turn it into a schema form unless the user requested that change.

## 1. The replication contract

Replication means **capability restoration**: the deliverable is the source's capability list, restored. Three rules keep it honest:

- The source's decisions are the spec. Defaults, switches, gates, interaction shapes — the original already made the product decisions; port them. Do not make the port more conservative than the source, and do not defer a capability by claiming a product decision is needed when the source already made it.
- Every capability in the source ends up in exactly one of three states: **ported**, **missing** (with the reason and what it would take), or **changed** (different shape, with the user's decision recorded). Nothing silently disappears and nothing is quietly re-architected.
- A deviation is reported **as a deviation**. Never package one as an improvement or an "architecture simplification" — the user decides whether a deviation is acceptable, not the porter.

Real examples from the bili-scroll port: local transcription was declared impossible because the host Python is frozen — wrong, the script pattern (own venv + run_command) makes it portable; the source's MCP server was swapped for native tools — the source was already an MCP server, so the default is to ship the same MCP config; a shape change like that is a `changed` row for the user to decide (and MCP-first is now the rule for MCP-origin plugins); DM delivery was deferred for "product semantics" the source had already decided (its default delivery mode is DM).

## 2. Licence first

Read the source licence before anything else.

- Permissive licence: reuse source as allowed; retain copyright, licence notices and required attribution.
- Copyleft or other conditional licence: assess the actual reuse and distribution obligations before copying; comply with them or explain the unresolved constraint. Copyleft is not an automatic ban on source reuse.
- Missing, unclear or restrictive licence: do not assume copying is allowed. Describe the limitation; obtain the needed permission or assess a permitted independent implementation.

Record the source version/commit, copied paths, required notices and modified boundaries. Never claim that reading a licence means no code was copied; report actual reuse truthfully.

## 3. Inventory the source

Fetch and read: the manifest, README, entry point, tool definitions, command definitions, skills, hooks, MCP config, and settings schema.

Build one table before writing any file:

| source item | kind | what it does | host dependencies | port decision |
| --- | --- | --- | --- | --- |
| `search_agent` tool | tool | searches the web | none | native tool |
| `/report` command | command | builds a report | internal API | command + operation |
| `postinstall` script | hook/script | downloads data | Node runtime | skill + run_command |
| settings page | UI | form with 4 fields | React component | reuse component and CSS; adapt host requests |
| sidebar panel | UI | live counter | React, websocket | window or region |
| `fs.watch` daemon | runtime | watches files | Node | assess existing process/runtime support; retain implementation when practical |

Rules for the decision column:

- **The source ships an MCP server?** Port the MCP config as-is. Do not translate its tools into native tools: an existing server is the whole capability, with zero re-implementation, and it stays dormant until the session needs it. Rewriting it is a `changed` row and needs the user's decision.
- **The source has a headless/unattended mode** (a CLI profile, a separate tool set, an approval policy)? Declare a matching `profiles` entry and start the round with it. Do not put the whitelist only in a prompt.
- Pure computation or a single API call that is called rarely: a skill plus a script run through `run_command`.
- Frequent calls, a strict return shape, or permissions `run_command` cannot express: a native tool.
- A many-tool capability used only in one flow: gate the tools with `visibility: "on_load"` + `skill`, or keep them as MCP. Twenty always-on tools is a cost every session pays.
- Preserve the original interactive UI and controls. Use `ui.pages`, `ui.windows` or a region as its container; schema forms and declarative blocks are defaults for new UI, not replacements for reusable source UI.
- If source runtime dependencies are needed, assess an existing host runtime or a plugin-owned environment. A bundled browser library such as React and a small API adapter are permitted reuse, not a reason to rewrite the UI. Do not recreate the entire source host just to run one plugin.
- Anything depending on a proprietary service or a local app the user must already own: port the call, list the credential or service as a prerequisite, and do not fake a key.

### Host capabilities to check before declaring a gap

These host contracts exist; a source feature that matches one is a port, not a rewrite:

| Source shape | Host contract |
|---|---|
| Node/other-language long-lived backend | `runtime: {kind: "process"}` in `plugin.json`; JSON-RPC over stdio, host-supervised lifecycle |
| Named agent presets, per-preset services/compaction | manifest `agentPresets`; `context.service("agent_presets")`; `runner.preset_service(name, preset_id)` |
| System-prompt injection at assembly time | `context.service("system_prompt_waterfall")` (synchronous handlers) |
| Chat/IM bridge (sessions, approvals, questions, streaming, commands) | `context.service("channel_host")` + `ChannelAdapter` |
| Message into the live Sunday session the user is watching | `context.service("live_turn_service").deliver_message(...)`; do not infer idle/running or call `turn.start` while a turn may be running |
| Manual child-session compact/fork/history/usage | `runner.compact` / `fork` / `session_info`; `preset_service("compaction").compact_now` |
| Plugin-owned working directory | `context.service("sub_agent_runner_factory")(work_root=...)` |
| Model list/capability/default | `context.service("model_catalog")` |
| Plugin credentials/secrets | `context.service("secrets")` — per-plugin, DPAPI-protected on Windows |
| Webhook/OAuth callback or plugin HTTP API | manifest `http.routes`; mounted at `/api/core/plugin-http/<plugin>/<path>` with token auth |
| Reload plugin code without restarting the app | `plugin.system.reload` (explicit; not a file watcher) |
| Several questions in one tool call | the built-in `question` tool accepts `questions: [...]` |
| Per-peer persistent history | stable agent name + host runtime state store |

Only report a host gap after checking this table. If the contract is missing, record the exact source behaviour and propose the smallest host addition; do not build a private duplicate inside the plugin.

## 4. One plugin folder

```
<name>/
├── plugin.json
├── skills/<name>/SKILL.md
├── tools/tools.jsonc
├── tools.py
├── mcp/mcp.json           # source MCP servers, copied as-is
├── commands.jsonc        # only if commands are numerous; otherwise inline in plugin.json
├── config/schema.jsonc
├── ui/panel.js
└── data/
```

There is one plugin system; no marker field is needed. Keep every tool handler dependency-free unless `engine.dependencies` declares the package.

## 5. Port per capability

- Tool: reuse the source implementation behind a `ToolResult` adapter where possible. Preserve argument names, defaults and return semantics unless a concrete incompatibility requires a documented change. If the source had many flow-specific tools, gate them with `visibility: "on_load"` + `skill`; do not add twenty always-on tools to every session.
- Python modules: `tools.py`, `ops.py` and `backend/__init__.py` are loaded one file at a time; the plugin root is not on `sys.path`. Add `sys.path.insert(0, str(Path(__file__).resolve().parent))` (`parent.parent` in the backend) before sibling imports, or keep each handler self-contained.
- Skill: rewrite the instructions for our environment. Keep the trigger description. Update every path, command and tool name to ours.
- Command: one entry in `commands`, pointing at a registered operation. If the source command only injected a prompt, make it a skill and a command that inserts the token.
- Hook: map the event; if the source hook depended on the other host's lifecycle, drop it and note the gap.
- MCP: copy the server declaration as the default carrier; keep secrets out of the file, use placeholders and tell the user what to fill in. MCP tools are not in the model's tool list: write the plugin's skill instructions for `mcp action=run` with `tool_name` and `arguments` (inspect with `servers` / `tools` / `schema`). For an unattended round, declare `approvedTools` with the exact write tools instead of a blanket auto-approval. Do not reimplement the server's tools in-process unless the user explicitly asks for that shape; record it as `changed` if they do.
- Config: convert the source settings into a JSON schema. Use `title` and `description` so the default panel is readable. A source control that has no equivalent (for example a file picker) becomes a string with a description, not a fake widget.
- UI: directly reuse the original component code, CSS, assets, layout and interaction. Adapt registration, scoped requests and teardown; map source theme variables when necessary. Test the original and port with the same data. Runtime style insertion must carry the host document's CSP nonce (use `context.addStyle` where available); an HTTP 200 alone does not prove styles rendered. Missing host APIs require an explicit gap or an authorized host change, not a fake success response.
- Overrides: only when the user explicitly asks to change host behaviour. Warn that a broken override can stop the app from starting.

## 6. Verification

1. Install locally with `plugin.system.install`.
2. Restart the app before exercising plugin code. Tools and operations are mounted at startup; until then they answer `Unsupported method` or are absent.
3. `plugin.system.list` and `plugin.system.ui`: every declaration parsed, no errors.
4. Exercise each ported capability once **through the host**, not by importing the module locally: call the operation over the app's RPC, let the model call the tool, open the window in the app. A local `python -c "import tools"` does not prove the host loader can load the plugin.
5. Check `backend.log` for `Plugin '<name>' load failed` and `plugins:handler import failed`; the plugin page reports declaration errors only.
6. Open every window and save the config once; restart and confirm `data/` survived.
7. Confirm the unported items are listed, not silently missing.

## 7. Difference report

Always end with this table, in the user's language. The status column uses exactly three values — **ported / missing / changed** — and any "changed" or "missing" row is a deviation the user must be able to decide on:

| source capability | our equivalent | status | notes |
| --- | --- | --- | --- |
| source MCP server | same MCP config | ported | declaration copied; server activates per session |
| source MCP server | native tools | changed | requires the user's approval; reuse was available |
| headless `--profile` round | `profiles.duty` | ported | tool whitelist + approval + budget, enforced by the host |
| web search tool | native tool | ported | same arguments |
| settings page | config schema | changed | source's four tabs became one schema form — confirm acceptable |
| background watcher | none | missing | needs a process; run `run_command` manually instead |
| OAuth login | none | missing | requires the vendor's client secret |

A port where every source capability maps to a "ported" row is a complete replication. Every "missing" or "changed" row is a deliverable, not a footnote — never balance them against "improvements" the port added.

Also state the licence conclusion, which original files were reused, the fixed upstream version/commit, and which adapters or rewrites were necessary. Preserve notices and use file hashes or a focused diff to substantiate unchanged source.

## Rules

- Never claim a port is complete while a capability is missing; the difference table is the deliverable.
- Never present a deviation as an improvement. "The source did X, we did Y" is always a deviation row for the user to decide.
- If the source is an MCP server, port the MCP config, not its tools. Reuse wins over reimplementation.
- Do not assume same-folder imports work; add the plugin root to `sys.path` or keep the handler self-contained.
- A capability is not verified until it has been called through the host after a restart.
- Capabilities that cannot run inside the host process are ported via a script in the plugin folder plus its own environment bootstrap (uv + venv) and `run_command` — "the host Python is frozen" is never a reason to drop one.
- Prefer a small compatibility adapter around reusable source. Do not recreate the entire source host or bundle its unrelated SDK/services merely to avoid identifying the actual boundaries.
- Reuse code only within the actual licence terms; retain required attribution and distribution obligations.
- Do not invent operations or manifest fields. If the feature needs a host capability we lack, report it.
- Preserve the original capability/tool surface during a port. Combining or redesigning tools is a separate user-requested change, not a default porting step.
