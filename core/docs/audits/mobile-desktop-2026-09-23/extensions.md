# Mobile runtime extensions audit (2026-09-23)

Read-only comparison of Android native Rust runtime against desktop Python for hooks, MCP, sub-agents, and instruction/memory context. Provider streaming, retry, attachments, and Study domain persistence are excluded; they are audited separately. No GUI or external model/server call was made. The isolated local repro fixture is preserved in [pre-hook-repro](pre-hook-repro/src/main.rs).

## Confirmed findings

### P1 — PreToolUse hook permission decisions are ignored

Rust runs the trusted pre-tool hook and consumes `updated_input` and `decision == "block"`, but never checks `permission_decision` before applying the tool's static permission (`core/runtime-rs/src/lib.rs:515-543`). Desktop Python treats `permission_decision == "deny"` as blocked and `"ask_user"` as requiring approval (`core/src/lamtools_core/kernel/loop.py:2498-2533`). Rust's own `PermissionRequest` handler does consume `allow`/`deny` (`runtime-rs/src/lib.rs:574-616`), so the gap is specifically `PreToolUse`.

Repro: `pre-hook-repro/src/main.rs` has a scripted model call to an AutoAllow `auto_test` tool, a counting tool, and a HookExecutor returning a `PreToolUse` decision. From the repository root run `cargo run --manifest-path core/docs/audits/mobile-desktop-2026-09-23/pre-hook-repro/Cargo.toml --quiet`. The original isolated fixture produced:

```
policy=deny status=completed auto_tool_execute_count=1
policy=ask_user status=completed auto_tool_execute_count=1
```

Both results should have prevented immediate execution under desktop semantics. Any trusted prompt/http/MCP hook emitting either policy for an auto tool can trigger this. This is an authorization failure, not an Android platform restriction.

### P1 — Study sub-agents inherit its prompt but lack Study tools and skills

Initial mobile `child_tools` is constructed from project files and MCP only (`core/mobile/src-tauri/src/lib.rs:540-559`); the parent receives Study graph/notes tools and skill loader later in a separate `tool_runtimes` vector (`:568-578`). Resume repeats the same split (`:733-781`). Child execution uses only `config.child_tools` (`core/runtime-rs/src/sub_agent.rs:451-467`) while inheriting `config.context` (`:490-513`). A Study child instructed to build a knowledge map or curate notes sees the Study prompt/catalog but cannot call `build_knowledge_net`, `notes`, `load_skill`, or `read_skill_reference`. Desktop passes plugin tool specs/handlers to its sub-agent runner (`core/src/lamtools_core/app/default_agent.py:2647-2670,2721-2728`). Repro: create a Study session, delegate a bounded map/notes task, inspect child's tool definitions; those names are absent. This is runtime assembly, not an OS limitation.

### P1 — New child after foreground approval loses the parent context

On a first turn, mobile passes the complete `context` into `SubAgentParentConfig` (`core/mobile/src-tauri/src/lib.rs:493-563`). On resumed foreground turns it instead creates `AgentContext::default()` and adds only the sub-agent guide (`:745-764`). `SubAgentHub::run_child` uses the configured context for any subsequently created child (`core/runtime-rs/src/sub_agent.rs:490-513`). Repro: obtain an approval pause in a project with `AGENTS.md`/`MEMORY.md` or in Study, approve, then have the resumed parent invoke `sub_agent`; the newly started child's system prompt omits project instructions, memory, and Study mode context/catalog. An already-running child resumed from its own saved continuation is distinct and not claimed to lose its context.

### P2 — Mobile general context omits desktop's global and configured files

