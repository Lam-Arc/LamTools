# LamTools 生态架构演进计划

> **For agentic workers:** Use executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LamImager 从单产品演进为 LamTools 生态首个应用，建立可被 LamAssistant/LamCoder/LamArtist 共享的核心架构。

**Architecture:** 6 个月分 5 阶段渐进式重构。先单仓库内拆分目录、定义全局协议；再引入 LangGraph 多 agent；最后转 Monorepo + Tauri 桌面壳启动 LamAssistant。

**Tech Stack:** Python (FastAPI) + Vue3 + LangGraph + Tauri + pnpm/uv workspaces

---

## 全局协议（贯穿所有 Phase）

以下 7 条规则是 LamTools 生态的**全局规范**，所有 Lam 应用必须遵守。

### 规则 0: Skill / Context / Plan 语义分层原则

任务不应被视为单一对象，而应由三个不同语义层共同描述：

- **skill**：思考偏置层，负责创作方法、计划总方针、质量偏好、约束原则
- **context**：运行时事实层，负责用户输入、参考图、上下文图、搜索结果、历史消息、用户偏好
- **plan**：执行结构层，负责 strategy、steps、step dependencies、checkpoint、expected outputs

必须遵守以下边界：

- `skill` 决定“怎么想”，不直接承载具体执行步骤
- `context` 决定“当前事实是什么”，不直接决定高层创作原则
- `plan` 决定“具体怎么做”，不承载高层创作哲学

三者关系应理解为：

```text
ExecutionPlan ≈ Planner(skill, context, intent) + LLM uncertainty
```

因此：

- `skill` 与 `plan` 不是严格可逆映射
- `context` 必须成为一等公民
- 后续 LangGraph 接入时，应以 `intent + skill + context -> planner -> ExecutionPlan` 为前提，而不是继续把所有职责压进 prompt 或 tool call

### 规则 1: Tool Schema（OpenAI Function Calling 兼容）

```python
class Tool(ABC):
    name: str
    description: str
    parameters: dict        # JSON Schema
    category: str           # "image" / "code" / "web" / "system" / "media"
    media_type: str | None  # "image" / "video" / "audio" / "3d" / "code" / "text"

@dataclass
class ToolResult:
    content: str
    meta: dict | None
    artifacts: list[Artifact] | None  # NEW: 多媒介产物

@dataclass
class Artifact:
    type: str           # "image" / "video" / "audio" / "3d_model" / "code" / "file"
    url: str
    mime_type: str
    size_bytes: int | None
    metadata: dict      # 类型特定（image 有 width/height）
```

### 规则 2: Provider Type 扩展协议

预留扩展类型（按需启用）：
- `llm` / `vision_llm` / `embedding`
- `image_gen` / `image_edit` / `image_search`
- `video_gen` / `audio_gen` / `3d_gen`
- `web_search` / `code_exec` / `storage`

provider 配置必须含 `category` 和 `capabilities` 字段。

### 规则 3: Cross-Product Event Bus 协议

```python
@dataclass
class LamEvent:
    event_id: str           # UUID
    timestamp: int          # ms
    source_product: str
    target_product: str | None
    event_type: str
    correlation_id: str     # 跨产品任务追踪
    payload: dict
```

标准事件类型：`task_started` / `task_progress` / `checkpoint_required` / `task_completed` / `task_failed` / `user_input_needed`

### 规则 4: Cross-Product Task Invocation 协议

每个 Lam 应用必须暴露：
- `POST /lamtools/invoke` — 接收任务调用
- `GET /lamtools/capabilities` — 暴露支持的 task_type

### 规则 5: Plugin Manifest 协议

第三方插件 manifest 格式（实现延后）：

```json
{
  "name": "github-tool",
  "version": "1.0.0",
  "manifest_version": "lamtools/v1",
  "tools": [...]
}
```

### 规则 6: Storage Path 协议

```
$LAMTOOLS_DATA_DIR/
├── shared/
│   ├── artifacts/{images,videos,code}/
│   ├── memory/
│   └── billing/
└── apps/{lamimager,lamassistant,...}/sessions/
```

### 规则 7: 版本兼容协议

所有 API/Event/Manifest 带 `version` 字段，core 提供版本协商机制。当前为 `v1`。

---

## Phase 0: Agent 模式上线（当前 → Month 1 Week 1）

**目标:** 把现有 agent 模式打磨到可用，发布 0.1.0，上传 GitHub 累积用户。

### Task 0.1: 修复剩余 bug

**Files:** 待发现

**Steps:**
- [ ] 完成 agent 模式当前所有已知 bug 修复
- [ ] 跑过完整测试矩阵（之前讨论的 T1-T11）
- [ ] 验证套图/单图/搜索/多轮场景

**Verification:**
- [ ] 所有测试用例通过
- [ ] SSE 事件流无异常
- [ ] 计费记录完整

**Commit:** `fix(agent): final bug fixes for 0.1.0 release`

### Task 0.2: 准备 0.1.0 发布

**Files:** `README.md`, `pyproject.toml`, `package.json`, `LICENSE`

**Steps:**
- [ ] 写 README（项目介绍、截图、5分钟配置教程）
- [ ] 选 LICENSE（推荐 MIT，符合开源生态目标）
- [ ] 设置 `pyproject.toml` version = "0.1.0"
- [ ] 设置 `frontend/package.json` version = "0.1.0"
- [ ] 写 CHANGELOG.md
- [ ] `.gitignore` 检查（确保 .env、data/ 等不上传）

**Verification:**
- [ ] `git clone` 后按 README 操作能跑起来
- [ ] 无敏感信息上传

**Commit:** `chore: prepare 0.1.0 release`

### Task 0.3: 上传 GitHub

**Steps:**
- [ ] 创建 GitHub 仓库 `lamimager`
- [ ] 推送代码
- [ ] 打 tag `v0.1.0`
- [ ] 写 GitHub Release Notes

**Verification:**
- [ ] 仓库可公开访问
- [ ] Release 页面完整

**Commit:** N/A（GitHub 操作）

---

## Phase 1: 架构梳理（Month 1，单仓库内）

**目标:** 后端目录拆分为 `core/` 和 `imager/`，定义生态协议，预埋跨产品接口。

> **关键说明:** 此阶段对用户**无感知影响**——HTTP API、数据库、启动命令均不变。仅内部 import 路径重组。版本号 0.1.x → 0.2.0。

> **新增说明：** 从本阶段开始，后续所有执行内核设计必须把 `skill / context / plan` 分层原则纳入考虑。即便暂时不全面实现 `skill`，也必须在接口和模型上预留其进入 Planner 主链的位置，避免 skill 长期废弃、plan 继续过载、context 继续散传。

### Task 1.1: 后端目录重组（选项 A 激进）

**Files:** `backend/app/` 整体重构

**Steps:**
- [ ] 创建新目录结构:
  ```
  backend/app/
  ├── core/                      (生态共享)
  │   ├── agent/                 (run_agent_loop, AgentEvent, ...)
  │   ├── tools/                 (Tool, ToolResult, Artifact, registry)
  │   ├── providers/             (ApiProvider, provider service)
  │   ├── billing/               (record_billing, calc_cost)
  │   ├── events/                (EventBus, LamEvent)
  │   ├── llm/                   (LLMClient)
  │   └── crypto/                (encrypt/decrypt)
  ├── imager/                    (LamImager 专属)
  │   ├── services/              (generate_service, plan_template_service, ...)
  │   ├── tools/                 (generate_image, plan, image_search, web_search)
  │   ├── routers/
  │   ├── models/
  │   └── schemas/
  ├── main.py                    (入口不变)
  ├── config.py
  └── database.py
  ```
- [ ] 移动文件到对应位置
- [ ] 更新所有 import 路径（`app.services.X` → `app.imager.services.X` 或 `app.core.X`）
- [ ] 保留 `app.main:app` 入口不变
- [ ] 运行测试套件确认无功能变更

