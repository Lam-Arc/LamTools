# 规划系统缺失修复计划

> **For agentic workers:** Use executing-plans skill to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 LamImager 规划（Plan）系统中发现的 30+ 个问题，按 P0-P3 分级逐步落地。

**Architecture:** 与 2026-05-09-lamtools-ecosystem.md 路线图对应分阶段执行。

**Tech Stack:** Python / FastAPI / Vue3 / LangGraph（Phase 2 起）

---

## Phase 0: 上 GitHub 前必修（影响发布质量）

### Task 0.1: 修复内置「套图生成」模板变量替换Bug

**Files:** `backend/app/services/plan_template_service.py`

**Steps:**
- [ ] 定位 `_BUILTIN_TEMPLATES` 中 `radiate` 策略的步骤（line 126-127），将 `{style}`、`{overall_theme}`、`{item.prompt}` 单花括号改为 `{{style}}`、`{{overall_theme}}`、`{{item.prompt}}` 双花括号

**Verification:**
- [ ] `apply_template(template_id="套图生成", variables={style:"...", overall_theme:"...", items:[{prompt:"..."}]})` 返回的 steps 中 prompt 正确替换了占位符

**Commit:** `fix(plan): align builtin radiate template variable syntax with regex`

### Task 0.2: 内置模板版本号 / 更新检测

**Files:** `backend/app/models/plan_template.py`, `backend/app/services/plan_template_service.py`

**Steps:**
- [ ] `PlanTemplate` 模型增加 `builtin_version: int = 1` 字段
- [ ] `seed_builtin_templates` 改为按 `name + is_builtin` 判重后，比对版本号，旧版覆盖写入
- [ ] 更新 `_BUILTIN_TEMPLATES` 常量结构加版本号

**Verification:**
- [ ] 修改内置模板后，seed 能自动更新已有模板（`builtin_version` 比对）
- [ ] 用户自定义模板不受影响

**Commit:** `feat(plan): add builtin_version for auto-update of seed templates`

### Task 0.3: 删除残留调试硬编码路径

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 搜索 `radiate_debug.log` 和 `E:/LamImager` 的所有出现
- [ ] 删除相关行（line 1004、1014、1037、1047 等）

**Verification:**
- [ ] `grep -r "E:/LamImager" backend/` 无结果
- [ ] `grep -r "radiate_debug" backend/` 无结果

**Commit:** `chore: remove debug hardcoded paths`

### Task 0.4: 修复 `_extract_items_from_text` 占位符自相矛盾

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] line 593-598 的回退分支：当无关键词命中时，不造 `item N` 占位符
- [ ] 改为在 items 为空时返回空列表，交由上层（LLM 或用户）重新规划
- [ ] 更新 plan tool 描述中"严禁使用占位符"的措辞

**Verification:**
- [ ] `_extract_items_from_text("帮我做6张图")` 返回 `[]`
- [ ] `_extract_items_from_text("包含开心、难过、愤怒、惊讶、睡觉、吃饭")` 返回 6 个项（补充之前缺失的愤怒/吃饭）

**Commit:** `fix(plan): remove item placeholder fallback in extraction`

### Task 0.5: 同步 AGENTS.md 与代码现状

**Files:** `AGENTS.md`

**Steps:**
- [ ] 检查并修正第 184-210 行中与实际代码不符的声明：
  - Direct Routing 的描述（已删除）
  - radiate anchor checkpoint 的描述（当前不阻塞）
- [ ] 检查其他与 plan 相关的描述
- [ ] 提交时附带 AGENTS.md 更新

**Verification:**
- [ ] AGENTS.md 中 plan 相关描述与代码一致

**Commit:** `docs: sync AGENTS.md with current plan implementation`

---

## Phase 1: 架构重组时处理（对齐前后端）

### Task 1.1: 后端实现 `_execute_parallel` 和 `_execute_iterative`

**Files:** `backend/app/services/generate_service.py`, `backend/app/services/plan_executor.py`（新建）

