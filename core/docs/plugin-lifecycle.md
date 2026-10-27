# Plugin backend readiness and recovery

The rebuilt lifecycle and transaction authority are documented in
[plugin host rebuild](../../agent_docs/plugin_host_rebuild.md). `plugin.*` management
operations forward to `plugin.system.*`; the same supervisor owns operations, tools
and MCP shutdown. See the linked acceptance report for current verification limits.
<!-- user:“该重建就重建”+(生命周期文档指向实际重建后的统一入口)。 -->

An installed plugin and its enabled preference are not evidence that its backend
is running. `plugin.list` preserves `enabled` and adds `available` plus a `backend`
object: `state`, `available`, `managed`, `attempts`, `error`, and `last_error`.
Errors retain a code, lifecycle phase, exception type, message and UTC timestamp;
the backend log retains the traceback. Diagnostics are process-local, not stored
in the installation/configuration ledger.

Managed backends move through `starting → ready`, or `failed` on load, startup,
health or cleanup errors. Stop revokes availability and services before awaiting
cleanup. A failed descriptor remains inspectable; it is not a working backend.
Backend-dependent tools, operations, UI modes/widgets, UI windows and newly
assembled skills/hooks/MCP contributions require readiness. Declaration inventories
in plugin.list remain visible for diagnosis. Ordinary tool input/operation errors
do not by themselves mean the entire backend crashed.

`plugin.enable` also retries failed startup. Failure returns an operation error
with `available: false`, a lifecycle error code, and backend diagnostics. The
enabled preference remains the user's intent; failure does not rewrite it to
disabled. `plugin.disable` stops the backend and retains configuration/data.
Successful retries clear the current error but preserve `last_error`.

## Backend contract

Use a synchronous `create_plugin(context)` factory. `create_runtime(context)` and
module-level hooks remain compatible. Async initialization belongs in optional
`start(context)` / `on_load(context)`; cleanup belongs in `stop()` / `on_unload()`.
Hooks may return any awaitable. Services are published only after managed startup
and the initial health probe succeed.

Optional runtime members:

- `health_check()`: synchronous or asynchronous; return `True` or
  `{"ready": true}` when healthy, `False` / `{"ready": false, "error": "…"}` or
  raise on failure. It runs at startup and approximately once per second.
- `lifecycle_tasks`: an iterable of explicitly owned **critical** asyncio
  tasks/futures. Any completion, exception or unexpected cancellation means the
  backend is no longer available. Do not include finite work or request tasks.
- `lifecycle_processes`: explicitly owned `asyncio.subprocess.Process` or
  `subprocess.Popen` instances. Exit of any member revokes availability. Stop
  terminates/waits remaining registered processes; never register a process
  shared with another plugin or the host.

Resource inventories may be properties, allowing a restart to expose replacement
tasks/processes. Stop hooks should be idempotent and cooperate with cancellation.
Workflow exposes its watcher and queue loops through this contract.

The host's PluginContext services `plugin.lifecycle.start_timeout`,
`plugin.lifecycle.health_timeout`, and `plugin.lifecycle.stop_timeout` set
positive finite deadlines (30 seconds each by default). Timeout revokes readiness
immediately and requests cancellation. A callback that continues after cancellation
is tracked; retry is refused until prior lifecycle work terminates and cleanup
succeeds. Late completion cannot promote the backend to ready.

HTTP startup joins isolated plugin startup tasks before reporting backend ready;
one failed plugin does not prevent other plugins or Sunday from starting. Direct
synchronous assembly retains the historical `start_lifecycle=False` factory-only
mode: its successfully constructed runtime is usable with `managed: false`, and
startup hooks are intentionally not run. Hosts opting into managed lifecycle must
await `await_plugin_backends(handles)` before advertising readiness.

## External-process backends

A plugin may declare a process instead of a Python backend:

```jsonc
"runtime": {
  "kind": "process",
  "command": ["node", "dist/server.js"],
  "cwd": ".",
  "env": {"NODE_ENV": "production"},
  "startupTimeoutMs": 15000,
  "requestTimeoutMs": 60000
}
```