**Verification:**
- [ ] `python -m py_compile` 全通过
- [ ] `uvicorn app.main:app` 启动正常
- [ ] 现有所有 API 端点行为不变

**Commit:** `refactor(arch): split backend into core/ and imager/ for ecosystem readiness`

### Task 1.2: 实现生态协议数据结构

**Files:** `backend/app/core/tools/__init__.py`, `backend/app/core/events/__init__.py`

**Steps:**
- [ ] `Tool` 类增加 `category: str`、`media_type: str | None` 字段
- [ ] 新建 `Artifact` dataclass
- [ ] `ToolResult` 增加 `artifacts: list[Artifact] | None` 字段
- [ ] 新建 `LamEvent` dataclass
- [ ] 新建 `EventBus` 抽象类（先实现 `InMemoryEventBus`）
- [ ] 现有工具适配新字段（默认值保证向后兼容）

**Verification:**
- [ ] 现有工具调用不破坏
- [ ] `ToolResult` 可选返回 artifacts

**Commit:** `feat(core): add Artifact, LamEvent, EventBus protocol`

### Task 1.3: 跨产品接口预埋

**Files:** `backend/app/core/lamtools_router.py`（新建）, `backend/app/main.py`

**Steps:**
- [ ] 实现 `POST /lamtools/invoke`:
  ```python
  # 接收 source_product / target_product / task_type / correlation_id / payload
  # 路由到对应的处理函数（首版只支持 task_type="agent_generate"）
  # 返回 task_id
  ```
- [ ] 实现 `GET /lamtools/capabilities`:
  ```python
  # 返回当前 LamImager 支持的 task_type 列表
  # ["agent_generate", "image_generate", "image_optimize"]
  ```
- [ ] 在 `main.py` 注册新路由
- [ ] 写简单的 curl 测试用例

**Verification:**
- [ ] `curl /lamtools/capabilities` 返回正确列表
- [ ] `curl /lamtools/invoke` 能触发 agent 生成

**Commit:** `feat(core): add /lamtools/invoke and /lamtools/capabilities endpoints`

### Task 1.4: 写生态协议文档

**Files:** `docs/lamtools-protocol.md`（新建）

**Steps:**
- [ ] 详述 7 条全局规则
- [ ] 给出每条规则的 schema 示例
- [ ] 给出 Cross-Product Invocation 完整示例
- [ ] 标注 `protocol_version: v1`

**Verification:**
- [ ] 文档对未来 LamAssistant 开发者可读

**Commit:** `docs: add LamTools ecosystem protocol v1`

### Task 1.5: 前端半分离重构

**Files:** `frontend/src/views/Sessions.vue`, 新建 `frontend/src/components/session/`

**Steps:**
- [ ] 提取共享子组件:
  - `MessageList.vue`
  - `InputBox.vue`
  - `ContextImages.vue`
  - `BillingTopbar.vue`（如果还没单独）
- [ ] Sessions.vue 拆为 `AgentSessionView.vue` 和 `WorkbenchSessionView.vue`，组合上述子组件
- [ ] 路由调整为 `/sessions/agent/:id` 和 `/sessions/workbench/:id`，保留 `/sessions/:id` 重定向到默认模式

**Verification:**
- [ ] Agent 模式和 Workbench 模式 UI 行为正确
- [ ] 现有 session 数据正常加载
- [ ] 切换模式不丢失上下文

**Commit:** `refactor(frontend): split Sessions.vue into Agent and Workbench views`

### Task 1.6: 发布 0.2.0

**Steps:**
- [ ] 升级版本号至 0.2.0
- [ ] 写 CHANGELOG（"内部架构重组，无功能变更"）
- [ ] 推送 tag `v0.2.0`

**Commit:** `chore: release 0.2.0`

---

## Phase 2: LangGraph + LLM 自主规划（Month 2-4，分 A/B 两期）

> **2026-05-12 决定记录**:
> 1. LangGraph 版本: `>=1.1.10,<1.2.0`（禁止 `1.1.7`，已被 PyPI yanked）
> 2. Sessions.vue 拆分已在 P1 收尾完成 (14 组件, 4082→1731 行)
> 3. P2A 并存策略: 默认 `use_langgraph=true`(app_settings), 旧 `run_agent_loop` 为回退
> 4. Tokenizer: `tiktoken>=0.7.0`, Python 升至 3.14 弃用 3.9

**目标:** 将 agent loop 升级为 LangGraph StateGraph，引入 LLM 自主规划能力（在 task_type 约束下），skill 与 context 正式进入规划链路，落地通用 checkpoint 与视觉质量检查，为 P3 评分系统预留完整接口。

> **关键定位**：LangGraph 在此阶段是**调度器升级**，不是救火工具。P1 已完成的统一执行内核（`ExecutionPlan → PlanExecutionService → Executor`）和三层分层原则（`skill / context / plan` 语义边界），共同构成 LangGraph 可以平稳接入的基础。Phase 2 不引入新执行器、不改执行语义、不重构前端路由。

### P2 准入条件（必须在 Phase 2B 之前满足）

以下标注为「P2A 桥接」的项在当前代码中未完成，但 P2A 的任务就是补齐它们——因此在进入 P2B 之前必须全部完成：

| 准入项 | 状态 | 完成于 |
|------|------|------|
| `ExecutionPlan` 已稳定 | ✅ | P1 Task 1 |
| `PlanExecutionService` 已落地 | ✅ | P1 Task 3 |
| Agent / Workbench 双入口统一后端执行 | ✅ | P1 Task 8/9 |
| `Artifact` + step 级 `ExecutionTrace` 已产出 | ✅ | P1 Task 10 |
| `PlanningContext` 已定义 | ✅ | P1 Task 0 |
| skill 数据模型已重定义为 planner bias（`strategy_hint/planning_bias/constraints/prompt_bias`） | ✗ | **P2A Task 2.0a** |
| `Sessions.vue` 已拆分为组件（AgentStreamCard/MessageList/InputArea 独立） | ✅ | P1 收尾 (14 组件, 1731 行) |

### 实施决定 (2026-05-12)

1. **LangGraph 版本**: `0.6.11` — 受限于运行环境 Python 3.9.13 (1.x 需 Python >=3.10), 0.6.x 仍支持 `StateGraph` + `astream_events()
   经过决策更改为1.10以上，1.20以下，python全部采用3.14+`
2. **Tokenizer**: `tiktoken>=0.7.0` (cl100k_base 编码, token 预算用)
3. **并存策略**: `app_settings.use_langgraph` 默认 `true`, 设 `false` 切回旧 `run_agent_loop()`
4. **Sessions.vue**: 拆分已于 P1 收尾完成, P2 仅验收确认

---

## P2A: 桥接 + 最小图迁移（Month 2）

P2A 的目标是**先让 LangGraph 跑起来**（sidebar assistant + 工作台生成路径可用且行为不变），同时补齐 skill 重定义和前端拆分这两个硬前置，为 P2B 的新节点扩展打好基础。

### P2A 图结构（最小化）

```
intent_node (代码驱动) → executor_node (PlanExecutionService) → END
```

P2A 不引入新节点。2-node 图只替换当前 agent loop 的调度层，skill/context 在 P2B 作为新节点接入。

---

### Task 2.0a: skill 模型重定义（P1 Task 1A）

**Files:**
- `backend/app/models/skill.py`（modify）
- `backend/app/schemas/skill.py`（modify）
- `backend/app/services/skill_engine.py`（modify）
- `backend/app/schemas/planning.py`（modify，`SkillInterface` 同步更新）

