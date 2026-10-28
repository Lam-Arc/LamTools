---
name: create-plugin
description: Build a LamTools plugin from a user's description and install it locally. Use when the user asks to create, write, build, or develop a plugin, turn a workflow into a plugin, add a tool, operation, backend, panel, window, mode or config page, or replace part of the host. Covers the three layers a plugin can touch (interaction, capability, module replacement), the minimal manifest, the six declarative capabilities, plugin operations and backends, configuration panels, UI regions and windows, modes, agent takeover, module overrides (backend and frontend), and the install-and-verify loop.
metadata:
  platforms: desktop
---

# Create Plugin

A plugin is a folder with `plugin.json`. `name` and `version` are the only required fields; everything else is optional and additive. A plugin that only has those two fields installs, shows up on the plugin page, and gets a default config panel.

There is one plugin system; every `plugin.json` is assembled by it. No marker or migration field exists.

Ask the user only what you cannot infer: what the plugin does, what it must remember, whether it needs a UI. Then decide what it touches, write it, install it, and exercise every declared capability once before claiming it works.

## Existing plugins and replicas

<!-- user:“在复刻或者说移植的状态下，尽可能使用原本的源码”+(已有实现先复用，不能按新插件默认流程重画)。 -->

When the request is a replica, migration or port of an existing plugin, follow `../port-plugin/SKILL.md` first. After checking the licence, prefer the original source, components, styles and assets with the smallest host adapter. A different framework is not itself a reason to rewrite. New-plugin recommendations below (schema forms, declarative blocks, design recipes) must not silently replace the original UI. Record concrete blockers and source differences for every necessary rewrite.

## 1. The three layers a plugin can touch

Everything a plugin does falls into three layers. Walk them in this order when deciding what to build.

### 交互层 — what the user sees and clicks

- Buttons: region `actions` bound to operations. Mark `dangerous: true` and the host asks for confirmation first; declare `inputSchema` and the host collects arguments before invoking.
- Readouts: declarative `blocks` — `text`, `status`, `metric`, `list`, `progress`.
- Anything richer (card walls, filters, charts, previews): a self-drawn `entry` — the host injects your module script and gives you an empty container to draw into.
- Forms: the config panel (schema-driven, or a custom panel script).
- Standalone flows: `ui.windows` — plain HTML pages opened as desktop windows.
- Split-pane pages: `ui.pages` — JavaScript ES modules exporting `mount(root, context)`, opened as independent split tabs. See `agent_docs/plugin_split_pages.md` for the manifest, scoped RPC and cleanup contract; use `plugins/bili-scroll/ui/wall-page.mjs` as a working example.
- Restyling: `styles` — plain CSS loaded page-wide; restyle existing UI through the stable `data-region` / `data-part` hooks.

Honest inventory: region blocks have **no input controls** — inputs happen through action arguments or the config panel. If you need dropdowns and inputs inside a region, write an `entry`. A plugin whose user-facing side is only the config form is not finished if the product needs buttons and browsing — check what the user expects to click.

### 能力层 — what the plugin does

- Tools: in-process functions the model calls.
- MCP servers: declared in `mcp/mcp.json`; the model inspects them with the `mcp` tool and executes them through `run_command` (`core mcp call`).
- Operations: RPC for buttons, commands and panels. **The model cannot call operations** — if the model needs the data, declare a tool that returns it.
- Host services for backends: session store, sub-agent runner (spawn isolated sessions), LLM client, event bus/sink, operation catalog, and live session delivery (`live_turn_service`, section 9). The channel/session services in section 9 are stable contracts; verify anything else in the host source before building on it.
- Scripts: files in your plugin folder executed on the user's machine (see "External dependencies" below).

### 覆盖层 — replacing host modules

If neither layer fits, replace host modules with `overrides`. Read section 13 first: this is the one mechanism that can stop the app from starting or the page from loading.

## 2. Choose the mechanism

**MCP or tool** (the most common decision). Check reuse first, then frequency.

- **The capability already exists as an MCP server** (the source plugin ships one, or a public server provides it) → ship that MCP config. This is the default and the cheapest path: the capability comes across whole, with zero re-implementation, and its tools never enter the prompt — the model inspects them with the `mcp` tool and runs one with `mcp action=run`. Rewriting an existing MCP server's tools as native tools is a shape change — a `changed` row in a port — and needs the user's decision. "Zero install" is not a reason to rewrite a working MCP.
- Called in most rounds → an in-process tool. The tool list is always present and the UI collapses its call cards.
- Called rarely, or only in one flow → MCP, or a tool gated with `visibility: "on_load"` + `skill` (section 5). A dormant server costs nothing in the prompt; an always-on tool costs every session.

Where the dependencies live is the second question:

- It runs on what the host already ships (for example httpx + public APIs)? → in-process, zero install.
- It needs dependencies the host does not ship? → MCP in your own environment, or a script (see "External dependencies").
- It is a long-running service, a watcher, a scheduler? → a backend.



**External dependencies — three ways out when something cannot run inside the host process:**

1. Skill guidance: declare the requirement in config ("needs Whisper and Python 3.10+"), and teach the user or the agent how to set it up.
2. `run_command` / a dedicated tool: ship a script in your plugin folder and execute it. Whether it runs depends on the user's machine, not host packaging. Provide a setup operation (for example: bootstrap uv, create a venv under your `data/`, install the packages) and degrade gracefully when the environment is missing — say what is missing and count what you skipped.
3. Your own MCP: wrap the script in your own MCP server and declare it in `mcp/mcp.json`.



**授权分层 — anything that acts as the user** (posting comments, sending DMs):

- Consent lives in a config switch: the user flipping it is standing authorization. Do not add per-call confirmation on top of a switch the user already flipped — it breaks unattended runs.
- Hard gates live in the handler: dedup, rate limits, credentials. Refuse in code; never rely on the model's judgment.
- Approval follows the run context: interactive rounds confirm drafts when unsure; unattended rounds run on the switch's authorization.

Real cases behind these rules — the bili-scroll replication and others — live in the bundled Wiki, in the 插件 article's 案例 section. Read it when a rule above feels abstract.



## 3. Manifest fields

| field | type | meaning |
| --- | --- | --- |
| `name` | string | required; one path segment (letters, digits, dot, underscore, dash), also the folder name |
| `version` | string | required; shown on the plugin page |
| `description` | string | one line |
| `scope` | `global` / `mode` / `session` | default `global`; scopes agent takeover and when the plugin's surfaces are active |
| `defaultEnabled` | boolean | first-install state; once the user flips the switch, the ledger wins forever |
| `engine` | object | `{ "python": ">=3.14", "app": ">=0.4", "platform": "windows-x64" }`, compared at install |
| `dependencies` | string[] | third-party imports, probed at install; missing ones are named but never block install |
| `skills` | string[] | `./`-relative skill root directories |
| `tools` | string[] | `./`-relative `tools.jsonc` files |
| `hooks` | string[] | `./`-relative hook JSON files |
| `mcp` | string[] | `./`-relative MCP config files |
| `commands` | object[] | slash commands, declared inline |
| `context` | object[] | `{ "file": "./x.md", "order": 50 }` |
| `config` | object | `{ "schema": "./config/schema.jsonc", "panel": "./config/panel.js" }` |
| `ui` | object | styles, script, regions, windows, modes |
| `agent` | object | prompt/tools/approval/context takeover |
| `operations` | string[] | `./`-relative `operations.jsonc` files |
| `backend` | string | `./`-relative entry; `backend/__init__.py` is the convention |
| `runtime` | object | `{ "kind": "process", "command": [...], "cwd": ".", "env": {...} }` — host-supervised external process backend (see section 9) |
| `http` | object | `{ "routes": [{ "method": "POST", "path": "/webhook", "operation": "demo.webhook" }] }` — token-protected HTTP routes dispatched to operations |
| `profiles` | object | named run profiles for unattended/sub-agent rounds — tool whitelist, approval, model scene, MCP servers/tools, budget (see section 9) |
| `agentPresets` | object[] | named presets for sub-agent rounds — mode, tool whitelist, model, leading prompt section (see section 9) |
| `overrides` | object | module replacements, backend and frontend keys |
| `skillModes` | object | skill root → modes that unlock it |

All `./` paths must stay inside the plugin folder; anything that escapes is rejected at read time. Unknown fields are ignored; do not invent fields and expect them to work. A misspelled field does not error — the capability simply never appears, so check the plugin page's declaration errors.

## 4. Files a plugin can ship

```
hello/
├── plugin.json
├── skills/<name>/SKILL.md        # skills
├── tools/tools.jsonc             # tool declarations
├── tools.py                      # tool handlers, imported as module:function
├── hooks/hooks.json              # hooks
├── mcp/mcp.json                  # MCP servers
├── operations.jsonc              # the plugin's own RPC surface
├── ops.py                        # operation handlers
├── backend/__init__.py           # background runtime factory
├── scripts/                      # scripts executed via run_command or tools
├── config/schema.jsonc           # config form
├── config/panel.js               # custom config panel
├── ui/style.css                  # injected styles
├── ui/panel.js                   # page script (also the ui.script)
├── ui/window.html                # standalone window entry
├── data/                         # plugin-owned data, kept across updates
└── logs/                         # plugin writes its own logs here
```

