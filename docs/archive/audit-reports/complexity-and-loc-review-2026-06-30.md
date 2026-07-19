# LamTools 复杂度与代码行数复审

日期：2026-06-30

目的：在上一轮 Core 主线收敛、Writer 前端 reducer 删除、Artist 旧生命周期事件删除之后，重新审查当前代码体量和复杂度来源，作为下一轮激进减法的依据。

最高目标文档：`docs/agent-architecture-north-star-2026-06-30.md`。本报告的行数目标和删除优先级必须服从该文档的 Core/member 主次判断。

维护标注（2026-07-02 Step 12 后）：

- 本文主体仍是 2026-06-30 的历史复审，下面关于 `TaskManager` SSE、Writer SSE -> CoreEvent 反向适配、Artist 旧生命周期事件、Writer provider parser 主线的判断不再全部代表当前实现。
- 当前状态以 `docs/core-member-architecture-refactor-design-2026-06-30.md` 的 Step 12 执行记录为准：Writer 旧 TaskManager/SSE 产品链路、旧 RuntimeEvent/CoreEvent 反向适配、Artist 私有 TaskManager/SessionEventHub/LamEvent 生产路径已经清理；Core 产品名扫描无命中。
- 剩余风险转为产品边界验证：Writer App Server envelope 仍是 Writer 产品层命名，Artist `TaskEventStream` / live route 仍是产品任务展示 adapter；它们不是 Core 基座事实源。

维护标注（2026-06-30 第一切片后）：

- 本报告主体行数是执行前快照，保留用于解释当时复杂度来源。
- 已落地：Core `RunItemEvent` + snapshot reducer contract；Writer runtime bridge 主路径改为 Core run item；删除 Writer SSE payload -> `core_event` 反向适配；删除 `core_adapter.py` / `test_writer_core_adapter.py`；删除 CLI 中 `writer_git_*` / `writer_part_updated` 旧 formatter。
- 仍待处理：`TaskManager` SSE 产品链路、`writer_service.py` 多投影、Writer app-server reducer 向 Core snapshot reducer 收敛、LLM/profile/toolkit 下沉 Core。
- 本轮局部差异净删约 700 行以上；下一次 LOC 复审应重新跑全口径统计，而不是沿用下方表格。

## 统计口径

活跃 runtime 源码只统计：

- `core/src`
- `core/ui/src`
- `members/writer/backend/app`
- `members/writer/backend/writer_cli`
- `members/writer/frontend/src`
- `members/artist/backend/app`
- `members/artist/frontend/src`
- `scripts`
- 根入口 `writer.cmd`、`artist.cmd`、`lamtools.cmd`

排除：`node_modules`、`.git`、虚拟环境、`target`、`release`、`dist`、`.vite`、`.archives`、`tmp`、`.codex-runtime`、`.writer-artifacts`、`e2e/real-task-runs`、个人临时文件和 lockfile。行数为当前工作区物理行；非空行单独列出。

## 总体判断

当前项目已经完成一批正确减法：Writer TUI、Writer 前端事件 reducer、Artist 旧生命周期事件、Artist 旧 `core_adapter.py` 等已从主线删除。现在复杂度不再主要来自“旧 runtime 双主线”，而是来自 **Core 主线周边仍有太多重复翻译层**。

最核心结论：

```text
Core 已能作为唯一运行主线，但 Writer 还没有变薄。
Writer 仍在 member 内承担 LLM 适配、prompt 拼接、工具执行、事件投影、SSE 兼容、CLI 展示和验收策略。
下一轮减法应先删重复协议和兼容事件，再把通用执行能力沉到 Core。
目标不是让 Writer 成为独立 agent，而是还原为 Core 的一个 member pack。
```

当前活跃 runtime 源码为 **86,127 物理行 / 76,099 非空行 / 341 文件**。其中 Writer 后端 runtime 单独占 **40,809 行**，占全量 **47.4%**；Writer 前后端合计 **48,831 行**，占 **56.7%**。这解释了为什么“基础功能已经在 Core 实现”，但 member 仍然很重：Writer 不是只保留 Kit/prompt/工具/验收/UI，而是还保留了大量协议桥接和 fallback 主线。