Mobile TypeScript sends only `modeContext` (`core/mobile/src/standalone/StandaloneTransport.ts:1012-1045`). Native fills project `AGENTS.md` and `MEMORY.md` only (`core/mobile/src-tauri/src/lib.rs:493-505`), and `system_context` emits those fields (`core/runtime-rs/src/lib.rs:830-884`). Desktop `ProjectContextLoader` additionally loads global AGENTS and memory, project `CLAUDE.md` and `CONTEXT.md`, and global/workspace `load_context.jsonc` additions/exclusions (`core/src/lamtools_core/app/project_context.py:12-23,77-157`), which enter non-Study prompts (`core/src/lamtools_core/app/base_agent.py:422-429,488-491`). Repro: place an instruction only in a project `CONTEXT.md` or configure a `load_context.jsonc` addition; mobile request lacks it. Android has an app-private project root, but those project files are available there; this is an assembly difference, not a filesystem impossibility.

### P2 — Mobile Study can accidentally load project AGENTS/MEMORY contrary to desktop Study isolation

Desktop Study explicitly skips the project context loader (`core/src/lamtools_core/app/base_agent.py:430-451,488-491`). Mobile native reads `AGENTS.md` and `MEMORY.md` whenever context fields are empty, including `study_tools == true` (`core/mobile/src-tauri/src/lib.rs:493-505`). Study sessions normally receive a separate `session-*` app-private workspace (`core/mobile/src/standalone/StandaloneTransport.ts:993-994`), so the issue triggers if those files exist there (for example created via project file tools). Then file instructions enter the Study system prompt alongside the canonical Study prompt. This is cross-mode contamination with a narrower trigger than the missing global context case.

### P2 — MCP configuration/startup failures have no mobile-facing report

`load_server_configs` silently skips a server without a nonempty `command` (`core/runtime-rs/src/mcp.rs:82-105`); `McpToolRuntime::load` collects spawn/discovery errors into `report.errors` (`:414-451`). Native loads the runtime on initial and resume turns but never inspects that report (`core/mobile/src-tauri/src/lib.rs:530-538,722-729`); the mobile extension store exposes only config get/update (`core/mobile/src/standalone/StandaloneExtensionsStore.ts:153-167`). Repro: configure a nonexistent stdio executable; the turn proceeds with no MCP tools and no returned failure diagnostic. A URL-only MCP entry is also skipped, but **desktop Python's MCP config loader likewise requires `command`** (`core/src/lamtools_core/mcp/config.py:36-50`), so remote URL support is a shared limitation, not a mobile-only parity finding. Desktop does log unreadable config; this report focuses on the mobile silent failure surface.

## Covered without another confirmed defect

| Area | Evidence | Conclusion / limit |
|---|---|---|
| Hook event lifecycle and required failures | `runtime-rs/src/lib.rs:395-442,515-768`; `runtime-rs/src/hooks.rs:433-690`; Python `plugins/engine.py`, `kernel/loop.py:2498-2850` | SessionStart, UserPromptSubmit, PreToolUse, PermissionRequest, PostToolUse(/Failure), and Stop are wired. Required hook failures block; optional failures audit. No further tested difference beyond PreToolUse policy. |
| Hook trust and project hook source | `mobile/src-tauri/src/lib.rs:1414-1447`; `runtime-rs/src/hooks.rs:218-294`; Python `plugins/hook_config.py:17-82` | Definition hashes gate execution; project `.lamtools/hooks.json` is read on both. Android intentionally has no shell command runner; required command hooks fail closed in `hooks.rs:502-558`, a platform limitation rather than silent bypass. |
| MCP transport | `runtime-rs/src/mcp.rs:1-175,414-508`; Python `mcp/config.py:36-61` | Both implement configured stdio server commands; URL-only entries are unsupported in both. Android ability to execute a particular command depends on its packaged environment, which was not tested. |
| Memory persistence | `mobile/src-tauri/src/lib.rs:920-1028`; Python `app/project_context.py:102-157` | Project `MEMORY.md` enters initial mobile prompt and dreaming can update it. The missing global/context-selection behavior is covered above. |

Audit limit: no real MCP subprocess, HTTP hook, remote model, or Android UI run was made. The P1 pre-hook defect was reproduced in a local executable fixture; the other findings are direct call-path deductions with stated triggers. No production code was edited during this audit.