`data/` survives updates and uninstall-with-keep-data. Never write user data anywhere else, and never assume the plugin folder itself is writable across updates.

## 5. Tools

```jsonc
{
  "tools": [
    {
      "name": "my_tool",
      "description": "What the tool does for the model",
      "input_schema": { "type": "object", "properties": { "query": { "type": "string" } }, "required": ["query"] },
      "permission": "ask_user",   // auto_allow | ask_user | hard_block
      "visibility": "always",     // always | on_load
      "skill": "my-skill",        // required when visibility=on_load
      "handler": "tools:my_tool", // module:function, resolved inside the plugin folder
      "timeout": 30               // optional, seconds
    }
  ]
}
```

Handler contract:

```python
async def my_tool(call) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    ...
    return ToolResult(call_id=call.id, name=call.name, status="ok", content="...")
```

Return `status="failed"` with a readable `error` for expected failures. The host does not check input or output schemas. Tools may return images for vision models via `ToolResult.model_image_data_url` — the same channel `read_file` uses; text-only models get a readable "cannot receive images" message instead.

Two naming rules:

- Two plugins may not declare the same tool name; the later one is refused and the conflict is reported. Same for commands and skills.
- A tool that reuses a **core tool's name** is a handler swap: keep the declaration minimal (name, permission, handler) and the host borrows the core tool's description and schemas. This is how built-ins like web search are re-implemented; the swap only changes the implementation, not the interface.

**Visibility.** `visibility` defaults to `always` — the tool is in the model's list in every session, even when the plugin's flow never runs. For tools that belong to one skill or flow, set `"visibility": "on_load"` with `"skill": "<skill-name>"`; they appear only after that skill loads. A plugin with eight or more flow-specific tools should gate them this way, or ship them as an MCP server instead (section 2). Twenty always-on tools is a prompt cost every conversation pays.

**Same-folder imports are not automatic.** `tools.py`, `ops.py` and `backend/__init__.py` are loaded one file at a time; for a plain `module:function` entry the plugin root is not on `sys.path`. `import helper` from any of them raises `ModuleNotFoundError` at load or call time. Either keep the handler self-contained, or put this before the sibling imports:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
```

For `backend/__init__.py` the plugin root is `Path(__file__).resolve().parent.parent`. Operation entries with a dotted module name are the exception: the host appends the plugin root before importing them.

## 6. Skills, hooks, MCP, context

- Skill: a folder with `SKILL.md` whose frontmatter has `name` and `description`. The description states when to use it; declare `skillModes` to scope a skill root to specific modes.
- Hook: `hooks/hooks.json`, same shape as host hook files. Events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `SessionStart`, `Stop`, `UserPromptSubmit`, `PermissionRequest`. Handler types: `command`, `http`, `mcp`, `prompt`. Hooks declared by a plugin are **trusted on install** — they do not go through the per-hook review flow that user hook files do. Installing a plugin is an explicit act of trust.
- MCP: `mcp/mcp.json` with an `mcpServers` object. The host merges it into the session's MCP config; the server command can point into your own environment (for example a venv your setup operation built). MCP tools are **not** added to the model's tool list: the model inspects them with the `mcp` tool (`servers` / `tools` / `schema`) and runs one with `mcp action=run, tool_name='mcp__server__tool', arguments={...}`. Each run is gated by that tool's declared `level` / `toolLevels`. The legacy `core mcp call` route still works as a compatibility alias inside `run_command`, but do not write new instructions against it. If the server cannot start, its tools are unavailable and the rest of the plugin keeps working.
- Context: declare files, not prompt text. Order is explicit; equal order sorts by file name, so a plugin always keeps its place. Context changes appear after the next context compaction or a new session, never mid-turn.

## 7. Slash commands

```jsonc
{
  "name": "demo-report",
  "title": "Demo report",
  "description": "Build today's report",
  "operation": "demo.report.build",
  "payload": { "scope": "today" }
}
```

`operation` is any registered RPC operation — yours (section 8) or the host's. Text typed after the command is appended to the payload. A command may instead declare an `effect`; the host returns it to the caller without executing an operation. Commands have no permission system of their own, the operation they call carries the permissions.

## 8. Plugin operations

Operations are the plugin's RPC surface — what buttons, commands, the config panel, and external callers invoke.

```jsonc
// operations.jsonc
{ "operations": [ { "name": "demo.refresh", "description": "Refresh the cache", "handler": "ops:refresh" } ] }
```

Handler contract: `async def refresh(request)`, returning an `OperationResult` or a plain dict payload. Handlers may accept keyword-only `work_root` and `data_dir`; the host passes what the signature asks for. Declared operations are mounted at startup and remounted by `plugin.system.reload`. An installed or updated plugin may answer `Unsupported method` until it is reloaded or the backend restarts. They stay available behind the plugin's enabled state, and conflicting names across plugins are refused. Plan the reload/restart into the verify loop (section 15).

**Operations are the user-facing RPC surface.** An Agent can also reach them through an existing `run_command` plus a plugin-declared CLI that connects to the running host. Prefer that route for existing command capabilities; do not add a duplicate Agent tool just to simplify arguments.

<!-- user:“实现这个插件，也正好实验我们的新插件架构”+(网络插件验证后的后台审批、导航及自绘面板合同)。 -->

Operations may declare `permission: "ask_user"` and an `impact` description, or `permission: "hard_block"`. The host checks its shared permission service before importing/executing the handler. Missing permission services fail closed for protected operations. Existing explicit host authorization remains effective. Unspecified permission retains legacy `auto_allow` behavior; system network modifications must explicitly declare protection.

Use `approvalFields: ["kind", "interface_index"]` to include selected concrete arguments in the confirmation. Only list non-sensitive fields; never include URLs with credentials, subscription links, cookies or tokens. The execution still uses the full server-captured request.

An unapproved call returns an `approval_required` result containing `approval.id`, `operation`, and `impact` (over JSON-RPC this is error data). Host UI bridges show `CoreConfirmDialog` and send `plugin.system.operation.respond` with the ID and `approve` / `deny`. The host executes only the captured request once; changing parameters, replaying, expiry or plugin changes cannot reuse it. A client-supplied `confirmed` field is never authorization. Agents must not manufacture approval responses.

For complete plugin pages, set `ui.pages[].navigation: true` to add the same page to the main left rail. Ordinary pages remain split-only. No dedicated host component or hard-coded plugin branch is needed.

Custom config panels receive `api.rpc` and `api.signal` in addition to config/schema/save. Their `mount` may return a cleanup function, synchronously or asynchronously. Prefer `api.rpc` over a global bridge so pending confirmations and subscriptions can be cancelled when the panel closes. The host stops a plugin backend before uninstalling its files; cleanup failure prevents file removal.

Choose a unique CLI command name and check `core --help` before declaring it. For example, the core already owns `network`, so Network Exploration uses `network-exploration`.

## 9. Backend

A backend is a long-lived runtime: watchers, sqlite stores, sessions, background tasks, schedulers.

```python
# backend/__init__.py
def create_plugin(context):
    return {
        "runtime": MyRuntime(context),       # or return the object directly
        "tool_handlers": {"demo.ping": ping},  # dynamic tools this backend serves
        "tool_providers": [],
        "services": {"cache": my_cache},       # registered as "<plugin>.<key>" services
    }