新的目标口径：

```text
Core + Writer member 才是一个完整产品。
Core 承担 agent 基础能力和通用执行框架。
Writer member 只保留 Writer persona、prompt、专用工具声明、验收策略、产品 UI 和极薄 adapter。
凡是 Writer 内重复实现 Core 已有基础能力的代码，都视为还原失败。
```

## 行数总览

| 范围 | 文件数 | 物理行 | 非空行 | 占比 |
|---|---:|---:|---:|---:|
| Writer backend runtime | 133 | 40,809 | 35,890 | 47.4% |
| Artist backend runtime | 83 | 15,917 | 13,802 | 18.5% |
| Core UI src | 28 | 9,520 | 8,867 | 11.1% |
| Writer frontend src | 25 | 8,022 | 7,287 | 9.3% |
| Core backend src | 34 | 6,090 | 5,139 | 7.1% |
| Artist frontend src | 29 | 4,772 | 4,276 | 5.5% |
| Repo scripts + cmd | 9 | 997 | 838 | 1.2% |
| **合计** | **341** | **86,127** | **76,099** | **100%** |

辅助口径：

| 范围 | 文件数 | 物理行 | 非空行 |
|---|---:|---:|---:|
| 测试代码 | 120 | 35,479 | 29,531 |
| 活跃 prompt/profile 文本 | 11 | 160 | 143 |

语言分布：

| 类型 | 文件数 | 物理行 | 非空行 |
|---|---:|---:|---:|
| `.py` | 252 | 63,446 | 55,342 |
| `.vue` | 23 | 12,787 | 11,735 |
| `.ts` | 55 | 6,667 | 5,946 |
| `.css` | 4 | 2,860 | 2,749 |
| `.ps1` | 4 | 326 | 290 |
| `.cmd` | 3 | 41 | 37 |

## 最大文件信号

| 文件 | 物理行 | 非空行 | 声明/定义信号 | 分支信号 | 判断 |
|---|---:|---:|---:|---:|---|
| `members/writer/backend/app/core/writer/core_kernel_adapter.py` | 5,932 | 5,336 | 170 | 1,138 | Writer 最大复杂度源，混合 prompt、工具、事件、验收、fallback |
| `core/ui/src/components/ChatThread.vue` | 3,768 | 3,475 | 509 | 675 | 共享 UI 过深，承担 part 归一化、时间线、工具、审批展示 |
| `members/writer/frontend/src/views/CoreWorkbenchView.vue` | 2,618 | 2,404 | 393 | 455 | 页面同时管输入、队列、审批、snapshot、thinking、滚动 |
| `core/ui/src/styles/layout.css` | 2,488 | 2,417 | 0 | 12 | 共享布局样式过大，说明 UI shell/theme 规则仍集中在单一样式文件 |
| `members/writer/backend/app/services/writer_service.py` | 2,466 | 2,300 | 66 | 390 | 入口编排、transcript、app projection、SSE 兼容混合 |
| `members/writer/frontend/src/views/SettingsView.vue` | 2,164 | 2,016 | 242 | 191 | Provider/Model/Agent/Tool/Theme 全在一个页面 |
| `members/artist/backend/app/core/artist/core_kernel_adapter.py` | 2,011 | 1,741 | 48 | 332 | Artist 已单主线，但仍保留 legacy context/fallback 语义 |
| `members/writer/backend/writer_cli/__main__.py` | 1,892 | 1,674 | 74 | 444 | 用户 CLI 与开发/诊断/旧事件展示混在一起 |
| `members/writer/backend/app/core/writer/agents/architecture_agent.py` | 1,839 | 1,721 | 50 | 314 | 子代理业务闭环较厚，但仍应复用主线工具/权限/事件协议 |
| `core/src/lamtools_core/kernel/loop.py` | 1,622 | 1,502 | 43 | 229 | Core 主循环可靠，但承担 stream、compaction、approval、runtime part |
| `members/writer/backend/app/routers/session.py` | 1,513 | 1,319 | 65 | 184 | 会话 API 仍有 legacy alias 与旧入口压力 |
| `members/writer/backend/app/core/writer/completion_verifier.py` | 1,297 | 1,166 | 91 | 316 | Writer 验收必要但过大，应深模块化 |
| `members/artist/backend/app/services/generate_service.py` | 1,243 | 1,107 | 31 | 222 | 图像执行、fallback、状态更新耦合 |
| `members/artist/backend/app/services/artist_service.py` | 1,241 | 1,127 | 31 | 262 | 入口编排、生成、事件桥接仍偏厚 |
| `members/artist/backend/app/cli.py` | 1,213 | 1,073 | 51 | 208 | CLI 里有 mock、fixture、session、VLM、image 多类职责 |

