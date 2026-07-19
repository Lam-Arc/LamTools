# Core / Member 架构重构执行计划

日期：2026-07-01

目标文档：[Core / Member 架构还原设计方案](core-member-architecture-refactor-design-2026-06-30.md)

当前起点：设计文档已记录到 `9.87`。后续执行不再随机删除小块，而是按本计划推进，每一步完成后都要把执行记录追加回目标设计文档。

## 1. 成熟方案对照

本计划采用的外部成熟形态：

- OpenAI Agents SDK：`Agent + Runner` 管 turns、tools、guardrails、handoffs、sessions；底层可用 Responses API，但运行编排应集中在 runtime 层。
- OpenAI Results / state：审批 interruption、可恢复 run state、streaming result 都属于运行层事实，不应散落到产品层。
- Claude Code SDK：内置 tools、hooks、subagents、MCP、permissions、sessions 属于 agent 基座能力；项目只配置权限和专用上下文。
- Claude Code subagents：子 agent 有独立 prompt、工具访问和权限，适合作为 Core 的通用能力，不应由单个 member 自行复制。

映射到 LamTools：

```text
Core = turn loop / operation / event / snapshot / provider / tool / permission / memory / sub-agent
Member = persona / prompt fragments / domain tools / verification / labels / product UI
Product = Core + Member adapter
```

## 2. 执行约束

1. 每个切片都先核实现状和引用，再改代码。
2. 旧路径只能在确认无生产入边或已有新主线替代后删除。
3. 每个切片必须有 targeted verification，不能只做静态删除。
4. 不覆盖当前工作区已有未提交改动；如需触碰同文件，先核对 diff。
5. 每个切片完成后追加到设计文档的执行记录，格式见本文第 5 节。
6. 行数下降不是唯一目标；必须能说明复杂度是消失、下沉到 Core，还是保留为领域能力。

## 3. 当前基线

截至 2026-07-01，本计划从以下状态继续：

- Writer 旧 `services/task_manager.py`：已删除。
- Writer 旧 `core/writer/core_adapter.py`：已删除。
- Writer 私有 `services/runtime_fact_projection.py`：已删除。
- Writer 私有 `services/runtime_fact_helpers.py`：已删除。
- Writer 前端 `runtime/transcript.ts`：仍存在，并被 `types/index.ts` 导出。
- Writer provider/profile：`utils/llm_client.py`、`utils/llm_adapter_profiles.py` 仍存在，并被 `core_kernel_adapter.py`、`routers/config.py` 使用。
- Artist `services/task_manager.py`：仍存在，并被 Artist router/service/executor 主线使用。
- `AgentApp`、`MemberKit`、`OperationCatalog`：当前未形成目标接口。

当前行数口径：

| 范围 | 文件数 | 行数 |
|---|---:|---:|
| Core `core/src` | 38 | 6,354 |
| Writer backend + CLI | 107 | 27,230 |
| Writer frontend src | 23 | 7,169 |
| Writer runtime 合计 | 130 | 34,399 |

当前工作区已有未提交改动，执行时不得误覆盖：

- `core/src/lamtools_core/kernel/loop.py`
- `core/src/lamtools_core/sse/__init__.py`
- `members/writer/frontend/src/appServer/store.ts`
- `members/writer/frontend/src/components/MarkdownRenderer.vue`
- `members/writer/frontend/src/views/CoreWorkbenchView.vue`
- `.archives/writer-clean-test-20260622-162954/repo/.writer-artifacts/writer_owned_subagent_site_20260620_210751`
- `resume-photo.jpg`
- `resume.html`
- `resume.md`
- `resume.pdf`

## 4. 分步执行计划

### Step 1：基线冻结

目标：固定当前事实，避免后续把历史文档、旧扫描结果和当前代码混在一起。

动作：

1. 扫描旧事件、旧 SSE、旧 provider parser、旧 transcript UI、Artist TaskManager。
2. 固定 Writer/Core 行数口径。
3. 记录当前未提交改动，避免误覆盖。
4. 将基线写回设计文档。

验收：

- `git status --short`
- `rg` 旧路径扫描只统计当前生产代码，不把历史 docs 当成当前事实。
- 行数口径已记录。

### Step 2：Core Contract 最小补齐

目标：补上目标架构的最小接口，不先大改业务。

动作：

1. 新增或整理 `AgentSpec`、`MemberKit`、`AgentApp`、`OperationCatalog` 的最小 contract。
2. 用 minimal member fixture 证明 Core 可独立装配。
3. Core contract 不能出现 Writer/Artist 产品名。

验收：

- Core contract tests 通过。
- `rg -n 'Writer|Artist|LamWriter|LamArtist' core/src/lamtools_core` 不出现业务分支。

### Step 3：Operation 主线接入 Writer

目标：CLI/GUI/HTTP 进入同一 operation。

动作：

1. 定义 `turn.start`、`turn.cancel`、`approval.respond`、`session.list`、`settings.get/update`。
2. Writer app-server 先接 operation。
3. Writer CLI 改为调 operation client。
4. GUI 只通过 app-server operation/snapshot 状态展示。

验收：