```

The factory must be synchronous; do initialization in `start(context)`. A runtime may expose `start`, `stop`, `health_check`, `lifecycle_tasks`, `lifecycle_processes` — the host starts it with the plugin enabled, stops it on disable, monitors health, and restarts the same instance on re-enable. Each backend gets its own model scene; it never inherits the conversation's model by accident. Declared tools keep working across restarts because one instance per plugin lives for the process.

Through `context` a backend reaches the host services listed in section 1 — for example `context.service("sub_agent_runner_factory")` spawns isolated sub-agent sessions, and the operation catalog executes any registered operation (scheduling, session queries). This is how a plugin implements its own schedulers and background flows: the timer lives in your runtime, the work it triggers runs where you point it.

### External-process backends

A Node, Rust or other process can be the backend without a Python shim:

```jsonc
// plugin.json
"runtime": {
  "kind": "process",
  "command": ["node", "dist/server.js"],
  "cwd": ".",
  "env": { "NODE_ENV": "production" },
  "startupTimeoutMs": 15000,
  "requestTimeoutMs": 60000
}
```

- The process speaks newline-delimited JSON-RPC 2.0 over stdio: `initialize`, `tools/call`, `operations/call`, `health`, `shutdown`. `initialize` returns `{name, version, tools?, operations?}`; tool calls return `{status, content, error, artifacts, metadata}` and operation calls return `{status, payload}`.
- Declare the tool and operation names in `tools.jsonc` / `operations.jsonc` as usual. For a process runtime the `handler` field may be omitted — the child process implements it.
- The host owns startup, readiness, health, stop and restart exactly like an in-process backend. `cwd` defaults to the plugin root; use it when the child expects its own directory. `env` is merged over the host environment.
- Do not print non-JSON text to stdout; use stderr for logs. The host logs stderr under the plugin name.
- Process backends cannot receive host callbacks yet. Keep protocol handlers request/response; long-running work should report through the plugin's operations or tools.

### HTTP routes

A plugin can expose webhooks or callbacks without registering a FastAPI router:

```jsonc
"http": {
  "routes": [
    {"method": "POST", "path": "/webhook", "operation": "demo.webhook"},
    {"method": "GET", "path": "/health", "operation": "demo.health", "auth": "none"}
  ]
}
```

- Routes mount under `/api/core/plugin-http/<plugin>/<path>` and dispatch to the named operation with `{method, path, query, body, headers}`.
- `auth` defaults to `token`. The host generates a bearer token in the plugin's secret store under `httpToken`; read it with `context.service("secrets").get("httpToken")` and show it to the user. Send it as `X-Plugin-Token` or `Authorization: Bearer …`.
- The operation must be owned by the plugin and declared `permission: "auto_allow"`; `ask_user` and `hard_block` routes are refused because HTTP cannot show an approval prompt.
- Paths are exact, must start with `/`, and cannot contain `..`, `?` or `#`. At most 32 routes per plugin.