**Steps:**
- [ ] `Skill` 模型新增 4 列：`strategy_hint`(String)、`planning_bias`(JSON)、`constraints`(JSON)、`prompt_bias`(JSON)
- [ ] `SkillCreate/Update/Response` schema 同步新增 4 字段
- [ ] `skill_engine.py` 新增 `skill_to_planner_hints()`：将 skill 转换为 `{strategy_hint, planning_bias, constraints, prompt_bias}` dict，**不**返回 ExecutionPlan
- [ ] `apply_skill()` 重定义：有 bias 字段 → 返回 planner hints；无 bias → 退化为 prompt 拼接（旧行为兼容）
- [ ] `SkillInterface`（`planning.py`）更新为 `strategy_hint/planning_bias/constraints` 字段

**Verification:**
- [ ] skill 创建时填写新字段正确入库
- [ ] `skill_to_planner_hints()` 返回结构化 dict（非 ExecutionPlan）
- [ ] `apply_skill()` 新旧路径均正常

**Commit:** `refactor(skill): redefine skills as planner bias carriers`

### Task 2.0b: Sessions.vue 组件拆分

**Files:**
- `frontend/src/views/Sessions.vue`（modify）
- 新建组件按 Phase 1-4 拆分方案顺序

**Steps:**
- [ ] Phase 1: `Lightbox.vue` / `CompareOverlay.vue` / `ContextMenu.vue` / `GeneratingIndicator.vue`
- [ ] Phase 2: `ComposerAttachments.vue` / `ComposerControls.vue` → 组装 `InputArea.vue`
- [ ] Phase 3: `TextMessageCard.vue` / `ImageMessageCard.vue` / `PlanMessageCard.vue` / `OptimizationCard.vue` → 组装 `MessageList.vue`
- [ ] Phase 4: `AssistantSidebar.vue`（DialogTab / OptimizeTab / PlanTab / SkillTab）
- [ ] `executePlan` 留在 `Sessions.vue`，不随 `AssistantSidebar` 下沉

**Verification:**
- [ ] 拆分后全部功能回归（agent/workbench 模式、消息渲染、侧栏四 tab、精修、上传、下载）

**Commit:** `refactor(frontend): split Sessions.vue into component hierarchy`

### Task 2.1: Agent Loop → LangGraph 最小迁移

**Files:**
- `backend/app/core/agent/graph.py`（新建）
- `backend/app/core/agent/state.py`（新建，定义 GraphState）
- `backend/app/services/agent_service.py`（modify，deprecate old loop）

**Steps:**
- [ ] **2.1a: GraphState 定义**
  ```python
  class AgentState(TypedDict):
      session_id: str
      messages: list[dict]
      intent: AgentIntent | None          # intent_node
      skill_hints: dict | None            # P2B skill_node
      planning_context: PlanningContext | None
      execution_plan: ExecutionPlan | None # P2B planner_node
      optimized_prompts: list[str]        # P2B prompt_builder_node
      artifacts: list[Artifact]           # executor_node
      critic_results: list[dict]          # P2B critic_node
      retry_count: int
      status: str
  ```
  - P2A 阶段只使用已有字段：`session_id / messages / planning_context / execution_plan / artifacts / status`
- [ ] **2.1b: 最小图（2 节点）**
  - `intent_node`：代码 intent parser → `task_type + intent_meta`（逻辑不变）
  - `executor_node`：`PlanExecutionService.execute()`（P1 已完成）
  - 无新节点、无 loop 边——P2A 的图是一次性直通，不是循环
  - SSE 事件格式不变，前端 `AgentStreamCard` 无感知
  - 旧 `run_agent_loop` 标记 deprecated，保留为回退入口

**Verification:**
- [ ] sidebar assistant 对话功能完全不变
- [ ] SSE 事件格式无变化
- [ ] 旧 `run_agent_loop` 仍可独立调用

**Commit:** `feat(p2a): migrate agent loop to minimal LangGraph StateGraph`

---

## P2B: 完整节点图 + LLM 自主规划（Month 3-4）

P2B 在 P2A 稳定的基础上逐节点扩展图结构。准入条件：Task 2.0a, 2.0b, 2.1 全部完成且通过回归。

### P2B 图结构（完整 7 节点）

```
                    ┌─────────────┐
                    │ intent_node │  代码驱动，输出 task_type（不变）
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ skill_node  │  skill_engine.apply_skill()
                    │ → planner   │  → planning_bias + constraints
                    │   hints     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ context_enrichment_node │
                    │ PlanningContext 标准化   │
                    │ token预算 / 图片缓存     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ planner_node │  LLM 在 task_type 约束下
                    │ → ExecutionPlan │  生成完整 ExecutionPlan
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ prompt_builder_node │
                    │ LLM 逐 step 多模态  │
                    │ 优化 prompt        │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ executor_node │  PlanExecutionService.execute()
                    └──────┬──────┘
                           │
                ┌──────────┴──────────┐
                │                     │
        ┌───────▼───────┐    ┌───────▼───────┐
        │ critic_node   │    │ checkpoint    │
        │ vision LLM    │    │ graph.        │
        │ score+tags    │    │ interrupt()   │
        │ +issues       │    └───────┬───────┘
        └───────┬───────┘            │
                │             approve → 继续
                │            retry_step → prompt_builder
         ┌──────▼──────┐   replan → planner_node
         │decision_node│
         │retry_score  │
         │→ 决策路由   │
         └──────┬──────┘
                │
    score ≥ threshold → 输出结果
    score < threshold → 回对应节点（按 decision 类型）
```

**关键设计护栏**：

- `intent_node` 继续使用代码 parser 输出 `task_type`（`single/multi_independent/iterative/radiate`），**不交给 LLM**
- `planner_node` 在 `task_type` 的约束下生成 `ExecutionPlan`——它自主决定 steps、依赖、checkpoint 位置，但 strategy 白名单由 task_type 限制（如 `radiate` 下不允许 `strategy=single`）
- `decision_node` 是 retry 决策的**唯一所有者**——graph 中所有"是否重做"的条件边都通过它路由，不通过 Critic 直接判断

---

### Task 2.2: skill_node + context_enrichment_node

**Files:**
- `backend/app/core/agent/nodes/skill_node.py`（新建）
- `backend/app/core/agent/nodes/context_node.py`（新建）
- `backend/app/core/agent/graph.py`（modify，添加新节点）
- `backend/app/services/skill_engine.py`（已有，P2A 已重定义）

**Steps:**
- [ ] **2.2a: skill_node**
  - 从 GraphState 读取 intent + 用户选择的 skill_ids
  - 调用 `skill_engine.apply_skill()`（P2A 重定义后版本）→ `planner_hints`
  - 输出写入 `AgentState.skill_hints`
  - 无 skill 时产出空 hints（保证下游接口一致）
  - 不调用 LLM（本节点是纯数据转换）
- [ ] **2.2b: context_enrichment_node（最小可用版本）**
  - 职责：调用 `PlanningContext` 的标准化方法，写回 state
  - 本节点自身不承载算法——`PlanningContext` 是数据与能力宿主，节点只是**薄调用方**
  - 最小版本包含：
    - **Token 预算壳**：定义优先级分层（system 500 / skill_bias 200 / input 500 / images 2000 / history 1500 / search 800），硬顶 6000，截断接口在位但初版不做复杂裁剪
    - **图片去重**：reference_images vs context_images vs history 中的同一 URL 只保留一份
  - 输出：标准化后的 `PlanningContext` → 写入 state

**Verification:**
- [ ] skill bias 正确传递到 planner_node（如 `strategy_hint="iterative"` → plan steps 数 ≥ 3）
- [ ] 无 skill 选中的 session 正常生成（空 hints 不报错）
- [ ] context 去重正确（同一图 URL 在多来源中只出现一次）

**Commit:** `feat(p2b): add skill_node and context_enrichment_node`

### Task 2.3: planner_node + prompt_builder_node