说明：声明/定义信号对 Vue/TS 会包含较多 `const`，不是严格函数数量。分支信号按 `if/for/while/try/catch/switch/case/&&/||` 等文本匹配估算，只用于识别复杂度集中区，不等同于严格圈复杂度。

## Writer 功能分类表

| 功能区 | 当前代码 | 应保留位置 | 复杂度判断 | 处理方向 |
|---|---|---|---|---|
| Writer persona / 固定 prompt | `prompts/writer/**`、`core/persona.py` | Writer | 可靠 | 保留，改成 Core prompt fragment provider 输入 |
| 项目规则 / AGENTS 装载 | `project_instructions.py`、`prompt_files.py` | Writer + Core prompt 协议 | 存疑 | 规则装载留 Writer，排序/预算沉 Core |
| LLM 配置与 provider profile | `utils/llm_client.py`、`llm_adapter_profiles.py`、`llm_adapters/*.jsonc` | Core LLM adapter + Writer 配置读取 | 重复 | profile/转换沉 Core，Writer 只管本地配置 |
| Writer Kit / agent loop 适配 | `core_kernel_adapter.py` | Writer Kit | 过重 | 保留 Kit 外壳，prompt/tool/event/LLM 通用部分拆走 |
| 工具规格和执行 | `tool_specs.py`、`tool_executor.py`、`core_kernel_adapter.py` | Core tool registry + Writer 专用工具 | 重复 | workspace/shell/git/web 沉 Core，Writer 特有验收/计划保留 |
| 权限与范围 | `permission.py`、`scope_guard.py`、`app_server/security.py` | Core 权限词汇 + Writer 策略 | 重复 | Core 统一权限接口，Writer 只提供策略参数 |
| App Server 协议 | `app_server/**` | Writer，未来双成员复用再抽 Core | 可靠到存疑 | 保留后端 snapshot 主线，压缩旧 runtime/SSE 桥 |
| Runtime event / Core event 桥 | `events.py`、`core_adapter.py`、`runtime_bridge.py` | 单一 event adapter | 债务 | 选一个 canonical run item event，删多余翻译 |
| Transcript / snapshot | `transcript_service.py`、`app_server/snapshot.py`、前端 `runtime/**` | 后端权威 snapshot | 存疑 | UI 只认 snapshot；transcript 降为审计或由 snapshot 派生 |
| CLI | `writer_cli/__main__.py` | Writer 产品入口 + dev 子入口 | 过重 | 普通命令和开发命令分层，旧事件展示删除 |
| GUI Workbench | `CoreWorkbenchView.vue`、`appServer/store.ts` | Writer UI | 过重 | 页面只接 selectors 和 operation adapter |
| Settings | `SettingsView.vue` | Writer UI panels + Core provider catalog | 过重 | 拆内部 panels，不新增外部路由 |
| 验收 / 自评 | `completion_verifier.py`、`self_review.py` | Writer | 必要但重 | 保留，按输入、判定、修复触发、证据拆深模块 |
| 子代理 | `agent_runtime.py`、`agents/architecture_agent.py` | Writer，Core 只管 agent 协议 | 存疑 | 不扩功能，先复用同一 ToolRegistry/权限上下文 |
| Novel 能力 | `core/writer/novel/**` | Writer | 产品专用 | 不上抽；只删无验证 fallback |

## 架构复杂度分析

### 1. Core 主线可靠，但 Core 还不够深