### Reloading plugin code

`plugin.system.reload` (alias `plugin.reload`) stops the backend, invalidates imported modules, loads the current files, starts the backend and remounts the plugin's operations. It is the no-restart path after editing an installed plugin; it is explicit, not a file watcher. Use `plugin.system.update` when replacing the plugin directory.

### Host services for channel and session plugins

These are stable contracts; do not import internal host modules when one exists.

| Service | Contract |
|---|---|
| `model_catalog` | `list()` / `resolve(ref)` / `default()` / `capability(ref)` / `providers()`; each model has `id`, `provider`, `capability`, `contextWindow`, `maxOutputTokens`. |
| `agent_presets` | `list()` / `has(id)` / `resolve(id)` / `compose(id, ...)` and per-preset services: `register_service(preset_id, name, service)` / `service_for(preset_id, name)`. |
| `system_prompt_waterfall` | synchronous `register(handler, plugin=..., order=...)`; the handler receives `PromptContext` and `PromptAssembly`. |
| `sub_agent_runner_factory` | `factory(work_root=...)` returns a runner; use `work_root` for a plugin-owned working directory. |
| `channel_host` | `ChannelHost.create(adapter=..., config=..., ...)` builds a `ChannelRuntime` for an IM bridge. |
| `live_turn_service` | `deliver_message(thread_id=..., text=..., client_message_id=..., work_root="")` returns `{ok, mode: "started"/"steered"/"queued", turn_id, run_id}`. Also `active_turn`, `start_turn`, `resume_turn`, `steer_turn`, `respond_approval`. One call owns the idle/running/paused decision; never read the runtime registry or build an active run id in the plugin. |
| `secrets` | Per-plugin secret view: `get(key, default="")` / `set(key, value)` / `delete(key)` / `keys()` / `has(key)`. Values are DPAPI-protected on Windows and isolated by plugin. |

A tool result with `artifacts` also emits `deliverables/presented`
(`{files, tool_name, call_id}`). Chat-channel plugins receive it through the
sub-agent event forwarder; deduplicate against `runtime.tool.finished` because
both carry the same artifacts.

`KernelSubAgentRunner` exposes child-session operations directly: `run(..., preset=...)`, `compact(session_id)`, `fork(session_id, new_agent_name)`, `session_info(session_id)`, and `preset_service(name, preset_id)` (the built-in `compaction` service has `compact_now(session_id)`).

For a chat channel, implement `ChannelAdapter` (`send_text`, `send_file`, `open_stream`, `ask_approval`, `ask_questions`, `handle_interaction`, `handle_text`, `cancel_pending`, `acknowledge_interaction`) and let `ChannelRuntime` own per-peer sessions, the merge queue, commands, approvals/questions, streaming, usage and compact/fork/reset. The runtime calls the host runner factory; the plugin keeps only network I/O and message formatting.

### Live session delivery

A chat bridge, scheduler or notifier may need to put a message into the Sunday session the user is currently watching. That is different from a plugin-owned sub-session: the live session already has its own turn state, guidance path and desktop projection. Route it through the host:

```python
live = context.service("live_turn_service")
result = await live.deliver_message(
    thread_id=session_id,
    text=text,
    client_message_id=message_id,
)
```

- `started`: the host began a normal user turn.
- `steered`: the host submitted the text as guidance to the running turn through the same operation the desktop uses, so the user-guide projection is written.
- `queued`: the turn was ending at the boundary; the host filed the text as the next user message instead of dropping it.
- Wait for the target turn's events and forward replies; do not decide idle/running yourself.

Never read `runtime_task_registry`, query the turn snapshot, or pass an `active_run_id` from the plugin. Do not call `turn.start` first while a turn may be running: it can block behind the session actor and turn a mid-turn message into the next turn. For approvals and questions, consume the live event stream and call `respond_approval`; keep one persistent target watcher as the single reply forwarder.

### Run profiles (unattended and sub-agent rounds)