**Files:**
- `backend/app/core/agent/nodes/planner_node.py`（新建）
- `backend/app/core/agent/nodes/prompt_builder_node.py`（新建）
- `backend/app/core/agent/graph.py`（modify）
- `backend/app/services/prompt_optimizer.py`（modify，`optimize_prompt()` 新增 `context_images` 参数）

**Steps:**
- [ ] **2.3a: planner_node（LLM 在 task_type 约束下自主规划）**
  - 输入：`intent.task_type + skill_hints + planning_context`
  - 调用 LLM 生成 `ExecutionPlan`：
    - `task_type` 由 `intent_node` 提供，**planner_node 不可修改**
    - `strategy` 在白名单内可选（但受 task_type 限制，如 `radiate` 下不允许 `single`）
    - 自主决定：step 数量、`reference_step_indices`、每步 `image_count`、`checkpoint` 位置
    - `skill_hints` 作为硬约束（`constraints.max_steps=3` → plan ≤ 3 步）
  - 输出：JSON → 反序列化为 `ExecutionPlan`（复用 P1 `from_steps()`）
  - 失败处理：invalid JSON → 重试 1 次 → 仍 fail → 回退 `_build_execution_plan()`
- [ ] **2.3b: prompt_builder_node（多模态逐步优化）**
  - 输入：`plan.steps[i] + skill_hints.prompt_bias + context_images`
  - 有 context_images → 调用 vision LLM（多模态）；无 → text LLM
  - `prompt_bias` 注入方式：`detail_level=rich` → "highly detailed, intricate textures"
  - 输出：`AgentState.optimized_prompts`
- [ ] **2.3c: prompt_optimizer.py 多模态升级**
  - `optimize_prompt()` 新增 `context_images: list[str] | None` 参数
  - 有图时走 vision LLM，无图时走纯文本（当前行为）
  - 这是 P3 蒙版多模态优化的前置，必须在 P2B 交付

**Verification:**
- [ ] "做一套6个表情包" → `intent_node → task_type=radiate` → `planner_node` 在 radiate 约束下生成 6 items + anchor 锚点
- [ ] `constraints.quality="photorealistic"` → prompt 注入 photorealistic 约束
- [ ] 有参考图 → prompt builder 产出体现参考图色调/风格
- [ ] `optimize_prompt()` 传 `context_images` 后走 vision LLM，无图时走文本 LLM

**Commit:** `feat(p2b): add LLM-driven planner and multimodal prompt builder`

### Task 2.4: critic_node + decision_node

**Files:**
- `backend/app/core/agent/nodes/critic_node.py`（新建）
- `backend/app/core/agent/nodes/decision_node.py`（新建）
- `backend/app/core/agent/critic_interface.py`（新建，P2↔P3 接口定义）
- `backend/app/core/agent/graph.py`（modify）

**Steps:**
- [ ] **2.4a: critic_node（仅视觉分析，不决策）**
  - 输入：executor_node 产出的 `Artifact` 列表 + 原始 prompt
  - 调用 vision LLM：
    - 技术质量评分（0-10）：构图、光照、清晰度、结构
    - 自动打标签（6 维 + 野值）
    - 缺陷列表（如有）：`["手指畸形", "背景漂浮"]`
  - 输出：`CriticOutput(artifact_id, score, tags, issues[])`
  - **不输出"是否 retry"的布尔值或建议**
- [ ] **2.4b: decision_node（retry 决策唯一所有者）**
  - 输入：`CriticOutput`
  - P2B 阶段：`retry_score = score / 10.0`（纯客观评分，偏好权重为 0）
  - 决策路由：
    - `score >= 7.0` → **pass**：输出结果，不重试
    - `5.0 <= score < 7.0` → **warn**：标记低质量，但仍输出（不阻塞流程）
    - `3.0 <= score < 5.0` → **retry_prompt**：回 `prompt_builder`，用 `issues` 增强 prompt 后重做当前 step
    - `score < 3.0`（严重缺陷如断肢）→ **retry_step**：回 `executor`，同一 plan step 重执行
  - 重试上限 2 次，超过取最高分版本
  - P3 接入后：`retry_score = α × objective + β × preference`，decision_node 接口不变
- [ ] **2.4c: P2↔P3 接口**
  ```python
  @dataclass
  class CriticOutput:
      artifact_id: str
      score: float          # 0-10
      tags: dict            # {style, color_temperature, ...}
      issues: list[str]     # ["构图杂乱", ...]
  ```
  - `PreferenceScore` 桩在 `backend/app/services/scorer.py` 预留
  - Critic 不知道 `decision_node` 如何使用它的输出
  - Critic 不知道 P3 scorer 的存在
- [ ] **2.4d: 配置**
  - `critic_mode`: `off` / `radiate_anchor_only` / `all`（默认 `radiate_anchor_only`）
  - `critic_max_retry`: 默认 2
  - 存入 `app_settings`，设置页提供开关

**Verification:**
- [ ] Critic 只产出 `{score, tags, issues}`，不包含 retry 字段
- [ ] decision_node 独立完成 `score → retry_score → 路由` 决策
- [ ] score >= 7.0 → 直接通过；5-7 → 标记低质量但输出；< 5 → 触发对应 retry
- [ ] off 模式下 Critic + decision 旁路，行为与当前无区别

**Commit:** `feat(p2b): add critic_node and decision_node, decoupled from scoring system`

### Task 2.5: Checkpoint 通用化

**Files:**
- `backend/app/core/agent/graph.py`（modify）
- `backend/app/routers/session.py`（modify，checkpoint endpoint）
- `frontend/src/components/session/CheckpointOverlay.vue`（modify）

**Steps:**
- [ ] **2.5a: radiate-only → 任意 PlanStep 的 checkpoint**
  - P1 的 `PlanStep.checkpoint: dict | None` 已在位
  - executor_node 执行 step 前检查：
    ```python
    if step.checkpoint and step.checkpoint.get("enabled"):
        graph.interrupt({"type": "checkpoint_required", ...})
    ```
  - 覆盖：radiate anchor、iterative 中间步骤、planner 生成的任意带 checkpoint step
- [ ] **2.5b: 三档 resume/reject 路由**
  - `POST /api/sessions/{id}/agent/checkpoint` 增加 `retry_level` 字段：
    - `approve` → `graph.command(resume)` → 继续执行
    - `retry_step` → 回 `excutor`，当前 step 重新生成（保留 plan 不变）
    - `replan` → 回 `planner_node`，带用户 feedback 重规划
  - 取消：`POST /api/sessions/{id}/cancel` → graph 中止
- [ ] **2.5c: 前端 CheckpointOverlay**
  - 展示图片 + step 描述 + checkpoint message
  - 已从 Sessions.vue 拆分独立，改动局部化

**Verification:**
- [ ] 任意 PlanStep 带 checkpoint=true → 执行后暂停
- [ ] approve → 继续 / retry_step → 重做当前步 / replan → 重规划
- [ ] cancel → graph 中止

**Commit:** `feat(p2b): generalize checkpoint to all PlanStep types with 3-level resume`

### Task 2.6: PlanningContext 深度升级

**Files:**
- `backend/app/schemas/planning.py`（modify）
- `backend/app/services/planning_context.py`（新建，context 管理能力）
- `backend/app/services/generate_service.py`（modify，适配新接口）

**Steps:**
- [ ] **2.6a: Token 预算系统**
  - `PlanningContext.budget_tokens()` 方法：
    - 优先级分层同 Task 2.2b 定义，硬顶 6000
    - 截断顺序：search_results → old_history → auto_context（非钉选）
    - 钉选图、用户上传参考图 → **不可截断**
  - token 计数：文本用 cl100k_base 近似，图片用 vision API 估算
- [ ] **2.6b: 图片描述缓存**
  - 首次进入上下文的图 → vision LLM 产出文本描述
  - 缓存到 session message metadata（不跨 session）
  - 后续引用传文本描述 + URL，不重传 base64
  - 缓存失效：蒙版精修后（P3 功能）