`CoreLoopKernel + Kit` 是正确主线，但 `core/src/lamtools_core/kernel/loop.py` 已经到 1,622 行。它不仅跑循环，还处理：

- stream fallback
- tool argument 安全摘要
- model retry 展示
- context compaction 和 fallback summary
- approval request 文案
- 多种 `runtime.part` 展示事件

这些能力有价值，但不应都暴露在主循环文件里。理想形态是 Kernel 外部 interface 仍只有 `run(turn_input)`，内部拆成 `ModelCaller`、`ToolRunner`、`ApprovalGate`、`ContextCompactor`、`RuntimeFactEmitter`。这是深模块化，不是新增业务抽象。

### 2. Writer 仍在重复解释协议

证据：

- `members/writer/backend/app/core/writer/core_adapter.py` 仍把 Writer SSE payload 映射回 CoreEvent。
- `events.py` 通过 `core_adapter.py` 给 Writer 事件加 `core_event` side channel。
- `writer_service.py` 同时发布 RuntimeEvent、落 transcript、调用 `persist_runtime_event_as_app_events()` 写 app projection，并保留 `_runtime_event_to_sse()`。
- `TaskManager` 仍作为 Writer SSE pub/sub 存在，`writer_service.py` 明确写着 “existing SSE subscribers”。
- Writer CLI 仍处理 `writer_git_snapshot`、`writer_git_branch`、`writer_git_checkpoint`、`writer_git_merge` 旧产品事件。

这说明 Writer 的事件路径还不是一条：

```text
Core fact -> canonical run item event -> server snapshot -> frontend selectors
```

而是仍然存在：

```text
CoreEvent
WriterRuntimeEvent
Writer SSE event
App Server event
Transcript block
ThreadSnapshot
CLI event renderer
Frontend selectors
```

这是当前最高价值减法点。

### 3. Writer 后端偏离“只保留 Kit/prompt/工具/验收”

Writer 后端 runtime 40,809 行，比 Core backend + Core UI 合计 15,610 行还多 2.6 倍。核心原因不是 Writer 业务本身必然这么大，而是：

- LLM profile/stream/tool call 转换重复在 Writer；
- prompt/context 拼接大量写在 Kit；
- 工具 spec、dispatch、权限、MCP、agent dispatch 多处并行；
- service 层仍承担 runtime event 到 app snapshot、transcript、SSE 的多重投影；
- CLI 仍承担用户命令、开发命令、旧事件渲染。

### 4. Artist 已更接近单主线，但还有旧形状残留

Artist 旧生命周期事件和旧 `core_adapter.py` 已删除，这是正确进展。剩余复杂度主要在：

- Artist 仍使用 SSE + `TaskManager` 作为实时传输主形状；
- `core_kernel_adapter.py` 中仍有 legacy visual context、legacy follow-up、fallback 语义；
- `frontend/src/api/core.ts` 仍写着 Artist schema fallback；
- `services/settings_service.py` 仍迁移旧 `default_optimize_provider_id`；
- `image_prep.py` 保留 `legacy_action_dict()`；
- `generate_service.py` 中图像 fallback、状态更新、事件推送耦合。

Artist 目前只有 Writer 稳定性确认不足，因此下一轮不应把 Artist 当成熟复用源，而应把它作为“验证 Core 通用能力是否足够”的第二适配器。

### 5. UI 复杂度来自状态 owner 不清

`ChatThread.vue`、Writer Workbench、SettingsView 都是典型浅 interface 问题：外部看似一个组件，内部知道太多协议和状态。

当前应坚持：

```text
后端 snapshot 是事实
frontend store 只 hydrate
selectors 是 UI 唯一输入
ChatThread 只渲染 canonical parts
Workbench 只调用 operation adapter
```

前端 reducer 已删，方向正确；剩余是把 selector/part normalization 从大组件中挪出去。

## 最优路径复核

建议主链路固定为：

```text
CLI / GUI
  -> Operation adapter
  -> Member App Server / member backend action
  -> CoreLoopKernel
  -> Core LLM adapter / Core ToolRegistry / Core StateStore / Core EventSink
  -> Member Kit: persona, product tools, acceptance, UI labels
  -> canonical run item event
  -> server snapshot
  -> frontend selectors
  -> product UI
```

