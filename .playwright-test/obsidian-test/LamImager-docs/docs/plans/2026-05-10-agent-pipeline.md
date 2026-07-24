# Agent Pipeline 最小闭环实施计划

> **For agentic workers:** Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成"语义解析 -> 策略匹配 -> 执行流程"最小闭环，让用户说什么系统至少能按合理路径干起来。

**Architecture:** 将当前"LLM 决定策略"的 Agent Loop 模式，改为"代码决定策略"的直接执行模式。意图解析输出 4 种 task_type，代码硬映射到对应执行器，LLM 仅负责内容生成（prompt/步骤/items），不参与策略裁决。

**Tech Stack:** Python 3.14+ / FastAPI / Vue3 / Pinia

---

## 核心设计

### 4 种任务类型 + 固定策略映射

| TaskType | Strategy | 执行器 | 说明 |
|----------|----------|--------|------|
| `single` | `single` | `_execute_single()` → `generate_images_core()` | 单张/多张同风格 |
| `multi_independent` | `parallel` | `execute_multi_independent()` → `asyncio.gather` | 多张独立图，无风格依赖 |
| `iterative` | `iterative` | LLM生成steps → `execute_iterative()` | 有步骤依赖，上一步影响下一步 |
| `radiate` | `radiate` | LLM生成items/style → `_execute_radiate()` | 套图/统一风格/同角色 |

### 语义解析优先级

1. **radiate** (最高): 套图/一组/系列/统一风格/同角色/表情包(无"不同风格")/图标集/四联画
2. **iterative**: 先...再.../草图→精修/基于上一张/继续改
3. **multi_independent**: 三视图+方向/方向枚举/N张不同风格/多个方案/分别画
4. **single** (默认): 其他所有情况

### 策略控制权

- **后端代码决定策略**，不依赖 LLM、前端、tool meta
- 前端 `agent_plan_strategy` 字段保留但后端忽略
- LLM 仅用于内容生成（prompt 优化、步骤拆分、items 生成）

---

## Task 1: 重构 AgentIntent 和策略映射表

**Files:** `backend/app/services/agent_intent_service.py`

**Steps:**
- [ ] 1.1 更新 `AgentIntent` dataclass：`task_type` 改为 `"single" | "multi_independent" | "iterative" | "radiate"`，移除 `uncertain` 和 `multi_item`
- [ ] 1.2 更新 `strategy` 字段默认值为 `"single"`，可选值为 `"single" | "parallel" | "iterative" | "radiate"`
- [ ] 1.3 添加 `STRATEGY_MAP` 常量：
  ```python
  STRATEGY_MAP: dict[str, str] = {
      "single": "single",
      "multi_independent": "parallel",
      "iterative": "iterative",
      "radiate": "radiate",
  }
  ```
- [ ] 1.4 添加 `TASK_TYPE_LABELS` 常量（用于前端展示）：
  ```python
  TASK_TYPE_LABELS: dict[str, str] = {
      "single": "单图生成",
      "multi_independent": "多图并行",
      "iterative": "迭代精修",
      "radiate": "套图辐射",
  }
  ```
- [ ] 1.5 更新 `_requires_consistency()` 函数：`multi_independent`/`radiate`/`iterative` 自动需要一致性
- [ ] 1.6 更新 `validate_agent_result()` 函数：适配新的 task_type 名称
- [ ] 1.7 重命名 `execute_multi_item_intent()` → `execute_multi_independent()`，更新内部 billing detail 中的 intent 字段

**Verification:**
- [ ] `agent_intent_service.py` 中不再有 `multi_item` 或 `uncertain` 字符串
- [ ] `STRATEGY_MAP` 包含 4 个映射
- [ ] 所有函数签名和返回值使用新的 task_type 名称

**Commit:** `refactor: unify AgentIntent to 4 task types with fixed strategy mapping`

---

## Task 2: 重写 parse_agent_intent() 语义解析

**Files:** `backend/app/services/agent_intent_service.py`