- [ ] **2.6c: 相关性过滤**
  - 轻量方案：prompt 关键字 vs 上下文项标签 overlap
  - 低相关性（< 0.3）→ 降权（token 预算占比减半）
  - 不剔除，只降权——避免话题切换时上下文全丢
- [ ] **2.6d: 职责澄清**
  - `PlanningContext` 是所有 context 管理算法的**唯一宿主**
  - `context_enrichment_node`（Task 2.2b）只调用 `PlanningContext` 的方法并将结果写回 state
  - 不出现"node 和 model 各写一份相同逻辑"的情况

**Verification:**
- [ ] 长 session 超 6000 token → 自动截断，钉选图保留
- [ ] 图片缓存：同图 3 次引用 → 1 次 vision 调用
- [ ] 切换主题（猫 → 建筑）→ 旧猫图降权但不出现在截断第一梯队

**Commit:** `feat(p2b): upgrade PlanningContext with deep token budget, image caching, and relevance filter`

---

### P2 执行顺序

```
P2A（Month 2）
  Task 2.0a (skill redef) ─┬─ 并行 ─┬─→ Task 2.1 (minimal graph)
  Task 2.0b (vue split)   ─┘        │
                                     ↓
                              2-node graph 可用
                              sidebar assistant 行为不变
                              旧 agent loop 仍可回退

  ←── P2A 里程碑：LangGraph 迁移完成，前端拆分完成 ──→

P2B（Month 3-4）
  Task 2.2 (skill_node + context_enrichment min)
      ↓
  Task 2.6 并行开始（PlanningContext 深度能力，不阻塞 2.3 起步）
      ↓
  Task 2.3 (planner + prompt_builder + multi-modal optimizer)
      ↓  ── Task 2.6 应在此之前完成，否则 prompt_builder 只能用简化 context
  Task 2.4 (critic + decision)
      ↓
  Task 2.5 (checkpoint 通用化)

  ←── P2B 里程碑：7-node 完整图可用 ──→
```

**并行约束：** Task 2.6 可与 2.2 并行起步（算法独立），但必须在 2.3 完成前交付——否则 `prompt_builder_node` 只能对接简化版 context，之后需要返工。

---

### P2 → P3 接口交付物

| 接口 | 位置 | P3 消费者 |
|------|------|----------|
| `CriticOutput(score, tags, issues)` | `critic_interface.py` | `scorer.py` → 双维评分 |
| `PreferenceScore` 桩 | `backend/app/services/scorer.py`（预留） | Task 3.1 |
| `optimize_prompt()` 新增 `context_images` 参数 | `backend/app/services/prompt_optimizer.py`（Task 2.3 交付） | Task 3.2A 多模态优化 |
| `PlanStep.checkpoint` 通用化 + 三档 resume | 图节点 + router | P2 自身消耗，无需 P3 改动 |
| `PlanningContext.budget_tokens()` 接口 | `backend/app/services/planning_context.py` | 长期使用 |

---

### 时间表更新

| Phase | 时间 | 里程碑 |
|-------|------|--------|
| Phase 0 | 当前 → M1 W1 | LamImager 0.1.0 上 GitHub |
| Phase 1 | M1-M2 | 执行内核收敛 + P1.5 三层分层，发布 0.2.0 |
| Phase 2A | M2 | LangGraph 最小迁移 + skill/vue 桥接，发布 0.2.5 |
| Phase 2B | M3-M4 | 7-node 完整图 + LLM 自主规划 + Critic + Checkpoint，发布 0.3.0 |
| Phase 3 | M4-M5 | 偏好学习与评分 + 蒙版精修 + 后处理，发布 0.4.0 |
| Phase 4 | M5-M6 | Monorepo + LamAssistant 雏形 |
| Phase 5 | M6-M7 | Tauri 桌面壳 + 集成测试，发布 1.0.0-beta |

---

## Phase 3: 用户价值落地（Month 3）

**目标:** 用户偏好学习与评分系统、蒙版精修、后处理工具、配置教程。

> **设计原则：以小见大** — LamImager 作为 LamTools 生态首个应用，偏好系统先采用可解释、可编辑的标签方案。未来 LamTools 生态成型时，各应用独立收集的标签数据将为通用嵌入模型和多应用用户画像提供训练种子。当前设计必须预留升级路径，不封闭在标签方案内。

### Task 3.1: 用户偏好学习与评分系统

**Files:**
- `backend/app/core/memory/`（新建）
- `backend/app/core/memory/models.py`（新建）
- `backend/app/imager/services/preference_service.py`（新建）
- `backend/app/imager/services/scorer.py`（新建）
- `backend/app/core/agent/critic.py`（modify，P2 已引入）
- `frontend/src/components/session/PreferenceRanking.vue`（新建）
- `frontend/src/views/Settings.vue`（modify，新增偏好管理面板）

---

#### 3.1.1 数据模型

**`user_preferences` 表（SQLite）**

```sql
CREATE TABLE user_preferences (
    id            TEXT PRIMARY KEY,           -- UUID
    dimension     TEXT NOT NULL,                -- 维度名: style / color_temperature / ...
    value         TEXT NOT NULL,                -- 标签值: "赛博朋克" / "warm" / ...
    confidence    REAL NOT NULL DEFAULT 0.0,   -- 置信度 0~1
    source        TEXT NOT NULL,               -- active_ranking / refine / download / pin / generate / manual
    source_app    TEXT NOT NULL DEFAULT 'lamimager',  -- 来源应用，为 LamTools 跨应用融合预留
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(dimension, value)                   -- 同维度同值只存一条
);
```

**`ranking_events` 表（排序原始数据，不压缩）**

```sql
CREATE TABLE ranking_events (
    id            TEXT PRIMARY KEY,           -- UUID
    session_id    TEXT NOT NULL,
    image_urls    TEXT NOT NULL,               -- JSON array: 被排序的图片 URL 列表
    ranked_order  TEXT NOT NULL,               -- JSON array: 排序后的 index 列表 [best, ..., worst]
    compared_pairs TEXT,                       -- JSON: 两两比较结果（Bradley-Terry 训练用）
    tags          TEXT NOT NULL,               -- JSON: 每张图对应的标签
    created_at    TEXT NOT NULL
);
```

保留 `ranking_events` 的原始比较数据是为了 LamTools 生态的未来价值——这些数据可以直接喂给 Bradley-Terry 模型或 CLIP 嵌入训练，而不需要重新收集。

---

#### 3.1.2 标签体系与提取

**6 维初始标签（可扩展）**

| 维度 | 类型 | 枚举值 / 野值 | 说明 |
|------|------|-------------|------|
| `style` | free | 赛博朋克 / 浮世绘 / 极简 / 概念艺术 / 写实摄影 / ... | 野值维度，vision LLM 自由命名，用户可编辑 |
| `color_temperature` | enum | warm / cool / neutral | 互斥 |
| `saturation` | enum | vivid / muted / desaturated | 互斥 |
| `composition` | enum | center / golden_ratio / symmetric / rule_of_thirds / freeform | 互斥 |
| `detail_level` | enum | minimal / moderate / rich / hyperdetailed | 互斥 |
| `subject_type` | free | 人物 / 场景 / 产品 / 概念 / 抽象 / ... | 野值维度 |

**标签提取时机**

| 触发事件 | 谁提取 | 何时 |
|---------|--------|------|
| 图片生成完成 | vision LLM/P2 Critic | Critic 评分时顺带产出标签（一次多模态调用同时输出 quality_score + tags） |
| 用户精修操作 | vision LLM | 精修完成后的结果图标注（与蒙版优化共享视觉调用） |
| 用户钉选图片 | 复用已有标签 | 钉选时直接提升该图已有标签的 confidence，不触发新 vision 调用 |
| 用户下载图片 | 复用已有标签 | 同上，confidence 增量小于钉选 |
| 主动排序 | vision LLM | 排序前对每张图生成标签（与排序图片组批量提交） |

