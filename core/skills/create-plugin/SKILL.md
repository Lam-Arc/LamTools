---
name: create-plugin
description: Scaffold a LamTools plugin (manifest + tools.jsonc + Python handler skeleton) from a user's description, then guide local install and verification. Use when the user asks to create, write, build, or develop a new plugin, add a custom tool, or make an existing capability into a plugin. Covers the full manifest schema, tools.jsonc fields, handler contract, permission model, and the install-and-verify loop.
---

# Create Plugin

Turn a user's capability request into a working LamTools plugin.

## Structure

```
<plugin-name>/
├── plugin.json            # manifest
├── tools/tools.jsonc      # native tool declarations
├── tools.py               # Python handlers (module for dynamic import)
└── config/schema.jsonc    # optional config schema
```

## Manifest fields (plugin.json)

| field | type | required | meaning |
|---|---|---|---|
| `name` | string | yes | unique plugin name (directory name convention) |
| `version` | string | yes | semantic version, e.g. `0.1.0` |
| `description` | string | no | one-line summary |
| `manifest_version` | string | no | defaults to `1`; other values are rejected |
| `skills` | string[] | no | `./`-relative SKILL.md root directories |
| `hooks` | string[] | no | `./`-relative hooks.json paths |
| `mcpServers` | string[] | no | `./`-relative MCP config paths |
| `tools` | string[] | no | `./`-relative tools.jsonc paths |
| `dependencies` | string[] | no | pip requirements, e.g. `["sqlite-vec>=0.1.9"]` |
| `configSchema` | string | no | `./`-relative JSONC schema for plugin config |

All `./`-relative paths must stay inside the plugin root.

## tools.jsonc

```jsonc
{
  "tools": [
    {
      "name": "my_tool",
      "description": "What the tool does for the model",
      "input_schema": { "type": "object", "properties": { "query": {"type": "string"} }, "required": ["query"] },
      "output_schema": {},
      "permission": "ask_user",   // auto_allow | ask_user | hard_block (default ask_user)
      "category": "my-category",
      "visibility": "always",     // always | on_load
      "skill": "my-skill",        // required when visibility=on_load — tool appears after this skill loads
      "handler": "tools:my_tool", // module:function, importable from the plugin's directory
      "timeout": 30               // optional execution timeout in seconds; omit = unlimited
    }
  ]
}
```

## Handler contract

- The handler module must be importable in the Core runtime. Put `tools.py` at the plugin root and add the plugin directory to `sys.path` if needed, or name modules so the runtime imports them (declare the full import path in `handler`).
- Handler signature: `async def my_tool(call) -> ToolResult` where `call` has `.id`, `.name`, `.arguments` (dict). Return a `ToolResult` with `status` in `ok | failed | blocked | skipped`, plus `content`/`error`.
- Return `status="failed"` with a clear `error` for expected failures; the model sees the error and can retry.

## Permission model

- `auto_allow`: runs without approval (only for safe, read-only work).
- `ask_user`: the user confirms each call — default and safe.
- `hard_block`: the tool is not injected at all.
- `access_tools.jsonc` tiers and ApprovalGate path/danger checks apply to plugin tools too. Users can override a tool's tier in permissions settings.

## Workflow

1. Ask the user what the tool should do, what inputs it takes, and what it returns. Prefer small, focused tools with one clear purpose.
2. Write the plugin directory under the workspace (e.g. `plugins/<name>/`), including `plugin.json` and `tools/tools.jsonc` and the handler module. Keep the handler dependency-free unless the manifest declares `dependencies`.
3. Validate the manifest: `name` set, all `./` paths inside the root, `manifest_version` is `1`, each tool has a `handler`, permissions/visibility are valid enum values.
4. Install locally: `plugin_install` with `source=local`, `path=<plugin directory>`. The user must approve the install.
5. Verify: call `plugin_list` to confirm the plugin is listed with its tools; load any `on_load` skill and confirm the tool becomes visible.
6. Test the tool once with a real input; fix the handler and reinstall (reinstall = update) if it fails.

## Rules

- Plugin code runs inside the Core process — never scaffold handlers that read credentials or arbitrary files without user-visible justification.
- Never invent manifest fields; stick to the schema above (unknown keys are tolerated but not documented).
- If the user wants a heavyweight plugin (RAG indexer, OCR, batch jobs), point them to the full plugin developer guide (`docs/plugin-dev-guide.md`) for dependency and lifecycle details.