**Steps:**
- [ ] 2.1 重写 `parse_agent_intent()` 函数，按新优先级顺序匹配：
  - **Priority 1 - radiate**: 匹配 `套图|一组|系列|一套|set|series|collection|pack`；匹配 `统一风格|同风格|same style|consistent`；匹配 `同一角色|同角色|same character`；匹配 `表情包|贴纸包|sticker pack|emoticon set`（排除含"不同风格"的）；匹配 `图标集|icon set|四联画|成组|插画集`；匹配 N张 + (同风格/统一/同角色/一套)
  - **Priority 2 - iterative**: 匹配 `先...再.../first...then...`；匹配 `草图.*精修|sketch.*refine`；匹配 `基于上一张|继续改|延续上一步`
  - **Priority 3 - multi_independent**: 匹配三视图+方向枚举；匹配裸方向枚举(正面/侧面/背面>=2)；匹配 N张不同风格/N个方案/分别画/每张不同；匹配 N张+列表枚举(无统一风格关键词)
  - **Priority 4 - single**: 默认兜底，包括变体/多张同风格/image_count>1
- [ ] 2.2 更新 `_make_intent()` 内部函数，使用 `STRATEGY_MAP` 自动设置 strategy
- [ ] 2.3 移除旧的 Rule 1-8 编号注释，用新的优先级标签替代
- [ ] 2.4 保留特殊规则：三视图+设定表关键词 → single
- [ ] 2.5 确保每个规则分支都返回正确的 task_type 和 strategy

**Verification:**
- [ ] 测试用例覆盖：
  - "画一只猫" → single
  - "做一套6个表情包" → radiate
  - "先出草图再精修" → iterative
  - "画3张不同风格的猫" → multi_independent
  - "三视图 正面侧面背面" → multi_independent
  - "套图4张 同一角色" → radiate
  - "生成4个不同logo方案" → multi_independent
  - "同一角色四个动作" → radiate

**Commit:** `refactor: rewrite parse_agent_intent with 4-type priority ordering`

---

## Task 3: 新增 LLM 步骤/参数生成函数

**Files:** `backend/app/services/agent_intent_service.py`

**Steps:**
- [ ] 3.1 新增 `_generate_iterative_steps()` 函数：
  ```python
  async def _generate_iterative_steps(
      db, prompt: str, context_messages: list[dict] | None,
      llm_provider_id: str, api_key: str, base_url: str, model_id: str,
  ) -> list[dict]:
  ```
  - 使用 LLM 生成迭代步骤列表
  - System prompt: "你是文生图规划师，将用户需求拆分为2-5个迭代步骤，每步基于上一步结果精修"
  - 输出格式: JSON 数组，每项含 `prompt`、`description`、`image_count`(默认1)、`image_size`(默认"1024x1024")
  - 失败回退: 单步 `[{prompt, description: "直接生成", image_count: 1}]`
- [ ] 3.2 新增 `_generate_radiate_params()` 函数：
  ```python
  async def _generate_radiate_params(
      db, prompt: str, expected_count: int, context_messages: list[dict] | None,
      llm_provider_id: str, api_key: str, base_url: str, model_id: str,
  ) -> dict:
  ```
  - 使用 LLM 生成 items、style、overall_theme
  - System prompt: "你是文生图规划师，将用户需求拆分为N个统一风格的子项"
  - 输出格式: JSON `{"items": [{prompt: "..."}], "style": "...", "overall_theme": "..."}`
  - 失败回退: 从 prompt 提取 items（复用 `_extract_items_from_text`），style 默认 "digital art illustration"
- [ ] 3.3 新增 `_generate_multi_independent_prompts()` 函数（基于现有 `_generate_item_prompts` 重构）：
  - 与 `_generate_item_prompts` 逻辑相同，但返回格式调整为 `list[dict]`，每项含 `prompt`、`description`、`image_count`
  - 保留原有 fallback 逻辑

**Verification:**
- [ ] 三个新函数都有清晰的 LLM 调用和 fallback 逻辑
- [ ] 返回格式与 `execute_iterative()`/`execute_parallel()`/`_execute_radiate()` 的输入格式兼容

**Commit:** `feat: add LLM-based step/item generation functions for direct execution`

---

## Task 4: 重构 handle_agent_generate() 路由

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 4.1 移除 `agent_plan_strategy` 覆盖逻辑（第841-844行），后端忽略前端传来的策略
- [ ] 4.2 新增 `_execute_single()` 函数：
  ```python
  async def _execute_single(
      db, session_id, data, intent, task_manager,
      image_provider_id, llm_provider_id,
  ) -> dict:
  ```
  - 直接调用 `generate_images_core()`
  - 传入 prompt、image_count、image_size、reference_images
  - 记录 billing
  - 保存系统消息
  - 返回标准结果 dict
