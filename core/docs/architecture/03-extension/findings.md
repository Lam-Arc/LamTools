# 插件 / 工具扩展架构发现

分析基线：`https://github.com/Lam-Arc/LamTools.git`，revision `5c1371e717dfa86e125665f7669526d758ad5bce`。本页回答“第三方能力如何进入 LamTools 运行时”。

## 边界

插件侧由 清单、注册表、Loader、生命周期、Trust 和 ***插件上下文***（`PluginContext`） 组成；运行时 侧由 ***核心工具箱***（`CoreToolbox`）、权限/审批 和 ***核心循环内核***（`CoreLoopKernel`） 消费已规范化的 工具 / 操作 / 事件 能力。插件不应直接取得 内核 或 会话 的内部对象。

现有 ***插件上下文***（`PluginContext`） 已采用 能力-oriented 设计，能提供 `operation_catalog`、权限、事件、task registry、LLM 和 project root 等依赖；`PluginRuntimeManager` 负责 后端 handle 的 start/stop。UI 扩展、CLI 扩展、desktop entry 和 MCP 文件也由 清单 统一发现。

## 职责

- ***插件注册表***（`PluginRegistry`） 负责 discover、清单 校验、安装根与启停状态，不应执行工具。
- Loader / 生命周期 负责加载 后端、创建 ***插件运行时句柄***（`PluginRuntimeHandle`）、注入 上下文、启动和停止。
- ***能力目录*** 负责 ToolSpec、处理器、操作 的注册与冲突处理。
- ***钩子引擎***（`HookEngine`） 负责 trusted hook 的匹配、执行、审计和 权限 决策；它不是普通 工具 executor。
- ***核心工具箱***（`CoreToolbox`） 负责把 core、MCP、durable、plugin 工具统一为模型可见 spec，并经 权限/审批 后执行。
- ***核心循环内核***（`CoreLoopKernel`） 只调用通用 工具/Result 端口，不按具体插件名分支。

标准扩展路径应是：

`plugin.json → PluginRegistry → PluginContext → Tool / Operation Catalog → CoreToolbox → CoreLoopKernel`

提供方 / 适配器 与 UI 扩展 是旁路扩展面，不应把实现细节倒灌进 运行时。

## 依赖

当前主依赖方向基本正确：插件 → 上下文/目录 → Toolbox → 运行时。工具名冲突、清单 hard block、权限 tier 和 disabled tools 已在 Toolbox 装配阶段收敛，说明扩展入口有实际的安全边界。

需要明确区分：

- 稳定 API：清单 模式、***插件上下文***（`PluginContext`） 的最小 能力、ToolSpec/操作 contract、权限/审批 contract、事件 contract。
- 内部 API：注册表 的扫描细节、***插件运行时句柄***（`PluginRuntimeHandle`）、Toolbox 内部 maps、***核心应用数据库***（`CoreAppDb`）、内核 私有 状态。
- 仅宿主 API：当前 上下文 中的 `services`、任意 `llm_client`、runtime registry 和未版本化 元数据。

## 耦合

1. ***插件上下文***（`PluginContext`） 同时暴露多个基础设施对象，且 `services: dict[str, Any]` 是明确的 escape hatch。它提升了兼容性，却也让插件可以依赖未经版本化的 宿主 内部服务。
2. ***核心工具箱***（`CoreToolbox`） 构造函数同时处理 core/MCP/durable/plugin specs、处理器、权限、mode、timeouts、availability、skill 和 plugin manager，已经是扩展与执行的汇聚点。
3. ***钩子引擎***（`HookEngine`） 同时支持 command、HTTP、MCP、prompt hook，并参与 权限 决策、audit 和阻断；安全职责与执行机制耦合度较高。
4. 插件 后端、UI 扩展 和 session visibility 都由应用装配层驱动；插件 API 尚未完全隔离于 `http_agent_app.py` / ***核心应用数据库***（`CoreAppDb`）。

## 风险

- P1：`PluginContext.services` 和宽 上下文 字段会使“稳定扩展 API”随应用实现一起漂移，插件升级与 Core 发布节奏被绑定。
- P1：工具 注册、权限判定和执行在 Toolbox 聚合，新增一种扩展能力可能触发多个不相关分支。
- P1：钩子/MCP/插件 共享事件、权限和 操作 目录 时，失败语义与信任模型容易不一致。
- P2：UI 扩展 与 后端 plugin 的 清单 拓扑很灵活，但缺少清晰的 能力 versioning / 兼容性 策略。

## 建议

1. 把 ***插件上下文***（`PluginContext`） 收窄为版本化的 类型化能力 view；将 `services` 改成显式、可声明的 能力 registry，并给每项能力定义 拥有者 和生命周期。
2. 拆分 ***插件描述符注册表***（`PluginDescriptorRegistry`）、***插件生命周期管理器***（`PluginLifecycleManager`）、***能力注册器***（`CapabilityRegistrar`） 与 ***工具执行器***（`ToolExecutor`）；注册表 只发现，目录 只注册，Executor 只执行。
3. 让所有 plugin/MCP/tool 调用经过单一 ***权限服务***（`PermissionService`） / ***审批闸门***（`ApprovalGate`）；***钩子引擎*** 只返回 决策，不直接拥有执行状态。
4. 为 ToolSpec、操作、UI 扩展 和 ***插件上下文*** 建立版本兼容矩阵，插件只依赖 公开契约。

## 证据

- `core/src/lamtools_core/plugins/models.py`
- `core/src/lamtools_core/plugins/registry.py`
- `core/src/lamtools_core/plugins/context.py`
- `core/src/lamtools_core/plugins/engine.py`
- `core/src/lamtools_core/plugins/lifecycle.py`
- `core/src/lamtools_core/plugins/operations_loader.py`
- `core/src/lamtools_core/plugins/tools.py`
- `core/src/lamtools_core/tool/default_toolbox.py`
- `core/src/lamtools_core/tool/approval.py`
- `core/src/lamtools_core/mcp/registry.py`
- `core/ui/src/plugins/registry.ts`
