# Plugin backend readiness and recovery

<!-- user:“继续，把 2 阶段都做完”+(实际执行、监听、作业和磁盘发布须各有启动代清理边界)。 -->
The new [phase-2 runtime contracts](../../agent_docs/plugin_phase2_runtime.md)
cover native owned processes, PowerShell/environment contributors, polling file
watches, async plugin jobs, real model calls/streams and durable writes. Disposal
revokes new calls, then joins owned resources through the existing scope cleanup.
Job callbacks must cooperate with cancellation; native process admission still
has a launch-to-Job-assignment race. Committed text, goals, config and audit
records survive plugin stop. This is not a sandbox or complete DSH runtime.

<!-- user:“宿主能力补齐和接口完善与文档更新”+(配置门面固定当前清单/启动代，保存与运行时应用分开)。 -->
Managed backends use `context.config.read/validate/replace` over existing config
paths. SDK replacement requires a content revision; management operations and
legacy bundled writers share the persistence and lock path. Validation remains
basic (required/top-level type/enum), not complete JSON Schema or DSH Config.
Saved files are not automatically applied or rolled back: responses explicitly
report applied=false. Old clients may omit revisions; the current UI has not yet
adopted them. See [config access v1](../../agent_docs/plugin_config_access.md).

<!-- user:“宿主能力补齐和接口完善与文档更新”+(凭据引用绑定当前 owner 和启动代，元数据查询与读取值明确分离)。 -->
Managed backends use `context.credentials.resolve/describe/set/unset` over the
existing encrypted string store. The facade pins owner and epoch; describe never
decrypts or returns values. Fresh reads and process-safe read-modify-replace
prevent stale instances from losing writes. Malformed files fail explicitly.
Committed values survive later startup failure; previously returned plaintext
cannot be retracted. Global environment fallback, grant records and update events
remain unimplemented. Legacy raw secret views retain their original lifecycle.
See [credential references v1](../../agent_docs/plugin_credentials.md).

<!-- user:“宿主能力补齐和接口完善与文档更新”+(持久 JSON 状态使用稳定插件数据目录，句柄绑定启动代而提交不属于注册回滚)。 -->
Managed backends use `context.storage.open` for small synchronous JSON KV state
in the existing stable plugin-data directory. Handles pin the owner and epoch;
SQLite transactions protect conditional revisions. Deletion retains revision
tombstones. Uncertain commit acknowledgements quarantine the handle until
reopen and reconciliation. Committed business state survives a later startup
failure. This is not a DSH schema-domain or backend registry implementation.
See [plugin storage v1](../../agent_docs/plugin_storage_access.md).

<!-- user:“宿主能力补齐和接口完善与文档更新”+(模型只读门面保留项目、场景与受管请求方边界)。 -->
Managed Python backends use `context.models.list/resolve/select` for local model
metadata and read-only scene selection. The facade pins workspace and requester
epoch; record IDs stay distinct from upstream model names. Exact aliases must
be unique. Selection uses existing chat/study/background memory and reports
same-scene replacements, without config writes or provider requests. Catalog
membership does not grant child-route authorization. See
[model access v1](../../agent_docs/plugin_model_access.md) for remaining gaps.

<!-- user:“宿主能力补齐和接口完善与文档更新”+(内存技能登记和撤回绑定原启动代，模型与用户调用策略分别检查)。 -->
Managed Python backends use `context.skills.register` for global embedded text
skills. The existing registry, model loader, user input preparation, and admin
catalog share these contributions. Model/user invocation policies and persistent
disable state apply independently; main, child, background and cloned runners
share that state. Embedded skills have no file location or extra resource grants.
Filesystem entries retain precedence. External providers, scope layers, directory
mounts and change/invalidation protocols remain unimplemented. See the
[embedded skills v1 contract](../../agent_docs/plugin_skill_extensions.md).

<!-- user:“宿主能力补齐和接口完善与文档更新”+(动态命令沿原目录/执行入口扩展并共享受管资源所有权)。 -->
Managed backends can use `context.commands.register` with `CommandInvocation`
and `CommandResult`. The existing command catalog, execution operation and live
adapter select the current session definition; active handlers hold a scope
lease. Revocation hides commands, rejects stale selections and drains callbacks
before cleanup. Legacy same-name actions cannot replace an owned handler.
This text-only subset does not implement DSH attachment, stable definition ID,
change notification, or command log contracts. The current UI requests only the
global catalog. See [dynamic commands v1](../../agent_docs/plugin_command_extensions.md).

<!-- user:“宿主能力补齐和接口完善与文档更新”+(提示词贡献绑定受管启动代，错误时原始提示词可恢复)。 -->
Managed Python backends use `context.prompts.section/variable/on_assemble` for
synchronous, scoped prompt contributions. Startup publication and revocation
follow the existing registration scope. Main and child agents reuse the same
waterfall. Assembly operates on detached copies, allowing the application to
log failures and fall back to untouched builtin text. This differs from DSH's
strict assembly failure. Complete prompts, dynamic context refresh/suppression,
change events, and shared tool-schema assembly remain unimplemented. See the
[prompt extensions v1 contract](../../agent_docs/plugin_prompt_extensions.md).

<!-- user:“宿主能力补齐和接口完善与文档更新”+(动态工具与事件随受管启动代撤回，执行复用原工具箱与权限)。 -->
Managed Python backends can use `context.tools.register/restrict/guard/on`.
The main and child toolboxes share the provider and numeric approval gate;
revocation hides contributions immediately and drains active calls. Registration
tokens fence stale approvals. Supported hooks are pre-execute (allow/deny),
post-execute (content patch), and result (read-only final observation).
There is no execute/waterfall wrapper, argument rewrite, dynamic ask, or complex
schema support. See [dynamic tools contract v1](../../agent_docs/plugin_tool_extensions.md).