**标签冲突处理**

同一维度下不同值是互斥的（用户不可能同时偏好 warm 和 cool）。但用户在不同 session 画不同类型的内容时标签会自然多样化——warm 在画黄昏景时出现 6 次，cool 在画科幻时出现 3 次。系统不视为"冲突"而是"多峰偏好"——warm 的 confidence 是 0.6，cool 的 confidence 是 0.3，新图评分时 warm 的匹配权重更高但 cool 也能贡献。

**confidence 加权金字塔**

```
源      │ confidence 增量     │ 说明
────────┼───────────────────┼─────────
手动编辑  │ 1.0 (直接写入)    │ 用户明确设置的值，不可被自动覆盖
主动排序  │ 0.15              │ 每次排序事件中排名最高的图，其标签 +0.15
精修操作  │ 0.08              │ 用户对图做精修（含蒙版），表示认可方向
下载      │ 0.05              │ 下载意味着足够满意
钉选      │ 0.05              │ 上下文引用意味着认可
生成      │ 0.02              │ 仅生成不操作，弱信号
```

confidence 不自动衰减——用户不会"变回不喜欢赛博朋克"。但如果用户长期不再生成某风格，自然不再获得增量，该标签在评分中的实际影响力会天然下降。手动编辑的标签（confidence=1.0）标记为 `locked`，不会被自动聚合冲淡。

---

#### 3.1.3 主动评分机制

**设计原理**

主动评分绕过了"隐式行为推断"的不确定性。用户拖拽排序一个 4 张图的组，产出的信息量等价于 6 对两两比较（Bradley-Terry 模型的标准输入）。这比分析 30 次生成/下载行为的推断更精准。

**触发条件**

```
session 累积生成图片数 >= 6（跨消息去重）
且 距离上次触发 >= 24 小时
且 用户设置 != "完全关闭"
且 当前不在生成/优化/规划中（不打断工作流）
```

**排序界面 `PreferenceRanking.vue`**

- 展示 3 组图片（如果 session 图片不够 3 组则展示所有可用组）
- 每组 2-4 张，用户拖拽排序（Best → Worst）
- 每组内的图片选自**同一维度差异较大**的候选池——确保每组内部有区分度
- 进度条：1/3 → 2/3 → 3/3
- 允许跳过任意组（"这组无法区分"按钮），未排序的不计入
- 排序完成后记录到 `ranking_events` 表，同时通过 vision LLM 批量提取每张图的标签
- 排名最高的图 → 其标签 confidence +0.15；排名最低的图 → 其标签 confidence -0.05（负面信号）

**图片组选择算法**

目标是让每组内部有足够的多样性来测试偏好，而非随机 4 张风格相似的图。

```
selection(images, n_groups=3, per_group=2..4):
  1. 对库内图片按标签聚类（6 维标签 → 粗聚类）
  2. 每组从不同聚类中抽样，确保组内多样性
  3. 优先选择 confidence 低的标签对应的图（系统不确定的地方才值得问）
  4. 排除已被排序过的完全重复组
```

**设置页控制**

在 Settings.vue 的偏好管理区域：

```
偏好学习:   [ 开启 ]  [ 暂停（24h）]  [ 完全关闭 ]

已学习的偏好:  ┌──────────────────────────────┐
              │ 风格: 赛博朋克 (confidence: 0.7) [编辑] [删除] │
              │ 色调: cool (confidence: 0.5)   [编辑] [删除] │
              │ ...                           │
              └──────────────────────────────┘
              [重置所有偏好]
```

---

#### 3.1.4 双维评分计算

**评分管线**

```
生成图 → Critic(客观) → objective_score
生成图 → vision LLM 打标签 → image_tags
image_tags vs user_preferences → preference_score
objective_score × α + preference_score × β → retry_score
```

**objective_score 的标准化**

Critic 产出的是 0-10 的原始分，覆盖构图/光照/清晰度/人体结构等维度（见 P2 Task 2.2）。评分器将其映射到 0-1：

```
objective_score = critic_raw / 10.0
```

**preference_score 的计算**

将用户偏好标签和图片标签分别编码为稀疏向量。每个维度展开成 one-hot-like 子维度：

```
user vector:    [style:赛博朋克=0.7, style:极简=0.3, color:warm=0.0, color:cool=0.5, ...]
image vector:   [style:赛博朋克=1.0, style:极简=0.0, color:warm=0.0, color:cool=1.0, ...]

preference_score = cosine_similarity(user_vector, image_vector)
```

enum 维度（一个图片只能有一个值）权重 1.0。free 维度（style/subject_type）允许多个标签，每个标签按其 confidence 在用户向量中分配比例。preference_score 范围 [-1, 1]，截断到 [0, 1]。

**置信度影响 score 的计算**

preference_score 不仅要看相似度，还要看"用户偏好有多大把握"。低 confidence 的偏好应该降低 β 的实际影响力，避免在偏好数据不足时乱打分：

```
effective_β = β × avg_user_confidence(user_vector)

retry_score = α × objective_score + effective_β × preference_score
```

例如用户偏好向量中所有标签的平均 confidence 只有 0.3，那么 actual β = 0.4 × 0.3 = 0.12 → 客观分主导。

**阈值与行动**

```
retry_score >= 0.8   → 通过，保存并展示
0.6 <= retry_score < 0.8  → 通过但不标记为 high quality
retry_score < 0.6    → 打回重做（含 retry_reason）
retry_score < 0.3    → 直接丢弃不重试（"这张图不值得再试"）
```

retry 时注入 `retry_reason` 到 prompt 优化链路，例如：

```
retry_reason = "构图杂乱(客观3.1)，与用户偏好的'对称构图'严重偏差"
→ optimizer("同一主题，对称构图，清晰光线", mode="retry")
```

**权重的可配置性**

α、β、retry_threshold 作为用户配置项，默认值分别为 0.6、0.4、0.6。设置页暴露为：

```
客观质量权重:  [━━━━━━━◦━━━━] 0.6
偏好匹配权重:  [━━━━◦━━━━━━━━] 0.4
重试阈值:      [━━━━◦━━━━━━━━] 0.6
```

---

#### 3.1.5 API 端点

```
GET    /api/memory/preferences
       → { preferences: [{dimension, value, confidence, source, locked}] }

PUT    /api/memory/preferences/{dimension}/{value}
        body: {confidence: float, locked: bool}
       → 手动编辑/锁定单个偏好标签

DELETE /api/memory/preferences/{dimension}/{value}
       → 删除单个偏好标签

POST   /api/memory/preferences/reset
       → 清空所有偏好（保留 ranking_events）

GET    /api/memory/ranking-events
       → { events: [...] } 分页

POST   /api/memory/ranking-events
        body: {session_id, image_urls[], ranked_order[], tags[][]}
       → 记录完整排序事件（前端提交）
```

所有端点仅操作本地数据库，无外部网络请求，无用户数据外泄。

---

#### 3.1.6 边界情况

| 场景 | 处理 |
|------|------|
| **冷启动**（无偏好数据） | `avg_user_confidence=0` → `effective_β=0` → 纯客观评分。用户完全不受影响 |
| **偏好漂移** | 不自动衰减 confidence。如果用户突然持续不喜欢某风格，新产生的行为（精修/下载）会给新标签提权，旧标签相对权重自然下降 |
| **标签爆炸**（free 维度如 style 出现 50+ 不同值） | 取 confidence top-5 用于评分计算，其余归档（仍可查看但不参与计算） |
| **用户手动设了一个极端的 locked 标签** | Locked 标签的 confidence 恒为 1.0 且不受聚合影响，它代表用户的显式意图。极端偏好的副作用由 α 兜底（客观分下限保护） |
| **vision LLM 打标签出错**（误判风格） | confidence 增量小（0.02-0.15），单次错误不会主导偏好。如果用户手动修正了被错误标记的标签，该标签直接更新为正确值 |
| **无 vision LLM 配置** | 标签提取退化为关键字匹配（从 prompt 中提取风格词），confidence 减半 |
| **偏好学习关闭** | 评分系统不注入偏好，retry 决策完全由客观评分驱动（与当前行为一致） |

