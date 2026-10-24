---
name: create-plugin
description: Build a LamTools plugin from a user's description and install it locally. Use when the user asks to create, write, build, or develop a plugin, turn a workflow into a plugin, add a tool, operation, backend, panel, window, mode or config page, or replace part of the host. Covers the minimal manifest, the six declarative capabilities, plugin operations and backends, configuration panels, UI regions and windows, modes, agent takeover, module overrides (backend and frontend), and the install-and-verify loop.
metadata:
  platforms: desktop
---

# Create Plugin

A plugin is a folder with `plugin.json`. `name` and `version` are the only required fields; everything else is optional and additive. A plugin that only has those two fields installs, shows up on the plugin page, and gets a default config panel.

There is one plugin system; every `plugin.json` is assembled by it. No marker or migration field exists.

Ask the user only what you cannot infer: what the plugin does, what it must remember, whether it needs a UI. Then pick the lightest mechanism that can do the job, write it, install it, and exercise every declared capability once before claiming it works.

## 1. Write the smallest thing that works

```
hello/
└── plugin.json
```

```json
{ "name": "hello", "version": "0.1.0" }
```

Install it (section 13), confirm it appears enabled on the plugin page, then grow it one capability at a time. A plugin that installs, enables, and shows no declaration error is a working plugin at every size.

## 2. Pick the lightest mechanism

| Need | Use |
| --- | --- |
| Knowledge, a repeatable procedure, a one-off script | a skill plus `run_command` |
| A slash-command trigger for an action | `commands` + an operation |
| Frequent calls with a strict return shape, or work that must bypass the highest command permission gate | a native tool |
| An RPC other surfaces (blocks, commands, the model) call | `operations` |
| A background service, a watcher, a database, sessions | a `backend` |
| A button or readout inside an existing panel | a declarative UI region |
| Settings | `config.schema` |
| A page no panel can host | `ui.windows` |
| A whole workspace with its own agent and main page | `scope: "mode"` + `ui.modes` + `agent` |
| Replacing part of the host itself | `overrides` |

Make a tool only when all three are true: it is called often, its return structure matters, and it needs permissions that `run_command` cannot express. Otherwise write a skill with a script and let `run_command` run it. A plugin that is one skill and one script is a good plugin.

## 3. Manifest fields

| field | type | meaning |
| --- | --- | --- |
| `name` | string | required; one path segment (letters, digits, dot, underscore, dash), also the folder name |
| `version` | string | required; shown on the plugin page |
| `description` | string | one line |
| `scope` | `global` / `mode` / `session` | default `global`; scopes agent takeover and when the plugin's surfaces are active |
| `defaultEnabled` | boolean | first-install state; once the user flips the switch, the ledger wins forever |
| `engine` | object | `{ "runtime": "python", "python": ">=3.14", "app": ">=0.4", "platform": "windows-x64" }`, compared at install |
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

Return `status="failed"` with a readable `error` for expected failures. The host does not check input or output schemas.

Two naming rules:

- Two plugins may not declare the same tool name; the later one is refused and the conflict is reported. Same for commands and skills.
- A tool that reuses a **core tool's name** is a handler swap: keep the declaration minimal (name, permission, handler) and the host borrows the core tool's description and schemas. This is how built-ins like web search are re-implemented; the swap only changes the implementation, not the interface.

## 6. Skills, hooks, MCP, context

- Skill: a folder with `SKILL.md` whose frontmatter has `name` and `description`. The description states when to use it; declare `skillModes` to scope a skill root to specific modes.
- Hook: `hooks/hooks.json`, same shape as host hook files. Events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `SessionStart`, `Stop`, `UserPromptSubmit`, `PermissionRequest`. Handler types: `command`, `http`, `mcp`, `prompt`. Hooks declared by a plugin are **trusted on install** — they do not go through the per-hook review flow that user hook files do. Installing a plugin is an explicit act of trust.
- MCP: `mcp/mcp.json` with an `mcpServers` object. The host merges it into the session's MCP config.
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

