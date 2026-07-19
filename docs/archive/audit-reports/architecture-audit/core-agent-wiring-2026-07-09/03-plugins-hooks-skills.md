# 03 - Plugin / Hook / Skill 接线审计

## 主验收结论

Core 已有插件发现、插件启停、HookRegistry、HookEngine 和 plugin/hook operation；Kernel 也能执行 `PreToolUse`。但 Core 自己的 CLI/App/HTTP 没有把这些能力接成可用入口。Skill 目前只有 roots/资源路径支撑，没有 Core 通用 SkillRegistry 和 `load_skill`。

## Core 已有能力

| 能力 | 现状 |
|---|---|
| PluginRegistry | 扫描用户/项目插件根，读取 `plugin.json`。 |
| PluginStateStore | 支持启停状态，默认启用。 |
| HookRegistry | 合并项目、用户、插件 hook 文件。 |
| HookEngine | 支持匹配、信任检查、command hook 执行、block/context/input/permission decision。 |
| Operation | 已有 `plugin.list`、`plugin.enable`、`plugin.disable`、`hook.list`、`hook.trust`。 |

## 证据

- 插件注册：`core/src/lamtools_core/plugins/registry.py:61`。
- 插件 hook/mcp/skill/agent 路径发现：`core/src/lamtools_core/plugins/registry.py:91`、`:104`、`:107`。
- plugin operation：`core/src/lamtools_core/plugins/operations.py:12`、`:29`、`:81`。
- HookRegistry：`core/src/lamtools_core/plugins/hook_config.py:25`。
- 支持解析的 handler 类型：`core/src/lamtools_core/plugins/hook_config.py:12`。
- HookEngine：`core/src/lamtools_core/plugins/engine.py:12`。
- 非 command handler 会跳过：`core/src/lamtools_core/plugins/engine.py:55`。
- Kernel 有 hook_engine 字段：`core/src/lamtools_core/kernel/loop.py:117`。
- Kernel 执行 `PreToolUse`：`core/src/lamtools_core/kernel/loop.py:1064`。

## Hook handler 状态

| Handler | 配置可解析 | 实际可执行 | 判断 |
|---|---:|---:|---|
| command | 是 | 是 | 可靠。 |
| http | 是 | 否 | 存疑，当前跳过。 |
| mcp | 是 | 否 | 存疑，当前跳过。 |
| prompt | 是 | 否 | 存疑，当前跳过。 |

## Core 入口缺口

- Core CLI 没有 `plugin`、`hook`、`skill` 子命令，只提供 `run`。
- Core CLI 创建 Kernel 时没有传 `HookEngine`。
- Core Agent operation 只有 `turn.start` 和占位 `approval.respond`。
- `/api/core` 没有 operation 总线，也不能直接 list/enable/trust/load/use。
- Writer app-server 反而暴露了 Core plugin/hook operation。

## Skill 状态

Core 只有这些支撑：

- plugin manifest 可声明 `skills`，读取为 `skill_roots`。
- command tools 有 `loaded_skill_roots`，用于允许 skill 脚本路径。
- workspace read tools 支持额外 resource roots。

缺少：

- 通用 SkillRegistry。
- `skill.list`。
- `skill.load` / `load_skill`。
- skill prompt index。
- 加载后把 skill root 纳入资源根和命令允许路径的统一状态。

Writer 当前拥有真正可用的 skill 实现：

- `members/writer/backend/app/core/writer/skills.py:18`。
- `members/writer/backend/app/core/writer/skills.py:42`。
- `members/writer/backend/app/core/writer/read_tools.py:180`。

## 分级

- 可靠：插件发现、插件启停、HookRegistry、command HookEngine、Writer 侧 plugin/hook RPC。
- 存疑：`http/mcp/prompt` hook handler，配置层支持但执行层跳过。
- 债务：Core 缺通用 SkillRegistry/load_skill；Core CLI/App/HTTP 不接 plugin/hook/skill；插件 `skill_roots/mcp_files/agent_roots` 多数停留在“可发现/可展示”。

## 接线建议

1. Core 提供 plugin/hook/skill operation catalog，并挂到 CLI 与 HTTP operation 总线。
2. Core 提供 HookEngine builder：输入 `work_root/data_dir/plugin_roots/trust_store`，输出 `HookEngine`。
3. Core CLI 和 member Kernel 创建时都调用同一个 HookEngine builder。
4. 把 Writer `load_skill` 下沉为 Core 通用工具。
5. skill 加载后统一更新 resource roots 和 loaded skill roots。

## 验收用例

- `core plugin list` 能列出 skills/hooks/mcp/agents。
- `core hook list` 能显示 trusted/pending。
- `core hook trust` 后，`core run` 的工具调用触发 command hook。
- `core skill list/load` 可用，加载后能读取 skill 文件和执行 skill scripts。