The host starts the child with the same supervisor, readiness, health, stop and
restart rules. The child speaks newline-delimited JSON-RPC 2.0 over stdio:
`initialize`, `tools/call`, `operations/call`, `health`, `shutdown`. Tool and
operation names are still declared in `tools.jsonc` / `operations.jsonc`; for a
process runtime the `handler` field may be omitted because the child implements
it. `cwd` defaults to the plugin root, and `env` is merged over the host
environment. Non-JSON stdout is rejected; stderr is logged under the plugin name.
Process backends do not receive host callbacks yet.

## Plugin HTTP routes

A manifest may declare a small HTTP surface:

```jsonc
"http": {
  "routes": [
    {"method": "POST", "path": "/webhook", "operation": "demo.webhook"}
  ]
}
```

Routes mount under `/api/core/plugin-http/<plugin>/<path>` and dispatch to the
named operation with `{method, path, query, body, headers}`. `auth` defaults to
`token`: the host generates a bearer token in the plugin's secret store under
`httpToken`, and callers send `X-Plugin-Token` or `Authorization: Bearer …`.
`auth: "none"` is available for local-only routes. The operation must belong to
the plugin and be `auto_allow`; interactive approvals cannot be answered over
HTTP. Paths are exact and cannot escape the route prefix.

## Reloading plugin code

`plugin.system.reload` (alias `plugin.reload`) stops the backend, invalidates
imported modules, loads the current files, starts the backend and remounts the
plugin's operations. It is an explicit no-restart path after editing an
installed plugin; it is not an automatic file watcher. Use `plugin.system.update`
when replacing the plugin directory itself.

## Host services for channel and session plugins

Plugins should use these contracts instead of importing host internals:

- `model_catalog`: list/resolve/default/capability/providers.
- `agent_presets`: list/has/resolve/compose plus per-preset
  `register_service` / `service_for`. The runner exposes
  `preset_service("compaction", preset_id)`; the built-in service has
  `compact_now(session_id)`.
- `system_prompt_waterfall`: synchronous append/replace sections.
- `sub_agent_runner_factory`: accepts `work_root` for a plugin-owned directory.
- `channel_host`: builds a `ChannelRuntime` from a `ChannelAdapter`; the runtime
  owns per-peer sessions, merge queues, commands, approvals/questions, streaming,
  usage and compact/fork/reset.
- `secrets`: a per-plugin secret view (`get` / `set` / `delete` / `keys`), backed
  by `PluginSecretStore`. Values are DPAPI-protected on Windows and isolated by
  plugin; the shared store is never exposed as a service.
- `deliverables/presented`: emitted after a tool returns artifacts, with
  `{files, tool_name, call_id}`. Channel plugins receive it through the
  sub-agent event forwarder; consumers should deduplicate against
  `runtime.tool.finished` artifacts.

`KernelSubAgentRunner` also exposes `compact`, `fork` and `session_info` for
manual child-session operations.

## Task 3 coordination and limits

Task 2 does not replace installation directories or implement transactional
updates. Task 3 must stop/revoke the old runtime and await termination **before**
replacing code, invalidate cached/stopped handles and imported modules, rebuild
affected operation/tool registrations, then start and verify the replacement.
Reusing a stopped runtime here is intentional for disable/enable compatibility;
it is not a code-update mechanism. A readiness check alone cannot validate an
update transaction or refresh already-bound handlers.

Deadlines bound awaitable hooks; synchronous Python callbacks that block the
event loop cannot be forcibly interrupted. Unregistered tasks/processes and
internal failures without an observable health check cannot be inferred safely.
Critical resource checks happen on availability queries and during the periodic
probe; the plugin panel refreshes status every two seconds. Already loaded prompt
text is not retracted from active conversations. No automatic restart loop is
introduced: the user explicitly retries after inspecting the error.

The standalone [lifecycle example](../examples/plugins/lifecycle-demo/README.md)
demonstrates the factory, service, task inventory, health probe, native tool and
RPC operation together. Regression coverage is in
`core/tests/test_plugin_startup_state.py` and
`core/ui/tests/plugin-startup-state.test.ts`.