这条路径下：

- Core 不认 Writer/Artist。
- Member 不再复制 runtime。
- CLI/GUI 不解释底层 event。
- Transcript 不再作为 UI 的第二事实源。
- SSE 如果保留，只是 Artist/旧接口的 transport，不是 Writer 主事实。

## Core 代码 vs fallback 策略

fallback 分两类处理：

| 类型 | 例子 | 判断 | 策略 |
|---|---|---|---|
| 外部系统可靠性 fallback | 模型 stream 空响应、本地 compaction fallback、图像 vision fallback、中文分词 heuristic fallback | 可保留 | 必须有显式原因、指标和测试，不作为第二主线 |
| 历史兼容 fallback | Writer SSE -> CoreEvent、`writer_git_*`、legacy alias、Settings 旧 local key、`Kept for API compatibility`、旧 runtime projection | 债务 | 无用户时应删，或迁移一次后删除 |

Core 里的 fallback 可以存在，但必须是“失败降级策略”；member 里的 fallback 如果只是为了旧接口、旧事件、旧字段继续运行，应进入删除清单。

## 应沉到 Core 的能力

| 能力 | 当前重复位置 | Core 目标形态 | 优先级 |
|---|---|---|---|
| LLM payload/response/stream/tool call/thinking/usage 转换 | Core、Writer、Artist | Core `LLMAdapter` 唯一转换层 | P0 |
| Provider adapter profile | Writer `llm_adapters`、Artist provider 语义 | Core provider/profile registry，member 只读配置 | P0 |
| Prompt fragment 排序和预算 | Core 有协议，Writer 手写拼接，Artist 单独 assembler | Core prompt assembler + member providers | P1 |
| Workspace read/write/search | Writer 工具内嵌 | Core optional workspace toolkit | P1 |
| Shell/Git/Web 通用工具 | Writer 内嵌，Artist 部分重复 | Core optional toolkits + member permission policy | P1 |
| Permission gate | Core tier、Writer scope/security | Core 统一 gate interface，member 提供策略 | P1 |
| Runtime state store / event sink | Writer/Artist 各自 in-memory/store/sink | Core in-memory + collecting/live sink | P2 |
| Canonical run item event | CoreEvent、WriterRuntimeEvent、AppEvent 多层 | Core 协议骨架 + member adapter | P0 |
| Operation catalog | CLI/GUI/文档各自维护 | Core operation metadata，member 注册公开操作 | P1 |
| UI part normalization | ChatThread 内部、Writer runtime 投影 | Core UI helper + snapshot selectors | P2 |

不应沉到 Core：

- Writer persona、执行纪律、reply contract。
- Writer completion verifier、architecture handoff、commit review、Novel 体系。
- Artist 图像生成、视觉上下文、视觉验收、谱系和 contact sheet。
- 产品 UI 文案、主题和业务设置。

## 死代码 / 重复 / 历史兼容候选

这些不是立即无脑删除清单；它们是下一轮删减前应逐个 `rg + targeted test` 核实的候选。