`operation` is any registered RPC operation — yours (section 8) or the host's. Text typed after the command is appended to the payload. A command may instead declare an `effect` (for example showing a plugin window); commands have no permission system of their own, the operation they call carries the permissions.

## 8. Plugin operations

Operations are the plugin's RPC surface — what blocks, commands, the config panel, and external callers invoke.

```jsonc
// operations.jsonc
{ "operations": [ { "name": "demo.refresh", "description": "Refresh the cache", "handler": "ops:refresh" } ] }
```

Handler contract: `async def refresh(request)`, returning an `OperationResult` or a plain dict payload. Handlers may accept keyword-only `work_root` and `data_dir`; the host passes what the signature asks for. Declared operations are mounted at startup, stay available behind the plugin's enabled state, and conflicting names across plugins are refused.

## 9. Backend

A backend is a long-lived runtime: watchers, sqlite stores, sessions, background tasks.

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
      { "id": "board", "title": "Board", "entry": "./ui/window.html", "width": 720, "height": 520, "fileDrop": true }
    ],
    "modes": [
      { "id": "focus", "title": "Focus", "tools": ["read_file", "demo.notes"], "exclusiveTools": true }
    ]
  }
}
```

- Block types: `text`, `status`, `metric`, `list`, `progress`. Region content appends by default, sorted by `order` then plugin name; `"replace": true` takes the region over (one replacer per region, conflicts reported).
- Actions: `dangerous: true` makes the host ask for confirmation first; `inputSchema` makes the host collect arguments in a small form before invoking.
- `entry` hands the region to plugin JavaScript: the host injects the module script once and leaves an empty container for it to draw into.
- Styles load as real stylesheets from the plugin folder, so relative `url(...)` references to shipped images and fonts work. Because they are page-wide CSS, a style-only plugin can restyle existing UI via the stable `data-region` / `data-part` hooks.
- Windows are plain HTML pages opened as desktop windows; `fileDrop` opts into drag-and-drop files. They call Core operations over the same API.
- A mode turns the main area into a plugin surface and appears in the mode switcher. `tools` restricts what the model sees in that mode; `exclusiveTools` makes the plugin's own tools visible only there. Mode components ship with the app for bundled plugins; third-party mode UIs come from regions, scripts, and overrides.

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

The host compares `python`, `app` and `platform` at install time and refuses the plugin naming the exact unmet constraint — write the constraints, do not ask the user to install a runtime. `dependencies` are import-probed at install; missing packages are listed in the install result with the pip hint but never block installation. The host does not install packages and does not bundle plugin dependencies: a dependency must be importable on the host (built-in, or installed by the user) or the plugin's tools will report the missing package at call time.

## 15. Install and verify

1. Write the folder under the workspace, for example `plugins/<name>/`.
2. Install with the `plugin.system.install` operation: `{ "source": "local", "path": "<folder>" }`, `{ "source": "zip", "path": "<zip>" }`, or `{ "source": "url", "url": "<zip url>", "sha256": "<optional digest>" }`. The plugin lands in the user plugin root.
3. Verify declarations: call `plugin.system.list` and confirm no declaration error, then the capability-specific checks — `plugin.system.ui` for regions/windows/modes, `plugin.system.agent` for takeover.
4. Exercise every declared capability once: run the tool, trigger the command, load the skill, open the window, save the config, restart the backend by disabling and enabling the plugin.
5. Update with `plugin.system.update` (same three sources) and confirm `data/` survived.
6. If a capability reports a declaration error, fix the manifest and update; never hand-edit files inside the installed root.

The definition of done is the loop above passing, not the files looking right.

## Rules

- Do not read credentials or unrelated files from a handler. If a plugin needs a secret, ask the user how it should be supplied.
- Do not write outside the plugin folder except through declared tools and `data/`.
- Do not add a second plugin runtime, a component protocol, or a permission system inside a plugin.
- Do not claim a capability works until you have exercised it once.
- If the request needs something the host does not offer, say what is missing instead of faking it.