A named profile is a host-enforced bundle for a round nobody is watching. Declare it in the manifest and start the round with it; do not put the same whitelist only in a prompt.

```jsonc
"profiles": {
  "duty": {
    "title": "Duty round",
    "tools": ["bili_duty", "bili_search", "run_command"],
    "approval": "auto",
    "modelScene": "background",
    "mcpServers": ["bilibili"],
    "mcpTools": ["mcp__bilibili__search", "mcp__bilibili__save_report"],
    "approvedTools": ["mcp__bilibili__bili_reply", "mcp__bilibili__bili_send_message"],
    "budget": { "maxToolCalls": 120, "maxTokens": 150000 }
  }
}
```

- `tools` is required and is the exact callable whitelist; the host refuses calls outside it, so a prompt cannot widen the round.
- `approval: "auto"` is the coarse switch: it lifts the round's confirmation threshold (in full access, up to level 3). Prefer `approvedTools` for the precise version.
- `mcpServers` activates those servers for the round; `mcpTools` restricts their tools (use `mcp__<server>__<tool>` names). `skills` limits which skills the round can load.
- `approvedTools` lists the exact MCP tools whose level-3 confirmation is skipped for this round. It is not a whitelist (that is `mcpTools`) and does not lower the tool's level or the capability cap; every other level-3 tool still asks. Use it for unattended writes instead of a blanket `approval: "auto"`, and let the user grant it — a plugin should not self-approve a write.
- `modelScene` picks that scene's model; `budget` ends the round when either counter is exhausted.
- Start the round with `context.service("run_profile")(profile="plugin:profile", task=prompt, agent="...")`; it resolves the profile and runs a headless sub-agent with `profile_spec`. It is async: from a backend thread, capture the host loop in `start()` and schedule it with `asyncio.run_coroutine_threadsafe`, then return instead of blocking the timer. The lower-level `sub_agent_runner_factory` still exists (`runner.run(task=..., profile_spec=...)`), but use `run_profile` unless you need custom kwargs. `profile.list` / `profile.resolve` are read-only RPC operations for inspecting declarations.

### Agent presets and system prompt waterfall

Two host contracts let a plugin shape a sub-agent round without reimplementing the host:

```jsonc
// plugin.json
"agentPresets": [
  { "id": "readonly", "title": "Read only", "mode": "low",
    "tools": ["read_file", "list_dir", "search_content"],
    "prompt": "This round may read and search, but must not modify files." }
]
```

- Presets come from enabled plugin manifests and from `agent-presets.jsonc` in the project/global config; config overrides a plugin preset with the same id. `mode`, `tools`, `model` and `prompt` are optional.
- A preset only fills values the caller did not set. An explicit `mode`, `allowed_tools` or `model` wins; `tools` is an exact whitelist for that round.
- The preset prompt becomes a leading system-prompt block, not a tail note. Callers start a round with `runner.run(..., preset="readonly")`; the runner re-applies the preset when an approval or question resumes.
- UI that lists presets should read `context.service("agent_presets").list()` / `has(id)`.
- A preset can mount a live service with `register_service(preset_id, "compaction", service)`, and a runner resolves it with `preset_service("compaction", preset_id)`. The host also provides a built-in compaction service for every preset.

The system-prompt waterfall lets a backend append or replace prompt sections at assembly time:

```python
waterfall = context.service("system_prompt_waterfall")
unregister = waterfall.register(handler, plugin="demo", order=100)

def handler(prompt_context, assembly):
    if prompt_context.agent_name == "my-agent":
        assembly.append_section("demo:rules", "Extra rules for this agent.", order=90)
    return assembly
```

- Handlers are synchronous. Returning an awaitable is rejected; the host prompt assembly is synchronous.
- `PromptContext` carries the session id, agent name, work root, active mode and session metadata, so a handler can scope its section to one agent.
- `assembly.append_section(name, text, order=...)` also appends the text; `replace_section(name, text)` updates both the section and its occurrence. Return `None` to leave the assembly unchanged.
- Register in `start()` and call the returned unregister function in `stop()`. A handler exception is logged and the built-in prompt is kept, so one plugin cannot break the turn.
- Sections become independently tracked blocks and follow the same freeze/notice cycle as built-in prompt blocks.

## 10. Config panel

```jsonc
// config/schema.jsonc
{
  "type": "object",
  "properties": {
    "endpoint": { "type": "string", "title": "Endpoint" },
    "retries": { "type": "integer", "default": 2 },
    "mode": { "type": "string", "enum": ["fast", "safe"] }
  },
  "required": ["endpoint"]
}
```

Types checked by the host: string, integer, number, boolean, array, object, plus `required` and `enum`. Values are read and written through the config operations and live in the plugin's `data/`. Secrets are stored as plain files in local data — say so if the user asks for encrypted storage, the host does not provide it.