- [ ] 4.3 重构 `handle_agent_generate()` 的路由部分（替换第903行之后的 agent loop 逻辑）：
  ```python
  strategy = STRATEGY_MAP.get(intent.task_type, "single")
  task_manager.update_task(session_id, TaskStatus.GENERATING,
      message=f"{TASK_TYPE_LABELS.get(intent.task_type, '')} | 策略: {strategy}")

  if strategy == "single":
      result = await _execute_single(db, session_id, data, intent, task_manager, image_provider_id, llm_provider_id)
  elif strategy == "parallel":
      result = await execute_multi_independent(db, session_id, intent, data, task_manager, llm_provider_id, image_provider_id)
  elif strategy == "iterative":
      # 1. LLM 生成步骤
      steps = await _generate_iterative_steps(db, prompt, data.context_messages, llm_provider_id, api_key, base_url, model_id)
      if not steps:
          # 明确报错，不静默失败
          result = {"error": "无法生成迭代步骤", "images": [], "steps": []}
      else:
          # 2. 执行迭代
          result = await execute_iterative(db, session_id, steps, image_provider_id, task_manager, accumulated_images=[], llm_provider_id=llm_provider_id)
  elif strategy == "radiate":
      # 1. LLM 生成 items/style/theme
      radiate_params = await _generate_radiate_params(db, prompt, intent.expected_count, data.context_messages, llm_provider_id, api_key, base_url, model_id)
      if not radiate_params.get("items"):
          result = {"error": "无法生成套图子项", "images": [], "steps": []}
      else:
          # 2. 构造 plan_meta 并执行 radiate
          plan_meta = {"items": radiate_params["items"], "style": radiate_params.get("style", ""), "overall_theme": radiate_params.get("overall_theme", "")}
          result = await _execute_radiate(db, session_id, plan_meta, data, task_manager, [], [], llm_provider_id, 0, 0, 0.0)
  ```
- [ ] 4.4 统一结果保存逻辑：所有策略执行完毕后，统一保存 agent 消息到数据库
- [ ] 4.5 统一 SSE 事件广播：在路由开始时广播 `task_started`（含 task_type 和 strategy），执行中广播 `task_progress`，结束时广播 `task_completed`
- [ ] 4.6 保留 agent loop 代码（不删除 `run_agent_loop`），但主生成路径不再使用它

**Verification:**
- [ ] `handle_agent_generate()` 中不再有 `run_agent_loop()` 调用
- [ ] 4 种策略都有明确的执行路径
- [ ] 每种策略的结果都保存为 agent 消息
- [ ] SSE 事件正确广播

**Commit:** `refactor: replace agent loop with fixed strategy routing in handle_agent_generate`

---

## Task 5: 补执行链硬断点

**Files:** `backend/app/services/generate_service.py`, `backend/app/services/plan_executor.py`, `backend/app/services/agent_intent_service.py`

**Steps:**
- [ ] 5.1 **radiate 硬断点**：
  - `_generate_radiate_params()` 返回空 items 时，明确报错 "无法从需求中提取套图子项，请描述更具体（如：做一套6个表情包，包含开心、生气、惊讶...）"
  - `_execute_radiate()` 中 style/theme 为空时，使用 `_extract_style_from_text()` 兜底，不再静默跳过
  - anchor 生成失败时，返回明确错误 "锚点网格图生成失败，请检查图像生成API配置"
  - grid crop 失败时，返回明确错误 "网格裁剪失败，将尝试直接生成各子项" 并 fallback 到逐项独立生成
- [ ] 5.2 **iterative 硬断点**：
  - `_generate_iterative_steps()` 返回空步骤时，明确报错 "无法生成迭代步骤，请描述更具体（如：先出草图，再精修细节）"
  - `execute_iterative()` 中确保上一步首图传给下一步（当前已实现 `reference_images = urls[:1]`，验证正确性）
  - 单步失败时不中断整体执行，但记录明确错误信息
- [ ] 5.3 **parallel 硬断点**：
  - `execute_multi_independent()` 中 items 为空时，明确报错 "无法提取生成子项"
  - `execute_parallel()` 中 steps 为空时返回 None，调用方检查并报错
  - 并发数量通过 `max_concurrent` 设置可控（当前已实现）
  - 每步结果通过 SSE 事件可见
