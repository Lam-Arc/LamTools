# 社区插件兼容矩阵（插件系统改造 S5 调研报告）

> 日期：2026-08-14 ｜ 状态：Claude Code / Codex 适配器已实现（`plugins/adapters.py`）；
> Harness 类待实测（不臆测格式）；opencode / OpenClaw 给出 MCP 化建议（不实现源码翻译）。

## 1. 兼容分层

| 层 | 含义 | 兼容难度 |
|---|---|---|
| 资产层 | SKILL.md 技能 / MCP server 工具 | **天然兼容**（LamTools 已支持） |
| manifest 层 | 社区 plugin.json → 本 manifest（`adapters.py` 翻译） | 按格式复杂度分优先级 |
| 运行模型 | 插件代码如何执行 | 决定"进程内兼容"还是"只能外部化" |

## 2. 逐社区矩阵

| 社区 | manifest 形态 | 资产 | 运行模型 | 兼容度 | 本期状态 |
|---|---|---|---|---|---|
| **Claude Code** | `.claude-plugin/plugin.json` + hooks.json（事件+matcher）+ .mcp.json + skills | hooks 与 LamTools 同构；SKILL.md/MCP 直通 | 配置型（hooks 声明 + command/http 执行） | **高** | ✅ 适配器已实现（事件映射 SessionEnd→Stop；Notification/SubagentStop/PreCompact 跳过+警告） |
| **Codex CLI** | plugin.json（id/runtime/executable/args/env）+ skills | SKILL.md 直通 | 外部可执行 → MCP 工具 | **高** | ✅ 适配器已实现（翻译为 mcpServers 配置，走既有 MCP 通道） |
| **OpenCode** | opencode.json + plugin.ts **源码**（TS API） | SKILL.md 直通 | TS 源码，无法进程内 | **低** | ⏸ 仅资产层手动并入；MCP 化建议（见 §4） |
| **OpenClaw** | Go 插件源码（ClawPlugin 接口）+ ClawHook（命令前缀触发） | SKILL.md / MCP 直通 | Go 源码，无法进程内 | **低** | ⏸ 同上 |
| **Harness 类**（DeepSeek harness 等） | 未实测 | ? | ? | **待调研** | ⏸ 实测计划见 §5 |

## 3. 适配器实现要点（已交付）

- `plugins/adapters.py`：`import_claude_code_plugin` / `import_codex_plugin`——翻译产物为标准 LamTools 插件（生成 plugin.json + 复制 hooks/mcp/skills），走既有 `plugin.install` 流程（`source=cc|claude-code|codex`）。
- Claude Code hooks：事件同名直通 + `SessionEnd→Stop`；`Notification`/`SubagentStop`/`PreCompact` 不支持 → 跳过并在安装结果 `warnings` 中透出（UI/CLI 可见）。
- Codex：`executable + args + env` → `mcp.json` 的 `mcpServers` 条目——外部进程工具走 **MCP 标准通道**，零新架构。
- 安装 = 翻译 + 复制到插件根 + 可选依赖安装；重装即更新。

## 4. 源码型插件（opencode / OpenClaw）MCP 化建议

源码型插件的 handler 无法在 core 进程内运行（§1 硬约束：同一 interpreter）。
可行接入路径（按推荐序）：

1. **MCP 化**：若插件逻辑可打包为外部进程（或已有 MCP server 形态），用 `mcpServers` 声明接入——工具能力完整，代价是外部进程管理。
2. **资产层并入**：插件内的 SKILL.md / MCP 配置直接复制进插件目录（天然兼容），仅工具 handler 不翻译。
3. **声明翻译 + 重写 handler**：翻译 manifest 的工具声明，handler 由用户/Agent 按 create-plugin skill 重写为 Python——工作量大，仅高价值插件值得。

## 5. Harness 类实测计划（不臆测格式）

Harness（DeepSeek harness 等）类社区插件的 manifest 格式 / 安装方式 / 运行模型未知，
**按文档原则不臆测**。启动 RAG 插件开发后并行执行：

1. 选取 2-3 个代表性 harness 项目（GitHub 检索 "harness" + agent/plugin 关键词）。
2. 实测三问：manifest 格式（字段/文件位置）？安装方式（目录复制 / 包管理器 / 构建）？运行模型（进程内 / 子进程 / MCP）？
3. 对照本矩阵分层，输出实测结果 → 决定是否新增适配器及其优先级。
4. 兼容性保障：本系统 manifest 已预留 `manifest_version`（缺省 1，未知版本报错）与 `x-*` 键透传——后续加适配器不破坏已装插件（§8 共识）。

## 6. 结论

- 社区生态的**主体（SKILL.md 技能 + MCP 工具）已天然兼容**；Claude Code / Codex 的
  manifest 适配器已实现并测试（`tests/test_plugin_adapters.py`，6 项）。
- 源码型插件（opencode TS / OpenClaw Go）受运行模型限制，只支持资产层与 MCP 化建议。
- Harness 类待实测后定适配优先级；`manifest_version` + `x-*` 预留保证演进不破坏已装插件。
