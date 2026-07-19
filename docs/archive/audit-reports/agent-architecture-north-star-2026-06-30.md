# LamTools Agent Architecture North Star

日期：2026-06-30

目的：把后续精简的判断标准从“少一点代码”提升为“结构一眼可懂、主次明确、毫无冗余”。最终目标不是让 Writer/Artist 各自成为一套 agent，而是让 **Core 成为可直接使用、可改造的 agent 基座**，Writer/Artist 成为领域特化 member 示例。

执行设计：`docs/core-member-architecture-refactor-design-2026-06-30.md`。

维护标注（2026-07-02 Step 12 后）：

- 本文是 North Star 和删减原则，保留有效；具体“当前仍存在”的旧链路请以执行设计 Step 12 记录为准。
- 已落地：Core 不再出现 Writer/Artist 产品名；新 member scaffold 生成 thin member package；Writer/Artist 运行事实主线已收敛到 Core loop / Core event projection / product adapter；旧 Writer TaskManager/SSE、旧 Writer SSE -> CoreEvent 反向适配、旧 Artist TaskManager/SessionEventHub/LamEvent 生产路径已删除。
- 仍需谨慎验收：Writer GUI 真实模型 turn、真实 approval continuation、历史文档中旧图示的阅读上下文。

## 1. 最终判断

当前方向必须从：

```text
Writer 是一个很大的产品，里面复用了一些 Core 能力
```

改为：

```text
Core 是完整 agent 基座
Core + Writer member = Writer 产品
Core + Artist member = Artist 产品
```

这意味着：

- Core 必须可以直接作为基础 agent 使用。
- 新工程师只看 Core，就能理解一个 agent 如何运行、调用模型、执行工具、保存状态、发事件、处理权限和恢复会话。
- 新工程师只看 Writer/Artist，就能看出它们只是领域特化：persona、prompt、领域工具声明、验收策略、产品 UI。
- Writer/Artist 中任何基础 agent 能力重复实现，都是结构失败，不是“业务复杂”。

## 2. 成熟方案参照

成熟 agent 框架的共同点不是“把每个产品做厚”，而是把运行骨架集中到平台层。

