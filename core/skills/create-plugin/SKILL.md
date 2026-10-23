---
name: create-plugin
description: Build a LamTools v2 plugin from a user's description and install it locally. Use when the user asks to create, write, build, or develop a plugin, turn a workflow into a plugin, add a tool, panel, window, mode or config page, or replace part of the host. Covers the minimal manifest, the six declarative capabilities, configuration panels, UI regions and windows, agent takeover, module overrides, and the install-and-verify loop.
metadata:
  platforms: desktop
---

# Create Plugin

A plugin is a folder with `plugin.json`. `name` and `version` are the only required fields; everything else is optional and additive. A plugin that only has those two fields installs, shows up, and gets a default config panel.

## 1. Write the smallest thing that works

```
hello/
└── plugin.json
```

```json
{ "name": "hello", "version": "0.1.0", "assembly": "v2" }
```

Set `"assembly": "v2"` in every new plugin. The legacy plugin system skips v2 plugins, so only one system assembles it.

Ask the user only what you cannot infer: what the plugin does, what it must remember, whether it needs a UI. Then pick the lightest mechanism below that can do the job.

## 2. Pick the lightest mechanism

| Need | Use |
| --- | --- |
| Knowledge, a repeatable procedure, a one-off script run | a skill plus `run_command` |
| Repeated work with a strict return shape, or work that must bypass the highest command permission gate | a native tool |
| A button or a small readout inside an existing panel | a declarative UI region |
| A form of settings | `config.schema` |
| A page that does not fit any panel | `ui.windows` |
| Replacing part of the host itself | `overrides` |

Make a tool only when all three are true: it is called often, its return structure matters, and it needs permissions that `run_command` cannot express. Otherwise write a skill with a script and let `run_command` run it. A plugin that is one skill and one script is a good plugin.

## 3. Manifest fields

| field | type | meaning |
| --- | --- | --- |
| `name` | string | required; one path segment, also the folder name |
| `version` | string | required |
| `description` | string | one line, shown in the plugin page |
| `assembly` | `"v2"` | marks the plugin for the new system |
| `scope` | `global` / `mode` / `session` | default `global`; required semantics for agent takeover |
| `skills` | string[] | `./`-relative skill root directories |
| `tools` | string[] | `./`-relative `tools.jsonc` files |
| `hooks` | string[] | `./`-relative hook JSON files |
| `mcp` | string[] | `./`-relative MCP config files |
| `commands` | object[] | slash commands, declared inline |
| `context` | object[] | extra context files, `{ "file": "./x.md", "order": 50 }` |
| `config` | object | `{ "schema": "./config/schema.jsonc", "panel": "./config/panel.js" }` |
| `ui` | object | styles, script, regions, windows |
| `agent` | object | prompt/tools/approval/context takeover |
| `overrides` | object | `{ "lamtools_core.some.module": "./modules/some.py" }` |
| `engine` | object | `{ "runtime": "python", "python": ">=3.11", "platform": "windows-x64", "dependencies": [] }` |

All `./` paths must stay inside the plugin folder. Unknown fields are ignored; do not invent fields and expect them to work.

## 4. Files a plugin can ship