For a custom panel, declare `config.panel` and register yourself; the host injects the script and calls `mount` with a root element and the config API:

```js
window.LamToolsPluginPanels = window.LamToolsPluginPanels || {};
window.LamToolsPluginPanels["hello"] = {
  mount(root, api) {
    // api.plugin -> { name, version, description }
    // api.config -> current values
    // api.schema -> parsed schema
    // api.save(values) -> Promise
    root.textContent = JSON.stringify(api.config);
  },
};
```

If the script never registers `mount` or throws, the host falls back to the default form; a broken panel never locks the user out.

## 11. UI

Regions are places the host already renders: `appRail`, `left`, `titlebar`, `main`, `right`, `composer`, `composerSide`, `message`, `settings`.

```jsonc
{
  "ui": {
    "styles": ["./ui/style.css"],
    "script": "./ui/panel.js",
    "regions": [
      {
        "region": "right",
        "order": 50,
        "blocks": [
          { "type": "status", "label": "State", "value": "ready" },
          { "type": "metric", "label": "Today", "value": 12, "detail": "entries" }
        ],
        "actions": [
          { "id": "refresh", "title": "Refresh", "operation": "demo.refresh" },
          { "id": "wipe", "title": "Wipe", "operation": "demo.wipe", "dangerous": true,
            "inputSchema": { "type": "object", "properties": { "scope": { "type": "string" } } } }
        ]
      },
      {
        "region": "main",
        "replace": true,
        "entry": "./ui/board.js"
      }
    ],
    "windows": [
      { "id": "board", "title": "Board", "entry": "./ui/window.html", "width": 720, "height": 520 }
    ],
    "modes": [
      { "id": "focus", "title": "Focus", "tools": ["read_file", "demo.notes"], "exclusiveTools": true }
    ]
  }
}
```

- Block types: `text`, `status`, `metric`, `list`, `progress`. Region content appends by default, sorted by `order` then plugin name; `"replace": true` takes the region over (one replacer per region, conflicts reported).
- Actions: `dangerous: true` makes the host ask for confirmation first; `inputSchema` makes the host collect arguments in a small form before invoking.
- `entry` hands the region to plugin JavaScript: the host injects the module script once and leaves an empty container for it to draw into. Card walls, filters and paginated browsing are built here — your script reads your operations and renders. Your script calls your own operations through the host bridge `window.LamToolsPluginRPC(method, params)` — the same channel the plugin page uses.
- Styles load as real stylesheets from the plugin folder, so relative `url(...)` references to shipped images and fonts work. Because they are page-wide CSS, a style-only plugin can restyle existing UI via the stable `data-region` / `data-part` hooks.
- Windows are plain HTML pages opened as desktop windows; they call Core operations over the same API.
- A mode turns the main area into a plugin surface and appears in the mode switcher. `tools` restricts what the model sees in that mode; `exclusiveTools` makes the plugin's own tools visible only there. Mode components ship with the app for bundled plugins; third-party mode UIs come from regions, scripts, and overrides.

A user-facing plugin usually needs more than a config form: if the product has buttons, lists, or browsing, build them with actions and entries, not just a schema.

## 12. Agent takeover

```jsonc
{
  "scope": "mode",
  "agent": {
    "mode": "focus",
    "prompt": "./prompt.md",
    "tools": ["read_file", "write_file"],
    "approval": "ask",
    "context": ["./context/rules.md"],
    "exclusiveTools": true
  }
}
```

The winning declaration replaces the whole agent identity: session-scoped first, then the active mode, then global; a second global declaration is refused. `prompt` replaces the leading instructions; `tools` restricts visible tools; `approval` is `ask`, `auto` or `block`; `context` appends files. Prompt, tools and context follow the compression cycle; approval and commands change immediately.

## 13. Overrides

Overrides replace a host module. Keys come in two families with one shared conflict table:

```jsonc
{
  "overrides": {
    "lamtools_core.some.module": "./modules/some_module.py",
    "@/components/SomePart.vue": "./modules/some_part.js"
  }
}
```

| family | target | replacement | takes effect |
| --- | --- | --- | --- |
| `lamtools_core.*` | a backend module | a Python file in the plugin | at startup; changes need an app restart |
| `@/...` | a frontend module path | a JS module in the plugin | when the page loads; changes need a full page reload |

Rules the author owns:

- Replacement is module-level, not function-level. Take a module, ship the whole module.
- The host does not check that your module exports the same names. A missing export breaks importers — the backend fails at startup, the frontend fails at page load — and that is your responsibility, not the host's.
- Two plugins cannot take the same target, across both families. The second is refused and the conflict is reported.
- `LAMTOOLS_SAFE_MODE=1` skips every override so a user can always recover.
- Query what is replaceable before promising it: the `plugin.system.behavior` operation lists every module and marks the kernel (loader, manifest, ledger, safe mode, logging) as not replaceable. Vendor dependencies and the desktop shell are not replaceable either.

Tell the user this explicitly before writing an override plugin: it is the one mechanism that can stop the app from starting or the page from loading.

## 14. Engine and dependencies

```jsonc
{ "engine": { "python": ">=3.14", "platform": "windows-x64" }, "dependencies": ["httpx>=0.27"] }
```

The host compares `python`, `app` and `platform` at install time and refuses the plugin naming the exact unmet constraint — write the constraints, do not ask the user to install a runtime. `dependencies` are import-probed at install; missing packages are listed in the install result with the pip hint but never block installation. The host does not install packages and does not bundle plugin dependencies: a dependency must be importable on the host (built-in, or installed by the user) or the plugin's tools will report the missing package at call time. Capabilities whose dependencies cannot ship in-process use the script patterns from section 2 instead.

## 15. Install, verify, and when changes take effect

1. Write the folder under the workspace, for example `plugins/<name>/`.
2. Install with the `plugin.system.install` operation: `{ "source": "local", "path": "<folder>" }`, `{ "source": "zip", "path": "<zip>" }`, or `{ "source": "url", "url": "<zip url>", "sha256": "<optional digest>" }`. The plugin lands in the user plugin root.
3. Confirm the installed root with `plugin.system.list` (`root`). The runtime reads that copy, not the workspace. On Windows it is normally `%APPDATA%\LamTools\plugins\<name>`; portable mode uses the app-side plugins directory.
4. After code or declaration changes, update the installed copy with `plugin.system.update` (or copy the files there) and call `plugin.system.reload`. A workspace edit alone is not visible to the running plugin. If host service code changed, restart the backend/app instead.
5. Verify declarations: call `plugin.system.list` and confirm no declaration error, then the capability-specific checks — `plugin.system.ui` for regions/windows/modes, `plugin.system.agent` for takeover.
6. Exercise every declared capability once **through the host**, not by importing the module yourself: call the operation over the app's RPC, let the model call the tool, load the skill, open the window in the app, save the config. A local `python -c "import tools"` proves nothing about the host loader.
7. Check `backend.log` for `Plugin '<name>' load failed` and `plugins:handler import failed`. The plugin page's `errors` array covers declaration errors, not runtime load failures: a plugin can look enabled and error-free while its backend and handlers failed to import.
8. Update with `plugin.system.update` (same three sources), reload or restart, and confirm `data/` survived.
9. If a capability reports a declaration error, fix the manifest and update; never hand-edit files inside the installed root.

**The runtime runs the installed copy**, not your workspace folder: handler code, `data/`, and saved config all live under the installed root (found via `plugin.system.list`'s `root` field). When settings need to change on the user's behalf, use the config operations (`plugin.system.config.get/update`) — never write a `data/config.jsonc` next to the workspace source, where the running tool will never see it.

**When changes take effect** — tell the user which of the three applies:

- Config values: immediate, on next read.
- Code and declarations: `plugin.system.reload` on the installed copy. Tools and operations are remounted by the reload. If host service code changed, restart the backend/app.
- Prompt-affecting changes (context, agent prompt, overrides): new session / compaction for prompts, app restart or full page reload for overrides.

The full table lives in the bundled Wiki's 插件 article.

The definition of done is the loop above passing, not the files looking right.

## Rules

- If the capability already exists as an MCP server, ship that MCP config; do not rewrite its tools in-process unless the user asks for that shape. Reuse wins over reimplementation.
- Do not leave a large set of flow-specific tools always visible. Gate them with `visibility: "on_load"` + `skill`, or use an MCP server.
- Do not assume same-folder imports work. Add the plugin root to `sys.path`, or keep each handler self-contained.
- Do not read credentials or unrelated files from a handler. If a plugin needs a secret, ask the user how it should be supplied.
- Do not write outside the plugin folder except through declared tools and `data/`.
- Do not add a second plugin runtime, a component protocol, or a permission system inside a plugin.
- Do not reimplement the host's live-session state machine. For messages into the session the user is watching, call `live_turn_service.deliver_message`; do not read the runtime registry or call `turn.start` yourself while a turn may be running.
- Verify the installed copy, not the workspace source: run the plugin through the host after a reload or restart.
- Do not claim a capability works until you have exercised it once through the host, after a reload or restart.
- Report what you did not build: if the request implies a capability you left out, say so — the missing part is a deliverable, not a footnote.
- If the request needs something the host does not offer, say what is missing instead of faking it.