| 候选 | 证据 | 债务类型 | 建议 |
|---|---|---|---|
| `members/writer/backend/app/core/writer/core_adapter.py` | Writer SSE payload 映射回 CoreEvent | 方向反了 | P0 核实引用后删除，保留 canonical event adapter |
| Writer `TaskManager` SSE | `writer_service.py` 仍服务 existing SSE subscribers | 旧 transport 主线残留 | P0 确认 CLI/GUI 不依赖后删除或降级 dev-only |
| `writer_git_*` 事件 | CLI、events、git_context、session router 仍处理 | 旧事件名残留 | P0 转成 app event / artifact event |
| `writer_service.py` app projection 内嵌函数 | `_persist_app_projection()`、`_publish_app_projection()` 嵌套在大流程 | 投影职责混入 service | P0 移到单一 projection module，随后删旧 SSE 分支 |
| `writer_service.py` `_runtime_event_to_sse()` | RuntimeEvent 再转 SSE | 旧展示协议 | P0 删除或 dev-only |
| `members/writer/backend/app/routers/session.py` legacy aliases | `_normalize_phase()` 中 legacy alias | 旧 API 兼容 | P1 无用户可直接迁移/删 |
| `scope_guard.py` compatibility methods | 注释写明 API compatibility | 旧接口兼容 | P1 如果只给 ToolExecutor 用，改调用方后删 |
| `llm_config_service.py` legacy default model fallback | 注释写明 legacy fallback | 旧配置迁移 | P1 做一次 DB 迁移后删 |
| Writer `SettingsView.vue` legacy local key | `legacyUiSystemKey` | 旧 UI 设置迁移 | P2 做一次版本迁移或直接删 |
| Artist `frontend/src/api/core.ts` fallback event mapper | 注释写明 unknown schema fallback | schema 未收敛 | P1 用 Core display schema 替换 |
| Artist `TaskManager` SSE | 后端/前端仍以 SSE 为实时形状 | 传输主线重复 | P1 Artist 重构时对齐 app-server/snapshot |
| Artist legacy visual context helpers | `core_kernel_adapter.py` 多处 legacy 注释 | 历史上下文形状 | P1 稳定后改成 typed visual context |
| Artist `settings_service.py` legacy provider setting | `default_optimize_provider_id` 迁移 | 旧设置迁移 | P2 做一次迁移后删 |
| Artist `image_prep.py legacy_action_dict()` | 显式 legacy 函数 | 旧 action 形状 | P2 核实无引用后删 |

## 优先删除清单

### P0：先删重复协议和旧传输

1. 删除 Writer SSE -> CoreEvent 反向适配：目标是 Core fact -> canonical event，不再从 Writer 旧事件补 Core metadata。
2. 删除或降级 Writer `TaskManager` SSE：App Server snapshot 已是主线，旧 SSE 不能继续作为产品显示路径。
3. 合并 `writer_git_*` 到 canonical artifact/git event：CLI 不再硬编码旧事件名。
4. 把 `writer_service.py` 的 runtime -> app projection 从大流程移出，并确认只剩一个 snapshot 事实源。
5. 为 canonical run item event 加 contract test：防止删兼容层后又把协议散回 UI。

### P1：把通用 agent 能力沉到 Core

1. Core LLM adapter 接管 provider profile、thinking、tool call、usage、stream chunk 转换。
2. Core prompt assembler 接管 fragment 排序、预算和截断；Writer/Artist 只提供 providers。
3. Core ToolRegistry + toolkits 接管 workspace/shell/git/web；Writer 只保留产品工具和验收工具。
4. Core PermissionGate 接管权限 interface；Writer/Artist 只传策略。
5. Operation catalog 固化 CLI/GUI/HTTP 入口，普通命令和 dev 命令分层。

### P2：大文件深模块化

1. `ChatThread.vue` 只保留渲染，part normalization、timeline grouping、tool/decision rendering helper 外移。
2. Writer `CoreWorkbenchView.vue` 只接 selectors 和 operation adapter，队列/审批/thinking 进入小模块。
3. Writer `SettingsView.vue` 拆 Provider/Model/Agent/Tool/Theme 内部 panel。
4. `CoreLoopKernel` 内部拆 `ModelCaller`、`ToolRunner`、`ApprovalGate`、`ContextCompactor`、`RuntimeFactEmitter`，外部 interface 不变。
5. Artist 在 Writer 稳定后对齐 app-server/snapshot，删除 SSE schema fallback。

## 激进行数目标

当前：**86k runtime 物理行**。

成熟本地 agent + 两个 member 的合理目标不是越少越好，而是核心 interface 深、member 薄。现在采用更激进的产品口径：**Writer 不再作为独立 agent runtime 计量，而是 Core 的一个 member pack；Core + Writer member 才是 Writer 产品**。

`6,000` 不是宽松目标，而是不可突破的硬上限。它的意义不是证明“6,000 一定最优”，而是防止主次颠倒：一旦 Writer member 超过 6,000 行，通常说明基础 agent 能力、兼容层、投影层或通用 UI 仍留在 member 内，没有回到 Core。