---

#### 3.1.7 LamTools 生态预留升级路径

**当前阶段（LamImager，标签方案）**

- 偏好存储为可编辑标签，用户可见可控
- 排序原始数据持久化到 `ranking_events`，为未来升级保留训练种子
- `preference_service.py` 的评分接口返回 `PreferenceScore(preference_score, confidence, tags[])`，接口不依赖内部实现
- `source_app = "lamimager"`，数据路径为 `shared/memory/`

**未来升级（LamTools 生态，嵌入方案）**

- `to_embedding_vector()` 从返回标签 one-hot 替换为返回 CLIP 视觉嵌入
- `ranking_events` 的历史数据可用于训练用户专属的嵌入模型或微调 CLIP
- `source_app` 字段支持跨应用融合：LamCoder 收集代码风格标签、LamAssistant 收集对话风格标签 → 融合为用户统一画像
- 融合算法由生态级的 preference broker 处理，不在 LamImager 范围内

**硬约束**

以下设计在当前阶段必须到位，否则升级时需要破坏性迁移：

1. 评分系统接口（`PreferenceScore` 模型）**不能在 LamImager 升级时修改**，新实现只需替换内部计算逻辑
2. `ranking_events` 的 `compared_pairs` 字段用 Bradley-Terry 标准格式存储，确保历史数据可直接重放
3. `user_preferences.source_app` 字段在位，LamTools 的 broker 通过 `WHERE source_app IN (...)` 实现 per-app 过滤

---

**Verification:**
- [ ] 冷启动：无偏好数据时，retry 决策纯客观评分驱动，行为与当前一致
- [ ] 偏好学习开启后：主动排序 3 组 → `ranking_events` 记录完整 → 标签 confidence 更新正确
- [ ] 用户偏好标签在设置页可见、可编辑单条、可一键重置
- [ ] retry_reason 可解释："客观分 4.2（构图杂乱），偏好分 0.3（与'对称'偏差大）→ retry_score 0.45 < 阈值 → 触发重试"
- [ ] 偏好学习关闭后：评分系统退化为纯客观评分
- [ ] 数据路径为 `shared/memory/`，跨 session 正确
- [ ] vision LLM 未配置时：标签提取降级为 prompt 关键字匹配，不报错

**Commit:** `feat(memory): add tag-based preference learning with dual-dimension scoring, active ranking, and lamtools upgrade path`

### Task 3.2: 图像后处理工具

**Files:** `backend/app/imager/tools/image_post.py`（新建）

**Steps:**
- [ ] 新建工具:
  - `crop_image(image_url, ratio | bbox)` → Artifact
  - `upscale_image(image_url, scale)` → Artifact（用 PIL 或外部 API）
  - `remove_background(image_url)` → Artifact（rembg 库或 API）
- [ ] 注册到 agent 工具集
- [ ] AGENT_SYSTEM_PROMPT 增加工具描述

**Verification:**
- [ ] Agent 能识别"裁剪"/"放大"/"去背景"指令并调用对应工具
- [ ] 产物作为 Artifact 返回

**Commit:** `feat(imager): add image post-processing tools`

### Task 3.2A: 蒙版精修（Mask-Based Refinement）

**Files:**
- `frontend/src/components/session/MaskEditor.vue`（新建）
- `frontend/src/components/session/ImageMessageCard.vue`（modify，P1 已拆分）
- `backend/app/services/prompt_optimizer.py`（modify）
- `backend/app/utils/image_client.py`（modify）
- `backend/app/utils/llm_client.py`（modify，新增 multimodal 调用）

**Steps:**
- [ ] 前端蒙版绘制组件 `MaskEditor.vue`：
  - 在消息图片上叠加 `<canvas>` 蒙版层
  - 笔刷工具：涂抹指定修改区域
  - 橡皮擦：清除蒙版区域
  - 笔刷大小可调
  - 产出 RGBA PNG mask（透明=不改，不透明=需要修改的区域）
  - 入口：`ImageMessageCard` 的"精修"按钮旁新增"蒙版精修"按钮，点击后弹出 lightbox + mask editor
- [ ] 后端蒙版优化 `mask_optimize()`：
  - 在 `prompt_optimizer.py` 新增 `optimize_prompt()` 的 `mode="mask"` 参数
  - **多模态视觉输入**：将原图 + mask 叠加图编码为 base64，连同用户文本指令一起发送给 vision LLM
  - Vision LLM 从叠加图中理解：原图整体内容、mask 区域的上下文关系、用户意图在视觉上的对应
  - 新增 4 个蒙版专用优化方向：
    - `区域融合` — 生成内容与周围区域自然过渡，无接缝
    - `对象替换` — 在 mask 区域插入指定对象，保持光照方向一致
    - `局部修复` — 修复 mask 区域缺陷，模仿周围纹理和颜色分布
    - `风格一致` — mask 区域生成内容与整图风格统一
  - 多模态优化链路：
    ```
    vision LLM 看到 [原图 + 红色mask叠加] + 用户输入 "去掉这条腿"
      → LLM 理解：图片底部有一多余肢体，周围是草地，光照从右上角
      → 输出："在图片底部草地区域移除多余的肢体，保持草地纹理自然延伸，
              不破坏原有光影方向，移除区域后地面连续无断裂"
    ```
  - 复用现有流式优化通道和 billing 路径
- [ ] 通用提示词优化升级为多模态 `optimize_prompt()`：
  - 新增可选 `context_images: list[str]` 参数（base64 或 URL）
  - 有 context_images 时 → vision LLM 接收图 + 文，输出视觉感知的优化 prompt
  - 无 context_images 时 → 退化为纯文本优化（当前行为不变）
  - 典型场景：
    ```
    用户输入 "画一张类似风格的" + 选中 2 张参考图
      → vision LLM 看到参考图的风格、构图、色调
      → 输出："数字插画风格，柔和的暖色调，中心构图，扁平化设计，
              粗轮廓线，低饱和度配色，类似参考图的视觉语言"
    ```
  - `context_images` 来源：reference_images（上传图）、contextImageList（上下文图、钉选图）
  - 前端：优化 Tab 增加"包含上下文图像"checkbox，勾选后自动注入当前会话的 context_images
  - 不额外增加 billing 路径，vision 调用的 token 按现有计费模型走
- [ ] 后端 `edit()` 接入 mask 参数：
  - `image_client.py` 的 `edit()` 新增可选 `mask: bytes | None` 参数
  - 将 mask 转为 base64 或 RGBA PNG 随请求发送
  - `/v1/images/edits` 原生支持 `image + mask + prompt` 三参数
- [ ] 蒙版精修完整链路：
  ```
  用户涂抹 mask + 输入 "去掉这条腿"
    → mask_optimize("去掉这条腿", mode="mask", image=原图, mask=mask图)
    → vision LLM 分析视觉上下文 → 生成视觉感知的优化 prompt
    → edit(image, mask, optimized_prompt)
  ```
- [ ] 回退策略：
  - 中转站不支持 `/v1/images/edits` → 降级为 chat_edit（优化后的 prompt 仍可用）
  - mask 为空（全透明）→ 退化为普通精修（行为不变）
  - vision LLM provider 未配置 → 降级为纯文本优化（当前行为）
- [ ] `MaskEditor` 交互细节：
  - 支持触摸板/手写板压感（pointer events + pressure）
  - 红色半透明叠加显示已涂抹区域
  - 支持 undo/redo
  - 支持一键全选/反选 mask