```
hello/
├── plugin.json
├── skills/<name>/SKILL.md        # skills
├── tools/tools.jsonc             # tool declarations
├── tools.py                      # tool handlers, imported as module:function
├── hooks/hooks.json              # hooks
├── mcp/mcp.json                  # MCP servers
├── config/schema.jsonc           # config form
├── config/panel.js               # custom config panel
├── ui/style.css                  # injected styles
├── ui/panel.js                   # optional page script
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
      "output_schema": {},
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

Return `status="failed"` with a readable `error` for expected failures. Do not validate the model's input beyond what the handler truly needs; the host does not check input or output schemas.

## 6. Skills, hooks, MCP, context

- Skill: a folder with `SKILL.md` whose frontmatter has `name` and `description`. The description states when to use it.
- Hook: `hooks/hooks.json` in the same shape as host hooks; see `core/docs` for events. Hooks run inside the host process.
- MCP: `mcp/mcp.json` with `mcpServers`. The host merges it into the session's MCP config.
- Context: declare files, not prompt text. Order is explicit; equal order is sorted by file name, so a plugin can always keep its place. Context changes appear after the next context compaction, not mid-turn.

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

`operation` is any registered RPC operation. Text typed after the command becomes `arguments` in the payload. Do not add a second execution channel; reuse operations.

## 8. Config panel

Every plugin has a config panel. If the plugin needs settings, declare a schema:

```jsonc
{
  "type": "object",
  "properties": {
    "endpoint": { "type": "string", "title": "Endpoint", "description": "Where requests go" },
    "retries": { "type": "integer", "default": 2 },
    "mode": { "type": "string", "enum": ["fast", "safe"] }
  },
  "required": ["endpoint"]
}
```

Values are stored in `data/config.jsonc` and read with the config operations. Types checked by the host: string, integer, number, boolean, array, object, plus `required` and `enum`. Anything else is passed through.

For a fully custom panel, declare `config.panel` and register yourself. The host injects the script and calls `mount` with a root element and the config API:

```js
window.LamToolsPluginPanels = window.LamToolsPluginPanels || {};
window.LamToolsPluginPanels["hello"] = {
  mount(root, api) {
    // api.plugin   -> { name, version, description }
    // api.config   -> current values
    // api.schema   -> parsed schema
    // api.save(values) -> Promise, writes data/config.jsonc
    root.textContent = JSON.stringify(api.config);
  },
};
```

If the script never registers `mount` or throws, the host falls back to the default form, so a broken panel never locks the user out.

## 9. UI

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
          { "id": "refresh", "title": "Refresh", "operation": "demo.refresh" }
        ]
      }
    ],
    "windows": [
      { "id": "board", "title": "Board", "entry": "./ui/window.html", "width": 720, "height": 520 }
    ]
  }
}
```

Block types: `text`, `status`, `metric`, `list`, `progress`. Adding a region appends to what is already there. `"replace": true` takes over a region; only one plugin can replace a region and the host reports the conflict. Styles are ordinary CSS in the page, so a plugin can restyle anything by selector. The optional `script` runs in the page for cases the declarative blocks cannot express.

Windows are plain HTML files opened as separate desktop windows. They call Core operations over the same API and can talk to the main page through `localStorage` or the host API. A window is the right shape for a pet, a floating board, or a long-running tool.

## 10. Agent takeover

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

The winning declaration replaces the whole agent identity: session-scoped first, then the active mode, then global. `prompt` replaces the leading instructions; `tools` restricts the visible tools; `approval` is `ask`, `auto` or `block`; `context` appends files. Tools, prompt and context follow the compression cycle; approval and commands change immediately.

## 11. Overrides

Overrides replace a host module before it is imported:

```jsonc
{ "overrides": { "lamtools_core.app.some_module": "./modules/some_module.py" } }
```

Rules the author owns:

- Replacement is module-level, not function-level. If you take a module, you ship the whole module.
- The host does not check that your module exports the same names. If an import breaks, the host logs the failure and the app may not start; that is your responsibility.
- Two plugins cannot take the same module. The second one is refused and the conflict is reported, not silently won.
- `LAMTOOLS_SAFE_MODE=1` skips every override so a user can recover.
- Overrides load at startup. Changing one requires restarting the app.

Tell the user this explicitly before writing an override plugin: it is the one mechanism that can stop the app from starting.

## 12. Engine and dependencies

```jsonc
{ "engine": { "runtime": "python", "python": ">=3.11", "platform": "windows-x64", "dependencies": ["httpx>=0.27"] } }
```

The host compares `python`, `app` and `platform` at install time and refuses the plugin with the exact unmet constraint. The host ships Python; do not ask the user to install a runtime. Keep dependencies minimal and declare them; pip installation is the user's decision.

## 13. Install and verify

1. Write the folder under the workspace, for example `plugins/<name>/`.
2. Install with the `plugin.system.install` operation: `{ "source": "local", "path": "<absolute folder>" }`, or `{ "source": "zip", "path": "<zip>" }`. The plugin is copied into the first plugin root. Updating uses `plugin.system.update` and keeps `data/`.
3. Check the plugin page, or call `plugin.system.list`, `plugin.system.ui`, `plugin.system.agent` and confirm the declarations are parsed without errors.
4. Exercise every declared capability once: run the tool, trigger the command, load the skill, open the window, save the config, restart and confirm `data/` is still there.
5. If a capability reports a declaration error, fix the manifest and update the plugin; do not hand-edit files inside the installed root.

## Rules

- Do not read credentials or unrelated files from a handler. If a plugin needs a secret, ask the user how it should be supplied.
- Do not write outside the plugin folder except through declared tools and `data/`.
- Do not add a second plugin runtime, a component protocol, or a permission system inside a plugin.
- Do not claim a capability works until you have exercised it once.
- If the request needs something the host does not offer, say what is missing instead of faking it.