**Steps:**
- [ ] 新建 `plan_executor.py`，包含 `_execute_parallel` 和 `_execute_iterative`
- [ ] `_execute_parallel(steps, ...)`:
  - 步骤之间无依赖，使用 `asyncio.Semaphore` 控制并发
  - 调用 `generate_images_core` 执行每步
  - 返回按步骤索引的结构化结果
- [ ] `_execute_iterative(steps, ...)`:
  - 顺序执行，上一步生成的首张图作为下一步 `reference_images`
  - 调用 `generate_images_core`
  - 返回结构化结果
- [ ] 后端 `handle_agent_generate` 中识别 `strategy` 并分派给对应执行器

**Verification:**
- [ ] parallel: 5 步能在 2 步的时间内完成（并发控制生效）
- [ ] iterative: 上一步的首张图正确传到下一步

**Commit:** `feat(plan): add backend parallel and iterative executors`

### Task 1.2: 处理 `data.plan_strategy` / `data.agent_plan_strategy` 字段

**Files:** `backend/app/services/generate_service.py`, `backend/app/schemas/session.py`

**Steps:**
- [ ] 确认这两个字段在后端的用途
- [ ] 如果不需要，从 schema 中移除或标记 deprecated
- [ ] 后端 agent 路径中读取 `data.agent_plan_strategy` 用于分派执行器

**Verification:**
- [ ] 前端传的 strategy 后端正确消费
- [ ] 无多余字段空转

**Commit:** `fix(plan): consume or remove plan_strategy fields`

### Task 1.3: `iterative/radiate` 意图后端分支

**Files:** `backend/app/services/agent_intent_service.py`, `backend/app/services/generate_service.py`

**Steps:**
- [ ] `handle_agent_generate` 中 `agent_intent_service` 解析出意图后，增加 `if` 分支：
  - `iterative` → 注入 AGENT_SYSTEM_PROMPT 提示 LLM 走 plan(iterative)
  - `multi_item` → 直接 `_execute_parallel` 或走 plan(parallel)
- [ ] 确保意图分析与实际执行器一致

**Verification:**
- [ ] 用户输入"先草图再精修"正确触发 iterative 分支
- [ ] 用户输入"生成 3 张不同风格猫"触发 parallel 或 LLM 自主调 plan

**Commit:** `feat(plan): connect intent parser to backend executors`

### Task 1.4: 清理死字段

**Files:** `backend/app/schemas/plan_template.py`

**Steps:**
- [ ] `PlanStepConditionSchema`（`type/on_pass/on_fail`）：删除（无消费方）
- [ ] `PlanTemplateApplyRequest.template_id`：删除或 schema 补上
- [ ] `reference_step_indices`：保留但标记 deprecated，或删除
- [ ] `Variable.default: str = ""` → 改为 `Any = ""`

**Verification:**
- [ ] 全仓消费方确认无使用后删除
- [ ] 编译通过

**Commit:** `refactor(plan): remove dead fields from schemas`

### Task 1.5: 模板验证前置

**Files:** `backend/app/services/plan_template_service.py`, `backend/app/schemas/plan_template.py`

**Steps:**
- [ ] `create_template` 中校验:
  - steps 至少 1 项
  - 每项必须有 `prompt`
  - strategy 在允许列表内
- [ ] `apply_template` 中校验:
  - required 变量必须提供
  - 缺变量时抛出明确错误，而非替成空串
- [ ] 前端 `PlanTemplateManage.vue` JSON 解析失败不默默吞错，弹提示

**Verification:**
- [ ] 创建模板时缺字段返回 422
- [ ] 应用模板时缺 required 变量返回明确错误

**Commit:** `feat(plan): add template validation on create and apply`

### Task 1.6: PlanTool 增加 `get_detail`

**Files:** `backend/app/tools/plan.py`

**Steps:**
- [ ] action 枚举增加 `get_detail`
- [ ] 返回单个模板的完整信息（全部 steps 含 prompt/negative_prompt/checkpoint 等）
- [ ] 更新 tool description