<!-- user:“宿主能力补齐和接口完善与文档更新”+(稳定宿主查询接口与 DSH 兼容阶段保持同一份说明)。 -->
Plugins can call `context.describe_host()` for a versioned, value-free snapshot
of live service names/scopes and available operations. Use
`context.require_service(name)` when a missing dependency must fail explicitly.
These Python host interfaces do not grant external-process callbacks or declare
DSH runtime compatibility. See [DSH compatibility and porting](../../agent_docs/dsh_compatibility.md)
for the pinned upstream inventory, offline migration script and remaining stages.

<!-- user:“宿主能力补齐和接口完善与文档更新”+(受管动态服务、依赖引用及 effect 与真实启停共用一个所有者)。 -->
Managed Python backends may register owned services and effects in `start` /
`on_load` using `register_service`, `bind_service`, `effect`, and `on_dispose`.
The host publishes the staged batch after initial health succeeds, withdraws it
on failure/stop, drains `ServiceRef.call()` leases before stop hooks, and cleans
effects in reverse order even if a stop hook fails. Failed cleanup blocks a new
registration epoch. See [owned service contract v1](../../agent_docs/plugin_owned_services.md)
for versioning, retry, cancellation and the differences from Cordis dependencies.

<!-- user:“每一个地方 sunday 都有等价或者近似接口”+(桌面插件在 start 即可绑定会话契约，消息不绕过 live 接收)。 -->
The desktop publishes the `SESSIONS` / `sessions` v1 contract before joining
plugin startup. It exposes create/state/prompt/update_queue/cancel/events/follow/wait
over the existing live host and durable events. Receipts are acceptance facts,
not completion; shutdown wakes passive readers before SQLite closes. See
[session control v1](../../agent_docs/plugin_session_control.md) for exact types,
queue/steer behavior and the still-unsupported DSH methods.

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

## 受管只读文件视图

user:“宿主能力补齐和接口完善与文档更新”+(文件读取视图随启动代撤回，项目切换不移动已有视图)。

start/on_load 取得的 context.filesystem 固定当时的 work_root 与 RegistrationScope。stat/read_bytes/read_text/list_dir 和 root 属性每次检查 scope；停用、失败清理及重启后旧视图不可继续调用。同步读取不注册后台任务；无需额外资源清理。限量目录读取可能不完整，无原子路径隔离、取消、I/O 截止时间或会话目录变更。详见 [文件契约](../../agent_docs/plugin_filesystem_access.md)。

## 受管手动压缩调用

user:“宿主能力补齐和接口完善与文档更新”+(停用先拒绝新的压缩调用，已接收调用保留租约直到真实宿主结果结束)。

context.compaction 绑定当前启动代与工作目录，compact_now 取得 RegistrationScope 调用租约并在 finally 释放。停用撤回后旧视图拒绝新请求，已接收调用继续；生命周期沿用既有 drain/等待/重试，不额外强制取消压缩。桌面宿主使用原 compact 命令认领目标运行，调用者取消仍传播；取消或异常不保证运行历史回滚。详见 [手动压缩](../../agent_docs/plugin_compaction_access.md)。

## 受管权限读取

user:“宿主能力补齐和接口完善与文档更新”+(权限读取随启动代撤回，返回数据不产生跨代授权)。

context.permissions 固定当前 RegistrationScope。catalog 同步检查作用域；read 占用调用租约，完成或取消时释放。停用拒绝旧视图的新请求并等待已接收读取结束。桌面 permission_access 固定会话存储身份，关闭或替换后拒绝读取；查询只读规范化偏好，不改权限或信任，不将结果视为一次性批准。详见 [权限读侧](../../agent_docs/plugin_permission_access.md)。

## 受管程序解析与环境构造

user:“写好清单，逐项打勾完成，不要出错”+(解析工具绑定启动代，不能把无进程资源误记为已实现进程回收)。

context.processes 的 resolve_executable/environment 为同步宿主工具，每次检查 RegistrationScope，停用或重启后旧视图不可继续调用。它们没有后台进程、流、任务或进程句柄；这不代表进程启动与终止已完成。文件查找和环境读取不保证跨调用快照。完整进程所有权、取消和范围退出证明保留后续验收。详见 [进程基础契约](../../agent_docs/plugin_process_access.md)。

## 文件只读门面 v2

user:“写好清单，逐项打勾完成，不要出错”+(新增读取方式延续原视图的启动代与固定目录，不额外授予链接穿透或文件权限)。

read_byte_range/lstat 每次检查原 RegistrationScope，旧视图撤回后不可调用。两者同步完成，不保留打开流或后台任务；文件句柄在范围读取返回/异常时关闭。lstat 可读最终链接元数据，仍拒绝根/上级链接。无异步取消、跨调用快照或原子路径隔离。详见 [文件门面](../../agent_docs/plugin_filesystem_access.md)。

## 文件只读门面 v3 的文本流

user:“继续，列好清单 逐项打勾”+(流迭代恢复时继续检查启动代，停用不遗留打开句柄)。

stream_text 创建时检查作用域、参数和初始文件，每次恢复迭代及正常耗尽前再次检查作用域。每块的文件句柄在 yield 前关闭，不登记跨块清理任务；丢弃未耗尽迭代器也不保留文件句柄。停止后旧流再次 next 会报 ServiceError。此前输出的前缀不代表完整成功，变化/解码失败或撤回后不得自动拼接重试结果。详见 [文本流边界](../../agent_docs/plugin_filesystem_access.md)。