**Verification:**
- [ ] 涂抹 mask 区域，生成图片仅该区域变化，非 mask 区域基本不变
- [ ] 蒙版优化后 prompt 自动注入"区域融合""无接缝"等约束，且含有视觉感知的细节（如"草地纹理""右上角光照"）
- [ ] 优化 Tab 勾选"包含上下文图像"后，优化结果明显更契合参考图的风格/色调/构图
- [ ] vision LLM 未配置时降级为纯文本优化，行为与当前一致
- [ ] 中转站不支持 `/v1/images/edits` 时降级到 chat_edit，不报错

**Commit:** `feat(refine): add mask-based inpainting with multimodal prompt optimization`

### Task 3.3: 配置教程 + Provider 推荐

**Files:** `docs/getting-started.md`（新建）, `frontend/src/views/Onboarding.vue`（暂不做向导，仅文档）

**Steps:**
- [ ] 写 5 分钟配置教程:
  - 推荐 1-2 个中转站（列出价格、注册链接）
  - 推荐 1 个免费 Serper key 申请方式
  - 截图配置流程
- [ ] 内置 provider 推荐列表（base_url 预填，用户只填 key）

**Verification:**
- [ ] 新用户跟着教程 5 分钟内能跑通 agent 模式

**Commit:** `docs: add getting-started guide with provider recommendations`

---

## Phase 4: Monorepo + LamAssistant 启动（Month 4）

**目标:** 转入 monorepo，启动 LamAssistant 雏形。

### Task 4.1: 建立 monorepo

**Files:** 整个仓库结构

**Steps:**
- [ ] 创建新仓库 `lamtools/`
- [ ] 目录结构:
  ```
  lamtools/
  ├── packages/                  (前端共享，pnpm workspaces)
  │   ├── ui-kit/
  │   ├── core-client/
  │   └── types/
  ├── python/                    (后端共享，uv workspaces)
  │   ├── lamtools-core/         (从 backend/app/core 抽出)
  │   └── lamtools-bus/
  ├── apps/
  │   ├── lamimager/
  │   │   ├── frontend/
  │   │   └── backend/
  │   └── lamassistant/
  │       ├── frontend/
  │       └── backend/
  ├── docs/
  ├── pnpm-workspace.yaml
  └── pyproject.toml
  ```
- [ ] 迁移 LamImager 进 `apps/lamimager/`
- [ ] 抽 `core/` 到 `python/lamtools-core/`
- [ ] 抽前端共享到 `packages/ui-kit/` 和 `packages/core-client/`
- [ ] 配置 workspace（pnpm + uv）
- [ ] CI 调整（GitHub Actions）

**Verification:**
- [ ] LamImager 在新结构下正常运行
- [ ] `pnpm install` 和 `uv sync` 能装好所有依赖

**Commit:** `refactor(monorepo): migrate to lamtools/ monorepo structure`

### Task 4.2: EventBus 转 SQLite 实现

**Files:** `python/lamtools-core/lamtools_core/events/sqlite_bus.py`（新建）

**Steps:**
- [ ] 新建 `SQLiteEventBus` 实现:
  - `events` 表: id/timestamp/source_product/target_product/event_type/correlation_id/payload(JSON)/consumed
  - `publish(event)` → INSERT
  - `subscribe(filter)` → 轮询查询（间隔 100ms）
  - `mark_consumed(event_id)`
- [ ] 替换 `InMemoryEventBus` 为默认实现
- [ ] 保留 `InMemoryEventBus` 用于测试

**Verification:**
- [ ] 跨进程发布事件能被订阅到
- [ ] 性能可接受（>100 events/sec）

**Commit:** `feat(events): add SQLite-backed event bus for cross-process`

### Task 4.3: LamAssistant 雏形

**Files:** `apps/lamassistant/`（新建）

**Steps:**
- [ ] 后端: 基于 lamtools-core 搭 FastAPI
- [ ] 前端: 复用 ui-kit
- [ ] 实现:
  - 简单聊天 UI
  - LLM 对话（agent 模式）
  - 跨产品调用: Assistant 识别"画一张..." → 调用 `lamimager.invoke(task_type="agent_generate")`
  - 任务状态汇总: 订阅 EventBus 上其他产品的 task_progress / task_completed
  - 任务确认 UI: 接收 `checkpoint_required` 事件，弹窗代理用户确认
- [ ] 文档: `apps/lamassistant/README.md`

**Verification:**
- [ ] Assistant 中说"帮我画一张猫" → 跳转或嵌入 LamImager 完成生成
- [ ] LamImager 的 checkpoint 能在 Assistant 中触发确认

**Commit:** `feat(assistant): launch LamAssistant with cross-product invocation`

---

## Phase 5: Tauri 桌面 + 集成测试（Month 5-6）

**目标:** 集成测试体系 + Tauri 桌面壳。

### Task 5.1: 集成测试体系

**Files:** `tests/integration/`（新建）

**Steps:**
- [ ] 关键 service 集成测试（用真实 API key 跑）:
  - LamImager: agent 单图、套图、搜索流程
  - LamAssistant: 跨产品调用 LamImager
- [ ] e2e 测试: 模拟用户操作完整流程
- [ ] CI 中跑（用 GitHub Actions secrets 注入 key）

**Verification:**
- [ ] 关键路径有自动化测试覆盖
- [ ] CI 通过

**Commit:** `test: add integration test suite`

### Task 5.2: Tauri 桌面壳

**Files:** `apps/desktop/`（新建 Tauri 项目）

**Steps:**
- [ ] `cargo install tauri-cli`
- [ ] 创建 Tauri 项目
- [ ] 主进程逻辑:
  - 启动 LamAssistant 后端（Python，端口 8000，主进程）
  - 按需启动 LamImager 后端（Python，端口 8001，子进程）
  - 加载前端 SPA（含 Assistant 和 Imager 视图）
- [ ] Sidecar 配置 Python 后端打包（PyInstaller 或 PyOxidizer）
- [ ] 系统托盘图标
- [ ] 跨平台构建（Windows/Mac/Linux）

**Verification:**
- [ ] 单一 .exe/.dmg 安装包，用户双击即可使用
- [ ] 后端进程随桌面应用启动/关闭

**Commit:** `feat(desktop): add Tauri desktop shell for LamTools`

### Task 5.3: 内测发布

**Steps:**
- [ ] 打包 Windows/Mac 版本
- [ ] 发布 GitHub Release（v0.5.0 或 v1.0.0-beta）
- [ ] 写发布文档

**Verification:**
- [ ] 朋友能下载安装包直接使用，无需配 Python 环境

**Commit:** `chore: release v1.0.0-beta with Tauri desktop`

---

## 不在本计划内的事

- **第三方插件协议实现**（规则 5）：协议已定义，实现时间待定
- **本地推理支持**（Stable Diffusion 本地）：低优先级，按需引入
- **语言重构**：不推荐，保持 Python+Vue3 至少 2 年
- **多用户/协作**：单用户桌面定位，不做
- **移动端**：Vue3 SPA 已能在移动浏览器跑，不做原生

---

## 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 蒙版精修依赖 `/v1/images/edits` 端点 | 中 | 中转站不支持时降级为 chat_edit；影响蒙版精度但不阻塞精修功能 |
| Phase 1 重构破坏现有功能 | 高 | Phase 1 前补充测试用例，每 task 后回归 |
| LangGraph 学习曲线 | 中 | 任务驱动学习，3 周分散学完 |
| Monorepo 迁移复杂 | 中 | Phase 4 时 LamImager 已稳定，迁移风险可控 |
| Tauri Python sidecar 打包难 | 中 | 后期用 PyOxidizer 替代 PyInstaller |
| 用户从 0.1.x 升 0.2.0 不会迁移 | 低 | 写 MIGRATION.md，发 Release Notes |