**Verification:**
- [ ] LLM 能 `plan(action="get_detail", template_id=...)` 看到完整内容

**Commit:** `feat(agent): add get_detail action to PlanTool`

---

## Phase 2: 与 LangGraph 同步落地

### Task 2.1: radiate checkpoint 真正阻塞

**Files:** `backend/app/services/generate_service.py`, `backend/app/core/agent/graph.py`

**Steps:**
- [ ] LangGraph `interrupt` 集成后，`_execute_radiate` 中的 checkpoint 调用改为 await
- [ ] 前端 `CheckpointModal` 展示锚点图
- [ ] `POST /api/sessions/{id}/agent/checkpoint` 真正生效

**Verification:**
- [ ] radiate 在锚点图生成后暂停，等待用户确认
- [ ] approve 继续，reject 中止

**Commit:** `feat(agent): make radiate anchor checkpoint blocking`

---

## Phase 3: 用户价值功能落地

### Task 3.1: 模板动态变量输入控件

**Files:** `frontend/src/views/PlanTemplateManage.vue`, `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 根据 `variable.type` 渲染不同控件:
  - `string` → `<input type="text">`
  - `select` → `<select>`（用 `options` 列表）
  - `number` → `<input type="number">`
  - `image` → 图片选择器（未来）
- [ ] 前端校验后调用 `apply_template`

**Verification:**
- [ ] `type=select` 的变量显示下拉菜单
- [ ] `required=true` 的变量图标标注

**Commit:** `feat(ui): dynamic variable input controls by type`

### Task 3.2: 模板预览（dry-run）

**Files:** `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 变量填充后添加"预览"按钮
- [ ] 调用 `apply_template`，展示展开后的 steps 列表（不执行）
- [ ] 用户确认后再进入执行阶段

**Verification:**
- [ ] 预览看到变量替换后的完整 prompt

**Commit:** `feat(ui): add template preview before execution`

### Task 3.3: 模板导入/导出

**Files:** `backend/app/routers/plan_template.py`, `frontend/src/api/planTemplate.ts`

**Steps:**
- [ ] 后端: `GET /api/plan-templates/export/{id}` 返回 JSON 文件
- [ ] 后端: `POST /api/plan-templates/import` 接收 JSON 文件并创建
- [ ] 前端: 模板列表加导出/导入按钮

**Verification:**
- [ ] 导出后再导入，模板内容一致

**Commit:** `feat(plan): add import/export endpoints`

### Task 3.4: 执行结果步骤级索引

**Files:** `backend/app/services/generate_service.py`

**Steps:**
- [ ] 每步生成图片时，`add_system_message` 的 metadata 中附加 `step_index`
- [ ] `_execute_radiate` 同理
- [ ] 前端显示"步骤 3/6"进度

**Verification:**
- [ ] message `metadata.step_index` 正确
- [ ] 前端可按步骤分组显示图片

**Commit:** `feat(plan): add step_index to generation metadata`

### Task 3.5: UI 暴露 radiate 策略选项

**Files:** `frontend/src/views/Sessions.vue`, `frontend/src/views/PlanTemplateManage.vue`

**Steps:**
- [ ] Sessions.vue 规划策略选项增加 radiate
- [ ] PlanTemplateManage.vue 创建模板策略下拉增加 radiate
- [ ] 描述文字说明 radiate 适用场景

**Verification:**
- [ ] 工作台模式可选 radiate 并执行
- [ ] 可创建 radiate 模板

**Commit:** `feat(ui): expose radiate strategy in workbench and template editor`

---

## 执行顺序

```
Phase 0（发布前）: 0.1 → 0.2 → 0.3 → 0.4 → 0.5（串行）
Phase 1（架构重组）: 1.1 → 1.2 → 1.5 → 1.6（串行）+ 1.4（并行）+ 1.3（依赖 1.1）
Phase 2（LangGraph）: 2.1（依赖 Phase 1 完成）
Phase 3（用户价值）: 3.1 / 3.2 / 3.3 / 3.4 / 3.5（相对独立，可并行）
```