| 参照 | 对 LamTools 的启发 |
|---|---|
| OpenAI Agents SDK 将 Agent 定义为 instructions、tools、handoffs、guardrails、structured outputs 等配置，并由 Runner 管理 turns、tools、sessions 等运行事务（官方文档：[Agents](https://openai.github.io/openai-agents-python/agents/)） | Core 应拥有 runner/kernel、model、tool、session、event、guardrail、handoff/sub-agent 骨架；member 只提供配置和领域逻辑 |
| OpenAI Agents SDK 的 tools 是 agent 行动能力目录，包含本地/runtime 工具、函数工具、agents as tools 等（官方文档：[Tools](https://openai.github.io/openai-agents-python/tools/)） | workspace/shell/git/web/MCP 等通用工具不应在 Writer/Artist 各写一套，应成为 Core toolkits |
| OpenAI Agents SDK 的 session 让 runner 自动维护多轮历史，避免每个应用手动管理 conversation state（官方文档：[Sessions](https://openai.github.io/openai-agents-python/sessions/)） | transcript/session/snapshot/event store 应是 Core 协议和骨架，member 只提供 DB adapter 或产品展示 adapter |
| Claude Code 的 subagents 是独立上下文、特定 prompt、特定工具权限的专门助手（官方文档：[Subagents](https://code.claude.com/docs/en/sub-agents)） | sub-agent 是 Core 能力；Writer/Artist 只声明角色、工具范围和验收，不复制 agent runtime |
| Claude Code hooks 围绕 session、turn、tool call、permission、compaction 等生命周期点触发（官方文档：[Hooks](https://code.claude.com/docs/en/hooks)） | Core 应拥有生命周期事件和 hook/guardrail 插槽；member 不应通过旧 SSE/projection 自己模拟生命周期 |
| Claude Code 通过 MCP 接入外部工具和数据源（官方文档：[MCP](https://code.claude.com/docs/en/mcp)） | MCP registry/client/tool adapter 是 Core optional capability；Writer/Artist 只能选择启用和配置 |

## 3. 当前结构问题

当前代码已经有 Core 主线，但还没有形成“Core 是唯一实现源”的效果。证据：

| 问题 | 当前证据 | 判断 |
|---|---|---|
| Writer 后端仍是最大运行体 | `members/writer/backend/app` + `writer_cli` 为 40,809 行；其中 `members/writer/backend/app/core` 单独 26,238 行 | Writer 仍像独立 agent，不像 member pack |
| Writer 前端仍承担通用状态展示 | `members/writer/frontend/src/views` 4,782 行，`CoreWorkbenchView.vue` 和 `SettingsView.vue` 仍承载 operation、queue、approval、model、scroll、settings 多类职责 | UI 还没有回到“产品壳 + shared UI” |
| Core 已有协议但 Writer 重复实现 | Core 有 `llm`、`tool`、`prompt`、`mem`、`session`、`event`、`agent`、`kernel`；Writer 仍有 `llm_client.py`、`llm_adapter_profiles.py`、`tool_executor.py`、`core_kernel_adapter.py`、`runtime_bridge.py` | Core 不是唯一实现源 |
| 事件事实源过多 | Writer 同时存在 CoreEvent、WriterRuntimeEvent、Writer SSE、App Server event、transcript block、thread snapshot、CLI formatter | 运行、展示、持久化混在一起 |
| 历史兼容仍给结构定形 | `core_adapter.py`、`TaskManager` SSE、`writer_git_*`、`turn_parser.py` 旧 key、`app_server/cleanup.py` 历史修复 | 旧系统还在定义当前代码形状 |
| Artist 也不是纯 member 示例 | Artist backend 15,917 行，`core/artist`、`services`、SSE、fallback 仍较厚 | 还不能作为“如何改造 Core”的清爽示例 |

## 4. 不可妥协目标

### 4.1 Core 目标

Core 必须成为一个可以直接使用的 agent 基座：

```text
core/src/lamtools_core/
  agent/ or app/       # 创建可运行 agent app 的极小入口
  kernel/              # loop/runner/state/decision/verification skeleton
  llm/                 # provider/profile/payload/stream/tool-call/usage
  tool/                # registry/executor/toolkits/permission context
  prompt/              # fragment providers/order/budget/truncation
  session/             # conversation/session store
  event/               # canonical run item events
  snapshot/            # snapshot reducer/projection skeleton
  approval/            # ask_user/permission/interrupt/resume
  artifact/            # file/diff/media/tool artifact protocol
  mem/                 # recall/store/provenance/budget
  mcp/                 # optional MCP registry/client
  ui-protocol/         # frontend consumes canonical snapshot/parts
```

Core 的公开 interface 应该小到可以在 README 中用一屏说明：

```text
AgentSpec + MemberKit + ToolRegistry + ModelProvider + SessionStore + EventSink
run(turn_input) -> RunResult / Snapshot stream
```

如果一个新成员需要先理解 Writer 的 service、SSE、projection、CLI formatter 才能接入 Core，说明 Core 还不够深。

### 4.2 Member 目标

Writer/Artist 必须是领域特化包：

```text
members/writer/
  member.toml or manifest.py
  prompts/
  kit.py
  tools.py
  verification.py
  agents/
  backend_adapter.py
  frontend/
```

```text
members/artist/
  member.toml or manifest.py
  prompts/
  kit.py
  tools.py
  visual_context.py
  verification.py
  backend_adapter.py
  frontend/
```

member 可以有领域逻辑，但不能拥有基础 agent runtime。

## 5. 6000 行硬上限

`6,000` 不一定是理论最优数字，但它是防止主次颠倒的硬上限。

| 范围 | 硬上限 | 含义 |
|---|---:|---|
| Writer backend runtime | <=3,000 | 只保留 member pack、领域 adapter、Writer 验收 |
| Writer frontend src | <=2,500 | 只保留产品界面；通用 shell、part normalization、state model 回 Core/shared UI |
| Writer prompt/config/入口薄壳 | <=500 | prompt/config/CLI 入口只能是薄壳 |
| Writer runtime 合计 | <=6,000 | 不可突破；超过即判定 Core/Member 职责未还原 |
| Writer 专属业务核心 | <=1,500 | persona、prompt、专用工具声明、验收、sub-agent 定义、UI 文案 |

这个上限的价值在于强迫做正确减法：

- 不能靠“Writer 功能多”解释 40k 行。
- 不能把基础能力留在 Writer，然后说 Core 已经有协议。
- 不能为了短期稳定继续保留旧 SSE、旧 projection、旧 parser。
- 不能让测试继续保护旧路径。

## 6. 留在 Member 的内容

### Writer

| 可留内容 | 不可留内容 |
|---|---|
| Writer persona、写作/代码协作 prompt、reply contract | LLM provider/profile/stream/tool-call 转换 |
| Writer 专用工具声明和少量领域 handler | workspace/shell/git/web/MCP 通用工具实现 |
| Writer completion verifier、自评、失败修复策略 | 通用 VerificationResult/Event/Artifact 协议 |
| Writer sub-agent 角色定义 | sub-agent runtime、权限、上下文隔离实现 |
| Writer 产品 UI 文案、设置页领域项 | 通用 session/sidebar/workbench/part normalization |
| Writer DB adapter / product route adapter | runtime、event、snapshot、projection 主实现 |

### Artist

| 可留内容 | 不可留内容 |
|---|---|
| 图像生成 persona、视觉上下文、风格/参考图策略 | 通用 LLM/tool/session/event runtime |
| image generation provider 领域 adapter | provider/profile/usage 基础转换 |
| visual verification、contact sheet、lineage 领域语义 | 通用 artifact/media 协议 |
| Artist 产品 UI | 通用 queue/session/snapshot/display shell |

## 7. Core 必须吸收的能力

| 能力 | 当前问题 | Core 目标 |
|---|---|---|
| LLM adapter/profile | Writer/Artist 仍可能各自解析 payload、stream、usage、thinking | Core 唯一转换层 |
| ToolRegistry + toolkits | Writer 内有文件/Git/Web/MCP 工具实现 | Core optional toolkits，member 只注册启用和领域 handler |
| Permission / approval | Core 有 tier，Writer 仍有 scope/security/app request 投影 | Core ApprovalGate + interrupt/resume |
| Prompt assembly | WriterKit 仍拼大段 prompt | Core fragment ordering/budget/truncation |
| Session / state | Writer DB session、App thread、transcript、snapshot 词汇重叠 | Core session store + snapshot skeleton |
| Event / display | 多事件族并存 | Core canonical RunItemEvent / DisplayPart |
| Artifact | tool artifact、git diff、media 形态分散 | Core artifact protocol |
| Sub-agent | Writer 有 AgentRuntime 和 architecture agent runtime | Core sub-agent runner，member 声明角色 |
| MCP | Writer 内部 `core/mcp` | Core optional MCP capability |
| UI protocol | ChatThread 识别旧 runtime/transcript | Core UI 只渲染 canonical snapshot parts |

## 8. 删除优先级

P0 不是“先做容易的”，而是先删最破坏结构美感的：

1. 删除 Writer SSE -> CoreEvent 反向适配。
2. 下线 Writer `TaskManager` SSE 产品链路。
3. 合并并删除 `writer_git_*`、`writer_part_updated` 等旧事件族。
4. 把 `writer_service.py` 拆到 Core runner + thin member adapter，不保留多投影 service。
5. 把 LLM/profile/tool-call/usage/stream 彻底收进 Core。
6. 把 workspace/shell/git/web/MCP 工具收进 Core optional toolkits。
7. 让前端只认 Core snapshot/part protocol。
8. 删除保护旧路径的测试，改为保护 Core contract 和 member 示例。

## 9. 精美结构验收

一个工程师看一眼项目后，应该能得到这些结论：

| 验收项 | 通过标准 |
|---|---|
| 目录一眼可读 | `core/` 是 agent platform；`members/*` 是领域包 |
| Core 不认产品名 | `core/src/lamtools_core` 中没有 Writer/Artist 业务名、业务分支、业务 prompt |
| member 不认 runtime 细节 | Writer/Artist 不实现 LLM stream、event projection、session store、tool runtime |
| 只有一条运行主线 | `turn -> Core runner -> canonical events -> snapshot -> UI` |
| 只有一套事件语言 | 没有 WriterRuntimeEvent、Writer SSE、CoreEvent side channel、app event 多层互转 |
| 只有一个状态事实源 | UI 只读 snapshot/selectors；transcript 是审计或由 snapshot 派生 |
| CLI/GUI 同源 | CLI 和 GUI 都调用同一个 operation catalog / app protocol |
| 测试保护新结构 | 测试验证 Core contract、member fixture、end-to-end flow，不保护旧兼容层 |
| 新 member 容易改造 | 新成员只需要 manifest、prompt、kit、tools、verification、UI adapter |
| 行数符合主次 | Writer runtime <=6,000；业务核心 <=1,500 |

## 10. 下一轮执行判断

后续任何改动都必须回答三个问题：

1. 这段代码如果留在 Writer/Artist，会不会让 member 看起来像独立 agent runtime？
2. 这段代码如果沉到 Core，会不会让新 member 更容易创建？
3. 这段代码如果删除，复杂度会消失，还是会在多个调用点重新出现？

执行策略：

- 复杂度消失：删除。
- 复杂度会在 Writer/Artist/新成员重复出现：沉 Core。
- 复杂度只服务领域语义：留 member，但必须小而清晰。
- 复杂度只服务历史兼容：迁移一次后删除。

## 结论

真正的目标不是“Writer 从 48k 压到 6k”，而是：

```text
Core 成为一个漂亮、稳定、可直接使用的 agent 基座。
Writer 和 Artist 成为两个清爽的改造示例。
任何重复 runtime、重复协议、重复 projection、重复工具实现都不允许继续存在。
```

当这个目标达成时，工程师看到的不是“一个大项目被拆成几个目录”，而是一个清楚的产品结构：

```text
Core = agent 的通用机器
Member = 领域化的薄配置、薄策略、薄 UI
Product = Core + Member
```