- [ ] 5.4 **single 硬断点**：
  - `_execute_single()` 中 provider 未找到时，明确报错 "未配置图像生成API"
  - 生成失败时，返回明确错误信息
- [ ] 5.5 **通用硬断点**：
  - 所有执行路径的异常都通过 `task_manager.update_task(session_id, TaskStatus.ERROR, message=...)` 广播
  - 所有执行路径的异常都通过 `add_system_message(db, session_id, error_msg, message_type="error")` 保存
  - 不再有静默失败（`pass`/`return None` 不带错误信息）

**Verification:**
- [ ] 每种策略的空输入/执行失败都有明确的错误消息
- [ ] 错误消息通过 SSE 广播到前端
- [ ] 错误消息保存到数据库

**Commit:** `fix: add hard breakpoints and explicit error handling for all execution paths`

---

## Task 6: 前端 - 移除策略选择UI + 显示任务类型和进度

**Files:** `frontend/src/views/Sessions.vue`, `frontend/src/types/index.ts`

**Steps:**
- [ ] 6.1 移除策略选择 UI（第471-480行的 `plan-strategy` 区域）
- [ ] 6.2 移除 `planStrategies` 和 `selectedPlanStrategy` 变量（第746-750行）
- [ ] 6.3 更新 `sendGenerate()` 中的请求构建：移除 `agent_plan_strategy` 字段（或设为空字符串让后端忽略）
- [ ] 6.4 更新 `TaskHandle` 接口，添加 `taskType` 和 `strategy` 字段：
  ```typescript
  export interface TaskHandle {
    sessionId: string
    type: 'generate' | 'optimize' | 'plan'
    status: 'running' | 'done' | 'error'
    progress: number
    total: number
    abortController: AbortController | null
    taskType?: string
    strategy?: string
  }
  ```
- [ ] 6.5 更新 `TaskUpdateEvent` 接口，添加 `task_type` 和 `strategy` 字段：
  ```typescript
  export interface TaskUpdateEvent {
    session_id: string
    status: string
    progress: number
    total: number
    message: string
    task_type?: string
    strategy?: string
  }
  ```
- [ ] 6.6 更新 SSE 事件处理：在 `onTaskUpdate` 回调中解析 `task_type` 和 `strategy`，更新 `TaskHandle`
- [ ] 6.7 更新生成指示器（第157-166行）：显示任务类型和策略
  ```html
  <span class="generating-text">
    {{ generatingText }}
    <span v-if="currentTaskType" class="task-type-badge">{{ taskTypeLabel }}</span>
  </span>
  ```
- [ ] 6.8 添加 `taskTypeLabel` 计算属性，映射 task_type 到中文标签
- [ ] 6.9 更新 `generatingText` 的初始值：从 "生成中..." 改为根据 agent_mode 显示 "Agent 分析中..."

**Verification:**
- [ ] 策略选择 UI 已移除
- [ ] 生成时显示任务类型标签
- [ ] SSE 事件正确解析 task_type 和 strategy

**Commit:** `feat: remove strategy selector, show task type and progress in UI`

---

## Task 7: 端到端验证

**Files:** 无新文件

**Steps:**
- [ ] 7.1 启动后端服务，确认无启动错误
- [ ] 7.2 启动前端服务，确认无编译错误
- [ ] 7.3 测试 single: 输入 "画一只猫"，验证直接生成图片
- [ ] 7.4 测试 multi_independent: 输入 "画3张不同风格的猫"，验证并行生成
- [ ] 7.5 测试 iterative: 输入 "先出草图再精修"，验证迭代执行
- [ ] 7.6 测试 radiate: 输入 "做一套6个表情包"，验证套图生成
- [ ] 7.7 验证错误场景：无 provider 时明确报错
- [ ] 7.8 验证 SSE 事件：生成过程中前端显示任务类型和进度

**Verification:**
- [ ] 4 种任务类型都能跑通完整流程
- [ ] 错误场景有明确提示
- [ ] 前端正确显示任务类型和进度

**Commit:** (no commit, verification only)

---

## 不做的事情（本阶段）

- LangGraph 迁移
- 完整 HTML 可视化 / Artifact 体系
- monorepo / Tauri
- prompt 极限优化
- Sessions.vue 大拆分
- 前后端彻底收敛
- 所有文档一致性一次性做完