- 普通 `writer run/resume/watch/session` 不绕过 operation。
- GUI turn 和 CLI run 走同一运行入口。

### Step 4：Event / Snapshot 最终收口

目标：运行事实只由 Core `RunItemEvent -> SnapshotReducer -> snapshot.core` 表达。

动作：

1. `runtime_bridge.py` 只保留产品副作用，不再做运行事实载体。
2. App ledger 对普通运行事件直接持久化 `core/runItem`。
3. 外层 Writer AppEvent 只保留产品输入、队列、审批回执等产品事实。

验收：

- message/tool/status/usage/artifact 都能从 `snapshot.core` 还原。
- 外层 Writer event 不承载运行状态。

### Step 5：前端去旧投影

目标：UI 只消费 snapshot selectors 和 canonical parts。

动作：

1. 清理 `runtime/transcript.ts` 的主线导出。
2. `ChatThread` 不再理解 Writer runtime event 或旧 content fallback。
3. transcript 若保留，只作为审计视图，不参与实时 UI。

验收：

- 刷新、审批等待、工具结果、最终回复都来自 snapshot selectors。
- 前端测试只保护 canonical snapshot/parts。

### Step 6：LLM / Provider 下沉 Core

目标：Writer 不解析 provider payload。

动作：

1. Core LLM adapter 接管 profile、request payload、stream chunk、tool call、usage、thinking。
2. Writer 只保留 provider/model 配置读取。
3. 删除或收缩 `llm_client.py`、`llm_adapter_profiles.py`、`llm_adapters/*.jsonc` 的通用语义。

验收：

- OpenAI-compatible 和 xfyun fixture 在 Core 测。
- Writer 不再出现 provider-specific response path parser。

### Step 7：Tool / Permission 下沉 Core

目标：通用工具和权限门属于 Core。

动作：

1. Core 提供 Workspace/Shell/Git/Web/MCP/SubAgent toolkits。
2. Core `ApprovalGate` 统一权限请求、等待、恢复。
3. Writer `tool_specs.py` 只声明启用工具和领域 handler。

验收：

- 通用文件、shell、git、web、MCP 执行不在 Writer。
- 审批等待和恢复由 Core contract 覆盖。

### Step 8：Prompt / Memory / Verification 收敛

目标：WriterKit 变薄，保留领域判断。

动作：

1. Core prompt assembler 管排序、预算、截断。
2. Core memory protocol 管 store/recall/provenance/budget。
3. Core `VerificationResult` 统一验收协议。
4. Writer 只提供 prompt fragments、Novel 领域记忆和领域验收规则。

验收：

- Writer 不再手写通用 prompt 拼接。
- 普通验收输出 Core result。

### Step 9：Writer Thin Member 化

目标：Writer 目录形态回到 member 包。

动作：

1. 整理为 `adapter.py`、`kit.py`、`tools.py`、`verification.py`、`prompts/`、`ui_labels.py` 等薄入口。
2. 删除重复 service、兼容壳和无入口模块。
3. 保留 Novel、架构顾问等真实领域能力。

验收：

- Writer backend runtime 先降到 20k，再降到 10k 以下。
- Writer 专属业务核心可以被清楚识别。

### Step 10：Artist 作为第二样例迁移

目标：证明 Core 不是 Writer 专用抽象。

动作：

1. Artist 接入同一 `MemberKit` 和 operation 主线。
2. 删除 Artist `TaskManager` / SSE runtime 和 fallback mapper。
3. 保留图像生成、视觉上下文、视觉验收、产品 API/UI。

验收：

- Writer/Artist 都不复制 LLM/tool/session/event runtime。
- Artist 是 thin member 示例。

### Step 11：Scaffold 更新

目标：新成员不会复制旧 Writer runtime。

动作：

1. 更新 `scaffold-member.ps1` 及模板。
2. 新 member 只生成 member manifest、kit、prompts、tools、verification、UI 壳。

验收：

- 新 member scaffold 不生成 runtime、provider parser、SSE manager。

### Step 12：最终验收

目标：确认重构完成，不只是在文件名上移动复杂度。

动作：

1. 全量扫描旧词汇。
2. 跑 Core / Writer / Artist targeted tests。
3. 跑真实 smoke：CLI run、GUI turn、approval、refresh、tool call。
4. 更新设计文档和历史审计文档维护标注。

验收：

- Writer runtime 阶段目标：`< 10k`。
- Writer runtime 最终目标：`<= 6k`。
- `rg` 查不到旧事件族、Writer SSE 产品链路、Writer provider parser 主线。

## 5. 执行记录格式

每个切片追加到设计文档：

```text
### 9.xx 执行记录：YYYY-MM-DD 第 xx 切片

目标：

- ...

已完成：

- ...

验证：

- `...`

当前收缩：

- ...

下一步：

- ...
```

## 6. 当前执行队列

1. Step 1-10：已完成，详见目标设计文档执行记录。
2. Step 11：已完成 scaffold 更新和临时 member 生成验证。
3. Step 12：进行中。
4. 当前下一步：清理临时 smoke 资源，提交 Step 12 第三切片；随后补最终审计标注和完成判定。