| 范围 | 当前行数 | 激进目标 | 变化 |
|---|---:|---:|---:|
| Core backend src | 6.1k | 10k-14k | 可增加，承接 LLM/tool/permission/event/session/snapshot 等通用能力 |
| Core UI src | 9.5k | 6k-8k | 保留共享 UI，但删除重复展示兼容 |
| Writer backend runtime | 40.8k | <=3k | 硬上限，只保留 member pack 和 adapter |
| Writer frontend src | 8.0k | <=2.5k | 硬上限，只保留 Writer 产品 UI |
| Writer prompt/config/入口薄壳 | 约数百行 | <=500 | 硬上限，只保留 prompt/profile 壳和命令薄入口 |
| **Writer runtime 合计** | **48.8k** | **<=6k** | **不可突破；超过即判定 Core/Member 职责未还原** |
| Artist backend runtime | 15.9k | 6k-8k | 后续按同一 member pack 口径重构 |
| Artist frontend src | 4.8k | 2.5k-3.5k | 删除产品内重复框架和兼容展示 |
| scripts + cmd | 1.0k | <=1k | 持平 |
| **总计** | **86.1k** | **38k-48k** | **减少 44%-56%，同时 Core 占比上升** |

更激进的单点目标：

- Writer runtime 总量必须进入 **6,000 行以内**。
- Writer 专属业务核心必须进入 **1,500 行以内**。
- Writer backend 不再拥有 LLM/provider/tool/event/session/snapshot 的基础实现，只能调用 Core interface。
- 如果为保留 Writer 代码而让 Core 变薄、Writer 变厚，判定为主次颠倒。
- 如果某段代码不是 Writer persona、prompt、专用工具声明、验收、产品 UI 或极薄 adapter，就默认不应留在 Writer。
- 单文件超过 1,500 行必须有明确深模块理由；否则进入拆分清单。
- UI 单组件超过 1,200 行必须拆成渲染层 + helper/selectors。
- 旧兼容 fallback 不再作为“有用户风险”保留，因为当前没有用户。

## 后续重构建议

推荐执行顺序：

1. **事件收敛先行**：删 Writer `core_adapter.py` 方向错误的映射，压缩 `events.py` 和 `writer_service.py` 的旧 SSE 分支。
2. **LLM adapter 下沉**：先处理 provider profile/tool call/thinking/usage 这些最容易双写的转换。
3. **ToolRegistry 下沉**：把 workspace/shell/git/web 变成 Core optional toolkits，让 WriterKit 退出工具 dispatch 细节。
4. **Prompt provider 化**：把 WriterKit 中的 prompt 拼接变成可测 fragment providers。
5. **UI 最后拆**：等 event/snapshot 稳定后再拆 ChatThread/Workbench，否则会被协议变化返工。
6. **Artist 作为第二适配器验证 Core**：不要先追求 Artist 产品完美，先用它证明 Core 通用能力确实能复用。

## 遗漏角度提醒

下一轮动手前还要补这几类核实：

- DB 迁移：删除 legacy 字段/事件前，确认默认数据库是否需要一次性清理脚本。
- CLI 脚本：确认 README、docs、测试和 Windows cmd 入口没有继续引用旧命令。
- GUI 行为：删除 SSE 或旧 projection 后，至少验证发送、刷新、运行中输入、审批、最终回复、会话重命名。
- 打包路径：Electron/Tauri/PyInstaller/pywebview 仍需单独裁决，不要让桌面封装继续并行。
- 文档维护：旧计划文档保留历史，但必须加当前状态标注，避免下轮把旧方案当事实。
- 安全策略：工具下沉 Core 时，不能把 Writer 的路径权限和命令审批弱化成通用默认放行。

## 结论

当前不是“Core 不够用”，而是 **Core 已经能跑，但通用能力还没有真正成为唯一实现**。Writer 代码多的主要原因是历史协议、fallback、SSE、projection、CLI 展示、工具 dispatch 仍在 member 内反复实现。

下一轮最有效的减法不是先拆 UI，也不是继续抽象新框架，而是：

```text
删旧事件/旧传输/旧投影
统一 LLM 和工具转换
让 WriterKit 只保留业务注入
让 Core 承担通用 agent 执行框架
```
